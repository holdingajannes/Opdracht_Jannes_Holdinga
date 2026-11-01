import uuid
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import (Flask, render_template, request, redirect, url_for, session,
                   flash, g, abort, send_from_directory)
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename

from db import init_db, get_connection
from notifications import notify_quotation_uploaded, notify_decision, send_reminders

app = Flask(__name__)
app.secret_key = "dev-sleutel-verander-in-productie"
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # max 20 MB per upload

UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
LOCAL_TZ = ZoneInfo("Europe/Amsterdam")

# ---------- Keuzelijsten en labels ----------

STATUS_LABELS = {
    "new": "Nieuw",
    "quotation_sent": "Offerte verstuurd",
    "changes_requested": "Wijzigingen gevraagd",
    "approved": "Goedgekeurd",
    "rejected": "Afgewezen",
    "order_created": "Order aangemaakt",
}
CRANE_TYPES = {"single_girder": "Enkelligger", "double_girder": "Dubbelligger", "gantry": "Portaalkraan"}
DUTY_CLASSES = ["1Bm", "1Am", "2m", "3m", "4m"]
POWER_SUPPLIES = ["400V / 3 fase / 50 Hz", "230V / 1 fase / 50 Hz", "Anders"]
CONTROL_METHODS = {"pendant": "Hangdrukknopkast", "radio": "Radiografische afstandsbediening", "cabin": "Cabine"}
OPTIONS = {"limit_switches": "Eindschakelaars", "lights": "Verlichting", "horn": "Claxon", "warning_light": "Zwaailicht"}
CURRENCIES = ["EUR", "USD", "GBP", "CNY"]
ALLOWED_ATTACHMENTS = {".pdf", ".dwg", ".dxf", ".png", ".jpg", ".jpeg", ".xlsx", ".docx", ".zip"}

REQUIRED_FIELDS = [
    "crane_type", "hoist_spec", "duty_class", "hoist_speed", "trolley_speed", "travel_speed",
    "runway", "span", "lift_height", "power_supply", "control_method", "environment",
]


@app.context_processor
def inject_labels():
    return dict(
        STATUS_LABELS=STATUS_LABELS, CRANE_TYPES=CRANE_TYPES, DUTY_CLASSES=DUTY_CLASSES,
        POWER_SUPPLIES=POWER_SUPPLIES, CONTROL_METHODS=CONTROL_METHODS, OPTIONS=OPTIONS,
        CURRENCIES=CURRENCIES,
    )


# ---------- Template filters ----------

@app.template_filter("localtime")
def localtime(value):
    """Zet een UTC-tijd uit de database om naar Nederlandse tijd."""
    if not value:
        return ""
    dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return dt.astimezone(LOCAL_TZ).strftime("%d-%m-%Y %H:%M")


@app.template_filter("duration")
def duration(days):
    """Toont een aantal dagen leesbaar: in uren als het minder dan een dag is."""
    if days is None:
        return "geen data"
    if days < 1:
        return f"{days * 24:.1f} uur"
    return f"{days:.1f} dagen"


# ---------- Inloggen en toegang ----------

