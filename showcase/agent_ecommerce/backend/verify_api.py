"""End-to-end API verification for PulseGear (uses requests, no shell)."""
import json
import urllib.request

BASE = "http://localhost:8000/api"


def call(method, path, token=None, body=None, expect=200):
    url = BASE + path
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Session-Token"] = token
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            code, payload = r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        code, payload = e.code, json.loads(e.read().decode())
    assert code == expect, f"{method} {path} -> {code} (expected {expect}): {payload}"
    return payload


# --- catalog -------------------------------------------------------------
prods = call("GET", "/products")
assert len(prods["products"]) >= 20, "expected >=20 seeded products"
print("GET /products:", len(prods["products"]), "products")

hit = call("GET", "/products?q=blanket")
assert any("b" in p["title"].lower() for p in hit["products"]), "search should match"
print("GET /products?q=…: search works")

cat = call("GET", "/products?category=Electronics")
assert all(p["category"] == "Electronics" for p in cat["products"])
print("GET /products?category=Electronics:", len(cat["products"]), "items")

# --- auth ----------------------------------------------------------------
admin = call("POST", "/auth/login", body={"email": "admin@pulsegear.com", "password": "admin123"})
adm_tok = admin["token"]
assert admin["role"] == "admin"
print("POST /auth/login: admin OK, role =", admin["role"])

user = call("POST", "/auth/login", body={"email": "demo@pulsegear.com", "password": "demo123"})
usr_tok = user["token"]
print("POST /auth/login: demo OK, role =", user["role"])

call("POST", "/auth/login", body={"email": "admin@pulsegear.com", "password": "wrong"}, expect=401)
print("POST /auth/login: bad password -> 401 OK")

# --- admin surface -------------------------------------------------------
stats = call("GET", "/admin/stats", token=adm_tok)
assert set(stats) >= {"revenue_cents", "orders", "products", "low_stock"}
print("GET /admin/stats:", stats)

orders = call("GET", "/admin/orders", token=adm_tok)
print("GET /admin/orders:", len(orders["orders"]), "orders")

call("GET", "/admin/stats", token=usr_tok, expect=401)
print("GET /admin/stats as customer -> 403 OK")

# --- cart + checkout -----------------------------------------------------
cart = call("POST", "/cart/add", token=usr_tok, body={"product_id": 6, "qty": 2})
assert cart["total_cents"] == 2 * 7900, f"cart total wrong: {cart['total_cents']}"
print("POST /cart/add: total =", cart["total_cents"])

cart = call("POST", "/cart/add", token=usr_tok, body={"product_id": 13, "qty": 1})
print("POST /cart/add: second item, items =", len(cart["items"]))

cart = call("POST", "/cart/set", token=usr_tok, body={"product_id": 6, "qty": 1})
assert cart["total_cents"] == 7900 + cart["items"][1]["line_total_cents"]
print("POST /cart/set: qty update works")

order = call("POST", "/orders", token=usr_tok, body={
    "address": "1 Main St, Springfield 90210", "card_last4": "4242"})
assert order["total_cents"] > 0 and order["order_id"] >= 1
print("POST /orders: order", order["order_id"], "total", order["total_cents"])

cart_after = call("GET", "/cart", token=usr_tok)
assert cart_after["items"] == []
print("GET /cart after order: cart cleared")

stats2 = call("GET", "/admin/stats", token=adm_tok)
assert stats2["orders"] == stats["orders"] + 1, "order should appear in admin stats"
print("GET /admin/stats: order count incremented ->", stats2["orders"])

# --- admin CRUD ----------------------------------------------------------
newp = call("POST", "/admin/products", token=adm_tok, expect=201, body={
    "title": "Test Widget", "brand": "TestCo", "category": "Test",
    "price_cents": 1999, "stock": 5, "image_url": "https://picsum.photos/seed/tw/480/480",
    "description": "A test product"})
assert newp["product"]["title"] == "Test Widget"
pid = newp["product"]["id"]
print("POST /admin/products: created id", pid)

upd = call("PUT", "/admin/products/" + str(pid), token=adm_tok, body={
    "title": "Test Widget v2", "brand": "TestCo", "category": "Test",
    "price_cents": 2499, "stock": 3, "image_url": "https://picsum.photos/seed/tw/480/480",
    "description": "Updated"})
assert upd["product"]["price_cents"] == 2499
print("PUT /admin/products:", upd["product"]["title"], "price", upd["product"]["price_cents"])

call("DELETE", "/admin/products/" + str(pid), token=adm_tok)
prods2 = call("GET", "/products")
assert not any(p["id"] == pid for p in prods2["products"])
print("DELETE /admin/products: removed cleanly")

# --- checkout auth gate --------------------------------------------------
call("POST", "/orders", body={"address": "x" * 20}, expect=400)
print("POST /orders without token -> 401 OK")

print("\nALL API CHECKS PASSED")
