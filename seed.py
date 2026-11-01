from werkzeug.security import generate_password_hash
from db import get_connection, init_db


def seed():
    init_db()
    with get_connection() as conn:
        # Niet dubbel vullen als er al gebruikers zijn
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
            print("Database bevat al data, seed overgeslagen.")
            return

        # Bedrijven
        conn.execute("INSERT INTO companies (id, name) VALUES (1, 'Bouwbedrijf De Vries')")
        conn.execute("INSERT INTO companies (id, name) VALUES (2, 'Staalhandel Jansen')")

        pw = generate_password_hash("test123", method="pbkdf2:sha256")

        # Gebruikers
        users = [
            (1, "Klant De Vries", "klant@devries.nl", pw, "client", 1),
            (2, "Klant Jansen", "klant@jansen.nl", pw, "client", 2),
            (3, "Sanne Verkoop", "sanne@clientname.nl", pw, "sales_engineer", None),
            (4, "Mark Verkoop", "mark@clientname.nl", pw, "sales_engineer", None),
            (5, "Admin", "admin@clientname.nl", pw, "admin", None),
        ]
        conn.executemany(
            "INSERT INTO users (id, name, email, password, role, company_id) VALUES (?, ?, ?, ?, ?, ?)",
            users,
        )

        # Koppeling verkoopingenieur aan bedrijf
        conn.execute("INSERT INTO sales_engineer_companies VALUES (3, 1)")
        conn.execute("INSERT INTO sales_engineer_companies VALUES (4, 2)")

    print("Testdata toegevoegd. Wachtwoord voor alle accounts: test123")


if __name__ == "__main__":
    seed()