"""Database layer: schema, connection helpers, and seed catalog.

SQLite with real relational tables — products, users, carts, orders.
All prices are stored as integer cents to avoid float money bugs.
"""
import os
import sqlite3
import hashlib
import secrets

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("SHOP_DB", os.path.join(BASE_DIR, "shop.db"))

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT UNIQUE NOT NULL,
    name          TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'customer' CHECK (role IN ('customer','admin')),
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sku         TEXT UNIQUE NOT NULL,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    category    TEXT NOT NULL,
    brand       TEXT NOT NULL DEFAULT '',
    price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
    stock       INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
    rating      REAL NOT NULL DEFAULT 0 CHECK (rating >= 0 AND rating <= 5),
    image_url   TEXT NOT NULL DEFAULT '',
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS carts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    token      TEXT UNIQUE NOT NULL,
    user_email TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS cart_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    cart_id    INTEGER NOT NULL REFERENCES carts(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id),
    qty        INTEGER NOT NULL CHECK (qty > 0),
    UNIQUE (cart_id, product_id)
);

CREATE TABLE IF NOT EXISTS orders (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    order_number TEXT UNIQUE NOT NULL,
    customer_name TEXT NOT NULL,
    email        TEXT NOT NULL,
    address      TEXT NOT NULL,
    total_cents  INTEGER NOT NULL CHECK (total_cents >= 0),
    status       TEXT NOT NULL DEFAULT 'placed'
                 CHECK (status IN ('placed','paid','shipped','delivered','cancelled')),
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS order_items (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id       INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id     INTEGER NOT NULL REFERENCES products(id),
    title_snapshot TEXT NOT NULL,
    price_cents    INTEGER NOT NULL,
    qty            INTEGER NOT NULL CHECK (qty > 0)
);

CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
CREATE INDEX IF NOT EXISTS idx_products_title ON products(title);
CREATE INDEX IF NOT EXISTS idx_cart_items_cart ON cart_items(cart_id);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
"""

SEED_PRODUCTS = [
    # (sku, title, category, brand, price_cents, stock, rating, description)
    ("ELEC-001", "AuraSound Pro Wireless Headphones", "Electronics", "AuraSound", 19900, 42, 4.7,
     "Active noise cancelling over-ear headphones with 40-hour battery and fast charge."),
    ("ELEC-002", "Nimbus 4K Smart TV 55\"", "Electronics", "Nimbus", 54900, 15, 4.5,
     "55-inch 4K HDR smart TV with voice remote and three HDMI 2.1 ports."),
    ("ELEC-003", "VoltCore 20000mAh Power Bank", "Electronics", "VoltCore", 3999, 130, 4.3,
     "USB-C PD 30W fast-charging power bank, charges a laptop and a phone together."),
    ("ELEC-004", "PulseFit 3 Fitness Watch", "Electronics", "PulseFit", 12900, 60, 4.6,
     "GPS, heart-rate and sleep tracking with 10-day battery life."),
    ("ELEC-005", "EchoType Mechanical Keyboard", "Electronics", "EchoType", 8900, 35, 4.4,
     "Hot-swappable tactile switches, RGB per-key lighting, aluminium frame."),
    ("HOME-001", "CloudNine Weighted Blanket 15lb", "Home & Kitchen", "CloudNine", 7900, 48, 4.8,
     "Breathable glass-bead weighted blanket, machine washable cotton cover."),
    ("HOME-002", "BaristaPro Espresso Machine", "Home & Kitchen", "BaristaPro", 34900, 18, 4.6,
     "15-bar pump espresso machine with steam wand and precision grinder."),
    ("HOME-003", "PureAir HEPA Air Purifier", "Home & Kitchen", "PureAir", 15900, 27, 4.5,
     "Covers 900 sq ft, captures 99.97% of particles, whisper-quiet night mode."),
    ("HOME-004", "Chef's Edge 10-Piece Knife Set", "Home & Kitchen", "Chef's Edge", 12900, 22, 4.7,
     "German stainless steel with self-sharening walnut block."),
    ("HOME-005", "Lumen Smart Desk Lamp", "Home & Kitchen", "Lumen", 4999, 80, 4.2,
     "Tunable white and RGB, wireless charging pad in the base."),
    ("BOOK-001", "The Lean Startup — Hardcover", "Books", "Currency", 1899, 200, 4.6,
     "Eric Ries on continuous innovation and validated learning."),
    ("BOOK-002", "Zero to One — Paperback", "Books", "Crown Business", 1499, 180, 4.5,
     "Peter Thiel's notes on startups and building the future."),
    ("BOOK-003", "Dune: 40th Anniversary Edition", "Books", "Ace", 2499, 90, 4.8,
     "Frank Herbert's sci-fi masterpiece with new foreword."),
    ("BOOK-004", "Atomic Habits — Hardcover", "Books", "Avery", 1699, 150, 4.8,
     "James Clear's system for building good habits and breaking bad ones."),
    ("FASH-001", "Northwind Merino Wool Sweater", "Fashion", "Northwind", 8900, 55, 4.4,
     "100% extra-fine merino wool, machine washable, three colourways."),
    ("FASH-002", "TrailBlaze Waterproof Hiking Boots", "Fashion", "TrailBlaze", 13900, 30, 4.6,
     "Gore-Tex membrane, vibram outsole, ankle support for day hikes."),
    ("FASH-003", "Everyday Carry Canvas Backpack", "Fashion", "FieldKit", 5900, 75, 4.3,
     "22L waxed canvas with padded 15\" laptop sleeve."),
    ("FASH-004", "Solstice Polarized Sunglasses", "Fashion", "Solstice", 6900, 65, 4.1,
     "UV400 polarized lenses with spring hinges and hard case."),
    ("TOYS-001", "CosmoBlox 250-Piece Building Set", "Toys & Games", "CosmoBlox", 4499, 110, 4.7,
     "STEM-compatible bricks with idea booklet, ages 6+."),
    ("TOYS-002", "StarQuest Strategy Board Game", "Toys & Games", "Nebula Games", 3999, 40, 4.6,
     "Area-control space strategy for 2-5 players, 60-90 minutes."),
    ("TOYS-003", "SkyRacer Pro RC Drone", "Toys & Games", "SkyRacer", 8999, 25, 4.2,
     "720p camera, altitude hold, two batteries for 24 minutes of flight."),
    ("SPTS-001", "FlexCore Adjustable Dumbbell 55lb", "Sports", "FlexCore", 21900, 20, 4.5,
     "Dial-a-weight from 5 to 55 lb, replaces 15 dumbbells."),
    ("SPTS-002", "HydroPeak Insulated Bottle 32oz", "Sports", "HydroPeak", 2999, 140, 4.8,
     "Double-wall vacuum insulation keeps drinks cold 24h or hot 12h."),
    ("SPTS-003", "AscentPro Yoga Mat 6mm", "Sports", "AscentPro", 3499, 95, 4.4,
     "Non-slip TPE mat with alignment lines and carry strap."),
]


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(8)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, _ = stored.split("$", 1)
    except ValueError:
        return False
    return secrets.compare_digest(hash_password(password, salt), stored)


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(reseed: bool = False) -> None:
    conn = get_conn()
    try:
        conn.executescript(SCHEMA)
        if reseed:
            for table in ("order_items", "orders", "cart_items", "carts", "products", "users"):
                conn.execute(f"DELETE FROM {table}")
        user_count = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
        if user_count == 0:
            conn.executemany(
                "INSERT INTO users (email, name, password_hash, role) VALUES (?, ?, ?, ?)",
                [
                    ("admin@pulsegear.com", "Store Admin", hash_password("admin123"), "admin"),
                    ("demo@pulsegear.com", "Demo Customer", hash_password("demo123"), "customer"),
                ],
            )
        product_count = conn.execute("SELECT COUNT(*) AS n FROM products").fetchone()["n"]
        if product_count == 0:
            conn.executemany(
                """INSERT INTO products
                   (sku, title, description, category, brand, price_cents, stock, rating, image_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (sku, title, desc, cat, brand, price, stock, rating,
                     f"https://picsum.photos/seed/{sku}/480/480")
                    for (sku, title, cat, brand, price, stock, rating, desc) in SEED_PRODUCTS
                ],
            )
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    init_db(reseed="--reseed" in __import__("sys").argv)
    conn = get_conn()
    print("users:", conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])
    print("products:", conn.execute("SELECT COUNT(*) FROM products").fetchone()[0])
    conn.close()
