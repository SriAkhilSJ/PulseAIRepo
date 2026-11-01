"""ShopFlow — a full-stack ecommerce server (Amazon-style).

Exposes a JSON REST API and serves the reactive frontend from ./frontend.
Run:  python server.py   ->  http://127.0.0.1:5000
"""
import os
import uuid
from functools import wraps

from flask import Flask, jsonify, request, send_from_directory, session

import db

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

# Demo admin key — in a real deployment this comes from an env var / auth system.
ADMIN_KEY = os.environ.get("SHOPFLOW_ADMIN_KEY", "admin-secret")

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
app.secret_key = os.environ.get("SHOPFLOW_SECRET", "dev-secret-change-me")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def product_row_to_dict(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "description": row["description"],
        "price": row["price"],
        "compare_at": row["compare_at"],
        "category_id": row["category_id"],
        "category": row["category_name"] if "category_name" in row.keys() else None,
        "category_slug": row["category_slug"] if "category_slug" in row.keys() else None,
        "image": row["image"],
        "stock": row["stock"],
        "rating": row["rating"],
        "reviews_count": row["reviews_count"],
        "featured": bool(row["featured"]),
    }


def get_session_id():
    if "sid" not in session:
        session["sid"] = uuid.uuid4().hex
    return session["sid"]


