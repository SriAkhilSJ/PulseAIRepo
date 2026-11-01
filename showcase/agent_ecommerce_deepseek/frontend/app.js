/* ShopFlow frontend — vanilla reactive store. Talks to the Flask JSON API. */

const API = "";

/* ---- deterministic visual for each product image slug (no external assets) ---- */
const IMG = {
  headphones:["🎧","#eef3ff","#c9d8ff"], laptop:["💻","#eef7f1","#bde6cf"],
  smartphone:["📱","#f3eefb","#d6c2f0"], tv:["📺","#eef6f9","#bfe3ef"],
  camera:["📷","#f4f1ea","#ddd0b0"], smartwatch:["⌚","#eef0f4","#cbd2e0"],
  speaker:["🔊","#fdeef3","#f3c4d8"], keyboard:["⌨️","#eef1f6","#c9d1dd"],
  mouse:["🖱️","#eef6f6","#c0e0dd"], monitor:["🖥️","#eef2fd","#c6d4fb"],
  powerbank:["🔋","#f0faf0","#c4e8c4"], tablet:["📱","#f5eefc","#ddc6f2"],
  drone:["🛸","#eef4f9","#c4dbef"], earbuds:["🎵","#f2eefb","#d3c6f0"],
  router:["📶","#eef8fa","#c1e6ee"], blender:["🥤","#f2f8ee","#cfe6c2"],
  cookware:["🍳","#f6f1ea","#e0cdb2"], vacuum:["🧹","#eef5f4","#c3ded9"],
  airfryer:["🍟","#fdf3e8","#f3d6ab"], purifier:["💨","#eef6fb","#c2ddf0"],
  coffee:["☕","#f5efe9","#dcc7b3"], kettle:["🫖","#f2f6f4","#cde0d8"],
  plates:["🍽️","#f6f4f0","#e0d8c8"], cutlery:["🥄","#f2f5f7","#ccd9e2"],
  pillow:["🛏️","#f3f0fb","#d6cdf0"], serum:["🧴","#fdeff5","#f5c4db"],
  moisturizer:["🧴","#eefaf5","#c0ebd9"], perfume:["🌸","#fdeef4","#f4c8dd"],
  toothbrush:["🪥","#eef8fb","#c2e4ef"], hairdryer:["💇","#fdf1f1","#f3c9c9"],
  tracker:["⌚","#eef3f9","#c5d7ea"], robot:["🤖","#eef2f8","#c6d3e6"],
  rccar:["🏎️","#fdeef0","#f3c4ca"], lego:["🧱","#fef7e8","#f2dcaa"],
  teddy:["🧸","#f7f1ea","#e3cdb6"], boardgame:["🎲","#eef4f6","#c6dde4"],
  novel:["📕","#fdeef0","#f2c6cd"], notebook:["📓","#eef2fb","#c6d3f4"],
  planner:["📔","#eef8f2","#c3e6d4"], cookbook:["📖","#f5f0e9","#ddcdb6"],
  yogamat:["🧘","#f0eefb","#cec6f2"], dumbbells:["🏋️","#f4f4f4","#d5d5d5"],
  waterbottle:["🚰","#eef8fa","#c2e5ee"], resistance:["💪","#fdf0ee","#f3c8c0"],
  running:["👟","#eef3fb","#c6d4f0"], bicycle:["🚲","#f0f8f0","#c6e6c6"],
  tent:["⛺","#eef7ef","#c3e3c6"], backpack:["🎒","#f3f4f0","#d3d8c8"],
  sunglasses:["🕶️","#f0f0f6","#c9c9dd"], blanket:["🧣","#f5f0f5","#ddcadd"],
  e_reader:["📗","#eef7f0","#c3e6cc"], humidifier:["💧","#eef4fb","#c4d9f2"],
  lamp:["💡","#fdf8e8","#f5e3a8"], microphone:["🎙️","#f0eefb","#cbc6f0"],
  gpu:["🎮","#eef7ee","#c2e6c2"], charger:["🔌","#f4f1f6","#d5cad9"],
  case:["📦","#f2f4f7","#ccd5e0"], ring:["💡","#f0f2fb","#c6ccf2"],
  default:["📦","#eef1f3","#cfd6db"],
};
function tile(slug){
  const [emoji,bg,fg] = IMG[slug] || IMG.default;
  return `<div class="thumb" style="background:linear-gradient(135deg,${bg},${fg})"><span style="font-size:52px">${emoji}</span></div>`;
}

