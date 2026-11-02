#!/usr/bin/env python3
"""End-to-end verification of the PulseCart API against a running server.

Exercises the full customer journey (browse -> search -> cart -> checkout)
plus admin authorization and inventory mutation. Run with the server up:

    python3 app.py &          # or: PORT=9000 python3 app.py
    python3 verify.py
"""
import json
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8000"
ADMIN_KEY = "admin-secret"

PASS = 0
FAIL = 0


def call(method, path, body=None, headers=None, cookie=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if cookie:
        req.add_header("Cookie", cookie)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else None), r.headers.get("Set-Cookie", "")
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, (json.loads(raw) if raw else None), ""
        except json.JSONDecodeError:
            return e.code, raw, ""


def check(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"PASS  {label}  {detail}")
    else:
        FAIL += 1
        print(f"FAIL  {label}  {detail}")


# ---- health -------------------------------------------------------------
st, b, _ = call("GET", "/api/health")
check("health", st == 200 and b.get("status") == "ok", f"status={st}")

# ---- catalog ------------------------------------------------------------
st, b, _ = call("GET", "/api/categories")
cats = b["categories"] if st == 200 else []
check("categories", st == 200 and len(cats) >= 4, f"n={len(cats)}")

st, b, _ = call("GET", "/api/products?limit=100")
products = b["products"] if st == 200 else []
check("products list", st == 200 and len(products) >= 10, f"n={len(products)}")

if products:
    p = products[0]
    need = {"id", "title", "price", "price_cents", "stock", "category", "rating"}
    check("product fields", need.issubset(p.keys()), f"missing={need - set(p.keys())}")

# ---- search actually filters -------------------------------------------
st, b, _ = call("GET", "/api/products?search=zzzznomatch")
check("search negative", st == 200 and b["count"] == 0, f"count={b.get('count')}")

st, b, _ = call("GET", "/api/products?search=head")
hit = b["count"] if st == 200 else -1
check("search positive filters", st == 200 and hit < len(products), f"matches={hit}/{len(products)}")

# ---- category filter ----------------------------------------------------
slug = cats[0]["slug"]
st, b, _ = call("GET", f"/api/products?category={slug}")
check("category filter", st == 200 and all(x["category_id"] == cats[0]["id"] for x in b["products"]),
      f"n={b.get('count')}")

# ---- product detail -----------------------------------------------------
pid = products[0]["id"]
st, b, _ = call("GET", f"/api/products/{pid}")
check("product detail", st == 200 and b["product"]["id"] == pid)

st, b, _ = call("GET", "/api/products/99999")
check("product 404", st == 404, f"status={st}")

# ---- cart ---------------------------------------------------------------
st, b, cookie = call("POST", "/api/cart/items", {"product_id": pid, "quantity": 2})
token = b.get("cart_token") if isinstance(b, dict) else None
check("cart add", st == 200 and b.get("count") == 2, f"count={b.get('count')}")

st, b, _ = call("GET", "/api/cart", cookie=cookie)
check("cart get via cookie", st == 200 and b.get("count") == 2, f"count={b.get('count')}")

item_id = b["items"][0]["item_id"] if b.get("items") else None
st, b, _ = call("PUT", f"/api/cart/items/{item_id}", {"quantity": 3}, cookie=cookie)
check("cart update qty", st == 200 and b.get("count") == 3, f"count={b.get('count')}")

st, b, _ = call("DELETE", f"/api/cart/items/{item_id}", cookie=cookie)
check("cart remove item", st == 200 and b.get("count") == 0, f"count={b.get('count')}")

# ---- checkout validation ------------------------------------------------
st, b, cookie = call("POST", "/api/cart/items", {"product_id": pid, "quantity": 1}, cookie=cookie)
st, b, _ = call("POST", "/api/checkout", {"name": "A", "email": "bad", "address": "x"}, cookie=cookie)
check("checkout rejects bad email", st == 400, f"status={st}")

st, b, _ = call("POST", "/api/checkout", {"name": "A", "email": "a@b.com", "address": "x"}, cookie=cookie)
order_ref = b.get("order_ref") if isinstance(b, dict) else None
check("checkout creates order", st == 201 and order_ref, f"ref={order_ref}")

# stock decremented
st, b, _ = call("GET", f"/api/products/{pid}")
check("stock decremented", st == 200 and b["product"]["stock"] == products[0]["stock"] - 1,
      f"stock {products[0]['stock']} -> {b['product']['stock']}")

# ---- admin auth ---------------------------------------------------------
st, _, _ = call("GET", "/api/orders")
check("orders blocked without key", st == 401, f"status={st}")

st, b, _ = call("GET", "/api/orders", headers={"X-Admin-Key": ADMIN_KEY})
check("orders with key", st == 200 and len(b["orders"]) >= 1, f"n={len(b.get('orders', []))}")

st, b, _ = call("GET", "/api/admin/stats", headers={"X-Admin-Key": ADMIN_KEY})
check("admin stats", st == 200 and "products" in b, f"keys={list(b.keys()) if isinstance(b, dict) else b}")

# ---- admin inventory mutation ------------------------------------------
st, b, _ = call("POST", "/api/products", {"title": "Test Widget", "price_cents": 1234, "stock": 5},
                headers={"X-Admin-Key": ADMIN_KEY})
new_id = b["product"]["id"] if st == 201 else None
check("admin create product", st == 201 and new_id, f"id={new_id}")

if new_id:
    st, b, _ = call("PUT", f"/api/products/{new_id}", {"stock": 42}, headers={"X-Admin-Key": ADMIN_KEY})
    check("admin update stock", st == 200 and b["product"]["stock"] == 42, f"stock={b.get('product', {}).get('stock')}")

    st, b, _ = call("DELETE", f"/api/products/{new_id}", headers={"X-Admin-Key": ADMIN_KEY})
    check("admin deactivate product", st in (200, 204), f"status={st}")

    st, _, _ = call("GET", f"/api/products/{new_id}")
    check("deactivated product hidden", st == 404, f"status={st}")

# ---- frontend served ----------------------------------------------------
req = urllib.request.Request(BASE + "/")
try:
    with urllib.request.urlopen(req) as r:
        html = r.read().decode()
    check("frontend served", r.status == 200 and "PulseCart" in html, f"len={len(html)}")
except Exception as e:  # noqa: BLE001
    check("frontend served", False, str(e))

print(f"\n{PASS} passed, {FAIL} failed")
raise SystemExit(1 if FAIL else 0)
