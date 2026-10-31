"""PulseCart — Amazon-style e-commerce backend.

Pure Python 3.11 stdlib (no third-party deps): threaded HTTP server + SQLite.
Run:  python server.py   ->  http://localhost:8000
Seed admin login: admin@pulsecart.com / admin12345
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "pulsecart.db"
FRONTEND_DIR = ROOT / "frontend"
PORT = int(__import__("os").environ.get("PORT", "8000"))
SESSION_TTL = timedelta(days=7)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# --------------------------------------------------------------------------- #
# Errors / helpers
# --------------------------------------------------------------------------- #
class ApiError(Exception):
    def __init__(self, status: int, message: str, **extra):
        super().__init__(message)
        self.status = status
        self.message = message
        self.extra = extra


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, _ = stored.split("$", 1)
    except ValueError:
        return False
    return secrets.compare_digest(hash_password(password, salt), stored)


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def require_fields(body: dict, *names: str) -> None:
    for name in names:
        value = body.get(name)
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ApiError(400, f"Missing required field: {name}")


# --------------------------------------------------------------------------- #
# Schema + seed data
# --------------------------------------------------------------------------- #
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'customer' CHECK (role IN ('customer','admin')),
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    category    TEXT NOT NULL,
    price_cents INTEGER NOT NULL CHECK (price_cents > 0),
    stock       INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
    rating      REAL NOT NULL DEFAULT 4.0 CHECK (rating BETWEEN 0 AND 5),
    rating_count INTEGER NOT NULL DEFAULT 0,
    emoji       TEXT NOT NULL DEFAULT '📦',
    color       TEXT NOT NULL DEFAULT '#232f3e',
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cart_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    qty        INTEGER NOT NULL CHECK (qty > 0),
    UNIQUE (user_id, product_id)
);
CREATE TABLE IF NOT EXISTS orders (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id),
    total_cents  INTEGER NOT NULL,
    status       TEXT NOT NULL DEFAULT 'placed'
                 CHECK (status IN ('placed','shipped','delivered','cancelled')),
    full_name    TEXT NOT NULL,
    address_line1 TEXT NOT NULL,
    city         TEXT NOT NULL,
    state        TEXT NOT NULL,
    zip          TEXT NOT NULL,
    country      TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS order_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id    INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id  INTEGER NOT NULL REFERENCES products(id),
    title       TEXT NOT NULL,
    qty         INTEGER NOT NULL,
    price_cents INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
CREATE INDEX IF NOT EXISTS idx_cart_user ON cart_items(user_id);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
"""