def require_admin(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if request.headers.get("X-Admin-Key") != ADMIN_KEY:
            return jsonify({"error": "admin key required"}), 401
        return fn(*args, **kwargs)
    return wrapper


# --------------------------------------------------------------------------- #
# static frontend
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


# --------------------------------------------------------------------------- #
# catalogue API
# --------------------------------------------------------------------------- #
@app.get("/api/categories")
def list_categories():
    conn = db.get_conn()
    rows = conn.execute("SELECT slug, name FROM categories ORDER BY name").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.get("/api/products")
def list_products():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    sort = request.args.get("sort", "featured")
    featured = request.args.get("featured")

    sql = """SELECT p.*, c.name AS category_name, c.slug AS category_slug
             FROM products p LEFT JOIN categories c ON c.id = p.category_id WHERE 1=1"""
    params = []
    if q:
        sql += " AND (p.title LIKE ? OR p.description LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    if category:
        sql += " AND c.slug = ?"
        params.append(category)
    if featured == "true":
        sql += " AND p.featured = 1"

    order = {
        "price_asc": "p.price ASC",
        "price_desc": "p.price DESC",
        "rating": "p.rating DESC",
        "newest": "p.id DESC",
        "featured": "p.featured DESC, p.rating DESC",
    }.get(sort, "p.featured DESC, p.rating DESC")
    sql += f" ORDER BY {order}"

    conn = db.get_conn()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return jsonify([product_row_to_dict(r) for r in rows])


@app.get("/api/products/<int:pid>")
def get_product(pid):
    conn = db.get_conn()
    row = conn.execute(
        """SELECT p.*, c.name AS category_name, c.slug AS category_slug
           FROM products p LEFT JOIN categories c ON c.id = p.category_id
           WHERE p.id = ?""",
        (pid,),
    ).fetchone()
    conn.close()
    if row is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(product_row_to_dict(row))


# --------------------------------------------------------------------------- #
# cart API
# --------------------------------------------------------------------------- #
def cart_payload(conn, sid):
    rows = conn.execute(
        """SELECT ci.id AS item_id, ci.quantity, p.*
           FROM cart_items ci JOIN products p ON p.id = ci.product_id
           WHERE ci.session_id = ? ORDER BY ci.id""",
        (sid,),
    ).fetchall()
    items = []
    subtotal = 0.0
    for r in rows:
        line = r["price"] * r["quantity"]
        subtotal += line
        items.append({
            "item_id": r["item_id"],
            "product_id": r["id"],
            "title": r["title"],
            "price": r["price"],
            "image": r["image"],
            "quantity": r["quantity"],
            "line_total": round(line, 2),
            "stock": r["stock"],
        })
    return {"items": items, "subtotal": round(subtotal, 2),
            "count": sum(i["quantity"] for i in items)}


@app.get("/api/cart")
def get_cart():
    sid = get_session_id()
    conn = db.get_conn()
    payload = cart_payload(conn, sid)
    conn.close()
    return jsonify(payload)


@app.post("/api/cart")
def add_to_cart():
    sid = get_session_id()
    data = request.get_json(silent=True) or {}
    pid = data.get("product_id")
    qty = int(data.get("quantity", 1) or 1)
    if not pid or qty < 1:
        return jsonify({"error": "product_id and positive quantity required"}), 400

    conn = db.get_conn()
    product = conn.execute("SELECT stock FROM products WHERE id = ?", (pid,)).fetchone()
    if product is None:
        conn.close()
        return jsonify({"error": "product not found"}), 404
    if qty > product["stock"]:
        conn.close()
        return jsonify({"error": "not enough stock"}), 409

    existing = conn.execute(
        "SELECT id, quantity FROM cart_items WHERE session_id = ? AND product_id = ?",
        (sid, pid),
    ).fetchone()
    if existing:
        new_qty = min(existing["quantity"] + qty, product["stock"])
        conn.execute("UPDATE cart_items SET quantity = ? WHERE id = ?", (new_qty, existing["id"]))
    else:
        conn.execute(
            "INSERT INTO cart_items (session_id, product_id, quantity) VALUES (?,?,?)",
            (sid, pid, qty),
        )
    conn.commit()
    payload = cart_payload(conn, sid)
    conn.close()
    return jsonify(payload)


@app.patch("/api/cart/<int:item_id>")
def update_cart_item(item_id):
    sid = get_session_id()
    data = request.get_json(silent=True) or {}
    qty = int(data.get("quantity", 1))
    conn = db.get_conn()
    row = conn.execute(
        "SELECT ci.id, p.stock FROM cart_items ci JOIN products p ON p.id = ci.product_id "
        "WHERE ci.id = ? AND ci.session_id = ?",
        (item_id, sid),
    ).fetchone()
    if row is None:
        conn.close()
        return jsonify({"error": "cart item not found"}), 404
    if qty < 1:
        conn.execute("DELETE FROM cart_items WHERE id = ?", (item_id,))
    else:
        if qty > row["stock"]:
            conn.close()
            return jsonify({"error": "not enough stock"}), 409
        conn.execute("UPDATE cart_items SET quantity = ? WHERE id = ?", (qty, item_id))
    conn.commit()
    payload = cart_payload(conn, sid)
    conn.close()
    return jsonify(payload)


@app.delete("/api/cart/<int:item_id>")
def remove_cart_item(item_id):
    sid = get_session_id()
    conn = db.get_conn()
    conn.execute("DELETE FROM cart_items WHERE id = ? AND session_id = ?", (item_id, sid))
    conn.commit()
    payload = cart_payload(conn, sid)
    conn.close()
    return jsonify(payload)


# --------------------------------------------------------------------------- #
# checkout / orders
# --------------------------------------------------------------------------- #
@app.post("/api/checkout")
def checkout():
    sid = get_session_id()
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    address = (data.get("address") or "").strip()
    if not name or not email or not address:
        return jsonify({"error": "name, email and address are required"}), 400

    conn = db.get_conn()
    cart = cart_payload(conn, sid)
    if not cart["items"]:
        conn.close()
        return jsonify({"error": "cart is empty"}), 400

    # verify stock and compute total
    for item in cart["items"]:
        if item["quantity"] > item["stock"]:
            conn.close()
            return jsonify({"error": f"insufficient stock for {item['title']}"}), 409

    cur = conn.execute(
        "INSERT INTO orders (session_id, customer, email, address, total, status) VALUES (?,?,?,?,?,?)",
        (sid, name, email, address, cart["subtotal"], "placed"),
    )
    order_id = cur.lastrowid
    for item in cart["items"]:
        conn.execute(
            "INSERT INTO order_items (order_id, product_id, title, price, quantity) VALUES (?,?,?,?,?)",
            (order_id, item["product_id"], item["title"], item["price"], item["quantity"]),
        )
        conn.execute("UPDATE products SET stock = stock - ? WHERE id = ?",
                     (item["quantity"], item["product_id"]))
    conn.execute("DELETE FROM cart_items WHERE session_id = ?", (sid,))
    conn.commit()
    conn.close()
    return jsonify({"order_id": order_id, "total": cart["subtotal"], "status": "placed"})


@app.get("/api/orders")
def list_orders():
    sid = get_session_id()
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT * FROM orders WHERE session_id = ? ORDER BY id DESC", (sid,)
    ).fetchall()
    orders = []
    for o in rows:
        items = conn.execute("SELECT * FROM order_items WHERE order_id = ?", (o["id"],)).fetchall()
        orders.append({**dict(o), "items": [dict(i) for i in items]})
    conn.close()
    return jsonify(orders)


