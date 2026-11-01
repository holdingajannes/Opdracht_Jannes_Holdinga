"""Controleert open offertes en verstuurt herinneringen.

In productie laat je dit script dagelijks automatisch draaien, bijvoorbeeld met cron:
    0 8 * * 1-5  cd /pad/naar/project && .venv/bin/python remind.py
"""
from db import init_db, get_connection
from notifications import send_reminders

if __name__ == "__main__":
    init_db()
    with get_connection() as conn:
        n = send_reminders(conn)
    print(f"{n} herinnering(en) verstuurd.")