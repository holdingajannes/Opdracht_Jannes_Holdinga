"""Alle e-mailmeldingen en herinneringen staan in dit bestand.

In dit prototype worden e-mails niet echt verstuurd, maar opgeslagen in de tabel
email_outbox en geprint in de console. In productie vervang je alleen de functie
send_email door echte verzending (SMTP of een maildienst).
"""
from datetime import datetime

BASE_URL = "http://127.0.0.1:5001"
REMINDER_DAYS = 3   # na zoveel dagen zonder reactie: herinnering aan verkoopingenieur
MANAGER_DAYS = 7    # na zoveel dagen: ook melding aan de manager


# ---------- Basis ----------

def send_email(conn, to_email, subject, body, proposal_id=None, kind="notification"):
    conn.execute(
        "INSERT INTO email_outbox (to_email, subject, body, proposal_id, kind) VALUES (?, ?, ?, ?, ?)",
        (to_email, subject, body, proposal_id, kind),
    )
    print(f"[E-MAIL] Aan: {to_email} | Onderwerp: {subject}")


def link(proposal_id):
    return f"{BASE_URL}/proposals/{proposal_id}"


def client_emails(conn, company_id):
    rows = conn.execute("SELECT email FROM users WHERE role = 'client' AND company_id = ?", (company_id,))
    return [r["email"] for r in rows]


def engineer_emails(conn, company_id):
    rows = conn.execute(
        """SELECT u.email FROM users u
           JOIN sales_engineer_companies s ON s.sales_engineer_id = u.id
           WHERE s.company_id = ?""", (company_id,))
    return [r["email"] for r in rows]


def manager_emails(conn):
    rows = conn.execute("SELECT email FROM users WHERE role = 'admin'")
    return [r["email"] for r in rows]


# ---------- Meldingen bij gebeurtenissen ----------

def notify_quotation_uploaded(conn, proposal, version, currency, price):
    """Naar de klant: nieuwe offerte of nieuwe versie."""
    pid = proposal["id"]
    if version == 1:
        subject = f"Nieuwe offerte voor aanvraag #{pid}"
        intro = "Er staat een offerte voor je aanvraag klaar."
        kind = "quotation_uploaded"
    else:
        subject = f"Offerte bijgewerkt voor aanvraag #{pid} (versie {version})"
        intro = f"Er staat een nieuwe versie ({version}) van de offerte voor je aanvraag klaar."
        kind = "quotation_updated"
    body = (
        f"Beste klant,\n\n{intro}\n\n"
        f"Prijs: {currency} {price:,.2f}\n\n"
        f"Bekijk en beoordeel de offerte: {link(pid)}\n\n"
        f"Met vriendelijke groet,\nCLIENTNAME"
    )
    for email in client_emails(conn, proposal["company_id"]):
        send_email(conn, email, subject, body, pid, kind)


def notify_decision(conn, proposal, event, details):
    """Naar de verkoopingenieur: klant heeft goedgekeurd, afgewezen of wijzigingen gevraagd."""
    pid = proposal["id"]
    titles = {
        "quotation_approved": "Offerte goedgekeurd",
        "quotation_rejected": "Offerte afgewezen",
        "changes_requested": "Wijzigingen gevraagd",
    }
    subject = f"{titles[event]}: aanvraag #{pid} ({proposal['company_name']})"
    body = (
        f"Beste collega,\n\n{proposal['company_name']} heeft gereageerd op aanvraag #{pid}.\n\n"
        f"{details}\n\n"
        f"Bekijk de aanvraag: {link(pid)}\n"
    )
    for email in engineer_emails(conn, proposal["company_id"]):
        send_email(conn, email, subject, body, pid, event)


# ---------- Herinneringen ----------

def send_reminders(conn, reminder_days=REMINDER_DAYS, manager_days=MANAGER_DAYS):
    """Zoekt offertes die te lang op de klant wachten en stuurt herinneringen.
    Elke herinnering gaat maar één keer per offerteversie. Geeft het aantal verstuurde herinneringen terug."""
    open_quotes = conn.execute(
        """SELECT p.id, p.company_id, c.name AS company_name, MAX(q.created_at) AS sent_at
           FROM proposals p
           JOIN companies c ON c.id = p.company_id
           JOIN quotations q ON q.proposal_id = p.id
           WHERE p.status = 'quotation_sent'
           GROUP BY p.id""").fetchall()

    now = datetime.utcnow()
    count = 0
    for row in open_quotes:
        sent_at = datetime.strptime(row["sent_at"], "%Y-%m-%d %H:%M:%S")
        days_open = (now - sent_at).total_seconds() / 86400

        def already_sent(kind):
            return conn.execute(
                "SELECT 1 FROM email_outbox WHERE proposal_id = ? AND kind = ? AND created_at >= ?",
                (row["id"], kind, row["sent_at"])).fetchone() is not None

        # Herinnering aan de verkoopingenieur
        if days_open >= reminder_days and not already_sent("reminder"):
            subject = f"Herinnering: offerte voor aanvraag #{row['id']} staat {days_open:.0f} dagen open"
            body = (
                f"Beste collega,\n\nDe offerte voor aanvraag #{row['id']} ({row['company_name']}) "
                f"wacht al {days_open:.0f} dagen op een reactie van de klant.\n"
                f"Neem eventueel contact op met de klant.\n\n{link(row['id'])}\n"
            )
            for email in engineer_emails(conn, row["company_id"]):
                send_email(conn, email, subject, body, row["id"], "reminder")
            add_system_event(conn, row["id"], "reminder_sent",
                             f"Herinnering verstuurd naar verkoopingenieur ({days_open:.0f} dagen open)")
            count += 1

        # Escalatie naar de manager
        if days_open >= manager_days and not already_sent("manager_reminder"):
            subject = f"Escalatie: offerte aanvraag #{row['id']} staat {days_open:.0f} dagen open"
            body = (
                f"Beste manager,\n\nDe offerte voor aanvraag #{row['id']} ({row['company_name']}) "
                f"staat al {days_open:.0f} dagen open zonder reactie van de klant.\n\n{link(row['id'])}\n"
            )
            for email in manager_emails(conn):
                send_email(conn, email, subject, body, row["id"], "manager_reminder")
            add_system_event(conn, row["id"], "manager_reminder_sent",
                             f"Melding verstuurd naar manager ({days_open:.0f} dagen open)")
            count += 1

    return count


def add_system_event(conn, proposal_id, event_type, details):
    """Geschiedenisregel zonder gebruiker, voor automatische acties."""
    conn.execute(
        "INSERT INTO proposal_events (proposal_id, user_id, event_type, details) VALUES (?, NULL, ?, ?)",
        (proposal_id, event_type, details),
    )