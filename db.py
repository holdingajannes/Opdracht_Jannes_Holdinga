import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "pipeline.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('client', 'sales_engineer', 'admin')),
    company_id INTEGER REFERENCES companies(id)
);

CREATE TABLE IF NOT EXISTS sales_engineer_companies (
    sales_engineer_id INTEGER NOT NULL REFERENCES users(id),
    company_id INTEGER NOT NULL REFERENCES companies(id),
    PRIMARY KEY (sales_engineer_id, company_id)
);

CREATE TABLE IF NOT EXISTS proposals (
    id INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    created_by INTEGER NOT NULL REFERENCES users(id),
    crane_type TEXT NOT NULL,
    hoist_spec TEXT,
    duty_class TEXT,
    hoist_speed REAL,
    trolley_speed REAL,
    travel_speed REAL,
    runway TEXT,
    span REAL,
    lift_height REAL,
    power_supply TEXT,
    control_method TEXT,
    environment TEXT CHECK (environment IN ('indoor', 'outdoor')),
    harsh_environment INTEGER DEFAULT 0,
    options TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS quotations (
    id INTEGER PRIMARY KEY,
    proposal_id INTEGER NOT NULL REFERENCES proposals(id),
    version INTEGER NOT NULL,
    reference TEXT,
    price REAL,
    currency TEXT DEFAULT 'EUR',
    delivery_time TEXT,
    valid_until TEXT,
    pdf_path TEXT,
    created_by INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS quotation_attachments (
    id INTEGER PRIMARY KEY,
    quotation_id INTEGER NOT NULL REFERENCES quotations(id),
    file_path TEXT NOT NULL,
    description TEXT
);

CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY,
    proposal_id INTEGER NOT NULL REFERENCES proposals(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    text TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS proposal_events (
    id INTEGER PRIMARY KEY,
    proposal_id INTEGER NOT NULL REFERENCES proposals(id),
    user_id INTEGER REFERENCES users(id),
    event_type TEXT NOT NULL,
    details TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY,
    order_number TEXT UNIQUE,
    proposal_id INTEGER NOT NULL UNIQUE REFERENCES proposals(id),
    quotation_id INTEGER NOT NULL REFERENCES quotations(id),
    company_id INTEGER NOT NULL REFERENCES companies(id),
    price REAL,
    currency TEXT,
    status TEXT NOT NULL DEFAULT 'confirmed',
    created_by INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS email_outbox (
    id INTEGER PRIMARY KEY,
    to_email TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    proposal_id INTEGER REFERENCES proposals(id),
    kind TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with get_connection() as conn:
        conn.executescript(SCHEMA)