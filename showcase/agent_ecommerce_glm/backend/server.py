#!/usr/bin/env python3
"""ShopWave - Amazon-style ecommerce platform.

Stdlib-only backend: SQLite persistence, token auth, cart, checkout,
order management and an admin API. Serves the frontend from ../frontend.

Run:  python backend/server.py      ->  http://localhost:8000
Demo accounts: admin@shopwave.dev / Admin123!   demo@shopwave.dev / demo1234
"""
import json
import os
import re
import secrets
import sqlite3
import sys
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import pbkdf2_hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))            # backend/
DB_PATH = os.path.join(ROOT, "data", "ecommerce.db")
FRONTEND_DIR = os.path.normpath(os.path.join(ROOT, "..", "frontend"))
PORT = int(os.environ.get("PORT", "8000"))
TAX_RATE = 0.08
FREE_SHIP_CENTS = 3500          # free shipping over $35
SHIP_CENTS = 599                # $5.99 flat otherwise
ORDER_STATUSES = ("pending", "paid", "shipped", "delivered", "cancelled")


# ---------------------------------------------------------------- database --
@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT UNIQUE NOT NULL,
    name          TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'customer',
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    category    TEXT NOT NULL,
    price_cents INTEGER NOT NULL,
    stock       INTEGER NOT NULL DEFAULT 0,
    image       TEXT NOT NULL DEFAULT '',
    rating      REAL NOT NULL DEFAULT 4.5,
    reviews     INTEGER NOT NULL DEFAULT 0,
    featured    INTEGER NOT NULL DEFAULT 0,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS carts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    token      TEXT UNIQUE NOT NULL,
    user_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cart_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    cart_id    INTEGER NOT NULL REFERENCES carts(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    quantity   INTEGER NOT NULL,
    UNIQUE (cart_id, product_id)
);
CREATE TABLE IF NOT EXISTS orders (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER REFERENCES users(id) ON DELETE SET NULL,
    email          TEXT NOT NULL,
    name           TEXT NOT NULL,
    address        TEXT NOT NULL,
    city           TEXT NOT NULL,
    zip            TEXT NOT NULL,
    payment_method TEXT NOT NULL,
    subtotal_cents INTEGER NOT NULL,
    shipping_cents INTEGER NOT NULL,
    tax_cents      INTEGER NOT NULL,
    total_cents    INTEGER NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending',
    created_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS order_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id    INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id  INTEGER NOT NULL,
    name        TEXT NOT NULL,
    price_cents INTEGER NOT NULL,
    quantity    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
CREATE INDEX IF NOT EXISTS idx_cart_items_cart ON cart_items(cart_id);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
"""

SEED_PRODUCTS = [
    # name, description, category, price_cents, stock, image, rating, reviews, featured
    ("Aurora X1 Wireless Headphones", "Adaptive noise cancelling, 40h battery, multipoint Bluetooth 5.3 with LDAC hi-res audio.", "Electronics", 19999, 84, "\U0001F3A7", 4.8, 2314, 1),
    ("VoltCore 20,000mAh Power Bank", "65W USB-C PD fast charging, charges a laptop and a phone at the same time.", "Electronics", 4999, 150, "\U0001F50B", 4.6, 1189, 1),
    ("PixelPro 4K Action Camera", "Waterproof to 10m, HyperSteady gimbal-style stabilization, 48MP stills.", "Electronics", 24999, 41, "\U0001F4F7", 4.5, 642, 0),
    ('NebulaBook 14" Ultra-thin Laptop', "16GB RAM, 512GB NVMe, 2.8K OLED display, 1.2kg magnesium chassis.", "Electronics", 99900, 18, "\U0001F4BB", 4.7, 389, 1),
    ("SonicBlast Portable Speaker", "360-degree sound, IP67 waterproof, 24h playtime, stereo pairing.", "Electronics", 7999, 96, "\U0001F50A", 4.4, 876, 0),
    ("FitPulse Smartwatch Series 5", "AMOLED always-on display, ECG, SpO2, 14-day battery, 120+ sport modes.", "Electronics", 12999, 73, "\u231A", 4.3, 1521, 0),
    ("BrewMaster Pour-Over Kettle", "Gooseneck spout, built-in thermometer, variable temperature control 1L.", "Home & Kitchen", 5999, 64, "\U0001FAD4", 4.7, 540, 0),
    ('ChefEdge 8" Damascus Chef Knife', "67-layer Damascus steel, VG-10 core, ergonomic pakkawood handle.", "Home & Kitchen", 8999, 37, "\U0001F52A", 4.8, 298, 0),
    ("AeroCrisp 6-qt Air Fryer", "Rapid convection, 8 one-touch presets, dishwasher-safe nonstick basket.", "Home & Kitchen", 11999, 52, "\U0001F35F", 4.6, 2043, 1),
    ("CloudNest Weighted Blanket", "15lb cooling glass-bead fill, breathable bamboo cover, queen size.", "Home & Kitchen", 6999, 45, "\U0001F6CF", 4.5, 918, 0),
    ("The Focus Engine", "A practical system for deep work in a distracted age. 288 pages, hardcover.", "Books", 1699, 210, "\U0001F4D5", 4.7, 3421, 0),
    ("Midnight Algorithm", "A detective hunts a killer hiding inside a city-wide neural network. Sci-fi thriller.", "Books", 1499, 340, "\U0001F4D7", 4.4, 1876, 0),
    ("The Founder's Playbook", "Field notes from 100 startups on pricing, hiring and surviving year two.", "Books", 2499, 120, "\U0001F4D8", 4.9, 762, 1),
    ("NorthTrail All-Weather Rain Jacket", "3-layer breathable waterproof shell, taped seams, packs into its own pocket.", "Fashion", 8999, 88, "\U0001F9E5", 4.6, 655, 0),
    ("EverydaySoft Merino Wool Tee", "17.5 micron merino, odor resistant, temperature regulating, machine washable.", "Fashion", 3999, 133, "\U0001F455", 4.5, 489, 0),
    ("UrbanStep Leather Sneakers", "Full-grain leather upper, cork insole, resoleable stitched construction.", "Fashion", 10999, 60, "\U0001F45F", 4.4, 371, 0),
    ("TrailBlazer 45L Hiking Backpack", "Ventilated suspension, rain cover included, hydration sleeve, 1.4kg.", "Sports & Outdoors", 9499, 54, "\U0001F392", 4.7, 823, 1),
    ("FlexCore Adjustable Dumbbells", "5-55lb per hand, dial-a-weight, steel plates with nylon trim.", "Sports & Outdoors", 15999, 26, "\U0001F3CB", 4.6, 512, 0),
    ("HydraPeak Insulated Bottle 32oz", "Double-wall vacuum steel, cold 36h / hot 18h, leakproof chug cap.", "Sports & Outdoors", 2999, 240, "\U0001F964", 4.8, 3911, 1),
    ("Lumiere Vitamin C Serum", "15% stabilized L-ascorbic acid with ferulic acid and vitamin E, 30ml.", "Beauty", 3499, 92, "\u2728", 4.5, 1287, 0),
    ("Silk & Sage Shampoo Duo", "Sulfate-free pair for color-treated hair, botanical oils, 2 x 350ml.", "Beauty", 2299, 118, "\U0001F9F4", 4.3, 640, 0),
    ("Galaxy Builders 1200-piece Set", "Modular space station with 6 minifigures, glow-in-the-dark elements.", "Toys & Games", 4999, 77, "\U0001F9F1", 4.8, 954, 1),
    ("PuzzleScape: Neon City 1000pc", "Matte anti-glare finish, poster included, precision die-cut pieces.", "Toys & Games", 1899, 165, "\U0001F9E9", 4.4, 402, 0),
    ("Cascadian Roast Whole-Bean Coffee", "Single-origin dark roast, notes of dark chocolate and cherry, 2lb bag.", "Grocery", 2799, 180, "\u2615", 4.7, 2250, 0),
    ("Golden Harvest Organic Olive Oil", "Cold-pressed extra virgin, early harvest, 1L dark glass bottle.", "Grocery", 1999, 145, "\U0001FAD2", 4.6, 781, 0),
]

SEED_USERS = [
    ("admin@shopwave.dev", "Store Admin", "Admin123!", "admin"),
    ("demo@shopwave.dev", "Demo Shopper", "demo1234", "customer"),
]


def hash_password(password):
    salt = secrets.token_hex(16)
    dk = pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120000).hex()
    return f"{salt}${dk}"


def verify_password(password, stored):
    salt, dk = stored.split("$", 1)
    check = pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120000).hex()
    return secrets.compare_digest(check, dk)


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with db() as conn:
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) c FROM products").fetchone()["c"] == 0:
            conn.executemany(
                "INSERT INTO products(name,description,category,price_cents,stock,image,"
                "rating,reviews,featured,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                [(n, d, c, p, s, i, r, rv, f, now()) for n, d, c, p, s, i, r, rv, f in SEED_PRODUCTS],
            )
        if conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"] == 0:
            conn.executemany(
                "INSERT INTO users(email,name,password_hash,role,created_at) VALUES(?,?,?,?,?)",
                [(e, n, hash_password(pw), role, now()) for e, n, pw, role in SEED_USERS],
            )


# ----------------------------------------------------------------- helpers --
class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


ROUTES = []


def route(method, pattern):
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), fn))
        return fn
    return deco


def read_json(handler):
    length = int(handler.headers.get("Content-Length", 0) or 0)
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise ApiError(400, "Invalid JSON body")
    if not isinstance(data, dict):
        raise ApiError(400, "JSON body must be an object")
    return data


def auth_user(headers):
    header = headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header[7:].strip()
    if not token:
        return None
    with db() as conn:
        row = conn.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?",
            (token,),
        ).fetchone()
    return dict(row) if row else None


def find_cart(headers, create=False, user=None):
    token = (headers.get("X-Cart-Token") or "").strip()
    if token:
        with db() as conn:
            row = conn.execute("SELECT * FROM carts WHERE token = ?", (token,)).fetchone()
        if row:
            return dict(row)
    if create:
        token = secrets.token_hex(16)
        with db() as conn:
            conn.execute(
                "INSERT INTO carts(token, user_id, created_at) VALUES(?,?,?)",
                (token, user["id"] if user else None, now()),
            )
        return {"id": None, "token": token, "user_id": user["id"] if user else None}
    return None


def cart_payload(conn, cart):
    rows = conn.execute(
        "SELECT ci.product_id, ci.quantity, p.name, p.price_cents, p.image, p.stock, p.active"
        " FROM cart_items ci JOIN products p ON p.id = ci.product_id WHERE ci.cart_id = ?",
        (cart["id"],),
    ).fetchall() if cart.get("id") else []
    items, subtotal = [], 0
    for r in rows:
        if not r["active"]:
            continue
        line = r["price_cents"] * r["quantity"]
        subtotal += line
        items.append({
            "product_id": r["product_id"], "name": r["name"],
            "price_cents": r["price_cents"], "quantity": r["quantity"],
            "image": r["image"], "stock": r["stock"], "line_total_cents": line,
        })
    shipping = 0 if subtotal == 0 or subtotal >= FREE_SHIP_CENTS else SHIP_CENTS
    tax = round(subtotal * TAX_RATE)
    return {
        "token": cart.get("token"), "items": items,
        "count": sum(i["quantity"] for i in items),
        "subtotal_cents": subtotal, "shipping_cents": shipping,
        "tax_cents": tax, "total_cents": subtotal + shipping + tax,
        "free_shipping_threshold_cents": FREE_SHIP_CENTS,
    }


def empty_cart():
    return {"token": None, "items": [], "count": 0, "subtotal_cents": 0,
            "shipping_cents": 0, "tax_cents": 0, "total_cents": 0,
            "free_shipping_threshold_cents": FREE_SHIP_CENTS}


def order_dict(conn, oid):
    row = conn.execute("SELECT * FROM orders WHERE id = ?", (oid,)).fetchone()
    if not row:
        return None
    order = dict(row)
    order["items"] = [dict(x) for x in conn.execute(
        "SELECT product_id, name, price_cents, quantity FROM order_items WHERE order_id = ?",
        (oid,)).fetchall()]
    return order


def public_user(u):
    return {k: u[k] for k in ("id", "name", "email", "role", "created_at")}


def require_user(user):
    if not user:
        raise ApiError(401, "Sign in required")
    return user


def require_admin(user):
    require_user(user)
    if user["role"] != "admin":
        raise ApiError(403, "Admin access required")
    return user


def create_session(conn, user_id):
    token = secrets.token_hex(24)
    conn.execute("INSERT INTO sessions(token, user_id, created_at) VALUES(?,?,?)",
                 (token, user_id, now()))
    return token


# ----------------------------------------------------------------- catalog --
@route("GET", r"/api/health")
def health(h, p, q, body, user, cart):
    return 200, {"ok": True, "service": "ShopWave", "time": now()}


@route("GET", r"/api/products")
def list_products(h, p, q, body, user, cart):
    where, args = ["active = 1"], []
    if q.get("q"):
        like = "%" + q["q"].strip() + "%"
        where.append("(name LIKE ? OR description LIKE ? OR category LIKE ?)")
        args += [like, like, like]
    if q.get("category"):
        where.append("category = ?")
        args.append(q["category"])
    if q.get("min_price"):
        where.append("price_cents >= ?")
        args.append(int(float(q["min_price"]) * 100))
    if q.get("max_price"):
        where.append("price_cents <= ?")
        args.append(int(float(q["max_price"]) * 100))
    order = {
        "price_asc": "price_cents ASC",
        "price_desc": "price_cents DESC",
        "rating": "rating DESC, reviews DESC",
        "newest": "id DESC",
    }.get(q.get("sort", ""), "featured DESC, rating DESC, id ASC")
    clause = " AND ".join(where)
    try:
        limit = min(max(int(q.get("limit", "60")), 1), 200)
    except ValueError:
        limit = 60
    with db() as conn:
        total = conn.execute(f"SELECT COUNT(*) c FROM products WHERE {clause}", args).fetchone()["c"]
        rows = conn.execute(
            f"SELECT * FROM products WHERE {clause} ORDER BY {order} LIMIT ?",
            args + [limit]).fetchall()
    return 200, {"total": total, "products": [dict(r) for r in rows]}


@route("GET", r"/api/products/(?P<id>\d+)")
def get_product(h, p, q, body, user, cart):
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM products WHERE id = ? AND active = 1", (p["id"],)).fetchone()
    if not row:
        raise ApiError(404, "Product not found")
    return 200, {"product": dict(row)}


@route("GET", r"/api/categories")
def list_categories(h, p, q, body, user, cart):
    with db() as conn:
        rows = conn.execute(
            "SELECT category, COUNT(*) AS count FROM products WHERE active = 1"
            " GROUP BY category ORDER BY category").fetchall()
    return 200, {"categories": [dict(r) for r in rows]}


# -------------------------------------------------------------------- auth --
@route("POST", r"/api/auth/register")
def register(h, p, q, body, user, cart):
    name = (body.get("name") or "").strip()
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    if not name:
        raise ApiError(400, "Name is required")
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise ApiError(400, "A valid email is required")
    if len(password) < 6:
        raise ApiError(400, "Password must be at least 6 characters")
    with db() as conn:
        if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            raise ApiError(409, "An account with that email already exists")
        cur = conn.execute(
            "INSERT INTO users(email, name, password_hash, role, created_at) VALUES(?,?,?,?,?)",
            (email, name, hash_password(password), "customer", now()))
        token = create_session(conn, cur.lastrowid)
        row = conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
    return 201, {"token": token, "user": public_user(dict(row))}


@route("POST", r"/api/auth/login")
def login(h, p, q, body, user, cart):
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not row or not verify_password(password, row["password_hash"]):
            raise ApiError(401, "Invalid email or password")
        token = create_session(conn, row["id"])
    return 200, {"token": token, "user": public_user(dict(row))}


@route("GET", r"/api/auth/me")
def me(h, p, q, body, user, cart):
    require_user(user)
    return 200, {"user": public_user(user)}


@route("POST", r"/api/auth/logout")
def logout(h, p, q, body, user, cart):
    header = h.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        with db() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (header[7:].strip(),))
    return 200, {"ok": True}


# -------------------------------------------------------------------- cart --
@route("GET", r"/api/cart")
def get_cart(h, p, q, body, user, cart):
    if not cart:
        return 200, empty_cart()
    with db() as conn:
        return 200, cart_payload(conn, cart)


@route("POST", r"/api/cart/items")
def add_to_cart(h, p, q, body, user, cart):
    try:
        product_id = int(body.get("product_id"))
        quantity = int(body.get("quantity", 1))
    except (TypeError, ValueError):
        raise ApiError(400, "product_id and quantity must be integers")
    if quantity < 1 or quantity > 99:
        raise ApiError(400, "Quantity must be between 1 and 99")
    with db() as conn:
        product = conn.execute(
            "SELECT * FROM products WHERE id = ? AND active = 1", (product_id,)).fetchone()
        if not product:
            raise ApiError(404, "Product not found")
        if product["stock"] < 1:
            raise ApiError(409, "Product is out of stock")
        if not cart:
            cart = find_cart(h.headers, create=True, user=user)
        existing = conn.execute(
            "SELECT * FROM cart_items WHERE cart_id = ? AND product_id = ?",
            (cart["id"], product_id)).fetchone()
        new_qty = min(quantity + (existing["quantity"] if existing else 0), product["stock"], 99)
        if existing:
            conn.execute("UPDATE cart_items SET quantity = ? WHERE id = ?",
                         (new_qty, existing["id"]))
        else:
            conn.execute("INSERT INTO cart_items(cart_id, product_id, quantity) VALUES(?,?,?)",
                         (cart["id"], product_id, new_qty))
        payload = cart_payload(conn, cart)
    return 201, payload


@route("PATCH", r"/api/cart/items/(?P<product_id>\d+)")
def update_cart_item(h, p, q, body, user, cart):
    if not cart:
        raise ApiError(404, "Cart not found")
    try:
        quantity = int(body.get("quantity"))
    except (TypeError, ValueError):
        raise ApiError(400, "quantity must be an integer")
    if quantity < 0 or quantity > 99:
        raise ApiError(400, "Quantity must be between 0 and 99")
    with db() as conn:
        if quantity == 0:
            conn.execute("DELETE FROM cart_items WHERE cart_id = ? AND product_id = ?",
                         (cart["id"], p["product_id"]))
        else:
            product = conn.execute(
                "SELECT stock FROM products WHERE id = ?", (p["product_id"],)).fetchone()
            if not product:
                raise ApiError(404, "Product not found")
            conn.execute(
                "UPDATE cart_items SET quantity = ? WHERE cart_id = ? AND product_id = ?",
                (min(quantity, product["stock"]), cart["id"], p["product_id"]))
        return 200, cart_payload(conn, cart)


@route("DELETE", r"/api/cart/items/(?P<product_id>\d+)")
def remove_cart_item(h, p, q, body, user, cart):
    if not cart:
        raise ApiError(404, "Cart not found")
    with db() as conn:
        conn.execute("DELETE FROM cart_items WHERE cart_id = ? AND product_id = ?",
                     (cart["id"], p["product_id"]))
        return 200, cart_payload(conn, cart)


# ---------------------------------------------------------------- checkout --
@route("POST", r"/api/checkout")
def checkout(h, p, q, body, user, cart):
    if not cart:
        raise ApiError(400, "Your cart is empty")
    payment = (body.get("payment_method") or "card").strip()
    name = (body.get("name") or "").strip()
    email = (body.get("email") or (user["email"] if user else "")).strip().lower()
    address = (body.get("address") or "").strip()
    city = (body.get("city") or "").strip()
    zip_code = (body.get("zip") or "").strip()
    missing = [f for f, v in (("name", name), ("email", email), ("address", address),
                              ("city", city), ("zip", zip_code)) if not v]
    if missing:
        raise ApiError(400, "Missing required fields: " + ", ".join(missing))
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise ApiError(400, "A valid email is required")
    if payment not in ("card", "cod"):
        raise ApiError(400, "payment_method must be 'card' or 'cod'")
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        items = conn.execute(
            "SELECT ci.product_id, ci.quantity, p.name, p.price_cents, p.stock"
            " FROM cart_items ci JOIN products p ON p.id = ci.product_id"
            " WHERE ci.cart_id = ? AND p.active = 1", (cart["id"],)).fetchall()
        if not items:
            raise ApiError(400, "Your cart is empty")
        for it in items:
            if it["stock"] < it["quantity"]:
                raise ApiError(409, "Insufficient stock for '%s' (%d left)"
                               % (it["name"], it["stock"]))
        subtotal = sum(i["price_cents"] * i["quantity"] for i in items)
        shipping = 0 if subtotal >= FREE_SHIP_CENTS else SHIP_CENTS
        tax = round(subtotal * TAX_RATE)
        total = subtotal + shipping + tax
        status = "paid" if payment == "card" else "pending"
        cur = conn.execute(
            "INSERT INTO orders(user_id, email, name, address, city, zip, payment_method,"
            " subtotal_cents, shipping_cents, tax_cents, total_cents, status, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (user["id"] if user else None, email, name, address, city, zip_code,
             payment, subtotal, shipping, tax, total, status, now()))
        order_id = cur.lastrowid
        for it in items:
            conn.execute(
                "INSERT INTO order_items(order_id, product_id, name, price_cents, quantity)"
                " VALUES(?,?,?,?,?)",
                (order_id, it["product_id"], it["name"], it["price_cents"], it["quantity"]))
            conn.execute("UPDATE products SET stock = stock - ? WHERE id = ?",
                         (it["quantity"], it["product_id"]))
        conn.execute("DELETE FROM cart_items WHERE cart_id = ?", (cart["id"],))
        order = order_dict(conn, order_id)
    return 201, {"order": order, "message": "Order placed successfully"}


@route("GET", r"/api/orders")
def my_orders(h, p, q, body, user, cart):
    require_user(user)
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT 100",
            (user["id"],)).fetchall()
        orders = [order_dict(conn, r["id"]) for r in rows]
    return 200, {"orders": orders}


@route("GET", r"/api/orders/(?P<id>\d+)")
def get_order(h, p, q, body, user, cart):
    with db() as conn:
        order = order_dict(conn, p["id"])
    if not order:
        raise ApiError(404, "Order not found")
    if not user or (order["user_id"] != user["id"] and user["role"] != "admin"):
        raise ApiError(403, "You do not have access to this order")
    return 200, {"order": order}


# ------------------------------------------------------------------- admin --
@route("GET", r"/api/admin/stats")
def admin_stats(h, p, q, body, user, cart):
    require_admin(user)
    with db() as conn:
        stats = {
            "active_products": conn.execute(
                "SELECT COUNT(*) c FROM products WHERE active = 1").fetchone()["c"],
            "orders": conn.execute("SELECT COUNT(*) c FROM orders").fetchone()["c"],
            "revenue_cents": conn.execute(
                "SELECT COALESCE(SUM(total_cents), 0) s FROM orders"
                " WHERE status != 'cancelled'").fetchone()["s"],
            "open_orders": conn.execute(
                "SELECT COUNT(*) c FROM orders WHERE status IN ('pending','paid')").fetchone()["c"],
            "customers": conn.execute(
                "SELECT COUNT(*) c FROM users WHERE role = 'customer'").fetchone()["c"],
            "low_stock": [dict(r) for r in conn.execute(
                "SELECT id, name, stock FROM products WHERE active = 1 AND stock < 5"
                " ORDER BY stock LIMIT 10")],
            "top_sellers": [dict(r) for r in conn.execute(
                "SELECT name, SUM(quantity) AS units, SUM(price_cents * quantity) AS revenue_cents"
                " FROM order_items GROUP BY name ORDER BY units DESC LIMIT 5")],
        }
    return 200, stats


@route("GET", r"/api/admin/products")
def admin_products(h, p, q, body, user, cart):
    require_admin(user)
    with db() as conn:
        rows = conn.execute("SELECT * FROM products ORDER BY id DESC LIMIT 500").fetchall()
    return 200, {"products": [dict(r) for r in rows]}


def product_fields(body, partial=False):
    fields = {}
    if "name" in body or not partial:
        name = (body.get("name") or "").strip()
        if not name:
            raise ApiError(400, "Name is required")
        fields["name"] = name
    if "description" in body or not partial:
        fields["description"] = (body.get("description") or "").strip()
    if "category" in body or not partial:
        category = (body.get("category") or "").strip()
        if not category:
            raise ApiError(400, "Category is required")
        fields["category"] = category
    if "price" in body:
        try:
            price = float(body["price"])
        except (TypeError, ValueError):
            raise ApiError(400, "price must be a number")
        if price <= 0:
            raise ApiError(400, "price must be positive")
        fields["price_cents"] = int(round(price * 100))
    if "stock" in body:
        try:
            stock = int(body["stock"])
        except (TypeError, ValueError):
            raise ApiError(400, "stock must be an integer")
        if stock < 0:
            raise ApiError(400, "stock cannot be negative")
        fields["stock"] = stock
    if "image" in body:
        fields["image"] = (body.get("image") or "").strip()[:8]
    if "rating" in body:
        try:
            rating = float(body["rating"])
        except (TypeError, ValueError):
            raise ApiError(400, "rating must be a number")
        fields["rating"] = min(max(rating, 0.0), 5.0)
    if "featured" in body:
        fields["featured"] = 1 if body["featured"] else 0
    if "active" in body:
        fields["active"] = 1 if body["active"] else 0
    return fields


@route("POST", r"/api/admin/products")
def admin_create_product(h, p, q, body, user, cart):
    require_admin(user)
    fields = product_fields(body, partial=False)
    with db() as conn:
        cols = ", ".join(list(fields) + ["created_at"])
        marks = ", ".join(["?"] * (len(fields) + 1))
        cur = conn.execute(f"INSERT INTO products({cols}) VALUES({marks})",
                           list(fields.values()) + [now()])
        row = conn.execute("SELECT * FROM products WHERE id = ?", (cur.lastrowid,)).fetchone()
    return 201, {"product": dict(row)}


@route("PATCH", r"/api/admin/products/(?P<id>\d+)")
def admin_update_product(h, p, q, body, user, cart):
    require_admin(user)
    fields = product_fields(body, partial=True)
    if not fields:
        raise ApiError(400, "No fields to update")
    with db() as conn:
        if not conn.execute("SELECT 1 FROM products WHERE id = ?", (p["id"],)).fetchone():
            raise ApiError(404, "Product not found")
        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE products SET {sets} WHERE id = ?",
                     list(fields.values()) + [p["id"]])
        row = conn.execute("SELECT * FROM products WHERE id = ?", (p["id"],)).fetchone()
    return 200, {"product": dict(row)}


@route("DELETE", r"/api/admin/products/(?P<id>\d+)")
def admin_delete_product(h, p, q, body, user, cart):
    require_admin(user)
    with db() as conn:
        if not conn.execute("SELECT 1 FROM products WHERE id = ?", (p["id"],)).fetchone():
            raise ApiError(404, "Product not found")
        conn.execute("UPDATE products SET active = 0 WHERE id = ?", (p["id"],))
    return 200, {"ok": True, "message": "Product archived"}


@route("GET", r"/api/admin/orders")
def admin_orders(h, p, q, body, user, cart):
    require_admin(user)
    with db() as conn:
        if q.get("status"):
            rows = conn.execute("SELECT id FROM orders WHERE status = ? ORDER BY id DESC LIMIT 200",
                                (q["status"],)).fetchall()
        else:
            rows = conn.execute("SELECT id FROM orders ORDER BY id DESC LIMIT 200").fetchall()
        orders = [order_dict(conn, r["id"]) for r in rows]
    return 200, {"orders": orders}


@route("PATCH", r"/api/admin/orders/(?P<id>\d+)")
def admin_update_order(h, p, q, body, user, cart):
    require_admin(user)
    status = (body.get("status") or "").strip()
    if status not in ORDER_STATUSES:
        raise ApiError(400, "status must be one of: " + ", ".join(ORDER_STATUSES))
    with db() as conn:
        if not conn.execute("SELECT 1 FROM orders WHERE id = ?", (p["id"],)).fetchone():
            raise ApiError(404, "Order not found")
        conn.execute("UPDATE orders SET status = ? WHERE id = ?", (status, p["id"]))
        order = order_dict(conn, p["id"])
    return 200, {"order": order}


# ------------------------------------------------------------------ server --
def match_route(method, path):
    for m, rx, fn in ROUTES:
        if m == method:
            mo = rx.match(path)
            if mo:
                return fn, mo.groupdict()
    return None, None


MIME = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml",
    ".png": "image/png", ".jpg": "image/jpeg", ".ico": "image/x-icon",
    ".json": "application/json", ".webmanifest": "application/manifest+json",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "ShopWave/1.0"
    protocol_version = "HTTP/1.1"

    def _send_json(self, status, obj):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path):
        if path == "/":
            path = "/index.html"
        fname = os.path.normpath(os.path.join(FRONTEND_DIR, path.lstrip("/")))
        if not fname.startswith(FRONTEND_DIR) or not os.path.isfile(fname):
            if "." not in os.path.basename(path):
                fname = os.path.join(FRONTEND_DIR, "index.html")  # SPA fallback
            if not os.path.isfile(fname):
                raise ApiError(404, "Not found")
        ext = os.path.splitext(fname)[1].lower()
        with open(fname, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _dispatch(self, method):
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            if path.startswith("/api"):
                fn, params = match_route(method, path)
                if not fn:
                    raise ApiError(404, "Not found")
                body = read_json(self) if method in ("POST", "PATCH", "PUT", "DELETE") else {}
                user = auth_user(self.headers)
                cart = find_cart(self.headers)
                status, payload = fn(self, params, query, body, user, cart)
                self._send_json(status, payload)
            elif method == "GET":
                self._send_file(path)
            else:
                raise ApiError(405, "Method not allowed")
        except ApiError as exc:
            self._send_json(exc.status, {"error": exc.message})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:  # noqa: BLE001 - last-resort handler
            traceback.print_exc()
            try:
                self._send_json(500, {"error": f"Internal server error: {exc}"})
            except Exception:
                pass

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PATCH(self):
        self._dispatch("PATCH")

    def do_PUT(self):
        self._dispatch("PATCH")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def log_message(self, fmt, *args):  # compact single-line access log
        sys.stdout.write("%s - %s\n" % (self.address_string(), fmt % args))
        sys.stdout.flush()


def main():
    init_db()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"ShopWave running at http://localhost:{PORT}  (Ctrl+C to stop)")
    print(f"Database: {DB_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
