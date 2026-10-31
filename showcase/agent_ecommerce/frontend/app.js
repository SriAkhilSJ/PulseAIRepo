/* Amazon.pulse E-Commerce Storefront & Vendor Central. Vanilla JS, zero build step. */
"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const state = {
  user: null,
  products: [],
  cart: { items: [], total_cents: 0 },
  category: "",
  query: "",
  sort: "featured",
  isAdminView: false,
};

const money = (c) => "$" + (c / 100).toFixed(2);

function splitPrice(cents) {
  const dollars = Math.floor(cents / 100);
  const remainder = String(cents % 100).padStart(2, "0");
  return { whole: dollars, fraction: remainder };
}

/* Escape HTML safely */
function esc(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/* API Client */
async function api(path, opts) {
  opts = opts || {};
  const headers = { "Content-Type": "application/json" };
  const token = localStorage.getItem("pg_token");
  if (token) headers["X-Session-Token"] = token;

  let cartToken = localStorage.getItem("pg_cart_token");
  if (!cartToken) {
    cartToken = "cart_" + Math.random().toString(36).substring(2, 12);
    localStorage.setItem("pg_cart_token", cartToken);
  }
  headers["X-Cart-Token"] = cartToken;

  const res = await fetch("/api" + path, {
    method: opts.method || "GET",
    headers: headers,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });

  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

function toast(msg) {
  const t = $("#amzToast");
  if (!t) return;
  t.innerHTML = `<span>✓</span> <span>${esc(msg)}</span>`;
  t.classList.add("show");
  setTimeout(() => {
    t.classList.remove("show");
  }, 2800);
}

/* ================== STOREFRONT CATALOG ================== */

async function loadProducts() {
  const p = new URLSearchParams();
  if (state.query) p.set("q", state.query);
  if (state.category) p.set("category", state.category);
  const data = await api("/products?" + p.toString());
  state.products = data.products || [];
}

async function renderProducts() {
  const sort = $("#amzSortSelect") ? $("#amzSortSelect").value : "featured";
  state.sort = sort;

  let list = state.products.slice();
  if (sort === "price_asc") list.sort((a, b) => a.price_cents - b.price_cents);
  else if (sort === "price_desc") list.sort((a, b) => b.price_cents - a.price_cents);
  else if (sort === "rating") list.sort((a, b) => b.rating - a.rating);
  else if (sort === "title") list.sort((a, b) => a.title.localeCompare(b.title));

  const grid = $("#amzProductGrid");
  if (!grid) return;

  if (list.length === 0) {
    grid.innerHTML = `
      <div style="grid-column: 1 / -1; padding: 60px 20px; text-align: center; background: #fff; border-radius: 8px;">
        <h3 style="font-size: 20px; margin-bottom: 8px;">No results found for "${esc(state.query || state.category)}"</h3>
        <p style="color: var(--amz-muted); margin-bottom: 16px;">Try checking your spelling or use more general terms.</p>
        <button class="btn-amz-cart" onclick="goHome()">Explore All Products</button>
      </div>`;
    $("#catalogResultCounter").innerHTML = `Showing <strong>0</strong> results for "${esc(state.query || state.category)}"`;
    return;
  }

  $("#catalogResultCounter").innerHTML = `Showing <strong>1-${list.length}</strong> of ${list.length} results for <span id="activeSearchLabel">"${esc(state.category || state.query || "All Departments")}"</span>`;

  grid.innerHTML = list.map((p, idx) => amzProductCardHtml(p, idx)).join("");
}

function amzProductCardHtml(p, idx) {
  const pObj = splitPrice(p.price_cents);
  const listPriceDollars = ((p.price_cents * 1.25) / 100).toFixed(2);
  const fullStars = Math.round(p.rating);
  const starsStr = "★".repeat(fullStars) + "☆".repeat(5 - fullStars);
  const reviewsCount = Math.floor(120 + (p.id * 173) % 4300);

  let badge = "";
  if (idx % 5 === 0) {
    badge = '<span class="badge-best-seller">#1 Best Seller</span>';
  } else if (idx % 5 === 2) {
    badge = '<span class="badge-amazons-choice">Amazon\'s <span>Choice</span></span>';
  }

  const dealChip = idx % 3 === 0 ? '<div class="amz-deal-chip">Limited time deal</div>' : "";
  const stockText = p.stock > 0 
    ? (p.stock < 10 ? `<span class="stock-status" style="color:#b12704;">Only ${p.stock} left in stock - order soon.</span>` : '<span class="stock-status">In Stock</span>')
    : '<span class="stock-status oos">Temporarily out of stock.</span>';

  return `
    <article class="amz-card" data-pid="${p.id}">
      <div class="amz-badge-slot">${badge}</div>
      <div class="amz-card-img-wrap">
        <img src="${esc(p.image_url)}" alt="${esc(p.title)}" loading="lazy" onerror="this.src='https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=400'">
      </div>
      <div class="amz-card-brand">${esc(p.brand)}</div>
      <div class="amz-card-title" title="${esc(p.title)}">${esc(p.title)}</div>
      
      <div class="amz-rating-row">
        <span class="amz-stars">${starsStr}</span>
        <span class="amz-review-count">(${reviewsCount.toLocaleString()})</span>
      </div>

      ${dealChip}

      <div class="amz-price-box">
        <span class="price-symbol">$</span>
        <span class="price-whole">${pObj.whole}</span>
        <span class="price-fraction">${pObj.fraction}</span>
        <span class="list-price">List: $${listPriceDollars}</span>
      </div>

      <div class="amz-prime-delivery">
        <span class="prime-logo">✓prime</span>
        <span>FREE delivery <span class="delivery-date">Tomorrow</span></span>
      </div>

      ${stockText}

      <div class="amz-btn-group">
        <button class="btn-amz-cart" onclick="addToCart(${p.id})" ${p.stock === 0 ? "disabled" : ""}>
          ${p.stock === 0 ? "Out of Stock" : "Add to Cart"}
        </button>
        <button class="btn-amz-buy" onclick="buyNow(${p.id})" ${p.stock === 0 ? "disabled" : ""}>
          Buy Now
        </button>
      </div>
    </article>
  `;
}

function doSearch() {
  state.query = $("#searchInput").value.trim();
  loadProducts().then(renderProducts);
}

function filterByCategory(cat) {
  state.category = cat;
  state.query = "";
  if ($("#searchInput")) $("#searchInput").value = "";
  if ($("#searchCategory")) $("#searchCategory").value = cat;

  // Update subnav active class
  $$(".nav-subnav a").forEach((a) => {
    if (a.textContent.includes(cat) && cat !== "") {
      a.classList.add("active");
    } else if (cat === "" && a.textContent.includes("Today's Deals")) {
      a.classList.add("active");
    } else {
      a.classList.remove("active");
    }
  });

  if (state.isAdminView) {
    toggleAdminPortal(false);
  }

  loadProducts().then(() => {
    renderProducts();
    scrollToGrid();
  });
}

function goHome() {
  state.category = "";
  state.query = "";
  if ($("#searchInput")) $("#searchInput").value = "";
  if ($("#searchCategory")) $("#searchCategory").value = "";
  if (state.isAdminView) toggleAdminPortal(false);
  loadProducts().then(() => {
    renderProducts();
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
}

function scrollToGrid() {
  const el = $("#catalogSection");
  if (el) el.scrollIntoView({ behavior: "smooth" });
}

function promptZip() {
  const current = $("#zipText").textContent;
  const newZip = prompt("Enter delivery postal code / city:", current);
  if (newZip) {
    $("#zipText").textContent = newZip;
    toast("Delivery location updated to " + newZip);
  }
}

/* ================== SHOPPING CART & DRAWER ================== */

function cartQty() {
  return state.cart.items.reduce((sum, item) => sum + item.qty, 0);
}

function updateCartBadges() {
  const qty = cartQty();
  const badge = $("#cartCountBadge");
  if (badge) badge.textContent = qty;
  const drawerCount = $("#cartDrawerCount");
  if (drawerCount) drawerCount.textContent = qty;
  const drawerSubtotal = $("#cartDrawerSubtotal");
  if (drawerSubtotal) drawerSubtotal.textContent = money(state.cart.total_cents);
}

async function loadCart() {
  try {
    state.cart = await api("/cart");
  } catch (e) {
    state.cart = { items: [], total_cents: 0 };
  }
  updateCartBadges();
}

function toggleCartDrawer(open) {
  const drawer = $("#cartDrawer");
  const overlay = $("#cartOverlay");
  if (!drawer || !overlay) return;

  if (open) {
    renderCartDrawer();
    drawer.classList.add("active");
    overlay.classList.add("active");
  } else {
    drawer.classList.remove("active");
    overlay.classList.remove("active");
  }
}

function renderCartDrawer() {
  updateCartBadges();
  const container = $("#cartDrawerItems");
  if (!container) return;

  if (!state.cart.items || state.cart.items.length === 0) {
    container.innerHTML = `
      <div style="text-align: center; padding: 40px 10px;">
        <svg style="width: 60px; height: 60px; fill: #d5d9d9; margin-bottom: 12px;" viewBox="0 0 24 24"><path d="M7 18c-1.1 0-1.99.9-1.99 2S5.9 22 7 22s2-.9 2-2-.9-2-2-2zM1 2v2h2l3.6 7.59-1.35 2.45c-.16.28-.25.61-.25.96 0 1.1.9 2 2 2h12v-2H7.42c-.14 0-.25-.11-.25-.25l.03-.12.9-1.63h7.45c.75 0 1.41-.41 1.75-1.03l3.58-6.49c.08-.14.12-.31.12-.48 0-.55-.45-1-1-1H5.21l-.94-2H1zm16 16c-1.1 0-1.99.9-1.99 2s.89 2 1.99 2 2-.9 2-2-.9-2-2-2z"/></svg>
        <h4 style="font-size: 16px; margin-bottom: 6px;">Your Amazon Cart is empty</h4>
        <p style="font-size: 13px; color: var(--amz-muted); margin-bottom: 16px;">Explore today's featured deals and founder essentials.</p>
        <button class="btn-amz-cart" onclick="toggleCartDrawer(false); scrollToGrid();">Shop Today's Deals</button>
      </div>`;
    return;
  }

  container.innerHTML = state.cart.items.map((item) => `
    <div class="cart-item-row">
      <img src="${esc(item.image_url)}" alt="${esc(item.title)}" onerror="this.src='https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=200'">
      <div class="cart-item-details">
        <div class="cart-item-title">${esc(item.title)}</div>
        <div class="cart-item-price">${money(item.price_cents * item.qty)}</div>
        <div style="font-size:12px; color:var(--amz-green); margin-bottom:4px;">In Stock</div>
        <div class="cart-item-ctrls">
          <label>Qty:
            <select class="cart-qty-select" onchange="setCartQty(${item.product_id}, this.value)">
              ${[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map(n => `<option value="${n}" ${n === item.qty ? "selected" : ""}>${n}</option>`).join("")}
            </select>
          </label>
          <a onclick="setCartQty(${item.product_id}, 0)">Delete</a>
          <a onclick="toast('Saved for later')">Save for later</a>
        </div>
      </div>
    </div>
  `).join("");
}

async function addToCart(pid) {
  try {
    state.cart = await api("/cart/add", {
      method: "POST",
      body: { product_id: pid, qty: 1 }
    });
    updateCartBadges();
    toast("Item added to cart");
    toggleCartDrawer(true);
  } catch (e) {
    toast("Error: " + e.message);
  }
}

async function buyNow(pid) {
  await addToCart(pid);
  proceedToCheckout();
}

async function setCartQty(pid, qty) {
  try {
    state.cart = await api("/cart/set", {
      method: "POST",
      body: { product_id: pid, qty: parseInt(qty, 10) }
    });
    renderCartDrawer();
  } catch (e) {
    toast("Error: " + e.message);
  }
}

async function proceedToCheckout() {
  if (state.cart.items.length === 0) {
    toast("Your cart is empty!");
    return;
  }

  showModal(`
    <h3 style="font-size: 20px; font-weight: 700; margin-bottom: 12px; display:flex; align-items:center; gap:8px;">
      <span>🔒</span> Amazon 1-Click Fast Checkout
    </h3>
    <div style="background:#f0f2f2; padding:12px; border-radius:6px; margin-bottom:16px; font-size:13px;">
      <div><strong>Shipping Address:</strong> Demo Customer, 440 Terry Ave N, Seattle, WA 98109</div>
      <div><strong>Payment Method:</strong> Amazon Prime Rewards Visa Signature (Ending in 4022)</div>
      <div><strong>Delivery Speed:</strong> Prime FREE Tomorrow by 10 AM</div>
    </div>
    <div style="font-size:15px; font-weight:700; margin-bottom:16px;">
      Order Total: <span style="color:#b12704; font-size:20px;">${money(state.cart.total_cents)}</span>
    </div>
    <button class="btn-checkout-amz" id="confirmOrderBtn" onclick="executeCheckout()">Place Your Order in USD</button>
    <p style="font-size:11px; color:var(--amz-muted); text-align:center; margin-top:8px;">
      By placing your order, you agree to Amazon's conditions of use and privacy notice.
    </p>
  `);
}

async function executeCheckout() {
  const btn = $("#confirmOrderBtn");
  if (btn) { btn.disabled = true; btn.textContent = "Processing Order..."; }

  try {
    const res = await api("/checkout", {
      method: "POST",
      body: {
        shipping_address: "Demo Customer, 440 Terry Ave N, Seattle, WA 98109",
        payment_method: "prime_visa"
      }
    });

    closeModal();
    toggleCartDrawer(false);
    await loadCart();

    showModal(`
      <div style="text-align: center; padding: 20px 0;">
        <div style="font-size: 48px; margin-bottom: 12px;">🎉</div>
        <h3 style="font-size: 22px; font-weight: 800; color: var(--amz-green); margin-bottom: 8px;">Order Placed Successfully!</h3>
        <p style="font-size: 15px; margin-bottom: 8px;">Order <strong>#${res.order.id}</strong></p>
        <p style="font-size: 14px; color: var(--amz-muted); margin-bottom: 20px;">
          A confirmation email has been sent. Your prime package will arrive tomorrow by 10:00 AM.
        </p>
        <button class="btn-amz-cart" onclick="closeModal()">Continue Shopping</button>
      </div>
    `);
    toast("Order #" + res.order.id + " placed!");
  } catch (e) {
    toast("Checkout failed: " + e.message);
    if (btn) { btn.disabled = false; btn.textContent = "Place Your Order"; }
  }
}

/* ================== ORDERS & AUTH ================== */

async function showOrdersModal() {
  try {
    const data = await api("/orders");
    const orders = data.orders || [];

    if (orders.length === 0) {
      showModal(`
        <h3 style="font-size: 20px; font-weight: 700; margin-bottom: 12px;">Your Orders</h3>
        <p style="color:var(--amz-muted); padding: 20px 0;">You have not placed any orders yet.</p>
        <button class="btn-amz-cart" onclick="closeModal()">Start Shopping</button>
      `);
      return;
    }

    const rows = orders.map((o) => `
      <div style="border:1px solid #d5d9d9; border-radius:6px; margin-bottom:12px; overflow:hidden;">
        <div style="background:#f0f2f2; padding:8px 14px; display:flex; justify-content:space-between; font-size:12px; color:var(--amz-muted);">
          <div>ORDER # <strong>${o.id}</strong></div>
          <div>TOTAL <strong>${money(o.total_cents)}</strong></div>
          <div>STATUS <strong style="color:var(--amz-green); text-transform:uppercase;">${esc(o.status)}</strong></div>
        </div>
        <div style="padding:12px 14px; font-size:13px;">
          <div><strong>Items:</strong> ${o.items_count || 1} items</div>
          <div style="color:var(--amz-muted); font-size:12px;">Placed on: ${new Date(o.created_at).toLocaleString()}</div>
        </div>
      </div>
    `).join("");

    showModal(`
      <h3 style="font-size: 20px; font-weight: 700; margin-bottom: 16px;">Your Orders (${orders.length})</h3>
      <div style="max-height: 400px; overflow-y: auto;">
        ${rows}
      </div>
    `);
  } catch (e) {
    toast("Failed to load orders: " + e.message);
  }
}

function openAuth() {
  if (state.user) {
    showModal(`
      <h3 style="font-size: 20px; font-weight: 700; margin-bottom: 12px;">Your Account</h3>
      <p style="margin-bottom: 6px;">Signed in as <strong>${esc(state.user.name)}</strong></p>
      <p style="color:var(--amz-muted); font-size:13px; margin-bottom: 16px;">${esc(state.user.email)} (${esc(state.user.role)})</p>
      <button class="btn-amz-cart" style="width:100%; margin-bottom:8px;" onclick="showOrdersModal()">View Your Orders</button>
      <button class="btn-amz-buy" style="width:100%; margin-bottom:8px;" onclick="toggleAdminPortal()">Vendor Central & Admin</button>
      <button class="btn-amz-cart" style="width:100%; background:#fff; border:1px solid #d5d9d9;" onclick="logout()">Sign Out</button>
    `);
    return;
  }

  showModal(`
    <div style="text-align: center; margin-bottom: 16px;">
      <span style="font-size: 24px; font-weight: 800; color: #131921;">amazon<span style="color: #ff9900;">.pulse</span></span>
      <h3 style="font-size: 20px; font-weight: 700; margin-top: 8px;">Sign In</h3>
    </div>
    <div style="margin-bottom: 12px;">
      <label style="display:block; font-size:13px; font-weight:700; margin-bottom:4px;">Email or mobile phone number</label>
      <input type="email" id="authEmail" value="demo@pulsegear.com" style="width:100%; padding:8px 10px; border:1px solid #888; border-radius:4px; font-size:14px;">
    </div>
    <div style="margin-bottom: 16px;">
      <label style="display:block; font-size:13px; font-weight:700; margin-bottom:4px;">Password</label>
      <input type="password" id="authPass" value="demo123" style="width:100%; padding:8px 10px; border:1px solid #888; border-radius:4px; font-size:14px;">
    </div>
    <button class="btn-amz-cart" style="width:100%; border-radius:4px; padding:10px;" onclick="executeLogin()">Sign In</button>
    <p style="font-size:12px; color:var(--amz-muted); margin-top:14px; text-align:center;">
      Pre-configured Demo Credentials: <code>demo@pulsegear.com</code> / <code>demo123</code>
    </p>
  `);
}

async function executeLogin() {
  const email = $("#authEmail").value.trim();
  const password = $("#authPass").value;

  try {
    const data = await api("/auth/login", {
      method: "POST",
      body: { email, password }
    });

    localStorage.setItem("pg_token", data.token);
    state.user = data.user;
    updateNavGreeting();
    closeModal();
    toast("Welcome back, " + data.user.name);
  } catch (e) {
    toast("Login failed: " + e.message);
  }
}

function logout() {
  localStorage.removeItem("pg_token");
  state.user = null;
  updateNavGreeting();
  closeModal();
  toast("Signed out successfully");
}

function updateNavGreeting() {
  const greeting = $("#navAccountGreeting");
  if (!greeting) return;
  if (state.user) {
    greeting.textContent = "Hello, " + state.user.name.split(" ")[0];
  } else {
    greeting.textContent = "Hello, sign in";
  }
}

/* ================== VENDOR ADMIN PORTAL ================== */

function toggleAdminPortal(show) {
  if (show === undefined) {
    state.isAdminView = !state.isAdminView;
  } else {
    state.isAdminView = show;
  }

  const storefront = $("#storefrontContainer");
  const admin = $("#adminPortalSection");

  if (state.isAdminView) {
    storefront.classList.add("hidden");
    admin.classList.remove("hidden");
    loadAdminDashboard();
    window.scrollTo({ top: 0, behavior: "smooth" });
  } else {
    storefront.classList.remove("hidden");
    admin.classList.add("hidden");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
}

async function loadAdminDashboard() {
  try {
    const [stats, productsData, ordersData] = await Promise.all([
      api("/admin/stats"),
      api("/admin/products"),
      api("/admin/orders")
    ]);

    $("#statRevenue").textContent = money(stats.revenue_cents || 0);
    $("#statOrders").textContent = stats.total_orders || 0;
    $("#statProducts").textContent = stats.total_products || 0;
    $("#statLowStock").textContent = stats.low_stock || 0;

    renderAdminInventory(productsData.products || []);
    renderAdminOrders(ordersData.orders || []);
  } catch (e) {
    toast("Admin loading error: " + e.message);
  }
}

function renderAdminInventory(products) {
  const tbody = $("#adminInventoryTableBody");
  if (!tbody) return;

  tbody.innerHTML = products.map((p) => `
    <tr>
      <td><code>SKU-${p.id.toString().padStart(4, "0")}</code></td>
      <td style="display:flex; align-items:center; gap:10px;">
        <img src="${esc(p.image_url)}" style="width:36px; height:36px; object-fit:contain; border-radius:4px; border:1px solid #ddd;" onerror="this.src='https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=100'">
        <span style="font-weight:600;">${esc(p.title)}</span>
      </td>
      <td><span style="background:#eef2f1; padding:3px 8px; border-radius:4px; font-size:12px;">${esc(p.category)}</span></td>
      <td><strong>${money(p.price_cents)}</strong></td>
      <td>${p.stock > 0 ? p.stock : '<strong style="color:var(--amz-red);">OOS</strong>'}</td>
      <td>★ ${p.rating.toFixed(1)}</td>
      <td>
        <button class="btn-amz-cart" style="padding:4px 8px; font-size:12px; border-radius:4px;" onclick="editProductStock(${p.id}, ${p.stock})">Adjust Stock</button>
      </td>
    </tr>
  `).join("");
}

function renderAdminOrders(orders) {
  const tbody = $("#adminOrdersTableBody");
  if (!tbody) return;

  tbody.innerHTML = orders.map((o) => {
    let statusClass = "status-paid";
    if (o.status === "shipped") statusClass = "status-shipped";
    if (o.status === "delivered") statusClass = "status-delivered";

    return `
      <tr>
        <td><strong>#${o.id}</strong></td>
        <td>${esc(o.user_name || "Guest")}</td>
        <td>${o.items_count || 1} items</td>
        <td><strong>${money(o.total_cents)}</strong></td>
        <td><span class="badge-status ${statusClass}">${esc(o.status)}</span></td>
        <td style="font-size:12px; color:var(--amz-muted);">${new Date(o.created_at).toLocaleDateString()}</td>
        <td>
          ${o.status !== "delivered" ? `
            <button class="btn-amz-cart" style="padding:4px 8px; font-size:12px; border-radius:4px;" onclick="cycleOrderStatus(${o.id}, '${o.status}')">
              Mark ${o.status === "paid" ? "Shipped" : "Delivered"}
            </button>
          ` : '<span style="color:var(--amz-green); font-weight:700;">Completed ✓</span>'}
        </td>
      </tr>
    `;
  }).join("");
}

async function cycleOrderStatus(orderId, currentStatus) {
  const nextStatus = currentStatus === "paid" ? "shipped" : "delivered";
  try {
    await api(`/admin/orders/${orderId}/status`, {
      method: "PUT",
      body: { status: nextStatus }
    });
    toast(`Order #${orderId} marked as ${nextStatus}`);
    loadAdminDashboard();
  } catch (e) {
    toast("Status update error: " + e.message);
  }
}

async function editProductStock(productId, currentStock) {
  const newStock = prompt("Enter new inventory quantity for product #" + productId + ":", currentStock);
  if (newStock === null) return;
  const stockNum = parseInt(newStock, 10);
  if (isNaN(stockNum) || stockNum < 0) {
    toast("Invalid stock quantity");
    return;
  }

  try {
    await api(`/admin/products/${productId}`, {
      method: "PUT",
      body: { stock: stockNum }
    });
    toast(`Stock updated to ${stockNum}`);
    loadAdminDashboard();
    loadProducts();
  } catch (e) {
    toast("Failed to update stock: " + e.message);
  }
}

function openAddProductModal() {
  showModal(`
    <h3 style="font-size: 20px; font-weight: 700; margin-bottom: 14px;">Add New SKU to Catalog</h3>
    <div style="display:flex; flex-direction:column; gap:10px; font-size:13px;">
      <div>
        <label style="font-weight:700;">Title</label>
        <input id="newTitle" placeholder="e.g. Mechanical Studio Keyboard" style="width:100%; padding:8px; border:1px solid #ccc; border-radius:4px;">
      </div>
      <div>
        <label style="font-weight:700;">Brand</label>
        <input id="newBrand" placeholder="e.g. KeyPulse" style="width:100%; padding:8px; border:1px solid #ccc; border-radius:4px;">
      </div>
      <div>
        <label style="font-weight:700;">Category</label>
        <select id="newCat" style="width:100%; padding:8px; border:1px solid #ccc; border-radius:4px;">
          <option value="Audio">Audio</option>
          <option value="Computers">Computers</option>
          <option value="Wearables">Wearables</option>
          <option value="Gaming">Gaming</option>
          <option value="Accessories">Accessories</option>
          <option value="Home">Home</option>
        </select>
      </div>
      <div style="display:flex; gap:10px;">
        <div style="flex:1;">
          <label style="font-weight:700;">Price (USD)</label>
          <input id="newPrice" type="number" step="0.01" placeholder="129.99" style="width:100%; padding:8px; border:1px solid #ccc; border-radius:4px;">
        </div>
        <div style="flex:1;">
          <label style="font-weight:700;">Stock</label>
          <input id="newStock" type="number" placeholder="25" style="width:100%; padding:8px; border:1px solid #ccc; border-radius:4px;">
        </div>
      </div>
      <div>
        <label style="font-weight:700;">Image URL</label>
        <input id="newImg" value="https://images.unsplash.com/photo-1587829741301-dc798b83add3?w=500" style="width:100%; padding:8px; border:1px solid #ccc; border-radius:4px;">
      </div>
      <button class="btn-amz-cart" style="padding:10px; margin-top:8px;" onclick="createProduct()">Save Product to Inventory</button>
    </div>
  `);
}

async function createProduct() {
  const title = $("#newTitle").value.trim();
  const brand = $("#newBrand").value.trim() || "Amazon Pulse";
  const category = $("#newCat").value;
  const priceVal = parseFloat($("#newPrice").value || "0");
  const stockVal = parseInt($("#newStock").value || "0", 10);
  const imageUrl = $("#newImg").value.trim();

  if (!title) { toast("Title is required"); return; }

  try {
    await api("/admin/products", {
      method: "POST",
      body: {
        title,
        brand,
        category,
        price_cents: Math.round(priceVal * 100),
        stock: stockVal,
        image_url: imageUrl,
        description: "Official Amazon Pulse Product"
      }
    });

    closeModal();
    toast("Product created successfully!");
    loadAdminDashboard();
    loadProducts();
  } catch (e) {
    toast("Creation error: " + e.message);
  }
}

/* ================== MODAL HELPER ================== */

function showModal(html) {
  const host = $("#modalHost");
  if (!host) return;

  host.innerHTML = `
    <div class="modal-overlay" onclick="if(event.target===this)closeModal()">
      <div class="modal-box">
        <button class="modal-close" onclick="closeModal()">&times;</button>
        ${html}
      </div>
    </div>
  `;
  host.classList.remove("hidden");
}

function closeModal() {
  const host = $("#modalHost");
  if (host) {
    host.innerHTML = "";
    host.classList.add("hidden");
  }
}

/* ================== BOOTSTRAP INITIALIZATION ================== */

async function boot() {
  // Check auth
  try {
    const me = await api("/auth/me");
    if (me && me.user) {
      state.user = me.user;
    }
  } catch (e) {
    state.user = null;
  }
  updateNavGreeting();

  // Load catalog & cart in parallel
  await Promise.all([
    loadProducts(),
    loadCart()
  ]);

  renderProducts();
}

window.addEventListener("DOMContentLoaded", boot);
