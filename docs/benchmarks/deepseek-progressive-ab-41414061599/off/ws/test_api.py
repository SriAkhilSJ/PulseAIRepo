import json, urllib.request, urllib.error, http.cookiejar

BASE = "http://127.0.0.1:8000"
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def call(path, method="GET", body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with op.open(req) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        return e.code, json.loads(raw or "{}")


ok = 0
fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print("  PASS " + name)
    else:
        fail += 1
        print("  FAIL " + name + " " + str(extra))


print("== products ==")
s, d = call("/api/products")
check("list products", s == 200 and d["count"] > 0, d)
first = d["products"][0]
s, d = call("/api/products?q=skillet")
check("search q=skillet", s == 200 and any("skillet" in p["title"].lower() for p in d["products"]), d)
s, d = call("/api/products?sort=price_asc")
prices = [p["price"] for p in d["products"]]
check("sort price_asc", prices == sorted(prices))
s, d = call("/api/categories")
check("categories", s == 200 and len(d["categories"]) > 0, d)
s, d = call("/api/products?in_stock=1")
check("in_stock filter", all(p["stock"] > 0 for p in d["products"]))

print("== cart ==")
pid = first["id"]
s, d = call("/api/cart")
check("empty cart", s == 200 and d["count"] == 0)
s, d = call("/api/cart", "POST", {"product_id": pid, "qty": 2})
check("add to cart", s == 200 and d["count"] == 2, d)
check("subtotal computed", d["subtotal"] == round(first["price"] * 2, 2), d)
item_id = d["items"][0]["item_id"]
s, d = call("/api/cart/%d" % item_id, "PATCH", {"qty": 3})
check("update qty", s == 200 and d["count"] == 3, d)
s, d = call("/api/cart", "POST", {"product_id": pid, "qty": 200})
check("qty>99 rejected", s == 400, d)
s, d = call("/api/cart", "POST", {"product_id": 999999, "qty": 1})
check("bad product 404", s == 404, d)
s, d = call("/api/cart", "POST", {"product_id": "x", "qty": 1})
check("bad type 400", s == 400, d)

print("== checkout ==")
s, d = call("/api/orders", "POST", {"customer_name": "Ada Lovelace", "email": "ada@example.com", "address": "1 Analytical Way"})
check("place order", s == 201 and d["order"]["reference"].startswith("NOVA-"), d)
ref = d["order"]["reference"]
s, d = call("/api/cart")
check("cart cleared after order", d["count"] == 0, d)
s, d = call("/api/orders")
check("order history", s == 200 and any(o["reference"] == ref for o in d["orders"]), d)

print("== admin auth ==")
s, d = call("/api/admin/stats")
check("admin blocked w/o token", s == 403, d)
H = {"X-Admin-Token": "nova-admin"}
s, d = call("/api/admin/stats", headers=H)
check("admin stats", s == 200 and d["products"] > 0 and d["orders"] >= 1, d)
s, d = call("/api/admin/products", headers=H)
check("admin product list", s == 200 and len(d["products"]) > 0)
s, d = call("/api/admin/products", "POST", {"title": "Test Widget", "category": "Gadgets", "price": 19.99, "stock": 5}, H)
check("create product", s == 201, d)
new_pid = d["product"]["id"]
s, d = call("/api/admin/products/%d" % new_pid, "PUT", {"title": "Test Widget v2", "category": "Gadgets", "price": 24.99, "stock": 8}, H)
check("update product", s == 200 and d["product"]["title"] == "Test Widget v2", d)
s, d = call("/api/admin/products", "POST", {"title": "x", "category": "Gadgets", "price": 1, "stock": 1}, H)
check("validation rejects short title", s == 400, d)
s, d = call("/api/admin/products/%d" % new_pid, "DELETE", headers=H)
check("delete product", s == 200 and d["deleted"] == new_pid, d)
s, d = call("/api/admin/orders", headers=H)
check("admin orders w/ item_count", s == 200 and any(o["reference"] == ref and "item_count" in o for o in d["orders"]), d)

print("")
print("RESULT: %d passed, %d failed" % (ok, fail))
