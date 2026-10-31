"""ShopZone — SQLite persistence layer.

Schema (idempotent), seed data, and auth/password helpers shared by the API.
All money is stored as INTEGER CENTS to avoid float rounding bugs.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(BASE_DIR, "app.db")

PBKDF2_ITERATIONS = 120_000
SESSION_TTL_DAYS = 7

# Business constants (used by checkout math on the server).
FREE_SHIPPING_THRESHOLD_CENTS = 3500
FLAT_SHIPPING_CENTS = 499
TAX_RATE = 0.0825

ORDER_STATUSES = ("placed", "processing", "shipped", "delivered", "cancelled")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    name          TEXT    NOT NULL,
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'customer'
                  CHECK (role IN ('customer','admin')),
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT    PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT    NOT NULL,
    expires_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT    NOT NULL,
    description  TEXT    NOT NULL DEFAULT '',
    category     TEXT    NOT NULL,
    price_cents  INTEGER NOT NULL CHECK (price_cents >= 0),
    stock        INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
    rating       REAL    NOT NULL DEFAULT 0.0 CHECK (rating >= 0.0 AND rating <= 5.0),
    rating_count INTEGER NOT NULL DEFAULT 0 CHECK (rating_count >= 0),
    vendor       TEXT    NOT NULL DEFAULT 'ShopZone Retail',
    emoji        TEXT    NOT NULL DEFAULT '📦',
    hue          INTEGER NOT NULL DEFAULT 210,
    active       INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_at   TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
CREATE INDEX IF NOT EXISTS idx_products_active   ON products(active);

CREATE TABLE IF NOT EXISTS orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER REFERENCES users(id),
    email           TEXT    NOT NULL,
    items_json      TEXT    NOT NULL,
    subtotal_cents  INTEGER NOT NULL CHECK (subtotal_cents >= 0),
    shipping_cents  INTEGER NOT NULL CHECK (shipping_cents >= 0),
    tax_cents       INTEGER NOT NULL CHECK (tax_cents >= 0),
    total_cents     INTEGER NOT NULL CHECK (total_cents >= 0),
    status          TEXT    NOT NULL DEFAULT 'placed'
                    CHECK (status IN ('placed','processing','shipped','delivered','cancelled')),
    ship_name       TEXT    NOT NULL,
    ship_line1      TEXT    NOT NULL,
    ship_city       TEXT    NOT NULL,
    ship_state      TEXT    NOT NULL,
    ship_zip        TEXT    NOT NULL,
    ship_country    TEXT    NOT NULL DEFAULT 'USA',
    idempotency_key TEXT UNIQUE,
    created_at      TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_orders_key  ON orders(idempotency_key);

CREATE TABLE IF NOT EXISTS reviews (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    user_id    INTEGER REFERENCES users(id),
    author     TEXT    NOT NULL,
    rating     INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment    TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reviews_product ON reviews(product_id);
"""