/* ---- tiny helpers ---- */
const $ = (s,r=document)=>r.querySelector(s);
const money = n => "$" + Number(n||0).toFixed(2);
const esc = s => String(s??"").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function stars(rating,count){
  const full = Math.round(rating);
  return `<span class="stars">${"★".repeat(full)}${"☆".repeat(5-full)}</span> ${rating} <span>(${count})</span>`;
}
async function api(path, opts){
  const res = await fetch(API+path, {headers:{"Content-Type":"application/json"}, credentials:"same-origin", ...opts});
  if(!res.ok){ let m="Request failed"; try{ m=(await res.json()).error||m; }catch(e){} throw new Error(m); }
  return res.status===204 ? null : res.json();
}

const App = {
  state: { categories:[], cart:{count:0,items:[],subtotal:0}, filter:{q:"",category:"",sort:"featured"}, adminKey: sessionStorage.getItem("adminKey")||"" },

  /* ---------- boot ---------- */
  async init(){
    await this.loadCategories();
    await this.refreshCart();
    this.routeFromHash();
    window.addEventListener("hashchange", ()=>this.routeFromHash());
  },

  async loadCategories(){
    this.state.categories = await api("/api/categories");
    const nav = $("#catNav");
    nav.innerHTML = [`<button data-cat="" class="active">All</button>`]
      .concat(this.state.categories.map(c=>`<button data-cat="${c.slug}">${esc(c.name)}</button>`)).join("");
    nav.querySelectorAll("button").forEach(b=>b.onclick=()=>{
      nav.querySelectorAll("button").forEach(x=>x.classList.remove("active"));
      b.classList.add("active");
      this.state.filter.category = b.dataset.cat;
      this.goHome();
    });
    $("#catSelect").innerHTML = `<option value="">All</option>` + this.state.categories.map(c=>`<option value="${c.slug}">${esc(c.name)}</option>`).join("");
  },

  routeFromHash(){
    const h = location.hash.replace(/^#\/?/,"");
    if(h.startsWith("product/")) return this.showProduct(Number(h.split("/")[1]));
    this.goHome();
  },
  goHome(){ location.hash = ""; this.renderCatalog(); },

  /* ---------- catalog ---------- */
  async renderCatalog(){
    const f = this.state.filter;
    const qs = new URLSearchParams();
    if(f.q) qs.set("q", f.q);
    if(f.category) qs.set("category", f.category);
    if(f.sort) qs.set("sort", f.sort);
    qs.set("limit", "60");
    let products=[];
    try{ products = await api("/api/products?"+qs.toString()); }catch(e){ return this.toast("Failed to load products"); }

    const hero = `
      <section class="hero">
        <h1>Everything you need, delivered fast.</h1>
        <p>Shop 30+ hand-picked products across electronics, home, beauty, books, sports and toys — with live search, filters, a real cart and instant checkout.</p>
      </section>`;
    const head = `<div class="section-title"><h2>${f.q?`Results for “${esc(f.q)}”`: f.category?esc(f.category.replace(/-/g," ")):"Featured products"}</h2>
      <span class="link" onclick="App.openAdmin()">Vendor / Admin →</span></div>`;
    const grid = products.length
      ? `<div class="grid">${products.map(p=>this.card(p)).join("")}</div>`
      : `<div class="empty">No products match your search.</div>`;
    $("#view").innerHTML = (f.q||f.category ? `<div class="section-title"><h2>${f.q?`Results for “${esc(f.q)}”`:esc(f.category.replace(/-/g," "))}</h2></div>` : hero+head) + grid;
    this.wireCards();
  },

  card(p){
    const off = p.compare_at && p.compare_at>p.price;
    return `<article class="card">
      ${off?`<span class="badge">-${Math.round((1-p.price/p.compare_at)*100)}%</span>`:""}
      <div onclick="location.hash='#/product/${p.id}'" style="cursor:pointer">${tile(p.image)}</div>
      <h3 onclick="location.hash='#/product/${p.id}'">${esc(p.title)}</h3>
      <div class="rating">${stars(p.rating,p.reviews_count)}</div>
      <div class="price">${money(p.price)}${off?`<span class="compare">${money(p.compare_at)}</span>`:""}</div>
      <button class="btn" data-add="${p.id}" ${p.stock<=0?"disabled":""}>${p.stock<=0?"Out of stock":"Add to cart"}</button>
    </article>`;
  },

  wireCards(){
    $("#view").querySelectorAll("[data-add]").forEach(b=>b.onclick=e=>{ e.stopPropagation(); this.addToCart(Number(b.dataset.add)); });
  },

  /* ---------- product detail ---------- */
  async showProduct(id){
    let p; try{ p = await api("/api/products/"+id); }catch(e){ return this.toast("Product not found"); }
    const off = p.compare_at && p.compare_at>p.price;
    $("#view").innerHTML = `
      <div class="detail">
        <div>
          ${tile(p.image)}
          <h1 style="margin-top:16px">${esc(p.title)}</h1>
          <div class="rating">${stars(p.rating,p.reviews_count)} &nbsp;·&nbsp; <span class="pill">${esc(p.category||"")}</span></div>
          <p style="color:#333;max-width:640px">${esc(p.description)}</p>
        </div>
        <div class="buybox">
          <div class="price" style="font-size:26px">${money(p.price)}${off?`<span class="compare">${money(p.compare_at)}</span>`:""}</div>
          <p style="color:${p.stock>0?'#067d62':'#b12704'};font-weight:600">${p.stock>0?`In stock — ${p.stock} left`:"Currently out of stock"}</p>
          <button class="btn block primary" id="dAdd" ${p.stock<=0?"disabled":""}>Add to cart</button>
          <button class="btn block alt" style="margin-top:8px" id="dBuy" ${p.stock<=0?"disabled":""}>Buy now</button>
          <p style="color:#565959;font-size:12px;margin-top:12px">Ships from ShopFlow · Free delivery on orders over $35 · 30-day returns</p>
        </div>
      </div>`;
    $("#dAdd").onclick = ()=>this.addToCart(p.id);
    $("#dBuy").onclick = async ()=>{ await this.addToCart(p.id); this.openCheckout(); };
  },

  /* ---------- cart ---------- */
  async refreshCart(){
    try{ this.state.cart = await api("/api/cart"); }catch(e){ this.state.cart={count:0,items:[],subtotal:0}; }
    $("#cartCount").textContent = this.state.cart.count;
  },
  async addToCart(pid, qty=1){
    try{ this.state.cart = await api("/api/cart",{method:"POST",body:JSON.stringify({product_id:pid,quantity:qty})}); }
    catch(e){ return this.toast(e.message); }
    $("#cartCount").textContent = this.state.cart.count;
    this.toast("Added to cart");
    this.renderCartBody();
  },
  async setQty(itemId, qty){
    try{ this.state.cart = qty<=0 ? await api("/api/cart/"+itemId,{method:"DELETE"}) : await api("/api/cart/"+itemId,{method:"PATCH",body:JSON.stringify({quantity:qty})}); }
    catch(e){ return this.toast(e.message); }
    $("#cartCount").textContent = this.state.cart.count;
    this.renderCartBody();
    if($("#view").querySelector(".detail")) {} // keep detail view
  },

  openCart(){ this.renderCartBody(); $("#cartDrawer").classList.add("open"); },
  closeCart(){ $("#cartDrawer").classList.remove("open"); },
  renderCartBody(){
    const c = this.state.cart, body = $("#cartBody"), foot = $("#cartFoot");
    if(!c.items.length){ body.innerHTML = `<div class="empty">Your cart is empty.<br><br><span class="link" onclick="App.closeCart()">Keep shopping</span></div>`; foot.innerHTML=""; return; }
    body.innerHTML = c.items.map(i=>`
      <div class="cart-line">
        <div style="width:64px;height:64px;border-radius:6px;overflow:hidden" onclick="App.closeCart();location.hash='#/product/${i.product_id}'" >${tile(i.image)}</div>
        <div class="info">
          <div class="link" onclick="App.closeCart();location.hash='#/product/${i.product_id}'">${esc(i.title)}</div>
          <div style="color:#565959;font-size:12px">${money(i.price)} each · ${i.stock} in stock</div>
          <div style="display:flex;align-items:center;gap:12px;margin-top:8px">
            <span class="qty"><button onclick="App.setQty(${i.item_id},${i.quantity-1})">−</button><span>${i.quantity}</span><button onclick="App.setQty(${i.item_id},${i.quantity+1})" ${i.quantity>=i.stock?"disabled":""}>+</button></span>
            <b>${money(i.line_total)}</b>
            <span class="link" style="margin-left:auto" onclick="App.setQty(${i.item_id},0)">Remove</span>
          </div>
        </div>
      </div>`).join("");
    const free = c.subtotal>=35;
    foot.innerHTML = `
      <div style="display:flex;justify-content:space-between;font-size:16px;margin-bottom:10px"><span>Subtotal</span><b>${money(c.subtotal)}</b></div>
      <p style="color:${free?'#067d62':'#565959'};font-size:12px;margin:0 0 12px">${free?"✅ Qualifies for FREE delivery":"Add "+money(35-c.subtotal)+" for FREE delivery"}</p>
      <button class="btn block primary" onclick="App.openCheckout()">Proceed to checkout</button>`;
  },

  /* ---------- checkout ---------- */
  openCheckout(){
    this.closeCart();
    if(!this.state.cart.items.length) return this.toast("Your cart is empty");
    this.modal(`<button class="close" onclick="App.closeModal()">✕</button>
      <h2>Checkout</h2>
      <p style="color:#565959">${this.state.cart.count} item(s) · Total <b>${money(this.state.cart.subtotal)}</b></p>
      <form id="coForm">
        <div class="row2">
          <div class="field"><label>Full name</label><input name="name" required placeholder="Jane Doe"></div>
          <div class="field"><label>Email</label><input name="email" type="email" required placeholder="jane@example.com"></div>
        </div>
        <div class="field"><label>Delivery address</label><textarea name="address" rows="3" required placeholder="123 Main St, City, ZIP"></textarea></div>
        <button class="btn block primary" type="submit">Place order</button>
      </form>`);
    $("#coForm").onsubmit = async e=>{
      e.preventDefault();
      const data = Object.fromEntries(new FormData(e.target));
      try{
        const order = await api("/api/checkout",{method:"POST",body:JSON.stringify(data)});
        await this.refreshCart();
        this.modal(`<button class="close" onclick="App.closeModal()">✕</button>
          <div style="text-align:center;padding:20px">
            <div style="font-size:52px">✅</div>
            <h2>Order placed</h2>
            <p style="color:#565959">Order <b>#${order.id??order.order_id??""}</b> confirmed. A receipt was sent to ${esc(data.email)}.</p>
            <button class="btn primary" onclick="App.closeModal();App.goHome()">Continue shopping</button>
          </div>`);
      }catch(err){ this.toast(err.message); }
    };
  },

  /* ---------- orders ---------- */
  async openOrders(){
    this.modal(`<button class="close" onclick="App.closeModal()">✕</button><h2>Your orders</h2><div id="ordBody" class="empty">Loading…</div>`);
    let orders=[]; try{ orders = await api("/api/orders"); }catch(e){}
    $("#ordBody").innerHTML = orders.length ? orders.map(o=>`
      <div style="border:1px solid #e3e6e6;border-radius:8px;padding:14px;margin-bottom:12px">
        <div style="display:flex;justify-content:space-between"><b>Order #${o.id}</b><span class="pill">${esc(o.status)}</span></div>
        <div style="color:#565959;font-size:12px;margin:4px 0 8px">${esc(o.created_at)} · ${esc(o.customer)}</div>
        ${(o.items||[]).map(i=>`<div style="font-size:13px">${i.quantity}× ${esc(i.title)} — ${money(i.price*i.quantity)}</div>`).join("")}
        <div style="text-align:right;font-weight:700;margin-top:6px">Total ${money(o.total)}</div>
      </div>`).join("") : `<div class="empty">No orders yet.</div>`;
  },

  /* ---------- admin ---------- */
  openAdmin(){
    if(!this.state.adminKey) return this.adminLogin();
    this.adminPanel();
  },
  adminLogin(){
    this.modal(`<button class="close" onclick="App.closeModal()">✕</button>
      <h2>Admin sign-in</h2>
      <p style="color:#565959">Enter the vendor/admin key to manage products and view orders.</p>
      <form id="adForm"><div class="field"><label>Admin key</label><input name="key" type="password" required placeholder="admin-secret"></div>
      <button class="btn block primary" type="submit">Sign in</button></form>`);
    $("#adForm").onsubmit = async e=>{
      e.preventDefault();
      const key = new FormData(e.target).get("key");
      try{
        await api("/api/admin/stats",{headers:{"X-Admin-Key":key}});
        this.state.adminKey = key; sessionStorage.setItem("adminKey", key);
        this.adminPanel();
      }catch(err){ this.toast("Invalid admin key"); }
    };
  },
  async adminPanel(){
    const H = {"X-Admin-Key":this.state.adminKey};
    let stats,products,orders;
    try{
      [stats,products,orders] = await Promise.all([
        api("/api/admin/stats",{headers:H}), api("/api/admin/products",{headers:H}), api("/api/admin/orders",{headers:H})
      ]);
    }catch(e){ sessionStorage.removeItem("adminKey"); this.state.adminKey=""; return this.adminLogin(); }

    this.modal(`<button class="close" onclick="App.closeModal()">✕</button>
      <h2>Vendor / Admin dashboard</h2>
      <div class="stat-row">
        <div class="stat"><b>${stats.products}</b><span>Products</span></div>
        <div class="stat"><b>${stats.orders}</b><span>Orders</span></div>
        <div class="stat"><b>${money(stats.revenue)}</b><span>Revenue</span></div>
        <div class="stat"><b>${stats.low_stock}</b><span>Low stock</span></div>
      </div>
      <div class="tabs">
        <button class="active" data-tab="products">Products</button>
        <button data-tab="orders">Orders</button>
        <button data-tab="new">+ New product</button>
        <button data-tab="signout" style="margin-left:auto">Sign out</button>
      </div>
      <div id="adTab"></div>`);
    const tabs = $("#modalPanel .tabs");
    tabs.querySelectorAll("[data-tab]").forEach(b=>b.onclick=()=>{
      if(b.dataset.tab==="signout"){ sessionStorage.removeItem("adminKey"); this.state.adminKey=""; this.closeModal(); return this.toast("Signed out"); }
      tabs.querySelectorAll("[data-tab]").forEach(x=>x.classList.remove("active")); b.classList.add("active");
      if(b.dataset.tab==="products") this.adminProducts(products);
      else if(b.dataset.tab==="orders") this.adminOrders(orders);
      else this.adminNewProduct();
    });
    this.adminProducts(products);
  },
  adminProducts(products){
    $("#adTab").innerHTML = `<table class="data-table"><thead><tr><th>ID</th><th>Title</th><th>Price</th><th>Stock</th><th></th></tr></thead><tbody>
      ${products.map(p=>`<tr><td>${p.id}</td><td>${esc(p.title)}</td><td>${money(p.price)}</td>
      <td>${p.stock<=5?`<span style="color:#b12704;font-weight:600">${p.stock}</span>`:p.stock}</td>
      <td><span class="link" onclick="App.adminEdit(${p.id})">Edit</span> · <span class="link" onclick="App.adminDelete(${p.id})">Delete</span></td></tr>`).join("")}
    </tbody></table>`;
  },
  adminOrders(orders){
    $("#adTab").innerHTML = orders.length ? `<table class="data-table"><thead><tr><th>#</th><th>Customer</th><th>Items</th><th>Total</th><th>Status</th></tr></thead><tbody>
      ${orders.map(o=>`<tr><td>${o.id}</td><td>${esc(o.customer)}<br><span style="color:#565959">${esc(o.email)}</span></td>
      <td>${(o.items||[]).map(i=>`${i.quantity}× ${esc(i.title)}`).join("<br>")}</td>
      <td>${money(o.total)}</td><td><span class="pill">${esc(o.status)}</span></td></tr>`).join("")}
    </tbody></table>` : `<div class="empty">No orders yet.</div>`;
  },
  adminNewProduct(){
    $("#adTab").innerHTML = this.productForm({});
    this.wireProductForm();
  },
  async adminEdit(id){
    const p = await api("/api/products/"+id);
    $("#adTab").innerHTML = this.productForm(p);
    this.wireProductForm(id);
  },
  productForm(p){
    return `<form id="pForm">
      <div class="field"><label>Title</label><input name="title" required value="${esc(p.title||"")}"></div>
      <div class="field"><label>Description</label><textarea name="description" rows="2">${esc(p.description||"")}</textarea></div>
      <div class="row2">
        <div class="field"><label>Price</label><input name="price" type="number" step="0.01" min="0" required value="${p.price??""}"></div>
        <div class="field"><label>Compare-at price</label><input name="compare_at" type="number" step="0.01" min="0" value="${p.compare_at??""}"></div>
      </div>
      <div class="row2">
        <div class="field"><label>Stock</label><input name="stock" type="number" min="0" required value="${p.stock??0}"></div>
        <div class="field"><label>Category</label><select name="category_slug">${this.state.categories.map(c=>`<option value="${c.slug}" ${p.category_slug===c.slug?"selected":""}>${esc(c.name)}</option>`).join("")}</select></div>
      </div>
      <div class="row2">
        <div class="field"><label>Image key</label><input name="image" value="${esc(p.image||"default")}" placeholder="e.g. headphones"></div>
        <div class="field"><label>Rating</label><input name="rating" type="number" step="0.1" min="0" max="5" value="${p.rating??4.5}"></div>
      </div>
      <button class="btn primary" type="submit">Save product</button>
    </form>`;
  },
  wireProductForm(id){
    $("#pForm").onsubmit = async e=>{
      e.preventDefault();
      const raw = Object.fromEntries(new FormData(e.target));
      const body = {title:raw.title, description:raw.description, price:Number(raw.price), stock:Number(raw.stock),
        compare_at: raw.compare_at?Number(raw.compare_at):null, rating:Number(raw.rating), image:raw.image, category_slug:raw.category_slug};
      const H = {"X-Admin-Key":this.state.adminKey};
      try{
        if(id) await api("/api/admin/products/"+id,{method:"PATCH",headers:H,body:JSON.stringify(body)});
        else await api("/api/admin/products",{method:"POST",headers:H,body:JSON.stringify(body)});
        this.toast(id?"Product updated":"Product created");
        this.adminPanel();
      }catch(err){ this.toast(err.message); }
    };
  },
  async adminDelete(id){
    if(!confirm("Delete this product?")) return;
    try{ await api("/api/admin/products/"+id,{method:"DELETE",headers:{"X-Admin-Key":this.state.adminKey}}); this.toast("Product deleted"); this.adminPanel(); }
    catch(e){ this.toast(e.message); }
  },

  /* ---------- misc ---------- */
  search(e){
    e.preventDefault();
    this.state.filter.q = $("#searchInput").value.trim();
    this.state.filter.category = $("#catSelect").value;
    this.goHome();
  },
  modal(html){ $("#modalPanel").innerHTML = html; $("#modal").classList.add("open"); },
  closeModal(){ $("#modal").classList.remove("open"); },
  toast(msg){ const t=$("#toast"); t.textContent=msg; t.classList.add("show"); clearTimeout(this._tt); this._tt=setTimeout(()=>t.classList.remove("show"),1800); },
};

document.addEventListener("DOMContentLoaded", ()=>App.init());