# --------------------------------------------------------------------------- #
# admin API
# --------------------------------------------------------------------------- #
@app.get("/api/admin/stats")
@require_admin
def admin_stats():
    conn = db.get_conn()
    revenue = conn.execute("SELECT COALESCE(SUM(total),0) AS r FROM orders").fetchone()["r"]
    orders = conn.execute("SELECT COUNT(*) AS c FROM orders").fetchone()["c"]
    products = conn.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"]
    low = conn.execute("SELECT COUNT(*) AS c FROM products WHERE stock < 20").fetchone()["c"]
    conn.close()
    return jsonify({"revenue": round(revenue, 2), "orders": orders,
                    "products": products, "low_stock": low})


@app.get("/api/admin/products")
@require_admin
def admin_products():
    conn = db.get_conn()
    rows = conn.execute(
        """SELECT p.*, c.name AS category_name, c.slug AS category_slug
           FROM products p LEFT JOIN categories c ON c.id = p.category_id
           ORDER BY p.id""",
    ).fetchall()
    conn.close()
    return jsonify([product_row_to_dict(r) for r in rows])


@app.post("/api/admin/products")
@require_admin
def admin_create_product():
    d = request.get_json(silent=True) or {}
    if not d.get("title") or d.get("price") is None:
        return jsonify({"error": "title and price required"}), 400
    conn = db.get_conn()
    cur = conn.execute(
        """INSERT INTO products (title, description, price, compare_at, category_id, image, stock, rating, reviews_count, featured)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (d["title"], d.get("description", ""), float(d["price"]), d.get("compare_at"),
         d.get("category_id"), d.get("image", ""), int(d.get("stock", 0)),
         float(d.get("rating", 0)), int(d.get("reviews_count", 0)),
         1 if d.get("featured") else 0),
    )
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return jsonify({"id": pid}), 201


@app.patch("/api/admin/products/<int:pid>")
@require_admin
def admin_update_product(pid):
    d = request.get_json(silent=True) or {}
    fields = ["title", "description", "price", "compare_at", "category_id",
              "image", "stock", "rating", "reviews_count", "featured"]
    sets, params = [], []
    for f in fields:
        if f in d:
            val = 1 if f == "featured" and d[f] else (0 if f == "featured" else d[f])
            sets.append(f"{f} = ?")
            params.append(val)
    if not sets:
        return jsonify({"error": "no fields to update"}), 400
    params.append(pid)
    conn = db.get_conn()
    conn.execute(f"UPDATE products SET {', '.join(sets)} WHERE id = ?", params)
    conn.commit()
    conn.close()
    return jsonify({"updated": pid})


@app.delete("/api/admin/products/<int:pid>")
@require_admin
def admin_delete_product(pid):
    conn = db.get_conn()
    conn.execute("DELETE FROM products WHERE id = ?", (pid,))
    conn.commit()
    conn.close()
    return jsonify({"deleted": pid})


@app.get("/api/admin/orders")
@require_admin
def admin_orders():
    conn = db.get_conn()
    rows = conn.execute("SELECT * FROM orders ORDER BY id DESC").fetchall()
    orders = []
    for o in rows:
        items = conn.execute("SELECT * FROM order_items WHERE order_id = ?", (o["id"],)).fetchall()
        orders.append({**dict(o), "items": [dict(i) for i in items]})
    conn.close()
    return jsonify(orders)


if __name__ == "__main__":
    db.init_db()
    app.run(host="127.0.0.1", port=5000, debug=True)