SEED_PRODUCTS = [
    # (title, description, category, price_cents, stock, rating, rating_count, emoji, color)
    ("AuraSound Wireless Headphones", "Over-ear ANC headphones with 40h battery, multipoint Bluetooth and USB-C fast charge.", "Electronics", 12900, 42, 4.6, 2311, "🎧", "#1b2a4a"),
    ("Nimbus 4K Smart TV 55\"", "Dolby Vision 4K panel with voice remote, 3 HDMI ports and streaming apps built in.", "Electronics", 44900, 18, 4.5, 987, "📺", "#0f2733"),
    ("VoltCore 20K Power Bank", "65W USB-C PD power bank that charges a laptop and two phones at once.", "Electronics", 5900, 120, 4.7, 4102, "🔋", "#243b2f"),
    ("PixelPulse Smartwatch", "AMOLED fitness watch with GPS, SpO2 tracking and 10-day battery life.", "Electronics", 15900, 55, 4.4, 1876, "⌚", "#2a1b3d"),
    ("SwiftKey Mechanical Keyboard", "Hot-swappable 75% mechanical keyboard with PBT keycaps and per-key RGB.", "Electronics", 8900, 63, 4.8, 5220, "⌨️", "#33261a"),
    ("EchoLite Bluetooth Speaker", "Palm-sized IPX7 speaker with 360° sound and 18 hours of playtime.", "Electronics", 3900, 200, 4.3, 3120, "🔊", "#123244"),
    ("The Silent Algorithm", "A thriller about a rogue trading bot that starts predicting elections.", "Books", 1499, 340, 4.6, 8210, "📘", "#1e3a5f"),
    ("Orbital Gardens", "Hard sci-fi epic: the first generation ship grows more than crops.", "Books", 1899, 210, 4.7, 5430, "🚀", "#2d1b3d"),
    ("Cook Once, Eat All Week", "90 batch-cooking recipes with shopping lists and 30-minute prep.", "Books", 2199, 175, 4.5, 2980, "📗", "#1f3d2b"),
    ("Founders' Fault Lines", "Twelve case studies of startups that nearly died and what saved them.", "Books", 2499, 88, 4.4, 1120, "📙", "#3d2b1f"),
    ("NimbusCloud Memory Foam Pillow", "Cooling gel-infused memory foam pillow with washable bamboo cover.", "Home & Kitchen", 4500, 150, 4.4, 6600, "🛏️", "#2f3a45"),
    ("BrewMaster Pour-Over Kettle", "Gooseneck electric kettle with ±1°C control and 60-minute hold.", "Home & Kitchen", 6900, 95, 4.8, 7340, "🫖", "#3d2f1b"),
    ("TerraCeramic 12-Piece Cookware", "Nonstick ceramic pots and pans, oven safe to 260°C, induction ready.", "Home & Kitchen", 12900, 44, 4.5, 2870, "🍳", "#3b2a2a"),
    ("LumaGlow Sunset Lamp", "16-color sunset projection lamp with remote and sleep timer.", "Home & Kitchen", 2900, 260, 4.2, 5100, "💡", "#3d1b2f"),
    ("EverFold Storage Cubes (6-Pack)", "Collapsible fabric organizer bins with reinforced handles and labels.", "Home & Kitchen", 2500, 180, 4.3, 3900, "🧺", "#2b3d2b"),
    ("AeroRunner Running Shoes", "Carbon-plated marathon trainers with recycled knit upper.", "Fashion", 13900, 70, 4.6, 4460, "👟", "#2a2a3d"),
    ("Northline Canvas Weekender", "40L water-resistant travel duffel with shoe garage and laptop sleeve.", "Fashion", 8900, 60, 4.5, 1900, "🎒", "#33301b"),
    ("Solstice Polarized Sunglasses", "UV400 polarized lenses in a lightweight titanium frame.", "Fashion", 7900, 110, 4.4, 2210, "🕶️", "#1b1b2a"),
    ("Merino Everyday Crew Socks (4-Pack)", "Temperature-regulating merino wool blend, cushioned heel and toe.", "Fashion", 3200, 240, 4.7, 8800, "🧦", "#2b2b3d"),
    ("Cosmic Builders Mega Set", "620-piece STEM construction kit with motor and 30 build guides.", "Toys & Games", 5900, 85, 4.8, 6120, "🧱", "#3d1b1b"),
    ("Galaxy Strategy Board Game", "Area-control board game for 2–5 players, 60–90 minutes per session.", "Toys & Games", 4900, 74, 4.7, 3550, "🎲", "#1b2f3d"),
    ("SkyPilot Stunt Drone", "Beginner-friendly drone with auto-hover, headless mode and 2 batteries.", "Toys & Games", 7900, 48, 4.2, 1470, "🛸", "#22332b"),
    ("TrailBlaze 3L Hydration Pack", "Lightweight running vest with 3L bladder and four front pockets.", "Sports", 6500, 66, 4.5, 2030, "🥾", "#2b3d1b"),
    ("IronCore Adjustable Dumbbells", "Pair of 5–52.5 lb dial dumbbells with compact storage trays.", "Sports", 29900, 25, 4.6, 4780, "🏋️", "#2f2f2f"),
    ("FlowState Yoga Mat Pro", "6mm non-slip TPE mat with alignment lines and carry strap.", "Sports", 4200, 130, 4.4, 2940, "🧘", "#1b3d3d"),
    ("StormDash Basketball (Official)", "Indoor/outdoor composite leather ball with moisture-wicking grip.", "Sports", 3600, 160, 4.3, 2610, "🏀", "#3d2a12"),
]


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = db()
    try:
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
            stamp = now_iso()
            conn.executemany(
                """INSERT INTO products
                   (title, description, category, price_cents, stock, rating,
                    rating_count, emoji, color, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                [(*p, stamp) for p in SEED_PRODUCTS],
            )
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            conn.execute(
                "INSERT INTO users (email, name, password_hash, role, created_at) VALUES (?,?,?,?,?)",
                ("admin@pulsecart.com", "PulseCart Admin",
                 hash_password("admin12345"), "admin", now_iso()),
            )
            conn.execute(
                "INSERT INTO users (email, name, password_hash, role, created_at) VALUES (?,?,?,?,?)",
                ("demo@pulsecart.com", "Demo Shopper",
                 hash_password("demo12345"), "customer", now_iso()),
            )
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Request context + routing
# --------------------------------------------------------------------------- #
class Ctx:
    def __init__(self, method: str, path: str, params: dict, body: dict, user: dict | None):
        self.method = method
        self.path = path
        self.params = params      # dict[str, list[str]]
        self.body = body
        self.user = user
        self.path_groups: tuple[str, ...] = ()

    def q(self, name: str, default: str = "") -> str:
        values = self.params.get(name)
        return values[0] if values else default


ROUTES: list[tuple[str, re.Pattern, object]] = []


def route(method: str, pattern: str):
    compiled = re.compile("^" + pattern + "$")

    def decorator(fn):
        ROUTES.append((method, compiled, fn))
        return fn

    return decorator


def current_user(conn: sqlite3.Connection, headers) -> dict | None:
    auth = headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:].strip()
    if not token:
        return None
    row = conn.execute(
        """SELECT u.id, u.email, u.name, u.role, s.token, s.expires_at
           FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?""",
        (token,),
    ).fetchone()
    if row is None or row["expires_at"] < now_iso():
        if row is not None:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            conn.commit()
        return None
    return {"id": row["id"], "email": row["email"], "name": row["name"],
            "role": row["role"], "token": row["token"]}


def require_user(ctx: Ctx) -> dict:
    if ctx.user is None:
        raise ApiError(401, "Sign in required")
    return ctx.user


def require_admin(ctx: Ctx) -> dict:
    user = require_user(ctx)
    if user["role"] != "admin":
        raise ApiError(403, "Admin access required")
    return user


def product_row_to_dict(row) -> dict:
    return dict(row)


# --------------------------------------------------------------------------- #
# Auth routes
# --------------------------------------------------------------------------- #
@route("POST", r"/api/auth/register")
def register(ctx: Ctx, conn):
    require_fields(ctx.body, "name", "email", "password")
    name, email, password = ctx.body["name"].strip(), ctx.body["email"].strip().lower(), ctx.body["password"]
    if not EMAIL_RE.match(email):
        raise ApiError(400, "Invalid email address")
    if len(password) < 8:
        raise ApiError(400, "Password must be at least 8 characters")
    if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
        raise ApiError(409, "An account with this email already exists")
    cur = conn.execute(
        "INSERT INTO users (email, name, password_hash, role, created_at) VALUES (?,?,?,?,?)",
        (email, name, hash_password(password), "customer", now_iso()),
    )
    token = create_session(conn, cur.lastrowid)
    conn.commit()
    return 201, {"token": token, "user": {"id": cur.lastrowid, "email": email, "name": name, "role": "customer"}}


@route("POST", r"/api/auth/login")
def login(ctx: Ctx, conn):
    require_fields(ctx.body, "email", "password")
    email, password = ctx.body["email"].strip().lower(), ctx.body["password"]
    row = conn.execute(
        "SELECT id, email, name, role, password_hash FROM users WHERE email = ?", (email,)
    ).fetchone()
    if row is None or not verify_password(password, row["password_hash"]):
        raise ApiError(401, "Invalid email or password")
    token = create_session(conn, row["id"])
    conn.commit()
    return 200, {"token": token,
                 "user": {"id": row["id"], "email": row["email"], "name": row["name"], "role": row["role"]}}


def create_session(conn: sqlite3.Connection, user_id: int) -> str:
    token = secrets.token_hex(32)
    conn.execute(
        "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?,?,?,?)",
        (token, user_id, now_iso(), (datetime.now(timezone.utc) + SESSION_TTL).isoformat()),
    )
    return token


@route("POST", r"/api/auth/logout")
def logout(ctx: Ctx, conn):
    user = require_user(ctx)
    conn.execute("DELETE FROM sessions WHERE token = ?", (user["token"],))
    conn.commit()
    return 200, {"ok": True}


@route("GET", r"/api/auth/me")
def me(ctx: Ctx, conn):
    user = require_user(ctx)
    return 200, {"user": {k: user[k] for k in ("id", "email", "name", "role")}}


# --------------------------------------------------------------------------- #
# Catalog routes
# --------------------------------------------------------------------------- #
SORTS = {
    "newest": "p.created_at DESC, p.id DESC",
    "price_asc": "p.price_cents ASC",
    "price_desc": "p.price_cents DESC",
    "rating": "p.rating DESC, p.rating_count DESC",
    "title": "p.title ASC",
}


@route("GET", r"/api/products")
def list_products(ctx: Ctx, conn):
    search = ctx.q("search").strip()
    category = ctx.q("category").strip()
    sort = ctx.q("sort", "newest")
    try:
        page = max(1, int(ctx.q("page", "1")))
        per_page = min(60, max(1, int(ctx.q("per_page", "12"))))
    except ValueError:
        raise ApiError(400, "page and per_page must be integers")
    min_price = ctx.q("min_price")
    max_price = ctx.q("max_price")
    min_rating = ctx.q("min_rating")

    where, args = ["1=1"], []
    if search:
        where.append("(LOWER(p.title) LIKE ? OR LOWER(p.description) LIKE ?)")
        like = f"%{search.lower()}%"
        args += [like, like]
    if category:
        where.append("p.category = ?")
        args.append(category)
    if min_price:
        where.append("p.price_cents >= ?")
        args.append(int(min_price) * 100)
    if max_price:
        where.append("p.price_cents <= ?")
        args.append(int(max_price) * 100)
    if min_rating:
        where.append("p.rating >= ?")
        args.append(float(min_rating))

    where_sql = " AND ".join(where)
    order_sql = SORTS.get(sort, SORTS["newest"])
    total = conn.execute(
        f"SELECT COUNT(*) FROM products p WHERE {where_sql}", args
    ).fetchone()[0]
    rows = conn.execute(
        f"""SELECT p.* FROM products p WHERE {where_sql}
            ORDER BY {order_sql} LIMIT ? OFFSET ?""",
        args + [per_page, (page - 1) * per_page],
    ).fetchall()
    categories = [r[0] for r in conn.execute(
        "SELECT DISTINCT category FROM products ORDER BY category")]
    return 200, {
        "products": [product_row_to_dict(r) for r in rows],
        "total": total, "page": page, "per_page": per_page,
        "pages": max(1, -(-total // per_page)),
        "categories": categories,
    }


@route("GET", r"/api/products/(\d+)")
def get_product(ctx: Ctx, conn):
    row = conn.execute("SELECT * FROM products WHERE id = ?", (ctx.path_groups[0],)).fetchone()
    if row is None:
        raise ApiError(404, "Product not found")
    return 200, {"product": product_row_to_dict(row)}


# --------------------------------------------------------------------------- #
# Cart routes
# --------------------------------------------------------------------------- #
@route("GET", r"/api/cart")
def get_cart(ctx: Ctx, conn):
    user = require_user(ctx)
    rows = conn.execute(
        """SELECT c.id, c.qty, p.id AS product_id, p.title, p.price_cents, p.stock,
                  p.emoji, p.color, p.rating
           FROM cart_items c JOIN products p ON p.id = c.product_id
           WHERE c.user_id = ? ORDER BY c.id""",
        (user["id"],),
    ).fetchall()
    items = [dict(r) for r in rows]
    subtotal = sum(i["price_cents"] * i["qty"] for i in items)
    return 200, {"items": items, "subtotal_cents": subtotal,
                 "count": sum(i["qty"] for i in items)}


@route("POST", r"/api/cart")
def add_to_cart(ctx: Ctx, conn):
    user = require_user(ctx)
    require_fields(ctx.body, "product_id")
    product_id = int(ctx.body["product_id"])
    qty = int(ctx.body.get("qty", 1))
    if qty < 1:
        raise ApiError(400, "Quantity must be at least 1")
    product = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if product is None:
        raise ApiError(404, "Product not found")
    if product["stock"] < 1:
        raise ApiError(409, "Product is out of stock")
    existing = conn.execute(
        "SELECT id, qty FROM cart_items WHERE user_id = ? AND product_id = ?",
        (user["id"], product_id),
    ).fetchone()
    new_qty = (existing["qty"] + qty) if existing else qty
    if new_qty > product["stock"]:
        raise ApiError(409, f"Only {product['stock']} in stock")
    if existing:
        conn.execute("UPDATE cart_items SET qty = ? WHERE id = ?", (new_qty, existing["id"]))
    else:
        conn.execute(
            "INSERT INTO cart_items (user_id, product_id, qty) VALUES (?,?,?)",
            (user["id"], product_id, qty),
        )
    conn.commit()
    return 201, {"ok": True, "message": f"Added {product['title']} to cart"}


@route("PATCH", r"/api/cart/(\d+)")
def update_cart_item(ctx: Ctx, conn):
    user = require_user(ctx)
    item_id, qty = ctx.path_groups[0], int(ctx.body.get("qty", 1))
    item = conn.execute(
        """SELECT c.id, c.product_id, p.stock FROM cart_items c
           JOIN products p ON p.id = c.product_id
           WHERE c.id = ? AND c.user_id = ?""",
        (item_id, user["id"]),
    ).fetchone()
    if item is None:
        raise ApiError(404, "Cart item not found")
    if qty < 1:
        conn.execute("DELETE FROM cart_items WHERE id = ?", (item_id,))
    else:
        if qty > item["stock"]:
            raise ApiError(409, f"Only {item['stock']} in stock")
        conn.execute("UPDATE cart_items SET qty = ? WHERE id = ?", (qty, item_id))
    conn.commit()
    return 200, {"ok": True}


@route("DELETE", r"/api/cart/(\d+)")
def delete_cart_item(ctx: Ctx, conn):
    user = require_user(ctx)
    cur = conn.execute(
        "DELETE FROM cart_items WHERE id = ? AND user_id = ?",
        (ctx.path_groups[0], user["id"]),
    )
    if cur.rowcount == 0:
        raise ApiError(404, "Cart item not found")
    conn.commit()
    return 200, {"ok": True}


# --------------------------------------------------------------------------- #
# Checkout + orders
# --------------------------------------------------------------------------- #
@route("POST", r"/api/checkout")
def checkout(ctx: Ctx, conn):
    user = require_user(ctx)
    require_fields(ctx.body, "full_name", "address_line1", "city", "state", "zip", "country")
    items = conn.execute(
        """SELECT c.product_id, c.qty, p.title, p.price_cents, p.stock
           FROM cart_items c JOIN products p ON p.id = c.product_id
           WHERE c.user_id = ? ORDER BY c.id""",
        (user["id"],),
    ).fetchall()
    if not items:
        raise ApiError(400, "Your cart is empty")
    for item in items:
        if item["qty"] > item["stock"]:
            raise ApiError(409, f"Only {item['stock']} left of '{item['title']}'")
    total = sum(i["price_cents"] * i["qty"] for i in items)

    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            """INSERT INTO orders (user_id, total_cents, status, full_name,
                                   address_line1, city, state, zip, country, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (user["id"], total, "placed", ctx.body["full_name"].strip(),
             ctx.body["address_line1"].strip(), ctx.body["city"].strip(),
             ctx.body["state"].strip(), ctx.body["zip"].strip(),
             ctx.body["country"].strip(), now_iso()),
        )
        order_id = cur.lastrowid
        for item in items:
            conn.execute(
                """INSERT INTO order_items (order_id, product_id, title, qty, price_cents)
                   VALUES (?,?,?,?,?)""",
                (order_id, item["product_id"], item["title"], item["qty"], item["price_cents"]),
            )
            conn.execute(
                "UPDATE products SET stock = stock - ? WHERE id = ?",
                (item["qty"], item["product_id"]),
            )
        conn.execute("DELETE FROM cart_items WHERE user_id = ?", (user["id"],))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return 201, {"order": get_order_dict(conn, order_id, user["id"])}


def get_order_dict(conn: sqlite3.Connection, order_id: int, user_id: int | None) -> dict:
    row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if row is None or (user_id is not None and row["user_id"] != user_id):
        raise ApiError(404, "Order not found")
    order = dict(row)
    order["items"] = [dict(r) for r in conn.execute(
        "SELECT * FROM order_items WHERE order_id = ?", (order_id,))]
    return order


@route("GET", r"/api/orders")
def list_orders(ctx: Ctx, conn):
    user = require_user(ctx)
    rows = conn.execute(
        """SELECT o.*, COUNT(oi.id) AS item_count,
                  COALESCE(SUM(oi.qty), 0) AS units
           FROM orders o LEFT JOIN order_items oi ON oi.order_id = o.id
           WHERE o.user_id = ? GROUP BY o.id ORDER BY o.id DESC""",
        (user["id"],),
    ).fetchall()
    return 200, {"orders": [dict(r) for r in rows]}


@route("GET", r"/api/orders/(\d+)")
def get_order(ctx: Ctx, conn):
    user = require_user(ctx)
    return 200, {"order": get_order_dict(conn, int(ctx.path_groups[0]), user["id"])}


# --------------------------------------------------------------------------- #
# Admin routes
# --------------------------------------------------------------------------- #
@route("GET", r"/api/admin/stats")
def admin_stats(ctx: Ctx, conn):
    require_admin(ctx)
    revenue = conn.execute(
        "SELECT COALESCE(SUM(total_cents),0) FROM orders WHERE status != 'cancelled'"
    ).fetchone()[0]
    return 200, {
        "revenue_cents": revenue,
        "orders": conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
        "products": conn.execute("SELECT COUNT(*) FROM products").fetchone()[0],
        "users": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
    }


@route("GET", r"/api/admin/orders")
def admin_orders(ctx: Ctx, conn):
    require_admin(ctx)
    rows = conn.execute(
        """SELECT o.*, u.email AS user_email, u.name AS user_name,
                  COUNT(oi.id) AS item_count
           FROM orders o JOIN users u ON u.id = o.user_id
           LEFT JOIN order_items oi ON oi.order_id = o.id
           GROUP BY o.id ORDER BY o.id DESC""",
    ).fetchall()
    return 200, {"orders": [dict(r) for r in rows]}


@route("PATCH", r"/api/admin/orders/(\d+)")
def admin_update_order(ctx: Ctx, conn):
    require_admin(ctx)
    status = ctx.body.get("status")
    if status not in ("placed", "shipped", "delivered", "cancelled"):
        raise ApiError(400, "status must be placed|shipped|delivered|cancelled")
    cur = conn.execute("UPDATE orders SET status = ? WHERE id = ?",
                       (status, ctx.path_groups[0]))
    if cur.rowcount == 0:
        raise ApiError(404, "Order not found")
    conn.commit()
    return 200, {"order": get_order_dict(conn, int(ctx.path_groups[0]), None)}


def validate_product_body(body: dict, partial: bool = False) -> dict:
    fields = {}
    if "title" in body or not partial:
        require_fields(body, "title")
        fields["title"] = str(body["title"]).strip()
    if "category" in body or not partial:
        require_fields(body, "category")
        fields["category"] = str(body["category"]).strip()
    if "price_cents" in body or not partial:
        price = body.get("price_cents")
        if not isinstance(price, int) or price <= 0:
            raise ApiError(400, "price_cents must be a positive integer (cents)")
        fields["price_cents"] = price
    if "stock" in body or not partial:
        stock = body.get("stock", 0)
        if not isinstance(stock, int) or stock < 0:
            raise ApiError(400, "stock must be a non-negative integer")
        fields["stock"] = stock
    if "description" in body:
        fields["description"] = str(body["description"]).strip()
    if "emoji" in body and body["emoji"]:
        fields["emoji"] = str(body["emoji"]).strip()[:8]
    if "color" in body and body["color"]:
        if not re.match(r"^#[0-9a-fA-F]{6}$", str(body["color"])):
            raise ApiError(400, "color must be a hex value like #1b2a4a")
        fields["color"] = body["color"]
    if "rating" in body:
        rating = float(body["rating"])
        if not 0 <= rating <= 5:
            raise ApiError(400, "rating must be between 0 and 5")
        fields["rating"] = rating
    if not fields:
        raise ApiError(400, "No valid fields to update")
    return fields


@route("POST", r"/api/admin/products")
def admin_create_product(ctx: Ctx, conn):
    require_admin(ctx)
    fields = validate_product_body(ctx.body, partial=False)
    fields.setdefault("description", "")
    fields.setdefault("emoji", "📦")
    fields.setdefault("color", "#232f3e")
    fields.setdefault("rating", 4.0)
    fields.setdefault("rating_count", 0)
    cols = ", ".join(fields)
    marks = ", ".join("?" for _ in fields)
    cur = conn.execute(
        f"INSERT INTO products ({cols}, created_at) VALUES ({marks}, ?)",
        (*fields.values(), now_iso()),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM products WHERE id = ?", (cur.lastrowid,)).fetchone()
    return 201, {"product": product_row_to_dict(row)}


@route("PATCH", r"/api/admin/products/(\d+)")
def admin_update_product(ctx: Ctx, conn):
    require_admin(ctx)
    product_id = ctx.path_groups[0]
    if conn.execute("SELECT 1 FROM products WHERE id = ?", (product_id,)).fetchone() is None:
        raise ApiError(404, "Product not found")
    fields = validate_product_body(ctx.body, partial=True)
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE products SET {sets} WHERE id = ?", (*fields.values(), product_id))
    conn.commit()
    row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    return 200, {"product": product_row_to_dict(row)}


@route("DELETE", r"/api/admin/products/(\d+)")
def admin_delete_product(ctx: Ctx, conn):
    require_admin(ctx)
    try:
        cur = conn.execute("DELETE FROM products WHERE id = ?", (ctx.path_groups[0],))
        conn.commit()
    except sqlite3.IntegrityError:
        raise ApiError(409, "Product is referenced by cart items or orders; set stock to 0 instead")
    if cur.rowcount == 0:
        raise ApiError(404, "Product not found")
    return 200, {"ok": True}


# --------------------------------------------------------------------------- #
# HTTP layer
# --------------------------------------------------------------------------- #
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "PulseCart/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args):  # quieter logs
        print(f"[{self.log_date_time_string()}] {self.command} {self.path}")

    # -- plumbing ---------------------------------------------------------- #
    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, rel_path: str) -> None:
        target = (FRONTEND_DIR / rel_path).resolve()
        if not str(target).startswith(str(FRONTEND_DIR.resolve())) or not target.is_file():
            self.send_json(404, {"error": "Not found"})
            return
        content_type = CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream")
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if method == "GET" and not path.startswith("/api/"):
            rel = "index.html" if path in ("/", "") else path.lstrip("/")
            self.send_file(rel)
            return

        body: dict = {}
        if method in ("POST", "PATCH", "PUT", "DELETE"):
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            if raw:
                try:
                    body = json.loads(raw)
                except json.JSONDecodeError:
                    self.send_json(400, {"error": "Request body must be valid JSON"})
                    return
        params = parse_qs(parsed.query)

        conn = db()
        try:
            user = current_user(conn, self.headers)
            for route_method, pattern, fn in ROUTES:
                if route_method != method:
                    continue
                match = pattern.match(path)
                if not match:
                    continue
                ctx = Ctx(method, path, params, body, user)
                ctx.path_groups = match.groups()
                status, payload = fn(ctx, conn)  # type: ignore[operator]
                self.send_json(status, payload)
                return
            self.send_json(404, {"error": f"No route for {method} {path}"})
        except ApiError as exc:
            self.send_json(exc.status, {"error": exc.message, **exc.extra})
        except Exception as exc:  # pragma: no cover - safety net
            print(f"!! Unhandled error on {method} {path}: {exc!r}")
            self.send_json(500, {"error": "Internal server error"})
        finally:
            conn.close()

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def do_PATCH(self):
        self.dispatch("PATCH")

    def do_PUT(self):
        self.dispatch("PATCH")  # alias

    def do_DELETE(self):
        self.dispatch("DELETE")


def main() -> None:
    init_db()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.daemon_threads = True
    print(f"PulseCart running at http://localhost:{PORT}")
    print("Seed admin: admin@pulsecart.com / admin12345")
    print("Seed customer: demo@pulsecart.com / demo12345")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
        print("Server stopped.")


if __name__ == "__main__":
    main()
