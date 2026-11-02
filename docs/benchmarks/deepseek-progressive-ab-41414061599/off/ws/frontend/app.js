/* Nova Market — storefront + admin hub (vanilla JS, no build step). */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const money = (n) =>
    "$" + Number(n || 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const state = {
    products: [],
    categories: [],
    category: "",
    q: "",
    inStock: false,
    sort: "featured",
    cart: { items: [], count: 0, subtotal: 0, shipping: 0, total: 0 },
    token: localStorage.getItem("nova_admin_token") || "",
    editing: null,
  };

  async function api(path, opts) {
    const res = await fetch(path, Object.assign({ headers: {} }, opts));
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "Request failed (" + res.status + ")");
    return data;
  }

  function toast(msg) {
    const el = $("toast");
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => (el.hidden = true), 2200);
  }

  function stars(rating) {
    const full = Math.round(rating);
    return "★★★★★".slice(0, full) + "☆☆☆☆☆".slice(0, 5 - full);
  }

  /* ------------------------------------------------------------------ */
  /* Storefront                                                          */
  /* ------------------------------------------------------------------ */

  async function loadCategories() {
    try {
      const data = await api("/api/categories");
      state.categories = data.categories || [];
      renderChips();
    } catch (e) { /* non-fatal */ }
  }

  function renderChips() {
    const box = $("categoryChips");
    const all = ["", ...state.categories];
    box.innerHTML = all
      .map((c) => {
        const label = c === "" ? "All" : c;
        const on = state.category === c ? " on" : "";
        return `<button class="chip${on}" data-cat="${c}">${label}</button>`;
      })
      .join("");
    box.querySelectorAll(".chip").forEach((b) =>
      b.addEventListener("click", () => {
        state.category = b.dataset.cat;
        renderChips();
        loadProducts();
      })
    );
  }

  async function loadProducts() {
    const p = new URLSearchParams();
    if (state.q) p.set("q", state.q);
    if (state.category) p.set("category", state.category);
    if (state.inStock) p.set("in_stock", "1");
    p.set("sort", state.sort);
    try {
      const data = await api("/api/products?" + p.toString());
      state.products = data.products || [];
      renderCatalog();
    } catch (e) {
      toast(e.message);
    }
  }

  function renderCatalog() {
    const grid = $("catalog");
    $("emptyState").hidden = state.products.length > 0;
    grid.innerHTML = state.products
      .map(
        (p) => `
      <article class="product" data-id="${p.id}">
        <div class="thumb">
          ${p.discount > 0 ? `<span class="deal">-${p.discount}%</span>` : ""}
          <img src="${p.image}" alt="${p.title}" loading="lazy" />
        </div>
        <h3 class="p-title">${p.title}</h3>
        <p class="brand">${p.brand}</p>
        <p class="rating">${stars(p.rating)} <span>${p.rating} (${p.reviews})</span></p>
        <p class="price">
          <span class="now">${money(p.price)}</span>
          ${p.list_price ? `<span class="was">${money(p.list_price)}</span>` : ""}
        </p>
        <p class="stock ${p.in_stock ? "ok" : "out"}">${p.in_stock ? "In stock" : "Out of stock"}</p>
        <button class="btn primary block" data-add="${p.id}" ${p.in_stock ? "" : "disabled"}>
          ${p.in_stock ? "Add to cart" : "Unavailable"}
        </button>
      </article>`
      )
      .join("");

    grid.querySelectorAll(".product").forEach((card) => {
      card.addEventListener("click", (e) => {
        if (e.target.closest("[data-add]")) return;
        openProduct(Number(card.dataset.id));
      });
    });
    grid.querySelectorAll("[data-add]").forEach((b) =>
      b.addEventListener("click", (e) => {
        e.stopPropagation();
        addToCart(Number(b.dataset.add));
      })
    );
  }

  function findProduct(id) {
    return state.products.find((p) => p.id === id);
  }

  function openProduct(id) {
    const p = findProduct(id);
    if (!p) return;
    $("productModal").innerHTML = `
      <div class="pm-grid">
        <img src="${p.image}" alt="${p.title}" />
        <div>
          <h2>${p.title}</h2>
          <p class="brand">by ${p.brand} · ${p.category}</p>
          <p class="rating">${stars(p.rating)} <span>${p.rating} (${p.reviews} reviews)</span></p>
          <p class="price"><span class="now">${money(p.price)}</span>
            ${p.list_price ? `<span class="was">${money(p.list_price)}</span>` : ""}</p>
          <p>${p.description}</p>
          <p class="stock ${p.in_stock ? "ok" : "out"}">${p.in_stock ? "In stock" : "Out of stock"}</p>
          <button class="btn primary block" onclick="Nova.addToCart(${p.id}, true)" ${p.in_stock ? "" : "disabled"}>
            ${p.in_stock ? "Add to cart" : "Unavailable"}
          </button>
        </div>
      </div>`;
    $("productOverlay").hidden = false;
  }

  function closeProduct(e) {
    if (e && e.target !== $("productOverlay")) return;
    $("productOverlay").hidden = true;
  }

  /* ------------------------------------------------------------------ */
  /* Cart                                                               */
  /* ------------------------------------------------------------------ */

  async function addToCart(productId, closeAfter) {
    try {
      state.cart = await api("/api/cart", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ product_id: productId, qty: 1 }),
      });
      renderCart();
      toast("Added to cart");
      if (closeAfter) closeProduct();
    } catch (e) {
      toast(e.message);
    }
  }

  async function setQty(itemId, qty) {
    try {
      state.cart = await api("/api/cart/" + itemId, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ qty }),
      });
      renderCart();
    } catch (e) { toast(e.message); }
  }

  function renderCart() {
    const c = state.cart;
    $("cartCount").textContent = c.count || 0;

    const box = $("cartItems");
    if (!c.items || !c.items.length) {
      box.innerHTML = `<p class="empty">Your cart is empty.</p>`;
    } else {
      box.innerHTML = c.items
        .map(
          (i) => `
        <div class="cart-line">
          <img src="${i.image}" alt="${i.title}" />
          <div class="cl-body">
            <p class="cl-title">${i.title}</p>
            <p class="muted">${money(i.price)}</p>
            <div class="qty">
              <button onclick="Nova.setQty(${i.item_id}, ${i.qty - 1})">−</button>
              <span>${i.qty}</span>
              <button onclick="Nova.setQty(${i.item_id}, ${i.qty + 1})">+</button>
              <button class="remove" onclick="Nova.setQty(${i.item_id}, 0)">Remove</button>
            </div>
          </div>
          <strong>${money(i.line_total)}</strong>
        </div>`
        )
        .join("");
    }

    $("cartSummary").innerHTML = `
      <div class="sum-row"><span>Subtotal</span><span>${money(c.subtotal)}</span></div>
      <div class="sum-row"><span>Shipping</span><span>${c.shipping ? money(c.shipping) : "FREE"}</span></div>
      <div class="sum-row total"><span>Total</span><span>${money(c.total)}</span></div>`;
    $("placeOrder").disabled = !c.items || !c.items.length;
  }

  async function checkout(e) {
    e.preventDefault();
    const msg = $("checkoutMsg");
    msg.textContent = "";
    try {
      const data = await api("/api/orders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          customer_name: $("c_name").value.trim(),
          email: $("c_email").value.trim(),
          address: $("c_address").value.trim(),
        }),
      });
      const ref = data.order.reference;
      msg.className = "form-msg ok";
      msg.textContent = `Order ${ref} confirmed — ${money(data.order.total)}`;
      toast("Order placed: " + ref);
      $("checkoutForm").reset();
      state.cart = await api("/api/cart");
      renderCart();
      loadProducts();
    } catch (err) {
      msg.className = "form-msg bad";
      msg.textContent = err.message;
    }
    return false;
  }

  function openCart() {
    $("cartOverlay").hidden = false;
    api("/api/cart").then((c) => { state.cart = c; renderCart(); }).catch(() => {});
  }
  function closeCart(e) {
    if (e && e.target !== $("cartOverlay")) return;
    $("cartOverlay").hidden = true;
  }

  function applyFilters() {
    state.q = $("q").value.trim();
    state.inStock = $("inStockOnly").checked;
    state.sort = $("sort").value;
    loadProducts();
  }

  function scrollToCatalog() {
    $("catalog").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function goHome() {
    $("q").value = "";
    state.q = ""; state.category = ""; state.sort = "featured"; state.inStock = false;
    $("sort").value = "featured"; $("inStockOnly").checked = false;
    renderChips();
    loadProducts();
    window.scrollTo({ top: 0, behavior: "smooth" });
    return false;
  }

  /* ------------------------------------------------------------------ */
  /* Admin hub                                                          */
  /* ------------------------------------------------------------------ */

  function toggleAdmin() {
    const admin = $("admin");
    const store = $("storefront");
    const showAdmin = admin.hidden;
    admin.hidden = !showAdmin;
    store.hidden = showAdmin;
    $("adminToggle").textContent = showAdmin ? "← Storefront" : "Admin Hub";
    if (showAdmin) {
      $("adminToken").value = state.token;
      if (state.token) loadAdmin();
    }
  }

  function saveToken() {
    state.token = $("adminToken").value.trim();
    localStorage.setItem("nova_admin_token", state.token);
    loadAdmin();
  }

  function adminHeaders() {
    return { "X-Admin-Token": state.token, "Content-Type": "application/json" };
  }

  async function loadAdmin() {
    const status = $("adminStatus");
    status.textContent = "Connecting…";
    try {
      const [stats, prods, orders] = await Promise.all([
        api("/api/admin/stats", { headers: adminHeaders() }),
        api("/api/admin/products", { headers: adminHeaders() }),
        api("/api/admin/orders", { headers: adminHeaders() }),
      ]);
      status.textContent = "Connected";
      renderStats(stats);
      renderAdminTable(prods.products || []);
      renderOrders(orders.orders || []);
    } catch (e) {
      status.textContent = "";
      toast(e.message);
    }
  }

  function renderStats(s) {
    $("stats").innerHTML = [
      ["Products", s.products],
      ["Low stock (<20)", s.low_stock],
      ["Orders", s.orders],
      ["Revenue", money(s.revenue)],
    ]
      .map(([k, v]) => `<div class="stat"><span>${k}</span><strong>${v}</strong></div>`)
      .join("");
  }

  function renderAdminTable(products) {
    $("adminTable").innerHTML = products
      .map(
        (p) => `
      <tr>
        <td class="cell-title">${p.title}</td>
        <td>${p.category}</td>
        <td>${money(p.price)}</td>
        <td class="${p.stock < 20 ? "low" : ""}">${p.stock}</td>
        <td class="cell-actions">
          <button class="link-btn" onclick="Nova.editProduct(${p.id})">Edit</button>
          <button class="link-btn danger" onclick="Nova.deleteProduct(${p.id})">Delete</button>
        </td>
      </tr>`
      )
      .join("") || `<tr><td colspan="5" class="muted">No products yet.</td></tr>`;
  }

  function renderOrders(orders) {
    $("ordersTable").innerHTML = orders
      .map(
        (o) => `
      <tr>
        <td>${o.reference}</td>
        <td>${o.customer_name}<br><span class="muted">${o.email}</span></td>
        <td>${o.item_count}</td>
        <td>${money(o.total)}</td>
        <td><span class="pill">${o.status}</span></td>
      </tr>`
      )
      .join("") || `<tr><td colspan="5" class="muted">No orders yet.</td></tr>`;
  }

  function editProduct(id) {
    api("/api/admin/products", { headers: adminHeaders() })
      .then((d) => {
        const p = (d.products || []).find((x) => x.id === id);
        if (!p) return;
        state.editing = id;
        $("p_id").value = p.id;
        $("p_title").value = p.title;
        $("p_brand").value = p.brand;
        $("p_category").value = p.category;
        $("p_price").value = p.price;
        $("p_list").value = p.list_price || "";
        $("p_stock").value = p.stock;
        $("p_image").value = p.image;
        $("p_desc").value = p.description;
        $("formTitle").textContent = "Edit product #" + p.id;
        $("formSubmit").textContent = "Update product";
        window.scrollTo({ top: 0, behavior: "smooth" });
      })
      .catch((e) => toast(e.message));
  }

  async function saveProduct(e) {
    e.preventDefault();
    const body = {
      title: $("p_title").value.trim(),
      brand: $("p_brand").value.trim(),
      category: $("p_category").value.trim(),
      price: parseFloat($("p_price").value),
      list_price: $("p_list").value ? parseFloat($("p_list").value) : null,
      stock: parseInt($("p_stock").value || "0", 10),
      image: $("p_image").value.trim(),
      description: $("p_desc").value.trim(),
    };
    const editing = state.editing;
    try {
      await api(editing ? "/api/admin/products/" + editing : "/api/admin/products", {
        method: editing ? "PUT" : "POST",
        headers: adminHeaders(),
        body: JSON.stringify(body),
      });
      toast(editing ? "Product updated" : "Product added");
      resetForm();
      loadAdmin();
    } catch (err) {
      toast(err.message);
    }
    return false;
  }

  async function deleteProduct(id) {
    if (!confirm("Delete this product permanently?")) return;
    try {
      await api("/api/admin/products/" + id, { method: "DELETE", headers: adminHeaders() });
      toast("Product deleted");
      loadAdmin();
    } catch (e) { toast(e.message); }
  }

  function resetForm() {
    state.editing = null;
    $("productForm").reset();
    $("p_id").value = "";
    $("formTitle").textContent = "Add product";
    $("formSubmit").textContent = "Save product";
  }

  /* ------------------------------------------------------------------ */

  document.addEventListener("DOMContentLoaded", () => {
    $("q").addEventListener("keydown", (e) => { if (e.key === "Enter") applyFilters(); });
    loadCategories();
    loadProducts();
    api("/api/cart").then((c) => { state.cart = c; renderCart(); }).catch(() => {});
  });

  window.Nova = {
    applyFilters, scrollToCatalog, goHome, openProduct, closeProduct,
    addToCart, setQty, openCart, closeCart, checkout,
    toggleAdmin, saveToken, editProduct, saveProduct, deleteProduct, resetForm,
  };
})();
