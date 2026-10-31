"""PulseGear — REST API server for the e-commerce store.

Zero-dependency Python HTTP server exposing a JSON API and serving the
frontend. Run `python backend/server.py`, then open http://localhost:8000.
"""
import json
import os
import re
import secrets
import sqlite3
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import get_conn, init_db, verify_password, hash_password  # noqa: E402

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.normpath(os.path.join(BASE_DIR, "..", "frontend"))
PORT = int(os.environ.get("PORT", "8000"))
SESSION_TTL = 7 * 24 * 3600

_sessions = {}  # token -> {"email", "role", "ts"}


def _now() -> float:
    return datetime.utcnow().timestamp()


def create_session(email: str, role: str) -> str:
    token = secrets.token_hex(16)
    _sessions[token] = {"email": email, "role": role, "ts": _now()}
    return token


def session_user(token: str):
    sess = _sessions.get(token or "")
    if not sess:
        return None
    if _now() - sess["ts"] > SESSION_TTL:
        _sessions.pop(token, None)
        return None
    sess["ts"] = _now()
    return sess


def require_admin(handler):
    sess = session_user(handler.headers.get("X-Session-Token", ""))
    if not sess or sess["role"] != "admin":
        handler.send_json({"error": "admin session required"}, 401)
        return None
    return sess


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------- plumbing
    def log_message(self, fmt, *args):  # quiet access log
        pass

    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode())
        except (ValueError, UnicodeDecodeError):
            return {}

    def handle_request(self, method):
        parsed = urlparse(self.path)
        path = parsed.path
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}

        if method == "GET" and (path == "/" or path.startswith("/static") or not path.startswith("/api")):
            return self.serve_static(path)

        routes = {
            ("GET", "/api/products"): self.list_products,
            ("GET", "/api/categories"): self.list_categories,
            ("POST", "/api/auth/register"): self.register,
            ("POST", "/api/auth/login"): self.login,
            ("POST", "/api/auth/logout"): self.logout,
            ("GET", "/api/auth/me"): self.me,
            ("GET", "/api/cart"): self.get_cart,
            ("POST", "/api/cart/items"): self.add_to_cart,
            ("POST", "/api/cart/add"): self.add_to_cart,
            ("PUT", "/api/cart/items"): self.update_cart_item,
            ("POST", "/api/cart/set"): self.update_cart_item,
            ("DELETE", "/api/cart/items"): self.remove_cart_item,
            ("POST", "/api/checkout"): self.checkout,
            ("POST", "/api/orders"): self.checkout,
            ("GET", "/api/orders"): self.list_orders,
            ("GET", "/api/admin/orders"): self.list_orders,
            ("GET", "/api/admin/products"): self.list_products,
            ("POST", "/api/admin/products"): self.create_product,
            ("PUT", "/api/admin/products"): self.update_product,
            ("DELETE", "/api/admin/products"): self.delete_product,
            ("GET", "/api/admin/stats"): self.admin_stats,
            ("PUT", "/api/admin/orders"): self.update_order_status,
        }
        func = routes.get((method, path))
        if func is None and path.startswith("/api/products/"):
            func = self.product_detail if method == "GET" else None
        elif func is None and path.startswith("/api/admin/products/"):
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[-1].isdigit():
                query["id"] = int(parts[-1])
                func = self.update_product if method == "PUT" else (self.delete_product if method == "DELETE" else None)
        elif func is None and path.startswith("/api/admin/orders/"):
            parts = path.strip("/").split("/")
            if len(parts) >= 4 and parts[3].isdigit():
                query["order_id"] = int(parts[3])
                func = self.update_order_status if method == "PUT" else None
        if func is None:
            return self.send_json({"error": "not found"}, 404)
        try:
            func(query)
        except sqlite3.Error as exc:
            self.send_json({"error": f"database error: {exc}"}, 500)

    def do_GET(self):
        self.handle_request("GET")

    def do_POST(self):
        self.handle_request("POST")

    def do_PUT(self):
        self.handle_request("PUT")

    def do_DELETE(self):
        self.handle_request("DELETE")

    def serve_static(self, path):
        if path in ("/", "/index.html", "/admin", "/login"):
            file_path = os.path.join(FRONTEND_DIR, "index.html")
        else:
            rel = path.lstrip("/").replace("..", "")
            file_path = os.path.normpath(os.path.join(FRONTEND_DIR, rel))
            if not str(file_path).startswith(FRONTEND_DIR):
                return self.send_json({"error": "forbidden"}, 403)
        if not os.path.isfile(file_path):
            file_path = os.path.join(FRONTEND_DIR, "index.html")
        try:
            with open(file_path, "rb") as fh:
                body = fh.read()
        except OSError:
            return self.send_json({"error": "frontend missing"}, 500)
        ctype = "text/html; charset=utf-8"
        if file_path.endswith(".js"):
            ctype = "application/javascript"
        elif file_path.endswith(".css"):
            ctype = "text/css"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # -------------------------------------------------------------- helpers
    def _product_row(self, row):
        return {
            "id": row["id"], "sku": row["sku"], "title": row["title"],
            "description": row["description"], "category": row["category"],
            "brand": row["brand"], "price_cents": row["price_cents"],
            "stock": row["stock"], "rating": row["rating"],
            "image_url": row["image_url"], "active": bool(row["active"]),
        }

    # -------------------------------------------------------------- catalog
    def list_products(self, query):
        sql = "SELECT * FROM products WHERE active = 1"
        params = []
        if query.get("q"):
            sql += " AND (title LIKE ? OR description LIKE ? OR brand LIKE ?)"
            like = f"%{query['q']}%"
            params += [like, like, like]
        if query.get("category"):
            sql += " AND category = ?"
            params.append(query["category"])
        sort = query.get("sort", "featured")
        sorts = {
            "price_asc": " ORDER BY price_cents ASC",
            "price_desc": " ORDER BY price_cents DESC",
            "rating": " ORDER BY rating DESC",
            "title": " ORDER BY title ASC",
            "featured": " ORDER BY rating DESC, id ASC",
        }
        sql += sorts.get(sort, sorts["featured"])
        conn = get_conn()
        try:
            rows = conn.execute(sql, params).fetchall()
            cats = [r["category"] for r in conn.execute(
                "SELECT DISTINCT category FROM products ORDER BY category").fetchall()]
        finally:
            conn.close()
        self.send_json({"products": [self._product_row(r) for r in rows], "categories": cats})

    def product_detail(self, query):
        pid = int(urlparse(self.path).path.rsplit("/", 1)[-1] or 0)
        conn = get_conn()
        try:
            row = conn.execute("SELECT * FROM products WHERE id = ? AND active = 1", (pid,)).fetchone()
        finally:
            conn.close()
        if not row:
            return self.send_json({"error": "product not found"}, 404)
        self.send_json({"product": self._product_row(row)})

    def list_categories(self, query):
        conn = get_conn()
        try:
            rows = conn.execute(
                "SELECT category, COUNT(*) AS n FROM products WHERE active=1 GROUP BY category ORDER BY category"
            ).fetchall()
        finally:
            conn.close()
        self.send_json({"categories": [{"name": r["category"], "count": r["n"]} for r in rows]})

    # ----------------------------------------------------------------- auth
    def register(self, query):
        body = self.read_body()
        email = str(body.get("email", "")).strip().lower()
        name = str(body.get("name", "")).strip()
        password = str(body.get("password", ""))
        if not email or "@" not in email or len(password) < 4:
            return self.send_json({"error": "valid email and 4+ char password required"}, 400)
        conn = get_conn()
        try:
            exists = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if exists:
                return self.send_json({"error": "email already registered"}, 409)
            conn.execute(
                "INSERT INTO users (email, name, password_hash, role) VALUES (?, ?, ?, ?)",
                (email, name or email, hash_password(password), "customer"))
            conn.commit()
        finally:
            conn.close()
        token = create_session(email, "customer")
        self.send_json({"token": token, "email": email, "role": "customer"})

    def login(self, query):
        body = self.read_body()
        email = str(body.get("email", "")).strip().lower()
        conn = get_conn()
        try:
            row = conn.execute(
                "SELECT email, password_hash, role FROM users WHERE email = ?", (email,)).fetchone()
        finally:
            conn.close()
        if not row or not verify_password(str(body.get("password", "")), row["password_hash"]):
            return self.send_json({"error": "invalid email or password"}, 401)
        token = create_session(row["email"], row["role"])
        self.send_json({"token": token, "email": row["email"], "role": row["role"]})

    def logout(self, query):
        token = self.headers.get("X-Session-Token", "")
        _sessions.pop(token, None)
        self.send_json({"ok": True})

    def me(self, query):
        sess = session_user(self.headers.get("X-Session-Token", ""))
        if not sess:
            return self.send_json({"error": "not logged in"}, 401)
        self.send_json({"user": {"email": sess["email"], "role": sess["role"], "name": sess["email"].split("@")[0].title()}})

    # ----------------------------------------------------------------- cart
    def _cart_token(self, query):
        tok = query.get("token") or self.headers.get("X-Cart-Token") or self.headers.get("X-Session-Token")
        if not tok:
            tok = "guest_default"
        return tok

    def _ensure_cart(self, token):
        if not token:
            return None
        conn = get_conn()
        try:
            row = conn.execute("SELECT id FROM carts WHERE token = ?", (token,)).fetchone()
            if not row:
                conn.execute("INSERT INTO carts (token) VALUES (?)", (token,))
                conn.commit()
                row = conn.execute("SELECT id FROM carts WHERE token = ?", (token,)).fetchone()
            return row["id"]
        finally:
            conn.close()

    def get_cart(self, query):
        token = self._cart_token(query)
        cart_id = self._ensure_cart(token)
        conn = get_conn()
        try:
            rows = conn.execute(
                """SELECT ci.id, ci.qty, p.id AS product_id, p.title, p.price_cents,
                          p.image_url, p.stock
                   FROM cart_items ci JOIN products p ON p.id = ci.product_id
                   WHERE ci.cart_id = ? ORDER BY ci.id""", (cart_id,)).fetchall()
        finally:
            conn.close()
        items = [{"id": r["id"], "qty": r["qty"], "product_id": r["product_id"],
                  "title": r["title"], "price_cents": r["price_cents"],
                  "image_url": r["image_url"], "stock": r["stock"],
                  "line_total_cents": r["qty"] * r["price_cents"]} for r in rows]
        subtotal = sum(i["line_total_cents"] for i in items)
        self.send_json({"items": items, "subtotal_cents": subtotal, "total_cents": subtotal,
                        "count": sum(i["qty"] for i in items)})

    def add_to_cart(self, query):
        body = self.read_body()
        token = self._cart_token(query)
        cart_id = self._ensure_cart(token)
        if not cart_id:
            return self.send_json({"error": "cart token required"}, 400)
        try:
            product_id = int(body.get("product_id"))
            qty = max(1, int(body.get("qty", 1)))
        except (TypeError, ValueError):
            return self.send_json({"error": "product_id and qty required"}, 400)
        conn = get_conn()
        try:
            prod = conn.execute("SELECT id, stock FROM products WHERE id = ? AND active = 1",
                                (product_id,)).fetchone()
            if not prod:
                return self.send_json({"error": "product not found"}, 404)
            existing = conn.execute(
                "SELECT id, qty FROM cart_items WHERE cart_id = ? AND product_id = ?",
                (cart_id, product_id)).fetchone()
            new_qty = min(prod["stock"], qty + (existing["qty"] if existing else 0))
            if new_qty <= 0:
                return self.send_json({"error": "out of stock"}, 409)
            if existing:
                conn.execute("UPDATE cart_items SET qty = ? WHERE id = ?", (new_qty, existing["id"]))
            else:
                conn.execute("INSERT INTO cart_items (cart_id, product_id, qty) VALUES (?, ?, ?)",
                             (cart_id, product_id, new_qty))
            conn.commit()
        finally:
            conn.close()
        self.get_cart(query)

    def update_cart_item(self, query):
        body = self.read_body()
        token = self._cart_token(query)
        cart_id = self._ensure_cart(token)
        conn = get_conn()
        try:
            target_id = body.get("item_id") or body.get("product_id")
            row = conn.execute(
                "SELECT ci.id, p.stock FROM cart_items ci JOIN products p ON p.id = ci.product_id "
                "WHERE (ci.id = ? OR ci.product_id = ?) AND ci.cart_id = ?",
                (target_id, target_id, cart_id)).fetchone()
            if not row:
                return self.send_json({"error": "cart item not found"}, 404)
            qty = max(0, int(body.get("qty", 1)))
            if qty == 0:
                conn.execute("DELETE FROM cart_items WHERE id = ?", (row["id"],))
            else:
                conn.execute("UPDATE cart_items SET qty = ? WHERE id = ?",
                             (min(qty, row["stock"]), row["id"]))
            conn.commit()
        finally:
            conn.close()
        self.get_cart(query)

    def remove_cart_item(self, query):
        token = self._cart_token(query)
        cart_id = self._ensure_cart(token)
        item_id = int(query.get("item_id", 0))
        conn = get_conn()
        try:
            conn.execute("DELETE FROM cart_items WHERE id = ? AND cart_id = ?", (item_id, cart_id))
            conn.commit()
        finally:
            conn.close()
        self.get_cart(query)

    # ------------------------------------------------------------- checkout
    def checkout(self, query):
        body = self.read_body()
        token = self._cart_token(query)
        cart_id = self._ensure_cart(token)
        sess = session_user(self.headers.get("X-Session-Token", ""))
        name = str(body.get("name", "") or (sess and sess["email"].split("@")[0].title()) or "Valued Customer").strip()
        email = str(body.get("email", "") or (sess and sess["email"]) or "").strip().lower()
        address = str(body.get("address", "")).strip()
        if not (name and "@" in email and address):
            return self.send_json({"error": "name, email and address are required"}, 400)
        if not cart_id:
            return self.send_json({"error": "cart is empty"}, 400)
        conn = get_conn()
        try:
            items = conn.execute(
                """SELECT ci.product_id, ci.qty, p.title, p.price_cents, p.stock
                   FROM cart_items ci JOIN products p ON p.id = ci.product_id
                   WHERE ci.cart_id = ?""", (cart_id,)).fetchall()
            if not items:
                return self.send_json({"error": "cart is empty"}, 400)
            for it in items:
                if it["qty"] > it["stock"]:
                    return self.send_json(
                        {"error": f"only {it['stock']} left of {it['title']}"}, 409)
            total = sum(it["qty"] * it["price_cents"] for it in items)
            order_number = "PG-" + datetime.utcnow().strftime("%Y%m%d") + "-" + secrets.token_hex(3).upper()
            cur = conn.execute(
                "INSERT INTO orders (order_number, customer_name, email, address, total_cents) "
                "VALUES (?, ?, ?, ?, ?)", (order_number, name, email, address, total))
            order_id = cur.lastrowid
            conn.executemany(
                "INSERT INTO order_items (order_id, product_id, title_snapshot, price_cents, qty) "
                "VALUES (?, ?, ?, ?, ?)",
                [(order_id, it["product_id"], it["title"], it["price_cents"], it["qty"]) for it in items])
            for it in items:
                conn.execute("UPDATE products SET stock = stock - ? WHERE id = ?",
                             (it["qty"], it["product_id"]))
            conn.execute("DELETE FROM cart_items WHERE cart_id = ?", (cart_id,))
            conn.commit()
        finally:
            conn.close()
        self.send_json({"ok": True, "order_number": order_number, "order_id": order_id, "total_cents": total})

    # --------------------------------------------------------------- orders
    def list_orders(self, query):
        sess = session_user(self.headers.get("X-Session-Token", ""))
        if not sess or sess["role"] != "admin":
            return self.send_json({"error": "admin session required"}, 401)
        conn = get_conn()
        try:
            orders = conn.execute(
                "SELECT * FROM orders ORDER BY id DESC LIMIT 200").fetchall()
            items = conn.execute(
                """SELECT oi.order_id, oi.title_snapshot, oi.qty, oi.price_cents
                   FROM order_items oi""").fetchall()
        finally:
            conn.close()
        by_order = {}
        for it in items:
            by_order.setdefault(it["order_id"], []).append(
                {"title": it["title_snapshot"], "qty": it["qty"], "price_cents": it["price_cents"]})
        result = [{**dict(o), "items": by_order.get(o["id"], [])} for o in orders]
        self.send_json({"orders": result})

    def update_order_status(self, query):
        sess = require_admin(self)
        if not sess:
            return
        body = self.read_body()
        oid = int(body.get("order_id", 0))
        status = str(body.get("status", ""))
        allowed = {"placed", "paid", "shipped", "delivered", "cancelled"}
        if status not in allowed:
            return self.send_json({"error": f"status must be one of {sorted(allowed)}"}, 400)
        conn = get_conn()
        try:
            cur = conn.execute("UPDATE orders SET status = ? WHERE id = ?", (status, oid))
            conn.commit()
            if cur.rowcount == 0:
                return self.send_json({"error": "order not found"}, 404)
        finally:
            conn.close()
        self.send_json({"ok": True})

    # ---------------------------------------------------------------- admin
    def create_product(self, query):
        sess = require_admin(self)
        if not sess:
            return
        body = self.read_body()
        title = str(body.get("title", "")).strip()
        try:
            price = int(body.get("price_cents", 0))
            stock = int(body.get("stock", 0))
        except (TypeError, ValueError):
            return self.send_json({"error": "price_cents and stock must be integers"}, 400)
        if not title or price <= 0:
            return self.send_json({"error": "title and positive price_cents required"}, 400)
        conn = get_conn()
        try:
            sku = str(body.get("sku") or ("NEW-" + secrets.token_hex(3).upper()))
            cur = conn.execute(
                """INSERT INTO products (sku, title, description, category, brand,
                   price_cents, stock, rating, image_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (sku, title, str(body.get("description", "")),
                 str(body.get("category", "General")), str(body.get("brand", "")),
                 price, stock, float(body.get("rating", 4.0)),
                 str(body.get("image_url") or f"https://picsum.photos/seed/{sku}/480/480")))
            conn.commit()
            pid = cur.lastrowid
            row = conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
        finally:
            conn.close()
        self.send_json({"product": self._product_row(row)}, 201)

    def update_product(self, query):
        sess = require_admin(self)
        if not sess:
            return
        body = self.read_body()
        pid = int(body.get("id") or query.get("id") or 0)
        fields = {}
        for key in ("title", "description", "category", "brand", "image_url"):
            if key in body:
                fields[key] = str(body[key])
        for key in ("price_cents", "stock"):
            if key in body:
                try:
                    fields[key] = max(0, int(body[key]))
                except (TypeError, ValueError):
                    return self.send_json({"error": f"{key} must be an integer"}, 400)
        if "active" in body:
            fields["active"] = 1 if body["active"] else 0
        if not fields:
            return self.send_json({"error": "no updatable fields provided"}, 400)
        conn = get_conn()
        try:
            sets = ", ".join(f"{k} = ?" for k in fields)
            cur = conn.execute(f"UPDATE products SET {sets} WHERE id = ?",
                               (*fields.values(), pid))
            conn.commit()
            if cur.rowcount == 0:
                return self.send_json({"error": "product not found"}, 404)
            row = conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
        finally:
            conn.close()
        self.send_json({"product": self._product_row(row)})

    def delete_product(self, query):
        sess = require_admin(self)
        if not sess:
            return
        pid = int(query.get("id", 0))
        conn = get_conn()
        try:
            conn.execute("UPDATE products SET active = 0 WHERE id = ?", (pid,))
            conn.commit()
        finally:
            conn.close()
        self.send_json({"ok": True})

    def admin_stats(self, query):
        sess = require_admin(self)
        if not sess:
            return
        conn = get_conn()
        try:
            stats = {
                "products": conn.execute("SELECT COUNT(*) FROM products").fetchone()[0],
                "orders": conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
                "revenue_cents": conn.execute(
                    "SELECT COALESCE(SUM(total_cents), 0) FROM orders").fetchone()[0],
                "low_stock": conn.execute(
                    "SELECT COUNT(*) FROM products WHERE stock <= 10 AND active = 1").fetchone()[0],
            }
            recent = conn.execute(
                "SELECT order_number, customer_name, total_cents, status, created_at "
                "FROM orders ORDER BY id DESC LIMIT 8").fetchall()
        finally:
            conn.close()
        stats["recent_orders"] = [dict(r) for r in recent]
        self.send_json(stats)


def main():
    init_db()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"PulseGear API + storefront on http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
