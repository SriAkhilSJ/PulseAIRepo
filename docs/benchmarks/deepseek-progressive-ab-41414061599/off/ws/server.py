#!/usr/bin/env python3
"""
Nova Market - Amazon-style ecommerce backend.

Zero third-party dependencies (python3 stdlib only) so it runs anywhere:

    python3 server.py            # http://127.0.0.1:8000
    PORT=9000 python3 server.py

Architecture
------------
* SQLite  (store.db)          - persistence: products, carts, orders
* REST/JSON API under /api/*  - validation + business logic
* frontend/                   - reactive storefront + admin hub

Admin endpoints require the header `X-Admin-Token`. Default token is
`nova-admin` and can be overridden with the ADMIN_TOKEN env var.
"""

import json
import os
import re
import secrets
import sqlite3
import threading
import time
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "store.db")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "nova-admin")
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))

DB_LOCK = threading.Lock()


# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT    NOT NULL,
    brand       TEXT    NOT NULL DEFAULT 'Nova',
    category    TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    price       REAL    NOT NULL CHECK (price >= 0),
    list_price  REAL,
    stock       INTEGER NOT NULL DEFAULT 0,
    rating      REAL    NOT NULL DEFAULT 4.5,
    reviews     INTEGER NOT NULL DEFAULT 0,
    image       TEXT    NOT NULL DEFAULT '',
    featured    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS cart_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL,
    product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    qty         INTEGER NOT NULL CHECK (qty > 0),
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (session_id, product_id)
);

CREATE TABLE IF NOT EXISTS orders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    reference     TEXT    NOT NULL UNIQUE,
    session_id    TEXT    NOT NULL,
    customer_name TEXT    NOT NULL,
    email         TEXT    NOT NULL,
    address       TEXT    NOT NULL,
    subtotal      REAL    NOT NULL,
    shipping      REAL    NOT NULL,
    total         REAL    NOT NULL,
    status        TEXT    NOT NULL DEFAULT 'confirmed',
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS order_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id   INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL,
    title      TEXT    NOT NULL,
    price      REAL    NOT NULL,
    qty        INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