@app.before_request
def load_user():
    g.user = None
    user_id = session.get("user_id")
    if user_id is not None:
        with get_connection() as conn:
            g.user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def login_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                return redirect(url_for("login"))
            if roles and g.user["role"] not in roles:
                flash("Je hebt geen toegang tot deze pagina.")
                return redirect(url_for("home"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        with get_connection() as conn:
            user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user and check_password_hash(user["password"], password):
            session.clear()
            session["user_id"] = user["id"]
            return redirect(url_for("home"))
        flash("Onjuist e-mailadres of wachtwoord.")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------- Hulpfuncties ----------

def get_visible_proposals(conn, status=None, company_id=None, min_age=None):
    """Eerst altijd de rolbeperking, daarna pas de filters van de gebruiker."""
    sql = """
        SELECT p.*, c.name AS company_name,
               julianday('now') - julianday(p.created_at) AS age_days
        FROM proposals p JOIN companies c ON c.id = p.company_id
        WHERE 1 = 1
    """
    params = []
    role = g.user["role"]
    if role == "client":
        sql += " AND p.company_id = ?"
        params.append(g.user["company_id"])
    elif role == "sales_engineer":
        sql += " AND p.company_id IN (SELECT company_id FROM sales_engineer_companies WHERE sales_engineer_id = ?)"
        params.append(g.user["id"])

    if status:
        sql += " AND p.status = ?"
        params.append(status)
    if company_id:
        sql += " AND p.company_id = ?"
        params.append(company_id)
    if min_age:
        sql += " AND julianday('now') - julianday(p.created_at) >= ?"
        params.append(min_age)

    sql += " ORDER BY p.created_at DESC"
    return conn.execute(sql, params).fetchall()


def get_visible_companies(conn):
    role = g.user["role"]
    if role == "client":
        return conn.execute("SELECT * FROM companies WHERE id = ?", (g.user["company_id"],)).fetchall()
    if role == "sales_engineer":
        return conn.execute(
            """SELECT * FROM companies WHERE id IN (
                   SELECT company_id FROM sales_engineer_companies WHERE sales_engineer_id = ?)
               ORDER BY name""", (g.user["id"],)).fetchall()
    return conn.execute("SELECT * FROM companies ORDER BY name").fetchall()


def get_proposal(conn, proposal_id):
    return conn.execute(
        """SELECT p.*, c.name AS company_name
           FROM proposals p JOIN companies c ON c.id = p.company_id
           WHERE p.id = ?""", (proposal_id,)).fetchone()


def can_view(conn, row):
    """Werkt voor elke rij met een company_id: aanvraag, offerte of bijlage."""
    role = g.user["role"]
    if role == "admin":
        return True
    if role == "client":
        return row["company_id"] == g.user["company_id"]
    found = conn.execute(
        "SELECT 1 FROM sales_engineer_companies WHERE sales_engineer_id = ? AND company_id = ?",
        (g.user["id"], row["company_id"]),
    ).fetchone()
    return found is not None


def log_event(conn, proposal_id, event_type, details=""):
    conn.execute(
        "INSERT INTO proposal_events (proposal_id, user_id, event_type, details) VALUES (?, ?, ?, ?)",
        (proposal_id, g.user["id"], event_type, details),
    )


def save_upload(file):
    """Slaat een bestand op met een unieke naam. Geeft (opgeslagen naam, originele naam) terug."""
    original = secure_filename(file.filename)
    stored = f"{uuid.uuid4().hex}_{original}"
    file.save(UPLOAD_DIR / stored)
    return stored, original


# ---------- Pagina's: aanvragen ----------

@app.route("/")
@login_required()
def home():
    status = request.args.get("status") or None
    company_id = request.args.get("company", type=int)
    min_age = request.args.get("age", type=int)
    with get_connection() as conn:
        proposals = get_visible_proposals(conn, status, company_id, min_age)
        companies = get_visible_companies(conn)
    return render_template("home.html", proposals=proposals, companies=companies, filters=request.args)


@app.route("/proposals/new", methods=["GET", "POST"])
@login_required("client")
def new_proposal():
    form = request.form
    if request.method == "POST":
        missing = [f for f in REQUIRED_FIELDS if not form.get(f, "").strip()]
        if missing:
            flash("Vul alle verplichte velden in.")
            return render_template("proposal_new.html", form=form)
        try:
            numbers = {f: float(form[f]) for f in ["hoist_speed", "trolley_speed", "travel_speed", "span", "lift_height"]}
        except ValueError:
            flash("Snelheden, overspanning en hijshoogte moeten getallen zijn.")
            return render_template("proposal_new.html", form=form)

        with get_connection() as conn:
            cur = conn.execute(
                """INSERT INTO proposals (company_id, created_by, crane_type, hoist_spec, duty_class,
                       hoist_speed, trolley_speed, travel_speed, runway, span, lift_height,
                       power_supply, control_method, environment, harsh_environment, options)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    g.user["company_id"], g.user["id"], form["crane_type"], form["hoist_spec"].strip(),
                    form["duty_class"], numbers["hoist_speed"], numbers["trolley_speed"],
                    numbers["travel_speed"], form["runway"].strip(), numbers["span"],
                    numbers["lift_height"], form["power_supply"], form["control_method"],
                    form["environment"], 1 if form.get("harsh_environment") else 0,
                    ",".join(form.getlist("options")),
                ),
            )
            proposal_id = cur.lastrowid
            log_event(conn, proposal_id, "proposal_submitted", "Aanvraag ingediend")

        flash("Je aanvraag is ingediend.")
        return redirect(url_for("proposal_detail", proposal_id=proposal_id))

    return render_template("proposal_new.html", form={})


@app.route("/proposals/<int:proposal_id>")
@login_required()
def proposal_detail(proposal_id):
    with get_connection() as conn:
        proposal = get_proposal(conn, proposal_id)
        if proposal is None or not can_view(conn, proposal):
            abort(404)
        quotations = conn.execute(
            "SELECT * FROM quotations WHERE proposal_id = ? ORDER BY version DESC", (proposal_id,)).fetchall()
        attachments = {}
        for a in conn.execute(
                """SELECT a.* FROM quotation_attachments a
                   JOIN quotations q ON q.id = a.quotation_id WHERE q.proposal_id = ?""", (proposal_id,)):
            attachments.setdefault(a["quotation_id"], []).append(a)
        comments = conn.execute(
            """SELECT c.*, u.name AS user_name, u.role AS user_role FROM comments c
               JOIN users u ON u.id = c.user_id
               WHERE c.proposal_id = ? ORDER BY c.created_at, c.id""", (proposal_id,)).fetchall()
        order = conn.execute("SELECT * FROM orders WHERE proposal_id = ?", (proposal_id,)).fetchone()
        events = conn.execute(
            """SELECT e.*, u.name AS user_name FROM proposal_events e
               LEFT JOIN users u ON u.id = e.user_id
               WHERE e.proposal_id = ? ORDER BY e.created_at, e.id""", (proposal_id,)).fetchall()
    return render_template("proposal_detail.html", proposal=proposal, quotations=quotations,
                           attachments=attachments, comments=comments, order=order, events=events)


# ---------- Offertes ----------

@app.route("/proposals/<int:proposal_id>/quotations", methods=["POST"])
@login_required("sales_engineer")
def upload_quotation(proposal_id):
    form = request.form
    back = redirect(url_for("proposal_detail", proposal_id=proposal_id))
    with get_connection() as conn:
        proposal = get_proposal(conn, proposal_id)
        if proposal is None or not can_view(conn, proposal):
            abort(404)
        if proposal["status"] in ("approved", "order_created"):
            flash("Deze aanvraag is al goedgekeurd. Er kan geen nieuwe offerte meer bij.")
            return back

        pdf = request.files.get("pdf")
        fields = ["reference", "price", "currency", "delivery_time", "valid_until"]
        if not all(form.get(f, "").strip() for f in fields) or not pdf or not pdf.filename:
            flash("Vul alle velden in en voeg de offerte-PDF toe.")
            return back
        if not pdf.filename.lower().endswith(".pdf"):
            flash("De offerte moet een PDF-bestand zijn.")
            return back
        try:
            price = float(form["price"])
        except ValueError:
            flash("De prijs moet een getal zijn.")
            return back
        extra_files = [f for f in request.files.getlist("attachments") if f and f.filename]
        for f in extra_files:
            if Path(f.filename).suffix.lower() not in ALLOWED_ATTACHMENTS:
                flash(f"Bestandstype van {f.filename} is niet toegestaan.")
                return back

        version = conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM quotations WHERE proposal_id = ?",
            (proposal_id,)).fetchone()[0]

        pdf_path, _ = save_upload(pdf)
        cur = conn.execute(
            """INSERT INTO quotations (proposal_id, version, reference, price, currency,
                   delivery_time, valid_until, pdf_path, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (proposal_id, version, form["reference"].strip(), price, form["currency"],
             form["delivery_time"].strip(), form["valid_until"], pdf_path, g.user["id"]),
        )
        quotation_id = cur.lastrowid
        for f in extra_files:
            stored, original = save_upload(f)
            conn.execute(
                "INSERT INTO quotation_attachments (quotation_id, file_path, description) VALUES (?, ?, ?)",
                (quotation_id, stored, original),
            )

        conn.execute("UPDATE proposals SET status = 'quotation_sent', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                     (proposal_id,))
        label = "Offerte" if version == 1 else "Nieuwe offerteversie"
        log_event(conn, proposal_id, "quotation_uploaded",
                  f"{label} {version} geüpload ({form['currency']} {price:,.2f})")
        notify_quotation_uploaded(conn, proposal, version, form["currency"], price)

    flash(f"Offerte versie {version} is geüpload.")
    return back


@app.route("/proposals/<int:proposal_id>/decision", methods=["POST"])
@login_required("client")
def decide(proposal_id):
    action = request.form.get("action")
    reason = request.form.get("reason", "").strip()
    back = redirect(url_for("proposal_detail", proposal_id=proposal_id))
    with get_connection() as conn:
        proposal = get_proposal(conn, proposal_id)
        if proposal is None or not can_view(conn, proposal):
            abort(404)
        if proposal["status"] != "quotation_sent":
            flash("Er is geen offerte die op jouw beslissing wacht.")
            return back
        version = conn.execute("SELECT MAX(version) FROM quotations WHERE proposal_id = ?",
                               (proposal_id,)).fetchone()[0]

        if action == "approve":
            new_status, event, details = "approved", "quotation_approved", f"Offerte versie {version} goedgekeurd"
        elif action in ("reject", "changes"):
            if not reason:
                flash("Geef een reden op bij afwijzen of wijzigingen vragen.")
                return back
            if action == "reject":
                new_status, event = "rejected", "quotation_rejected"
                details = f"Offerte versie {version} afgewezen: {reason}"
            else:
                new_status, event = "changes_requested", "changes_requested"
                details = f"Wijzigingen gevraagd op versie {version}: {reason}"
        else:
            abort(400)

        conn.execute("UPDATE proposals SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                     (new_status, proposal_id))
        log_event(conn, proposal_id, event, details)
        notify_decision(conn, proposal, event, details)

    flash(details)
    return back


@app.route("/quotations/<int:quotation_id>/pdf")
@login_required()
def quotation_pdf(quotation_id):
    with get_connection() as conn:
        q = conn.execute(
            """SELECT q.pdf_path, p.company_id FROM quotations q
               JOIN proposals p ON p.id = q.proposal_id WHERE q.id = ?""", (quotation_id,)).fetchone()
        if q is None or not can_view(conn, q):
            abort(404)
    return send_from_directory(UPLOAD_DIR, q["pdf_path"])


@app.route("/attachments/<int:attachment_id>")
@login_required()
def attachment_file(attachment_id):
    with get_connection() as conn:
        a = conn.execute(
            """SELECT a.file_path, a.description, p.company_id FROM quotation_attachments a
               JOIN quotations q ON q.id = a.quotation_id
               JOIN proposals p ON p.id = q.proposal_id WHERE a.id = ?""", (attachment_id,)).fetchone()
        if a is None or not can_view(conn, a):
            abort(404)
    return send_from_directory(UPLOAD_DIR, a["file_path"], download_name=a["description"], as_attachment=True)


# ---------- Opmerkingen en orders ----------

@app.route("/proposals/<int:proposal_id>/comments", methods=["POST"])
@login_required("client", "sales_engineer")
def add_comment(proposal_id):
    text = request.form.get("text", "").strip()
    back = redirect(url_for("proposal_detail", proposal_id=proposal_id))
    if not text:
        flash("Een opmerking mag niet leeg zijn.")
        return back
    with get_connection() as conn:
        proposal = get_proposal(conn, proposal_id)
        if proposal is None or not can_view(conn, proposal):
            abort(404)
        conn.execute("INSERT INTO comments (proposal_id, user_id, text) VALUES (?, ?, ?)",
                     (proposal_id, g.user["id"], text))
        log_event(conn, proposal_id, "comment_added", "Opmerking geplaatst")
    return back


@app.route("/proposals/<int:proposal_id>/order", methods=["POST"])
@login_required("sales_engineer")
def create_order(proposal_id):
    back = redirect(url_for("proposal_detail", proposal_id=proposal_id))
    with get_connection() as conn:
        proposal = get_proposal(conn, proposal_id)
        if proposal is None or not can_view(conn, proposal):
            abort(404)
        if proposal["status"] != "approved":
            flash("Alleen een goedgekeurde offerte kan worden omgezet naar een order.")
            return back
        q = conn.execute(
            """SELECT id, version, price, currency FROM quotations
               WHERE proposal_id = ? ORDER BY version DESC LIMIT 1""", (proposal_id,)).fetchone()
        cur = conn.execute(
            """INSERT INTO orders (proposal_id, quotation_id, company_id, price, currency, created_by)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (proposal_id, q["id"], proposal["company_id"], q["price"], q["currency"], g.user["id"]),
        )
        order_number = f"ORD-{cur.lastrowid:05d}"
        conn.execute("UPDATE orders SET order_number = ? WHERE id = ?", (order_number, cur.lastrowid))
        conn.execute("UPDATE proposals SET status = 'order_created', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                     (proposal_id,))
        log_event(conn, proposal_id, "order_created",
                  f"Order {order_number} aangemaakt op basis van offerte versie {q['version']}")
    flash(f"Order {order_number} is aangemaakt.")
    return back


# ---------- Mijn meldingen (alle gebruikers) ----------

@app.route("/notifications")
@login_required()
def my_notifications():
    with get_connection() as conn:
        emails = conn.execute(
            "SELECT * FROM email_outbox WHERE to_email = ? ORDER BY id DESC LIMIT 100",
            (g.user["email"],)).fetchall()
    return render_template("notifications.html", emails=emails)


# ---------- Beheer ----------

@app.route("/admin/emails")
@login_required("admin")
def admin_emails():
    with get_connection() as conn:
        emails = conn.execute("SELECT * FROM email_outbox ORDER BY id DESC LIMIT 200").fetchall()
    return render_template("admin_emails.html", emails=emails)


@app.route("/admin/reminders", methods=["POST"])
@login_required("admin")
def run_reminders():
    with get_connection() as conn:
        n = send_reminders(conn)
    flash(f"{n} herinnering(en) verstuurd.")
    return redirect(url_for("admin_emails"))


@app.route("/admin/assignments", methods=["GET", "POST"])
@login_required("admin")
def admin_assignments():
    with get_connection() as conn:
        engineers = conn.execute(
            "SELECT id, name, email FROM users WHERE role = 'sales_engineer' ORDER BY name").fetchall()
        companies = conn.execute("SELECT id, name FROM companies ORDER BY name").fetchall()

        if request.method == "POST":
            conn.execute("DELETE FROM sales_engineer_companies")
            for e in engineers:
                for c in companies:
                    if request.form.get(f"a_{e['id']}_{c['id']}"):
                        conn.execute("INSERT INTO sales_engineer_companies (sales_engineer_id, company_id) VALUES (?, ?)",
                                     (e["id"], c["id"]))
            flash("Koppelingen opgeslagen.")
            return redirect(url_for("admin_assignments"))

        current = {(r["sales_engineer_id"], r["company_id"])
                   for r in conn.execute("SELECT * FROM sales_engineer_companies")}
    return render_template("admin_assignments.html", engineers=engineers, companies=companies, current=current)


@app.route("/admin/reports")
@login_required("admin")
def admin_reports():
    with get_connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM proposals").fetchone()[0]
        won = conn.execute(
            "SELECT COUNT(*) FROM proposals WHERE status IN ('approved', 'order_created')").fetchone()[0]
        lost = conn.execute("SELECT COUNT(*) FROM proposals WHERE status = 'rejected'").fetchone()[0]
        conversion = (won / (won + lost) * 100) if (won + lost) else None

        # Gemiddelde tijd van aanvraag tot eerste offerte (in dagen)
        avg_to_quote = conn.execute(
            """SELECT AVG(julianday(fq.first_quote) - julianday(p.created_at))
               FROM proposals p
               JOIN (SELECT proposal_id, MIN(created_at) AS first_quote
                     FROM quotations GROUP BY proposal_id) fq ON fq.proposal_id = p.id""").fetchone()[0]

        # Gemiddelde tijd van offerte tot reactie van de klant (in dagen)
        avg_to_decision = conn.execute(
            """SELECT AVG(julianday(e.created_at) - julianday(
                   (SELECT MAX(q.created_at) FROM quotations q
                    WHERE q.proposal_id = e.proposal_id AND q.created_at <= e.created_at)))
               FROM proposal_events e
               WHERE e.event_type IN ('quotation_approved', 'quotation_rejected', 'changes_requested')"""
        ).fetchone()[0]

        status_counts = conn.execute(
            "SELECT status, COUNT(*) AS n FROM proposals GROUP BY status ORDER BY n DESC").fetchall()

        per_engineer = conn.execute(
            """SELECT u.name,
                      SUM(CASE WHEN p.status = 'quotation_sent' THEN 1 ELSE 0 END) AS open_quotes,
                      SUM(CASE WHEN p.status IN ('new', 'changes_requested') THEN 1 ELSE 0 END) AS to_do
               FROM users u
               LEFT JOIN sales_engineer_companies s ON s.sales_engineer_id = u.id
               LEFT JOIN proposals p ON p.company_id = s.company_id
               WHERE u.role = 'sales_engineer'
               GROUP BY u.id ORDER BY u.name""").fetchall()

    return render_template("admin_reports.html", total=total, won=won, lost=lost, conversion=conversion,
                           avg_to_quote=avg_to_quote, avg_to_decision=avg_to_decision,
                           status_counts=status_counts, per_engineer=per_engineer)


@app.route("/admin/audit")
@login_required("admin")
def admin_audit():
    with get_connection() as conn:
        events = conn.execute(
            """SELECT e.*, u.name AS user_name, c.name AS company_name
               FROM proposal_events e
               LEFT JOIN users u ON u.id = e.user_id
               JOIN proposals p ON p.id = e.proposal_id
               JOIN companies c ON c.id = p.company_id
               ORDER BY e.created_at DESC, e.id DESC LIMIT 500""").fetchall()
    return render_template("admin_audit.html", events=events)


if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5001)