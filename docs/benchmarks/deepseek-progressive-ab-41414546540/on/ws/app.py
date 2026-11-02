#!/usr/bin/env python3
"""
PulseCart - Amazon-like Ecommerce Platform (backend).

Zero third-party dependencies: uses only the Python standard library plus
SQLite for persistence. Serves both the REST/JSON API and the static frontend.

Run:      python3 app.py            (defaults to http://127.0.0.1:8000)
Custom:   PORT=9000 python3 app.py

Admin API key: env ADMIN_KEY, default "admin-secret".
"""
import json
import os
import re
import sqlite3
import secrets
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE_DIR, "store.db"))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
ADMIN_KEY = os.environ.get("ADMIN_KEY", "admin-secret")

# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    slug TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    category_id INTEGER REFERENCES categories(id),
    price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
    stock       INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
    rating      REAL NOT NULL DEFAULT 0,
    image_emoji TEXT NOT NULL DEFAULT '📦',
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS carts (
    token      TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cart_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    cart_token TEXT NOT NULL REFERENCES carts(token) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id),
    qty        INTEGER NOT NULL CHECK (qty > 0),
    UNIQUE (cart_token, product_id)
);
CREATE TABLE IF NOT EXISTS orders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    order_ref     TEXT NOT NULL UNIQUE,
    customer_name TEXT NOT NULL,
    email         TEXT NOT NULL,
    address       TEXT NOT NULL,
    total_cents   INTEGER NOT NULL,
    status        TEXT NOT NULL DEFAULT 'placed',
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS order_items (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id       INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id     INTEGER NOT NULL,
    title_snapshot TEXT NOT NULL,
    price_cents    INTEGER NOT NULL,
    qty            INTEGER NOT NULL
);
"""

SEED_CATEGORIES = [
    ("Electronics", "electronics"),
    ("Home & Kitchen", "home-kitchen"),
    ("Books", "books"),
    ("Fitness", "fitness"),
    ("Toys & Games", "toys-games"),
    ("Beauty", "beauty"),
]

SEED_PRODUCTS = [
    ("Wireless Noise-Cancelling Headphones", "Over-ear ANC headphones, 40h battery, USB-C fast charge.", "electronics", 12999, 42, 4.6, "🎧"),
    ("4K Ultra HD Smart TV 55\"", "HDR10+, built-in streaming apps, voice remote included.", "electronics", 44900, 12, 4.4, "📺"),
    ("Mechanical Keyboard (RGB)", "Hot-swappable switches, per-key RGB, aluminium frame.", "electronics", 8999, 60, 4.7, "⌨️"),
    ("Portable Bluetooth Speaker", "IPX7 waterproof, 24h playtime, deep bass radiator.", "electronics", 4599, 120, 4.3, "🔊"),
    ("Espresso Machine Pro", "15-bar pump, milk frother, dual boiler for back-to-back shots.", "home-kitchen", 21900, 18, 4.5, "☕"),
    ("Air Fryer 6L", "Rapid air circulation, 8 presets, dishwasher-safe basket.", "home-kitchen", 7499, 55, 4.6, "🍳"),
    ("Ceramic Dinnerware Set (16pc)", "Reactive-glaze stoneware, microwave and dishwasher safe.", "home-kitchen", 6500, 30, 4.2, "🍽️"),
    ("Robot Vacuum & Mop", "LiDAR mapping, auto-empty dock, app scheduling.", "home-kitchen", 32999, 9, 4.1, "🤖"),
    ("The Pragmatic Programmer", "20th anniversary edition, classic software craft.", "books", 3499, 200, 4.9, "📘"),
    ("Designing Data-Intensive Applications", "The definitive guide to distributed systems.", "books", 4299, 150, 4.8, "📕"),
    ("Atomic Habits", "Proven framework for building better habits.", "books", 1899, 300, 4.7, "📗"),
    ("Adjustable Dumbbell Set", "5-52.5 lb per hand, quick-change dial, compact stand.", "fitness", 24999, 22, 4.5, "🏋️"),
    ("Yoga Mat (6mm, Non-Slip)", "Eco TPE, alignment lines, carry strap included.", "fitness", 2999, 180, 4.4, "🧘"),
    ("Smart Jump Rope", "Cordless mode, app-tracked jumps, calorie counter.", "fitness", 1999, 95, 4.2, "🤸"),
    ("Building Blocks 1000pc", "STEM construction set, compatible with major brands.", "toys-games", 3999, 140, 4.6, "🧱"),
    ("Strategy Board Game Deluxe", "2-5 players, 60-min sessions, award-winning.", "toys-games", 5499, 48, 4.7, "🎲"),
    ("Vitamin C Brightening Serum", "20% L-ascorbic acid, hyaluronic base, 30ml.", "beauty", 3299, 88, 4.5, "🧴"),
    ("Hydrating Sheet Mask (10-pack)", "Ceramide + squalane, fragrance-free.", "beauty", 1599, 210, 4.3, "🧖"),
]


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    fresh = not os.path.exists(DB_PATH)
    conn = get_db()
    conn.executescript(SCHEMA)
    if fresh or conn.execute("SELECT COUNT(*) c FROM products").fetchone()["c"] == 0:
        now = datetime.now(timezone.utc).isoformat()
        for name, slug in SEED_CATEGORIES:
            conn.execute("INSERT OR IGNORE INTO categories(name, slug) VALUES (?, ?)", (name, slug))
        for title, desc, cat_slug, price, stock, rating, emoji in SEED_PRODUCTS:
            cat_id = conn.execute("SELECT id FROM categories WHERE slug=?", (cat_slug,)).fetchone()["id"]
            conn.execute(
                "INSERT INTO products(title, description, category_id, price_cents, stock, rating, image_emoji, active, created_at)"
                " VALUES (?,?,?,?,?,?,?,1,?)",
                (title, desc, cat_id, price, stock, rating, emoji, now),
            )
    conn.commit()
    conn.close()


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def row_to_product(row, categories):
    return {
        "id": row["id"],
        "title": row["title"],
        "description": row["description"],
        "category_id": row["category_id"],
        "category": categories.get(row["category_id"], "Uncategorised"),
        "price_cents": row["price_cents"],
        "price": round(row["price_cents"] / 100, 2),
        "stock": row["stock"],
        "rating": row["rating"],
        "image_emoji": row["image_emoji"],
        "active": bool(row["active"]),
    }


def category_map(conn):
    return {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM categories")}


def cart_summary(conn, token):
    rows = conn.execute(
        "SELECT ci.id item_id, ci.qty, p.id, p.title, p.price_cents, p.image_emoji, p.stock, p.active"
        " FROM cart_items ci JOIN products p ON p.id = ci.product_id"
        " WHERE ci.cart_token = ? ORDER BY ci.id",
        (token,),
    ).fetchall()
    items = []
    subtotal = 0
    for r in rows:
        line = r["price_cents"] * r["qty"]
        subtotal += line
        items.append({
            "item_id": r["item_id"], "product_id": r["id"], "title": r["title"],
            "image_emoji": r["image_emoji"], "price": round(r["price_cents"] / 100, 2),
            "price_cents": r["price_cents"], "qty": r["qty"],
            "stock": r["stock"], "active": bool(r["active"]), "line_total": round(line / 100, 2),
        })
    shipping = 0 if subtotal == 0 or subtotal >= 3500 else 499
    return {
        "items": items,
        "count": sum(i["qty"] for i in items),
        "subtotal_cents": subtotal,
        "subtotal": round(subtotal / 100, 2),
        "shipping_cents": shipping,
        "shipping": round(shipping / 100, 2),
        "total_cents": subtotal + shipping,
        "total": round((subtotal + shipping) / 100, 2),
    }


# --------------------------------------------------------------------------
# Request handler
# --------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "PulseCart/1.0"

    # ---- low-level helpers ----
    def _send(self, status, payload):
        body = json.dumps(payload, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Admin-Key")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return {}

    def _cart_token(self):
        return self.headers.get("X-Cart-Token") or parse_qs(urlparse(self.path).query).get("cart", [None])[0]

    def _ensure_cart(self, conn, token):
        if not token:
            token = secrets.token_hex(16)
            conn.execute("INSERT INTO carts(token, created_at) VALUES (?, ?)",
                         (token, datetime.now(timezone.utc).isoformat()))
            conn.commit()
        else:
            if not conn.execute("SELECT 1 FROM carts WHERE token=?", (token,)).fetchone():
                conn.execute("INSERT INTO carts(token, created_at) VALUES (?, ?)",
                             (token, datetime.now(timezone.utc).isoformat()))
                conn.commit()
        return token

    def _is_admin(self):
        return self.headers.get("X-Admin-Key") == ADMIN_KEY

    def log_message(self, fmt, *args):
        pass  # keep the console clean

    # ---- static files ----
    def _serve_static(self, path):
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        safe = os.path.normpath(os.path.join(FRONTEND_DIR, rel))
        if not safe.startswith(FRONTEND_DIR) or not os.path.isfile(safe):
            safe = os.path.join(FRONTEND_DIR, "index.html")
        ctype = {
            ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css",
            ".svg": "image/svg+xml", ".json": "application/json",
        }.get(os.path.splitext(safe)[1], "application/octet-stream")
        with open(safe, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---- HTTP verbs ----
    def do_OPTIONS(self):
        self._send(204, {})

    def do_GET(self):
        parsed = urlparse(self.path)
        path, qs = parsed.path, parse_qs(parsed.query)
        if not path.startswith("/api/"):
            return self._serve_static(path)
        try:
            self._route_get(path, qs)
        except Exception as exc:  # noqa: BLE001
            self._send(500, {"error": str(exc)})

    def do_POST(self):
        self._handle_write("POST")

    def do_PUT(self):
        self._handle_write("PUT")

    def do_DELETE(self):
        self._handle_write("DELETE")

    def _handle_write(self, method):
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            return self._send(404, {"error": "not found"})
        try:
            self._route_write(method, parsed.path)
        except Exception as exc:  # noqa: BLE001
            self._send(500, {"error": str(exc)})

    # ---- GET routes ----
    def _route_get(self, path, qs):
        conn = get_db()
        try:
            if path == "/api/health":
                return self._send(200, {"status": "ok", "time": datetime.now(timezone.utc).isoformat()})

            if path == "/api/categories":
                cats = [dict(r) for r in conn.execute(
                    "SELECT c.id, c.name, c.slug, COUNT(p.id) product_count FROM categories c"
                    " LEFT JOIN products p ON p.category_id=c.id AND p.active=1 GROUP BY c.id ORDER BY c.name")]
                return self._send(200, {"categories": cats})

            if path == "/api/products":
                cats = category_map(conn)
                sql = "SELECT * FROM products WHERE active=1"
                args = []
                if qs.get("search"):
                    term = f"%{qs['search'][0].lower()}%"
                    sql += " AND (LOWER(title) LIKE ? OR LOWER(description) LIKE ?)"
                    args += [term, term]
                if qs.get("category"):
                    sql += " AND category_id=(SELECT id FROM categories WHERE slug=?)"
                    args.append(qs["category"][0])
                if qs.get("min_price"):
                    sql += " AND price_cents >= ?"
                    args.append(int(float(qs["min_price"][0]) * 100))
                if qs.get("max_price"):
                    sql += " AND price_cents <= ?"
                    args.append(int(float(qs["max_price"][0]) * 100))
                sort = (qs.get("sort") or ["relevance"])[0]
                sql += {
                    "price_asc": " ORDER BY price_cents ASC",
                    "price_desc": " ORDER BY price_cents DESC",
                    "rating": " ORDER BY rating DESC",
                    "newest": " ORDER BY id DESC",
                }.get(sort, " ORDER BY rating DESC, id ASC")
                rows = conn.execute(sql, args).fetchall()
                products = [row_to_product(r, cats) for r in rows]
                return self._send(200, {"products": products, "count": len(products)})

            m = re.match(r"^/api/products/(\d+)$", path)
            if m:
                row = conn.execute("SELECT * FROM products WHERE id=? AND active=1", (int(m.group(1)),)).fetchone()
                if not row:
                    return self._send(404, {"error": "product not found"})
                return self._send(200, {"product": row_to_product(row, category_map(conn))})

            if path == "/api/cart":
                token = self._ensure_cart(conn, self._cart_token())
                data = cart_summary(conn, token)
                data["cart_token"] = token
                return self._send(200, data)

            if path == "/api/orders":
                if not self._is_admin():
                    return self._send(401, {"error": "admin key required"})
                orders = []
                for o in conn.execute("SELECT * FROM orders ORDER BY id DESC"):
                    items = [dict(r) for r in conn.execute("SELECT * FROM order_items WHERE order_id=?", (o["id"],))]
                    orders.append({**dict(o), "total": round(o["total_cents"] / 100, 2), "items": items})
                return self._send(200, {"orders": orders})

            if path == "/api/admin/stats":
                if not self._is_admin():
                    return self._send(401, {"error": "admin key required"})
                stats = {
                    "products": conn.execute("SELECT COUNT(*) c FROM products WHERE active=1").fetchone()["c"],
                    "orders": conn.execute("SELECT COUNT(*) c FROM orders").fetchone()["c"],
                    "revenue_cents": conn.execute("SELECT COALESCE(SUM(total_cents),0) c FROM orders WHERE status!='cancelled'").fetchone()["c"],
                    "low_stock": [row_to_product(r, category_map(conn)) for r in conn.execute(
                        "SELECT * FROM products WHERE active=1 AND stock <= 15 ORDER BY stock ASC")],
                }
                stats["revenue"] = round(stats["revenue_cents"] / 100, 2)
                return self._send(200, stats)

            return self._send(404, {"error": "unknown endpoint"})
        finally:
            conn.close()

    # ---- write routes ----
    def _route_write(self, method, path):
        conn = get_db()
        body = self._read_json()
        try:
            # ---- cart mutations ----
            if path == "/api/cart/items" and method == "POST":
                token = self._ensure_cart(conn, body.get("cart_token") or self._cart_token())
                pid, qty = int(body.get("product_id", 0)), max(1, int(body.get("qty", 1)))
                prod = conn.execute("SELECT id, stock FROM products WHERE id=? AND active=1", (pid,)).fetchone()
                if not prod:
                    return self._send(404, {"error": "product not found"})
                existing = conn.execute("SELECT id, qty FROM cart_items WHERE cart_token=? AND product_id=?",
                                        (token, pid)).fetchone()
                new_qty = (existing["qty"] if existing else 0) + qty
                if new_qty > prod["stock"]:
                    return self._send(400, {"error": f"only {prod['stock']} in stock"})
                if existing:
                    conn.execute("UPDATE cart_items SET qty=? WHERE id=?", (new_qty, existing["id"]))
                else:
                    conn.execute("INSERT INTO cart_items(cart_token, product_id, qty) VALUES (?,?,?)",
                                 (token, pid, qty))
                conn.commit()
                data = cart_summary(conn, token)
                data["cart_token"] = token
                return self._send(200, data)

            m = re.match(r"^/api/cart/items/(\d+)$", path)
            if m and method == "PUT":
                token = self._ensure_cart(conn, body.get("cart_token") or self._cart_token())
                item_id = int(m.group(1))
                qty = int(body.get("qty", 1))
                row = conn.execute("SELECT ci.id, p.stock FROM cart_items ci JOIN products p ON p.id=ci.product_id"
                                   " WHERE ci.id=? AND ci.cart_token=?", (item_id, token)).fetchone()
                if not row:
                    return self._send(404, {"error": "cart item not found"})
                if qty <= 0:
                    conn.execute("DELETE FROM cart_items WHERE id=?", (item_id,))
                elif qty > row["stock"]:
                    return self._send(400, {"error": f"only {row['stock']} in stock"})
                else:
                    conn.execute("UPDATE cart_items SET qty=? WHERE id=?", (qty, item_id))
                conn.commit()
                data = cart_summary(conn, token)
                data["cart_token"] = token
                return self._send(200, data)

            m = re.match(r"^/api/cart/items/(\d+)$", path)
            if m and method == "DELETE":
                token = self._ensure_cart(conn, self._cart_token())
                conn.execute("DELETE FROM cart_items WHERE id=? AND cart_token=?", (int(m.group(1)), token))
                conn.commit()
                data = cart_summary(conn, token)
                data["cart_token"] = token
                return self._send(200, data)

            if path == "/api/checkout" and method == "POST":
                token = self._ensure_cart(conn, body.get("cart_token") or self._cart_token())
                summary = cart_summary(conn, token)
                if not summary["items"]:
                    return self._send(400, {"error": "your cart is empty"})
                name, email, address = body.get("name", "").strip(), body.get("email", "").strip(), body.get("address", "").strip()
                if not name or not email or not address:
                    return self._send(400, {"error": "name, email and address are required"})
                if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
                    return self._send(400, {"error": "invalid email address"})
                for item in summary["items"]:
                    stock = conn.execute("SELECT stock FROM products WHERE id=?", (item["product_id"],)).fetchone()["stock"]
                    if item["qty"] > stock:
                        return self._send(409, {"error": f"'{item['title']}' only has {stock} left"})
                ref = "PC-" + datetime.now(timezone.utc).strftime("%y%m%d") + "-" + secrets.token_hex(3).upper()
                cur = conn.execute(
                    "INSERT INTO orders(order_ref, customer_name, email, address, total_cents, status, created_at)"
                    " VALUES (?,?,?,?,?, 'placed', ?)",
                    (ref, name, email, address, summary["total_cents"], datetime.now(timezone.utc).isoformat()))
                order_id = cur.lastrowid
                for item in summary["items"]:
                    conn.execute("INSERT INTO order_items(order_id, product_id, title_snapshot, price_cents, qty)"
                                 " VALUES (?,?,?,?,?)",
                                 (order_id, item["product_id"], item["title"], item["price_cents"], item["qty"]))
                    conn.execute("UPDATE products SET stock = stock - ? WHERE id = ?", (item["qty"], item["product_id"]))
                conn.execute("DELETE FROM cart_items WHERE cart_token=?", (token,))
                conn.commit()
                return self._send(201, {"order_ref": ref, "total": summary["total"], "status": "placed"})

            # ---- admin mutations ----
            if path == "/api/products" and method == "POST":
                if not self._is_admin():
                    return self._send(401, {"error": "admin key required"})
                if not body.get("title") or body.get("price_cents") is None:
                    return self._send(400, {"error": "title and price_cents are required"})
                cat_id = body.get("category_id")
                cur = conn.execute(
                    "INSERT INTO products(title, description, category_id, price_cents, stock, rating, image_emoji, active, created_at)"
                    " VALUES (?,?,?,?,?,?,?,1,?)",
                    (body["title"], body.get("description", ""), cat_id, int(body["price_cents"]),
                     int(body.get("stock", 0)), float(body.get("rating", 0)),
                     body.get("image_emoji", "📦"), datetime.now(timezone.utc).isoformat()))
                conn.commit()
                row = conn.execute("SELECT * FROM products WHERE id=?", (cur.lastrowid,)).fetchone()
                return self._send(201, {"product": row_to_product(row, category_map(conn))})

            m = re.match(r"^/api/products/(\d+)$", path)
            if m and method == "PUT":
                if not self._is_admin():
                    return self._send(401, {"error": "admin key required"})
                pid = int(m.group(1))
                row = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
                if not row:
                    return self._send(404, {"error": "product not found"})
                fields = {k: body[k] for k in
                          ("title", "description", "category_id", "price_cents", "stock", "rating", "image_emoji", "active")
                          if k in body}
                if "active" in fields:
                    fields["active"] = 1 if fields["active"] else 0
                if fields:
                    sets = ", ".join(f"{k}=?" for k in fields)
                    conn.execute(f"UPDATE products SET {sets} WHERE id=?", (*fields.values(), pid))
                    conn.commit()
                row = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
                return self._send(200, {"product": row_to_product(row, category_map(conn))})

            m = re.match(r"^/api/products/(\d+)$", path)
            if m and method == "DELETE":
                if not self._is_admin():
                    return self._send(401, {"error": "admin key required"})
                pid = int(m.group(1))
                if not conn.execute("SELECT 1 FROM products WHERE id=?", (pid,)).fetchone():
                    return self._send(404, {"error": "product not found"})
                conn.execute("UPDATE products SET active=0 WHERE id=?", (pid,))
                conn.commit()
                return self._send(200, {"deleted": pid})

            m = re.match(r"^/api/orders/(\d+)/status$", path)
            if m and method == "PUT":
                if not self._is_admin():
                    return self._send(401, {"error": "admin key required"})
                status = body.get("status")
                if status not in ("placed", "shipped", "delivered", "cancelled"):
                    return self._send(400, {"error": "invalid status"})
                conn.execute("UPDATE orders SET status=? WHERE id=?", (status, int(m.group(1))))
                conn.commit()
                return self._send(200, {"order_id": int(m.group(1)), "status": status})

            return self._send(404, {"error": "unknown endpoint"})
        finally:
            conn.close()


def main():
    init_db()
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"PulseCart running on http://127.0.0.1:{port}  (admin key: {ADMIN_KEY})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")


if __name__ == "__main__":
    main()