CREATE INDEX IF NOT EXISTS idx_cart_session ON cart_items(session_id);
"""

SEED = [
    ("Aurora 4K Ultra HD Smart TV, 55\"", "Aurora", "Electronics", "Cinematic 4K HDR panel with Dolby Atmos, built-in streaming hub and voice remote.", 649.00, 799.00, 42, 4.7, 1832, "aurora-tv"),
    ("Pulse Wireless Noise-Cancelling Headphones", "Pulse", "Electronics", "Adaptive ANC, 40-hour battery and spatial audio for commute and studio alike.", 199.99, 249.00, 120, 4.6, 4210, "pulse-headphones"),
    ("Nimbus 14\" Ultralight Laptop, 16GB/512GB", "Nimbus", "Computers", "1.1kg magnesium chassis, 20-hour battery, 2.8K display.", 1099.00, 1249.00, 18, 4.8, 964, "nimbus-laptop"),
    ("Vertex Mechanical Keyboard, Hot-Swappable", "Vertex", "Computers", "75% layout, gasket mount, RGB per-key and USB-C detachable cable.", 129.50, 159.00, 75, 4.5, 1180, "vertex-keyboard"),
    ("Halo Smartwatch Series 6, GPS + Cellular", "Halo", "Wearables", "Blood-oxygen, ECG, sleep staging and 7-day battery life.", 329.00, None, 64, 4.6, 2740, "halo-watch"),
    ("Echo Home Speaker with Ambient Light", "Echo", "Smart Home", "Room-filling sound, built-in assistant and adaptive lighting.", 89.99, 119.00, 210, 4.4, 8901, "echo-speaker"),
    ("Terra Espresso Machine, 15-Bar", "Terra", "Kitchen", "Café-grade pressure, PID temperature control and steam wand.", 349.00, 429.00, 33, 4.7, 640, "terra-espresso"),
    ("Cascade Air Purifier for Large Rooms", "Cascade", "Home", "HEPA-13 filtration covering 1200 sq ft, whisper-quiet night mode.", 219.00, 269.00, 88, 4.5, 1320, "cascade-purifier"),
    ("Drift Wireless Earbuds with ANC", "Drift", "Electronics", "Compact case, 32-hour total playback, IPX5 sweat resistance.", 79.99, 99.00, 300, 4.3, 5610, "drift-earbuds"),
    ("Orion Gaming Monitor 27\", 165Hz QHD", "Orion", "Computers", "1ms response, HDR400, adaptive sync for tear-free play.", 279.00, 339.00, 51, 4.6, 942, "orion-monitor"),
    ("Lumen Desk Lamp with Wireless Charging", "Lumen", "Home", "Flicker-free LEDs, 5 colour temperatures and a Qi charging base.", 59.00, 79.00, 145, 4.4, 2103, "lumen-lamp"),
    ("Trailhead Running Shoes, Unisex", "Trailhead", "Fitness", "Responsive foam midsole with a grippy all-terrain outsole.", 119.00, 145.00, 190, 4.5, 3300, "trailhead-shoes"),
    ("Forge Adjustable Dumbbell Set, 5-52lb", "Forge", "Fitness", "Dial-based weight changes in seconds; replaces 15 pairs.", 399.00, 499.00, 22, 4.8, 780, "forge-dumbbells"),
    ("Kindle-style Paperwhite Reader 8GB", "Leaf", "Electronics", "300ppi glare-free display, adjustable warm light, waterproof.", 139.00, None, 160, 4.7, 6120, "leaf-reader"),
    ("Sable Cast Iron Dutch Oven, 6Qt", "Sable", "Kitchen", "Enamelled cast iron, oven-safe to 500°F, lifetime warranty.", 99.00, 139.00, 70, 4.8, 1540, "sable-dutchoven"),
    ("Bloom Robot Vacuum with Self-Empty Base", "Bloom", "Smart Home", "LiDAR mapping, 60-day debris bag and app scheduling.", 449.00, 549.00, 40, 4.5, 2210, "bloom-vacuum"),
    ("Quill Fountain Pen Gift Set", "Quill", "Office", "Brass barrel, smooth medium nib and two ink cartridges.", 45.00, 65.00, 130, 4.6, 410, "quill-pen"),
    ("Summit Insulated Water Bottle, 32oz", "Summit", "Fitness", "Keeps drinks cold 36h / hot 18h, leak-proof lid.", 34.00, 45.00, 420, 4.7, 9100, "summit-bottle"),
    ("Nova Standing Desk 55\", Electric", "Nova", "Office", "Dual motors, 4 memory presets and integrated cable tray.", 469.00, 599.00, 26, 4.6, 870, "nova-desk"),
    ("Cove Weighted Blanket, 15lb", "Cove", "Home", "Breathable cotton shell with evenly distributed micro-glass beads.", 74.00, 99.00, 95, 4.5, 1680, "cove-blanket"),
    ("Atlas Backpack, 28L Commuter", "Atlas", "Office", "Water-resistant shell, padded 16\" laptop sleeve, luggage pass-through.", 89.00, 119.00, 110, 4.6, 2450, "atlas-backpack"),
    ("Vista Drone with 4K Gimbal Camera", "Vista", "Electronics", "31-minute flight time, obstacle sensing and cinematic modes.", 549.00, 649.00, 15, 4.7, 520, "vista-drone"),
    ("Ember Electric Toothbrush, Smart", "Ember", "Health", "Pressure sensor, 5 modes and 3-week battery per charge.", 69.00, 89.00, 240, 4.5, 3760, "ember-toothbrush"),
    ("Compass Cast Iron Skillet, 12\"", "Compass", "Kitchen", "Pre-seasoned, restaurant-grade iron for stove-to-oven cooking.", 39.00, 55.00, 180, 4.8, 4020, "compass-skillet"),
]


def seed(conn):
    if conn.execute("SELECT COUNT(*) AS n FROM products").fetchone()["n"] > 0:
        return
    for i, p in enumerate(SEED):
        title, brand, cat, desc, price, list_price, stock, rating, reviews, slug = p
        conn.execute(
            """INSERT INTO products
               (title, brand, category, description, price, list_price, stock, rating, reviews, image, featured)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (title, brand, cat, desc, price, list_price, stock, rating, reviews,
             f"https://picsum.photos/seed/{slug}/600/450", 1 if i % 4 == 0 else 0),
        )
    conn.commit()


def init_db():
    with connect() as conn:
        conn.executescript(SCHEMA)
        seed(conn)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def product_payload(row):
    d = dict(row)
    d["in_stock"] = d["stock"] > 0
    d["discount"] = (
        round((1 - d["price"] / d["list_price"]) * 100)
        if d.get("list_price") else 0
    )
    return d


def err(message, status=HTTPStatus.BAD_REQUEST, field=None):
    body = {"error": message}
    if field:
        body["field"] = field
    return status, body


