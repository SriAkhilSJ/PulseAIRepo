#!/usr/bin/env python3
"""
ShopNova — an Amazon-style ecommerce platform.

Pure Python 3 standard library: http.server for the REST API + static hosting,
sqlite3 for real relational persistence. No third-party dependencies.

Run:  python3 server.py      (then open http://localhost:8000)
Seed accounts:
  admin:    admin@shopnova.dev / admin123
  customer: demo@shopnova.dev / demo1234
"""
import json
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from hashlib import pbkdf2_hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "shopnova.db")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
PORT = int(os.environ.get("PORT", "8000"))

SESSION_DAYS = 7
ORDER_STATUSES = ("placed", "shipped", "delivered", "cancelled")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


# ---------------------------------------------------------------- database

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def rows(cursor):
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, r)) for r in cursor.fetchall()]


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()
    return digest, salt


def verify_password(password, salt, expected):
    digest, _ = hash_password(password, salt)
    return secrets.compare_digest(digest, expected)


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    salt          TEXT NOT NULL,
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
    price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
    stock       INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
    emoji       TEXT NOT NULL DEFAULT '📦',
    rating      REAL NOT NULL DEFAULT 4.5,
    active      INTEGER NOT NULL DEFAULT 1,
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
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    status      TEXT NOT NULL DEFAULT 'placed' CHECK (status IN ('placed','shipped','delivered','cancelled')),
    total_cents INTEGER NOT NULL,
    address     TEXT NOT NULL,
    city        TEXT NOT NULL,
    zip         TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS order_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id    INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id  INTEGER,
    title       TEXT NOT NULL,
    price_cents INTEGER NOT NULL,
    qty         INTEGER NOT NULL CHECK (qty > 0)
);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
CREATE INDEX IF NOT EXISTS idx_cart_user ON cart_items(user_id);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
"""

SEED_PRODUCTS = [
    ("NovaBook Air 14\" Laptop", "Feather-light 14-inch laptop with 18-hour battery, 16GB RAM and a 512GB SSD.", "Electronics", 89999, 24, "💻", 4.7),
    ("PulseBuds Pro Earbuds", "Active noise cancelling earbuds with spatial audio and 30-hour case life.", "Electronics", 12999, 60, "🎧", 4.6),
    ("Volt Charge 65W GaN Charger", "Pocket-size 65W GaN charger with dual USB-C and fast-charge for laptops.", "Electronics", 3999, 120, "🔌", 4.8),
    ("Aura 55\" 4K Smart TV", "55-inch 4K HDR smart TV with Dolby Vision and voice remote.", "Electronics", 54999, 12, "📺", 4.5),
    ("Nimble Mechanical Keyboard", "Hot-swappable 75% mechanical keyboard with gasket mount and PBT keys.", "Electronics", 8999, 35, "⌨️", 4.7),
    ("The Lean Startup Blueprint", "A practical playbook for building products customers actually want.", "Books", 1499, 80, "📘", 4.4),
    ("Deep Focus: The Science of Attention", "How elite performers train attention — with a 12-week practice program.", "Books", 1299, 65, "📕", 4.6),
    ("Galactic Drift (Sci-Fi Trilogy)", "The complete trilogy: three civilizations, one collapsing wormhole.", "Books", 2499, 40, "📚", 4.8),
    ("Cloudnest Memory Foam Pillow", "Cooling gel memory foam pillow, adjustable loft, washable cover.", "Home", 4499, 90, "🛏️", 4.3),
    ("ChefEdge 8\" Damascus Knife", "Hand-finished Damascus steel chef knife with walnut handle.", "Home", 7999, 28, "🔪", 4.9),
    ("Lumen Glow Floor Lamp", "Dimmable LED floor lamp with warm-to-cool tunable white.", "Home", 5999, 45, "💡", 4.2),
    ("Trailblazer Waterproof Jacket", "3-layer breathable shell rated for monsoon-grade downpours.", "Fashion", 8999, 50, "🧥", 4.5),
    ("Everyday Merino Crew Tee", "Odor-resistant merino blend tee that stays fresh for a week of wear.", "Fashion", 3499, 100, "👕", 4.4),
    ("Stride Runner Sneakers", "Nitro-foam daily trainers with recycled knit upper.", "Fashion", 7499, 70, "👟", 4.6),
    ("BlockBots Creator Set", "860-piece robotics building set with motorized joints and app guides.", "Toys", 4999, 55, "🤖", 4.7),
    ("Star Rocket Building Kit", "Launch-ready model rocket kit with recovery parachute, ages 10+.", "Toys", 3999, 48, "🚀", 4.5),
    ("FlexCore Adjustable Dumbbells", "5–52 lb per hand dial-a-weight dumbbells with cradle stand.", "Sports", 19999, 20, "🏋️", 4.6),
    ("HydraPeak Insulated Bottle", "32 oz vacuum-insulated bottle — ice cold 24h, steaming hot 12h.", "Sports", 2999, 150, "🧴", 4.8),
    ("GlowLab Vitamin C Serum", "15% vitamin C + ferulic serum for bright, even skin tone.", "Beauty", 2499, 85, "🧪", 4.3),
]

SEED_USERS = [
    ("Site Admin", "admin@shopnova.dev", "admin123", "admin"),
    ("Demo Shopper", "demo@shopnova.dev", "demo1234", "customer"),
]


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = get_db()
    try:
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"] == 0:
            for title, desc, cat, price, stock, emoji, rating in SEED_PRODUCTS:
                conn.execute(
                    "INSERT INTO products (title, description, category, price_cents, stock, emoji, rating, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (title, desc, cat, price, stock, emoji, rating, now_iso()),
                )
        if conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"] == 0:
            for name, email, password, role in SEED_USERS:
                digest, salt = hash_password(password)
                conn.execute(
                    "INSERT INTO users (name, email, password_hash, salt, role, created_at) VALUES (?,?,?,?,?,?)",
                    (name, email, digest, salt, role, now_iso()),
                )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------- sessions

def create_session(user_id):
    token = secrets.token_hex(32)
    conn = get_db()
    try:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now_iso(),))
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?,?,?,?)",
            (token, user_id, now_iso(),
             (datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()
    return token


def user_from_request(headers):
    auth = headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:].strip()
    if not token:
        return None
    conn = get_db()
    try:
        cur = conn.execute(
            "SELECT u.id, u.name, u.email, u.role FROM sessions s"
            " JOIN users u ON u.id = s.user_id"
            " WHERE s.token = ? AND s.expires_at > ?",
            (token, now_iso()),
        )
        found = cur.fetchone()
        return dict(found) if found else None
    finally:
        conn.close()


def require_user(headers, admin=False):
    user = user_from_request(headers)
    if user is None:
        raise ApiError(401, "Sign in required.")
    if admin and user["role"] != "admin":
        raise ApiError(403, "Admin access required.")
    return user


# ---------------------------------------------------------------- helpers

def clean_str(value, field, max_len=200, required=True):
    if not isinstance(value, str) or not value.strip():
        if required:
            raise ApiError(400, f"{field} is required.")
        return ""
    value = value.strip()
    if len(value) > max_len:
        raise ApiError(400, f"{field} is too long (max {max_len} chars).")
    return value


def to_int(value, field, minimum=None, maximum=None):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ApiError(400, f"{field} must be a whole number.")
    if minimum is not None and number < minimum:
        raise ApiError(400, f"{field} must be at least {minimum}.")
    if maximum is not None and number > maximum:
        raise ApiError(400, f"{field} must be at most {maximum}.")
    return number


def product_dict(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "description": row["description"],
        "category": row["category"],
        "price_cents": row["price_cents"],
        "stock": row["stock"],
        "emoji": row["emoji"],
        "rating": row["rating"],
        "active": bool(row["active"]),
    }


# ---------------------------------------------------------------- handlers

def api_register(body, user, params):
    name = clean_str(body.get("name"), "Name", 80)
    email = clean_str(body.get("email"), "Email", 120).lower()
    password = body.get("password")
    if not EMAIL_RE.match(email):
        raise ApiError(400, "Enter a valid email address.")
    if not isinstance(password, str) or len(password) < 6:
        raise ApiError(400, "Password must be at least 6 characters.")
    digest, salt = hash_password(password)
    conn = get_db()
    try:
        if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            raise ApiError(409, "An account with this email already exists.")
        cur = conn.execute(
            "INSERT INTO users (name, email, password_hash, salt, role, created_at) VALUES (?,?,?,?,'customer',?)",
            (name, email, digest, salt, now_iso()),
        )
        conn.commit()
        user_id = cur.lastrowid
    finally:
        conn.close()
    token = create_session(user_id)
    return 201, {"token": token, "user": {"id": user_id, "name": name, "email": email, "role": "customer"}}


def api_login(body, user, params):
    email = clean_str(body.get("email"), "Email", 120).lower()
    password = body.get("password")
    if not isinstance(password, str):
        raise ApiError(400, "Password is required.")
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    finally:
        conn.close()
    if not row or not verify_password(password, row["salt"], row["password_hash"]):
        raise ApiError(401, "Incorrect email or password.")
    token = create_session(row["id"])
    return 200, {"token": token, "user": {"id": row["id"], "name": row["name"],
                                          "email": row["email"], "role": row["role"]}}


def api_me(user, params):
    conn = get_db()
    try:
        cart_count = conn.execute(
            "SELECT COALESCE(SUM(qty),0) AS n FROM cart_items WHERE user_id = ?", (user["id"],)
        ).fetchone()["n"]
    finally:
        conn.close()
    return 200, {"user": user, "cart_count": cart_count}


# ---------------------------------------------------------------- cart / orders

def cart_rows(conn, user_id):
    items = rows(conn.execute(
        "SELECT ci.id AS cart_item_id, ci.qty, p.* FROM cart_items ci"
        " JOIN products p ON p.id = ci.product_id"
        " WHERE ci.user_id = ? AND p.active = 1 ORDER BY ci.id", (user_id,)))
    out, subtotal = [], 0
    for it in items:
        line_total = it["price_cents"] * it["qty"]
        subtotal += line_total
        out.append({
            "cart_item_id": it["cart_item_id"], "product_id": it["id"],
            "title": it["title"], "emoji": it["emoji"], "category": it["category"],
            "price_cents": it["price_cents"], "qty": it["qty"], "stock": it["stock"],
            "line_total_cents": line_total,
        })
    return out, subtotal


def api_cart_get(user, params):
    conn = get_db()
    try:
        items, subtotal = cart_rows(conn, user["id"])
    finally:
        conn.close()
    count = sum(i["qty"] for i in items)
    return 200, {"items": items, "subtotal_cents": subtotal,
                 "count": count, "shipping_cents": 0 if subtotal == 0 or subtotal >= 5000 else 499}


def api_cart_add(user, params, body):
    product_id = to_int(body.get("product_id"), "Product id", 1)
    qty = to_int(body.get("qty", 1), "Quantity", 1, 20)
    conn = get_db()
    try:
        product = conn.execute("SELECT * FROM products WHERE id = ? AND active = 1",
                               (product_id,)).fetchone()
        if not product:
            raise ApiError(404, "Product not found.")
        existing = conn.execute("SELECT id, qty FROM cart_items WHERE user_id = ? AND product_id = ?",
                                (user["id"], product_id)).fetchone()
        new_qty = qty + (existing["qty"] if existing else 0)
        if new_qty > product["stock"]:
            raise ApiError(400, f"Only {product['stock']} in stock.")
        if existing:
            conn.execute("UPDATE cart_items SET qty = ? WHERE id = ?", (new_qty, existing["id"]))
        else:
            conn.execute("INSERT INTO cart_items (user_id, product_id, qty) VALUES (?,?,?)",
                         (user["id"], product_id, qty))
        conn.commit()
    finally:
        conn.close()
    return 200, {"ok": True, "message": "Added to cart."}


def api_cart_update(user, params, body):
    product_id = to_int(body.get("product_id"), "Product id", 1)
    qty = to_int(body.get("qty"), "Quantity", 0, 20)
    conn = get_db()
    try:
        if qty == 0:
            conn.execute("DELETE FROM cart_items WHERE user_id = ? AND product_id = ?", (user["id"], product_id))
        else:
            product = conn.execute("SELECT stock FROM products WHERE id = ?", (product_id,)).fetchone()
            if not product:
                raise ApiError(404, "Product not found.")
            if qty > product["stock"]:
                raise ApiError(400, f"Only {product['stock']} in stock.")
            conn.execute("UPDATE cart_items SET qty = ? WHERE user_id = ? AND product_id = ?",
                         (qty, user["id"], product_id))
        conn.commit()
    finally:
        conn.close()
    return 200, {"ok": True}


def api_checkout(user, params, body):
    address = clean_str(body.get("address"), "Address", 160)
    city = clean_str(body.get("city"), "City", 80)
    zip_code = clean_str(body.get("zip"), "ZIP", 16)
    conn = get_db()
    try:
        items, subtotal = cart_rows(conn, user["id"])
        if not items:
            raise ApiError(400, "Your cart is empty.")
        shipping = 0 if subtotal >= 5000 else 499
        total = subtotal + shipping
        conn.execute("BEGIN")
        cur = conn.execute(
            "INSERT INTO orders (user_id, status, total_cents, address, city, zip, created_at)"
            " VALUES (?, 'placed', ?, ?, ?, ?, ?)",
            (user["id"], total, address, city, zip_code, now_iso()))
        order_id = cur.lastrowid
        for it in items:
            product = conn.execute("SELECT stock, active FROM products WHERE id = ?",
                                   (it["product_id"],)).fetchone()
            if not product or not product["active"] or product["stock"] < it["qty"]:
                raise ApiError(409, f"'{it['title']}' is no longer available in that quantity.")
            conn.execute("UPDATE products SET stock = stock - ? WHERE id = ?",
                         (it["qty"], it["product_id"]))
            conn.execute(
                "INSERT INTO order_items (order_id, product_id, title, price_cents, qty) VALUES (?,?,?,?,?)",
                (order_id, it["product_id"], it["title"], it["price_cents"], it["qty"]))
        conn.execute("DELETE FROM cart_items WHERE user_id = ?", (user["id"],))
        conn.commit()
    finally:
        conn.close()
    return 201, {"ok": True, "order_id": order_id, "total_cents": total,
                 "message": "Order placed successfully!"}


def api_orders(user, params):
    conn = get_db()
    try:
        orders = rows(conn.execute(
            "SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT 50", (user["id"],)))
        result = []
        for o in orders:
            items = rows(conn.execute(
                "SELECT title, price_cents, qty FROM order_items WHERE order_id = ?", (o["id"],)))
            result.append({
                "id": o["id"], "status": o["status"], "total_cents": o["total_cents"],
                "created_at": o["created_at"], "address": o["address"],
                "city": o["city"], "zip": o["zip"],
                "items": items,
            })
    finally:
        conn.close()
    return 200, {"orders": result}


# ---------------------------------------------------------------- routing

def api_products(body, user, params):
    q = (params.get("q") or [""])[0].strip().lower()
    category = (params.get("category") or [""])[0].strip()
    sort = (params.get("sort") or ["featured"])[0]
    conn = get_db()
    try:
        sql = "SELECT * FROM products WHERE active = 1"
        args = []
        if q:
            sql += " AND (LOWER(title) LIKE ? OR LOWER(description) LIKE ?)"
            args += [f"%{q}%", f"%{q}%"]
        if category:
            sql += " AND category = ?"
            args.append(category)
        if sort == "price_asc":
            sql += " ORDER BY price_cents ASC"
        elif sort == "price_desc":
            sql += " ORDER BY price_cents DESC"
        elif sort == "rating":
            sql += " ORDER BY rating DESC"
        else:
            sql += " ORDER BY id ASC"
        items = rows(conn.execute(sql, args))
    finally:
        conn.close()
    return 200, {"products": [product_dict(r) for r in items]}


def api_categories(body, user, params):
    conn = get_db()
    try:
        cats = rows(conn.execute(
            "SELECT category, COUNT(*) AS count FROM products WHERE active = 1"
            " GROUP BY category ORDER BY category"))
    finally:
        conn.close()
    return 200, {"categories": cats}


def api_product_get(body, user, params):
    product_id = to_int(params.get("id"), "Product id", 1)
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM products WHERE id = ? AND active = 1",
                           (product_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        raise ApiError(404, "Product not found.")
    return 200, {"product": product_dict(row)}


def api_admin_product_create(user, params, body):
    if user["role"] != "admin":
        raise ApiError(403, "Admin access required.")
    title = clean_str(body.get("title"), "Title", 140)
    description = clean_str(body.get("description"), "Description", 1000, required=False)
    category = clean_str(body.get("category"), "Category", 60)
    price = to_int(body.get("price_cents"), "Price", 1, 10_000_000)
    stock = to_int(body.get("stock"), "Stock", 0, 1_000_000)
    emoji = clean_str(body.get("emoji", "📦"), "Emoji", 8, required=False) or "📦"
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO products (title, description, category, price_cents, stock, emoji, rating, created_at)"
            " VALUES (?,?,?,?,?,?,4.5,?)",
            (title, description, category, price, stock, emoji, now_iso()))
        conn.commit()
        pid = cur.lastrowid
        row = conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
    finally:
        conn.close()
    return 201, {"product": product_dict(row)}


def api_admin_product_update(user, params, body):
    if user["role"] != "admin":
        raise ApiError(403, "Admin access required.")
    product_id = to_int(params.get("id"), "Product id", 1)
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        if not row:
            raise ApiError(404, "Product not found.")
        title = clean_str(body.get("title", row["title"]), "Title", 140)
        description = clean_str(body.get("description", row["description"]), "Description", 1000, required=False)
        category = clean_str(body.get("category", row["category"]), "Category", 60)
        price = to_int(body.get("price_cents", row["price_cents"]), "Price", 1, 10_000_000)
        stock = to_int(body.get("stock", row["stock"]), "Stock", 0, 1_000_000)
        active = body.get("active", bool(row["active"]))
        if not isinstance(active, bool):
            active = bool(active)
        conn.execute(
            "UPDATE products SET title=?, description=?, category=?, price_cents=?, stock=?, active=? WHERE id=?",
            (title, description, category, price, stock, int(active), product_id))
        conn.commit()
        row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    finally:
        conn.close()
    return 200, {"product": product_dict(row)}


def api_admin_product_delete(user, params, body):
    if user["role"] != "admin":
        raise ApiError(403, "Admin access required.")
    product_id = to_int(params.get("id"), "Product id", 1)
    conn = get_db()
    try:
        cur = conn.execute("UPDATE products SET active = 0 WHERE id = ?", (product_id,))
        if cur.rowcount == 0:
            raise ApiError(404, "Product not found.")
        conn.execute("DELETE FROM cart_items WHERE product_id = ?", (product_id,))
        conn.commit()
    finally:
        conn.close()
    return 200, {"ok": True}


def api_admin_orders(user, params):
    if user["role"] != "admin":
        raise ApiError(403, "Admin access required.")
    conn = get_db()
    try:
        orders = rows(conn.execute(
            "SELECT o.*, u.name AS customer_name, u.email AS customer_email"
            " FROM orders o JOIN users u ON u.id = o.user_id"
            " ORDER BY o.id DESC LIMIT 100"))
        result = []
        for o in orders:
            items = rows(conn.execute(
                "SELECT title, price_cents, qty FROM order_items WHERE order_id = ?", (o["id"],)))
            result.append({
                "id": o["id"], "status": o["status"], "total_cents": o["total_cents"],
                "created_at": o["created_at"],
                "customer": f"{o['customer_name']} ({o['customer_email']})",
                "ship_to": f"{o['address']}, {o['city']} {o['zip']}",
                "items": items,
            })
    finally:
        conn.close()
    return 200, {"orders": result}


def api_admin_order_status(user, params, body):
    if user["role"] != "admin":
        raise ApiError(403, "Admin access required.")
    order_id = to_int(params.get("id"), "Order id", 1)
    status = clean_str(body.get("status"), "Status", 20).lower()
    if status not in ORDER_STATUSES:
        raise ApiError(400, f"Status must be one of: {', '.join(ORDER_STATUSES)}.")
    if status == "cancelled":
        conn = get_db()
        try:
            order = conn.execute("SELECT id FROM orders WHERE id = ? AND status = 'placed'",
                                 (order_id,)).fetchone()
            if not order:
                raise ApiError(400, "Only 'placed' orders can be cancelled.")
            items = rows(conn.execute(
                "SELECT product_id, qty FROM order_items WHERE order_id = ?", (order_id,)))
            for it in items:
                if it["product_id"]:
                    conn.execute("UPDATE products SET stock = stock + ? WHERE id = ?",
                                 (it["qty"], it["product_id"]))
            conn.execute("UPDATE orders SET status = 'cancelled' WHERE id = ?", (order_id,))
            conn.commit()
        finally:
            conn.close()
    else:
        conn = get_db()
        try:
            cur = conn.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
            if cur.rowcount == 0:
                raise ApiError(404, "Order not found.")
            conn.commit()
        finally:
            conn.close()
    return 200, {"ok": True}


# ---------------------------------------------------------------- routing

ROUTES = {
    ("POST", "/api/register"): (api_register, False),
    ("POST", "/api/login"): (api_login, False),
    ("POST", "/api/logout"): (api_logout, False),
    ("GET", "/api/me"): (api_me, True),
    ("GET", "/api/products"): (api_products, False),
    ("GET", "/api/categories"): (api_categories, False),
    ("GET", "/api/product"): (api_product_get, False),
    ("GET", "/api/cart"): (api_cart_get, True),
    ("POST", "/api/cart"): (api_cart_add, True),
    ("PATCH", "/api/cart"): (api_cart_update, True),
    ("DELETE", "/api/cart"): (api_cart_clear, True),
    ("POST", "/api/orders"): (api_checkout, True),
    ("GET", "/api/orders"): (api_orders_list, True),
    ("GET", "/api/admin/stats"): (api_admin_stats, True),
    ("GET", "/api/admin/products"): (api_admin_products, True),
    ("POST", "/api/admin/products"): (api_admin_product_create, True),
    ("PATCH", "/api/admin/products"): (api_admin_product_update, True),
    ("DELETE", "/api/admin/products"): (api_admin_product_delete, True),
    ("GET", "/api/admin/orders"): (api_admin_orders, True),
    ("PATCH", "/api/admin/orders"): (api_admin_order_status, True),
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ShopNova/1.0"

    def log_message(self, fmt, *args):  # quiet default logging
        pass

    # -- response helpers -------------------------------------------------
    def send_json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ApiError(400, "Request body must be valid JSON.")
        if not isinstance(data, dict):
            raise ApiError(400, "Request body must be a JSON object.")
        return data

    def dispatch(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = parse_qs(parsed.query)

        if path.startswith("/api/"):
            route = ROUTES.get((self.command, path))
            if route is None:
                # path with id segment e.g. /api/product?id=1 uses query params
                return self.send_json(404, {"error": "Unknown endpoint."})
            handler, needs_auth = route
            try:
                body = self.read_body() if self.command in ("POST", "PATCH", "DELETE") else {}
                user = require_user(self.headers) if needs_auth else user_from_request(self.headers)
                result = handler(body, user, params)
                status, payload = result
                self.send_json(status, payload)
            except ApiError as e:
                self.send_json(e.status, {"error": e.message})
            except Exception as e:  # noqa: BLE001
                self.send_json(500, {"error": f"Internal error: {e}"})
            return

        if self.command != "GET":
            return self.send_json(405, {"error": "Method not allowed."})
        return self.serve_static(path)

    def serve_static(self, path):
        if path == "/":
            path = "/index.html"
        safe = os.path.normpath(path).lstrip("/\\")
        full = os.path.join(FRONTEND_DIR, safe)
        if not os.path.abspath(full).startswith(os.path.abspath(FRONTEND_DIR)):
            return self.send_json(403, {"error": "Forbidden."})
        if not os.path.isfile(full):
            return self.send_json(404, {"error": "Not found."})
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".ico": "image/x-icon",
        }.get(os.path.splitext(full)[1], "application/octet-stream")
        with open(full, "rb") as fh:
            data = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.dispatch()

    def do_POST(self):
        self.dispatch()

    def do_PATCH(self):
        self.dispatch()

    def do_DELETE(self):
        self.dispatch()


def run():
    init_db()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"ShopNova running at http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()