SEED_PRODUCTS = [
    # title, category, price_cents, stock, rating, rating_count, vendor, emoji, hue, description
    ("Aurora ANC Wireless Headphones", "Electronics", 12999, 42, 4.6, 1284, "Aurora Audio", "🎧", 232,
     "Over-ear Bluetooth 5.3 headphones with hybrid active noise cancellation, 40-hour battery, and USB-C fast charge."),
    ("Nimbus 14 Ultrabook 16GB/512GB", "Electronics", 89900, 8, 4.4, 312, "Nimbus Computing", "💻", 205,
     "14-inch 2.8K OLED laptop with a 12-core processor, 16GB RAM, 512GB SSD, and all-day 18-hour battery life."),
    ("PulseFit Smartwatch Series 5", "Electronics", 7999, 55, 4.2, 867, "PulseFit", "⌚", 260,
     "AMOLED smartwatch with heart-rate and SpO2 tracking, GPS workout mapping, and 10-day standby battery."),
    ("EchoDome Portable Bluetooth Speaker", "Electronics", 4599, 120, 4.1, 2043, "EchoDome", "🔊", 285,
     "360-degree sound, IPX7 waterproofing, and 20 hours of playtime in a pocketable rugged shell."),
    ("Lumen 4K Action Camera", "Electronics", 14999, 18, 4.5, 521, "Lumen Optics", "📷", 195,
     "4K60 action camera with hyper-stabilization, waterproof to 10m without a case, and Wi-Fi offload."),
    ("VoltEdge 65W GaN Wall Charger", "Electronics", 2999, 200, 4.7, 3901, "VoltEdge", "🔌", 45,
     "Three-port GaN charger that powers a laptop and two phones at once, 40% smaller than stock bricks."),
    ("ChefCore 10-Piece Nonstick Cookware Set", "Home & Kitchen", 7999, 30, 4.3, 745, "ChefCore", "🍳", 25,
     "Ceramic nonstick pots and pans with stay-cool handles; oven safe to 400F and dishwasher friendly."),
    ("BrewMaster Precision Pour-Over Kettle", "Home & Kitchen", 5499, 47, 4.8, 1109, "BrewMaster", "☕", 15,
     "Gooseneck kettle with 1-degree temperature control, hold mode, and a balanced counterweighted handle."),
    ("SwiftClean Robot Vacuum", "Home & Kitchen", 24999, 12, 4.1, 632, "SwiftClean", "🧹", 190,
     "LiDAR-mapping robot vacuum with 2700Pa suction, auto-boost on carpet, and app zone scheduling."),
    ("CloudNest Memory Foam Pillow (2-Pack)", "Home & Kitchen", 3999, 80, 4.4, 2870, "CloudNest", "🛏️", 265,
     "Shredded gel memory foam pillows you can dial to your loft; machine-washable bamboo covers."),
    ("The Silent Ledger — Hardcover Thriller", "Books", 1899, 140, 4.5, 5231, "Meridian Press", "📚", 350,
     "A forensic accountant uncovers a laundering scheme that reaches her own family firm. 416 pages."),
    ("Deep Focus: The Science of Attention", "Books", 1599, 96, 4.6, 1893, "Meridian Press", "📖", 30,
     "A research-backed guide to training attention in an age of infinite distraction."),
    ("Trailcrest Waterproof Hiking Shoes", "Fashion", 6999, 64, 4.3, 954, "Trailcrest", "👟", 120,
     "Breathable waterproof membrane, grippy Vibram-style outsole, and a rock plate for technical trails."),
    ("Everyday Merino Crew Tee", "Fashion", 3499, 150, 4.2, 410, "Northloom", "👕", 210,
     "17.5-micron merino wool tee that resists odor for days of wear; machine washable."),
    ("Calla Leather Crossbody Bag", "Fashion", 8999, 22, 4.7, 388, "Calla Atelier", "👜", 340,
     "Full-grain vegetable-tanned leather crossbody with waxed canvas lining and brass hardware."),
    ("IronForge Adjustable Dumbbell 5-52 lb", "Sports & Outdoors", 29999, 10, 4.6, 720, "IronForge", "🏋️", 0,
     "Dial-adjustable dumbbell replaces 15 pairs; safety-lock cradle and knurled steel handle."),
    ("ZenFlow Yoga Mat 6mm Non-Slip", "Sports & Outdoors", 2599, 90, 4.4, 1560, "ZenFlow", "🧘", 160,
     "Closed-cell TPE mat with alignment lines; grips when wet and ships with a carry strap."),
    ("Summit 45L Trekking Backpack", "Sports & Outdoors", 11999, 5, 4.8, 296, "Summit Gear", "🎒", 100,
     "Load-transferring aluminum frame, 45 liters of daisy-chained storage, rain cover included."),
    ("GalaxyBrick Space Station 1,200 pcs", "Toys & Games", 5999, 40, 4.9, 812, "GalaxyBrick", "🚀", 240,
     "Buildable orbital station with rotating solar arrays, mini crew, and a comic-style build guide."),
    ("PuzzlePeak 1,000-Pc Mountain Vista", "Toys & Games", 1499, 75, 4.3, 233, "PuzzlePeak", "🧩", 130,
     "Linen-finish puzzle with poster reference; low-glare print and precision die cut."),
    ("Glowlab Vitamin C Serum 30ml", "Beauty", 2199, 110, 4.5, 3344, "Glowlab", "🧴", 320,
     "15% stabilized vitamin C with ferulic acid and vitamin E; fragrance-free, dermatologist tested."),
    ("Silkline Ionic Hair Dryer", "Beauty", 4999, 33, 4.2, 677, "Silkline", "💨", 55,
     "Brushless ionic dryer with 4 heat and 2 speed settings, cool shot, and concentrator nozzle."),
    ("Cascade Roasters Whole Bean Coffee 2lb", "Grocery", 2399, 130, 4.7, 4102, "Cascade Roasters", "☕", 20,
     "Medium roast single-origin Colombian beans; roasted-to-order and shipped within 48 hours."),
    ("Alpine Trail Mix Family Pack", "Grocery", 1299, 88, 4.1, 519, "Alpine Harvest", "🥜", 80,
     "Roasted almonds, cashews, cranberries, and dark chocolate chips. No artificial anything."),
]


def db_path() -> str:
    return os.environ.get("SHOPZONE_DB", DEFAULT_DB)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


# --------------------------------------------------------------------------- auth

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS
    )
    return f"pbkdf2${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iters, salt, digest = stored.split("$")
        if scheme != "pbkdf2":
            return False
        calc = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iters)
        )
        return secrets.compare_digest(calc.hex(), digest)
    except (ValueError, TypeError):
        return False


def create_session(conn: sqlite3.Connection, user_id: int) -> str:
    token = secrets.token_hex(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS)).isoformat(
        timespec="seconds"
    )
    conn.execute(
        "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?,?,?,?)",
        (token, user_id, now_iso(), expires),
    )
    conn.commit()
    return token


def user_for_token(conn: sqlite3.Connection, token: str | None):
    if not token:
        return None
    return conn.execute(
        "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id"
        " WHERE s.token = ? AND s.expires_at > ?",
        (token, now_iso()),
    ).fetchone()


def delete_session(conn: sqlite3.Connection, token: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()


# --------------------------------------------------------------------------- seeding

def seed_products(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT INTO products"
        " (title, description, category, price_cents, stock, rating, rating_count,"
        "  vendor, emoji, hue, active, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,1,?)",
        [(t, d, c, p, s, r, rc, v, e, h, now_iso())
         for (t, c, p, s, r, rc, v, e, h, d) in SEED_PRODUCTS],
    )


def seed_users(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT INTO users (email, name, password_hash, role, created_at) VALUES (?,?,?,?,?)",
        [
            ("admin@shopzone.demo", "Store Admin", hash_password("admin123"), "admin", now_iso()),
            ("demo@shopzone.demo", "Demo Shopper", hash_password("demo1234"), "customer", now_iso()),
        ],
    )


def init_db() -> str:
    """Create tables and seed demo data. Safe to call on every boot."""
    conn = get_conn()
    try:
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) AS n FROM products").fetchone()["n"] == 0:
            seed_products(conn)
        if conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] == 0:
            seed_users(conn)
        conn.commit()
    finally:
        conn.close()
    return db_path()