# --------------------------------------------------------------------------
# Request handler
# --------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "NovaMarket/1.0"

    # ---- plumbing --------------------------------------------------------
    def log_message(self, fmt, *args):
        pass  # keep the console clean

    def _json(self, status, payload, extra_headers=None):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _raw(self, status, body, content_type, extra_headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw or b"{}")
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return None  # signals malformed payload

    def _session(self):
        cookie = SimpleCookie(self.headers.get("Cookie"))
        if "nova_sid" in cookie:
            return cookie["nova_sid"].value, None
        sid = secrets.token_hex(16)
        return sid, f"nova_sid={sid}; Path=/; SameSite=Lax; Max-Age=2592000"

    def _admin(self, params):
        return self.headers.get("X-Admin-Token") == ADMIN_TOKEN

    # ---- routing ---------------------------------------------------------
    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def do_PUT(self):
        self._route("PUT")

    def do_PATCH(self):
        self._route("PATCH")

    def do_DELETE(self):
        self._route("DELETE")

    def _route(self, method):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        sid, set_cookie = self._session()
        extra = {"Set-Cookie": set_cookie} if set_cookie else {}
        try:
            status, payload = self.dispatch(method, path, params, sid)
        except Exception as exc:  # pragma: no cover - safety net
            status, payload = HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)}
        if path.startswith("/api"):
            self._json(status, payload, extra)
        else:
            self._serve_static(path, payload, status)

    # ---- API -------------------------------------------------------------
    def dispatch(self, method, path, params, sid):
        # --- products (public)
        if path == "/api/categories" and method == "GET":
            with connect() as conn:
                rows = conn.execute(
                    "SELECT category, COUNT(*) n FROM products GROUP BY category ORDER BY category"
                ).fetchall()
            return HTTPStatus.OK, {"categories": [dict(r) for r in rows]}

        if path == "/api/products" and method == "GET":
            return self.list_products(params)

        m = re.fullmatch(r"/api/products/(\d+)", path)
        if m and method == "GET":
            with connect() as conn:
                row = conn.execute("SELECT * FROM products WHERE id=?", (m.group(1),)).fetchone()
            if not row:
                return err("Product not found", HTTPStatus.NOT_FOUND)
            return HTTPStatus.OK, product_payload(row)

        # --- cart
        if path == "/api/cart" and method == "GET":
            return self.get_cart(sid)
        if path == "/api/cart" and method == "POST":
            return self.add_to_cart(sid)
        m = re.fullmatch(r"/api/cart/(\d+)", path)
        if m and method == "PATCH":
            return self.update_cart(sid, int(m.group(1)))
        if m and method == "DELETE":
            return self.remove_cart(sid, int(m.group(1)))

        # --- orders
        if path == "/api/orders" and method == "POST":
            return self.create_order(sid)
        if path == "/api/orders" and method == "GET":
            with connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM orders WHERE session_id=? ORDER BY id DESC", (sid,)
                ).fetchall()
            return HTTPStatus.OK, {"orders": [dict(r) for r in rows]}

        # --- admin
        if path.startswith("/api/admin"):
            if not self._admin(params):
                return err("Admin token required", HTTPStatus.UNAUTHORIZED)
            return self.admin(method, path, params)

        return err("Not found", HTTPStatus.NOT_FOUND)

    def list_products(self, params):
        q = (params.get("q") or "").strip()
        category = (params.get("category") or "").strip()
        sort = params.get("sort") or "featured"
        clauses, args = [], []
        if q:
            clauses.append("(title LIKE ? OR brand LIKE ? OR description LIKE ?)")
            like = f"%{q}%"
            args += [like, like, like]
        if category and category.lower() != "all":
            clauses.append("category = ?")
            args.append(category)
        if params.get("max_price"):
            try:
                args.append(float(params["max_price"])); clauses.append("price <= ?")
            except ValueError:
                pass
        if params.get("in_stock") == "1":
            clauses.append("stock > 0")

        order = {
            "price_asc": "price ASC",
            "price_desc": "price DESC",
            "rating": "rating DESC",
            "newest": "id DESC",
            "featured": "featured DESC, reviews DESC",
        }.get(sort, "featured DESC, reviews DESC")

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM products {where} ORDER BY {order} LIMIT 200", args
            ).fetchall()
        return HTTPStatus.OK, {"products": [product_payload(r) for r in rows], "count": len(rows)}

    def get_cart(self, sid):
        with connect() as conn:
            rows = conn.execute(
                """SELECT c.id AS item_id, c.qty, p.*
                   FROM cart_items c JOIN products p ON p.id = c.product_id
                   WHERE c.session_id=? ORDER BY c.id""", (sid,)
            ).fetchall()
            items, subtotal = [], 0.0
            for r in rows:
                d = product_payload(r)
                d["item_id"] = d.pop("item_id")
                d["line_total"] = round(d["price"] * d["qty"], 2)
                subtotal += d["line_total"]
                items.append(d)
        shipping = 0.0 if subtotal >= 50 or subtotal == 0 else 6.99
        return HTTPStatus.OK, {
            "items": items,
            "count": sum(i["qty"] for i in items),
            "subtotal": round(subtotal, 2),
            "shipping": round(shipping, 2),
            "total": round(subtotal + shipping, 2),
        }

    def add_to_cart(self, sid):
        data = self._body()
        if data is None:
            return err("Malformed JSON body")
        pid, qty = data.get("product_id"), data.get("qty", 1)
        if not isinstance(pid, int):
            return err("product_id must be an integer", field="product_id")
        if not isinstance(qty, int) or qty < 1 or qty > 99:
            return err("qty must be between 1 and 99", field="qty")
        with connect() as conn:
            p = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
            if not p:
                return err("Product not found", HTTPStatus.NOT_FOUND, "product_id")
            if p["stock"] < qty:
                return err(f"Only {p['stock']} in stock", HTTPStatus.CONFLICT, "qty")
            conn.execute(
                """INSERT INTO cart_items (session_id, product_id, qty) VALUES (?,?,?)
                   ON CONFLICT(session_id, product_id)
                   DO UPDATE SET qty = MIN(qty + excluded.qty, 99)""",
                (sid, pid, qty),
            )
            conn.commit()
        return self.get_cart(sid)

    def update_cart(self, sid, item_id):
        data = self._body()
        if data is None:
            return err("Malformed JSON body")
        qty = data.get("qty")
        if not isinstance(qty, int) or qty < 0 or qty > 99:
            return err("qty must be between 0 and 99", field="qty")
        with connect() as conn:
            item = conn.execute(
                "SELECT * FROM cart_items WHERE id=? AND session_id=?", (item_id, sid)
            ).fetchone()
            if not item:
                return err("Cart item not found", HTTPStatus.NOT_FOUND)
            if qty == 0:
                conn.execute("DELETE FROM cart_items WHERE id=?", (item_id,))
            else:
                conn.execute("UPDATE cart_items SET qty=? WHERE id=?", (qty, item_id))
            conn.commit()
        return self.get_cart(sid)

    def remove_cart(self, sid, item_id):
        with connect() as conn:
            conn.execute("DELETE FROM cart_items WHERE id=? AND session_id=?", (item_id, sid))
            conn.commit()
        return self.get_cart(sid)

    def create_order(self, sid):
        data = self._body()
        if data is None:
            return err("Malformed JSON body")
        name = (data.get("customer_name") or "").strip()
        email = (data.get("email") or "").strip()
        address = (data.get("address") or "").strip()
        if len(name) < 2:
            return err("Please enter your full name", field="customer_name")
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            return err("Please enter a valid email", field="email")
        if len(address) < 8:
            return err("Please enter a full shipping address", field="address")

        with connect() as conn:
            rows = conn.execute(
                """SELECT c.qty, p.id, p.title, p.price, p.stock
                   FROM cart_items c JOIN products p ON p.id = c.product_id
                   WHERE c.session_id=?""", (sid,)
            ).fetchall()
            if not rows:
                return err("Your cart is empty", HTTPStatus.CONFLICT)
            for r in rows:
                if r["stock"] < r["qty"]:
                    return err(f"'{r['title']}' only has {r['stock']} left", HTTPStatus.CONFLICT)

            subtotal = round(sum(r["price"] * r["qty"] for r in rows), 2)
            shipping = 0.0 if subtotal >= 50 else 6.99
            total = round(subtotal + shipping, 2)
            ref = "NOVA-" + secrets.token_hex(4).upper()
            cur = conn.execute(
                """INSERT INTO orders
                   (reference, session_id, customer_name, email, address, subtotal, shipping, total)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (ref, sid, name, email, address, subtotal, shipping, total),
            )
            oid = cur.lastrowid
            for r in rows:
                conn.execute(
                    "INSERT INTO order_items (order_id, product_id, title, price, qty) VALUES (?,?,?,?,?)",
                    (oid, r["id"], r["title"], r["price"], r["qty"]),
                )
                conn.execute("UPDATE products SET stock = stock - ? WHERE id=?", (r["qty"], r["id"]))
            conn.execute("DELETE FROM cart_items WHERE session_id=?", (sid,))
            conn.commit()
        return HTTPStatus.CREATED, {
            "order": {"id": oid, "reference": ref, "total": total,
                      "subtotal": subtotal, "shipping": shipping, "status": "confirmed"}
        }

    # ---- admin -----------------------------------------------------------
    def admin(self, method, path, params):
        if path == "/api/admin/stats" and method == "GET":
            with connect() as conn:
                products = conn.execute("SELECT COUNT(*) n FROM products").fetchone()["n"]
                low = conn.execute("SELECT COUNT(*) n FROM products WHERE stock < 20").fetchone()["n"]
                orders = conn.execute("SELECT COUNT(*) n FROM orders").fetchone()["n"]
                revenue = conn.execute("SELECT COALESCE(SUM(total),0) r FROM orders").fetchone()["r"]
            return HTTPStatus.OK, {"products": products, "low_stock": low,
                                   "orders": orders, "revenue": round(revenue, 2)}

        if path == "/api/admin/orders" and method == "GET":
            with connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM orders ORDER BY id DESC LIMIT 100"
                ).fetchall()
                out = []
                for o in rows:
                    items = conn.execute(
                        """SELECT title, price, qty FROM order_items
                           WHERE order_id=? ORDER BY id""", (o["id"],)
                    ).fetchall()
                    d = dict(o)
                    d["items"] = [dict(i) for i in items]
                    d["item_count"] = sum(i["qty"] for i in items)
                    out.append(d)
            return HTTPStatus.OK, {"orders": out}

        if path == "/api/admin/products" and method == "GET":
            with connect() as conn:
                rows = conn.execute("SELECT * FROM products ORDER BY id DESC").fetchall()
            return HTTPStatus.OK, {"products": [product_payload(r) for r in rows]}

        if path == "/api/admin/products" and method == "POST":
            return self.upsert_product(None)

        m = re.fullmatch(r"/api/admin/products/(\d+)", path)
        if m and method == "PUT":
            return self.upsert_product(int(m.group(1)))
        if m and method == "DELETE":
            with connect() as conn:
                conn.execute("DELETE FROM products WHERE id=?", (m.group(1),))
                conn.commit()
            return HTTPStatus.OK, {"deleted": int(m.group(1))}
        return err("Not found", HTTPStatus.NOT_FOUND)

    def upsert_product(self, pid):
        data = self._body()
        if data is None:
            return err("Malformed JSON body")
        title = (data.get("title") or "").strip()
        category = (data.get("category") or "").strip()
        if len(title) < 3:
            return err("Title must be at least 3 characters", field="title")
        if not category:
            return err("Category is required", field="category")
        try:
            price = float(data.get("price"))
            stock = int(data.get("stock", 0))
        except (TypeError, ValueError):
            return err("Price and stock must be numbers", field="price")
        if price < 0 or stock < 0:
            return err("Price and stock must be positive", field="price")
        brand = (data.get("brand") or "Nova").strip()
        desc = (data.get("description") or "").strip()
        image = (data.get("image") or "").strip() or \
            f"https://picsum.photos/seed/{secrets.token_hex(4)}/600/450"
        list_price = data.get("list_price")
        try:
            list_price = float(list_price) if list_price not in (None, "", 0) else None
        except (TypeError, ValueError):
            list_price = None

        with connect() as conn:
            if pid is None:
                cur = conn.execute(
                    """INSERT INTO products (title, brand, category, description, price,
                                             list_price, stock, image)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (title, brand, category, desc, price, list_price, stock, image),
                )
                pid = cur.lastrowid
            else:
                if not conn.execute("SELECT 1 FROM products WHERE id=?", (pid,)).fetchone():
                    return err("Product not found", HTTPStatus.NOT_FOUND)
                conn.execute(
                    """UPDATE products SET title=?, brand=?, category=?, description=?,
                       price=?, list_price=?, stock=?, image=? WHERE id=?""",
                    (title, brand, category, desc, price, list_price, stock, image, pid),
                )
            conn.commit()
            row = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
        return (HTTPStatus.CREATED if pid else HTTPStatus.OK), {"product": product_payload(row)}

    # ---- static ----------------------------------------------------------
    def _serve_static(self, path, payload, status):
        if path.startswith("/api"):
            return
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        target = os.path.normpath(os.path.join(FRONTEND_DIR, rel))
        if not target.startswith(FRONTEND_DIR) or not os.path.isfile(target):
            self._raw(HTTPStatus.NOT_FOUND, b"Not found", "text/plain")
            return
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".svg": "image/svg+xml",
            ".json": "application/json",
        }.get(os.path.splitext(target)[1], "application/octet-stream")
        with open(target, "rb") as fh:
            self._raw(HTTPStatus.OK, fh.read(), ctype)


def main():
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Nova Market running on http://{HOST}:{PORT}")
    print(f"Admin token: {ADMIN_TOKEN}  (send as X-Admin-Token header)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
