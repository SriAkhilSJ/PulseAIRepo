"""Database layer: schema creation, connection helper, and seed catalogue."""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shop.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT NOT NULL UNIQUE,
    slug    TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS products (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    price        REAL NOT NULL CHECK (price >= 0),
    compare_at   REAL,
    category_id  INTEGER REFERENCES categories(id),
    image        TEXT NOT NULL DEFAULT '',
    stock        INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
    rating       REAL NOT NULL DEFAULT 0,
    reviews_count INTEGER NOT NULL DEFAULT 0,
    featured     INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS cart_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity   INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    UNIQUE(session_id, product_id)
);

CREATE TABLE IF NOT EXISTS orders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    customer    TEXT NOT NULL DEFAULT 'Guest',
    email       TEXT NOT NULL DEFAULT '',
    address     TEXT NOT NULL DEFAULT '',
    total       REAL NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'placed',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS order_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id   INTEGER NOT NULL REFERENCES orders(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    title      TEXT NOT NULL,
    price      REAL NOT NULL,
    quantity   INTEGER NOT NULL
);
"""

CATEGORIES = [
    ("Electronics", "electronics"),
    ("Home & Kitchen", "home-kitchen"),
    ("Books", "books"),
    ("Fitness", "fitness"),
    ("Toys & Games", "toys-games"),
    ("Beauty", "beauty"),
]

# (title, description, price, compare_at, category_slug, image, stock, rating, reviews, featured)
PRODUCTS = [
    ("Wireless Noise-Cancelling Headphones", "40-hour battery, adaptive ANC, plush memory-foam cups.", 199.99, 249.99, "electronics", "headphones", 42, 4.7, 1840, 1),
    ("4K Ultra HD Smart TV 55\"", "Quantum-dot panel with HDR10+ and built-in streaming apps.", 429.00, 599.00, "electronics", "tv", 15, 4.5, 920, 1),
    ("Mechanical Keyboard TKL", "Hot-swappable switches, RGB backlight, aluminium frame.", 89.50, 119.00, "electronics", "keyboard", 60, 4.6, 512, 0),
    ("Noise-Cancelling Earbuds", "IPX5 sweatproof, 30h total playback, wireless charging case.", 79.99, 99.99, "electronics", "earbuds", 88, 4.4, 1330, 0),
    ("USB-C Docking Station 12-in-1", "Dual 4K HDMI, 100W passthrough, gigabit ethernet.", 64.99, None, "electronics", "dock", 34, 4.3, 288, 0),
    ("Portable Power Bank 20000mAh", "Fast-charge 65W PD for laptops and phones.", 49.99, 59.99, "electronics", "powerbank", 120, 4.6, 764, 0),
    ("Stainless Steel Cookware Set 10pc", "Tri-ply construction, oven-safe to 500F, induction ready.", 249.00, 329.00, "home-kitchen", "cookware", 22, 4.8, 410, 1),
    ("Robot Vacuum with Mapping", "LiDAR navigation, self-emptying base, 3000Pa suction.", 349.99, 449.99, "home-kitchen", "vacuum", 18, 4.4, 1205, 1),
    ("Espresso Machine 15-Bar", "Stainless steel, milk frother wand, dual thermostat.", 179.95, 219.00, "home-kitchen", "espresso", 26, 4.5, 640, 0),
    ("Air Purifier HEPA 13", "Covers 1000 sq ft, auto mode, quiet 24dB operation.", 129.99, 159.99, "home-kitchen", "purifier", 40, 4.6, 890, 0),
    ("Ceramic Dinner Plate Set 6", "Reactive glaze, microwave and dishwasher safe.", 45.00, None, "home-kitchen", "plates", 75, 4.5, 320, 0),
    ("Memory Foam Pillow 2-Pack", "Cooling gel layer, adjustable loft, machine washable.", 39.99, 54.99, "home-kitchen", "pillow", 95, 4.3, 1540, 0),
    ("The Pragmatic Programmer", "Your journey to mastery, 20th anniversary edition.", 34.99, 49.99, "books", "book1", 200, 4.9, 3120, 1),
    ("Atomic Habits", "An easy proven way to build good habits and break bad ones.", 16.99, 27.00, "books", "book2", 180, 4.8, 5410, 1),
    ("Designing Data-Intensive Applications", "The big ideas behind reliable, scalable systems.", 42.50, 59.99, "books", "book3", 90, 4.9, 2210, 0),
    ("The Lean Startup", "How today's entrepreneurs use continuous innovation.", 14.99, 24.00, "books", "book4", 150, 4.5, 1980, 0),
    ("Deep Work", "Rules for focused success in a distracted world.", 15.99, 25.00, "books", "book5", 130, 4.6, 1670, 0),
    ("Adjustable Dumbbell Set 5-52lb", "Dial selector, space-saving, sold as single.", 299.00, 399.00, "fitness", "dumbbell", 30, 4.7, 830, 1),
    ("Yoga Mat Extra Thick", "Non-slip TPE, 6mm cushioning, carry strap included.", 29.99, 39.99, "fitness", "yogamat", 140, 4.5, 2210, 0),
    ("Smart Fitness Tracker Watch", "Heart rate, SpO2, 14-day battery, 100+ sport modes.", 59.99, 89.99, "fitness", "tracker", 110, 4.2, 3120, 0),
    ("Resistance Bands Set 11pc", "Stackable up to 150lb with handles and ankle straps.", 24.99, None, "fitness", "bands", 210, 4.4, 990, 0),
    ("Building Blocks 1000pc Set", "Creative bricks compatible with major brands, ages 6+.", 39.99, 54.99, "toys-games", "blocks", 85, 4.7, 1420, 0),
    ("Strategy Board Game Deluxe", "2-5 players, 90-min depth, wooden components.", 54.99, 69.99, "toys-games", "boardgame", 48, 4.8, 760, 1),
    ("RC Stunt Car 4WD", "360-degree flips, 2.4GHz remote, 40-min runtime.", 34.99, 49.99, "toys-games", "rccar", 70, 4.3, 1110, 0),
    ("STEM Robotics Kit", "Build 12 robots, learn coding with visual blocks.", 79.99, 99.99, "toys-games", "robotics", 36, 4.6, 540, 0),
    ("Vitamin C Brightening Serum", "20% THD ascorbate, hyaluronic acid, fragrance-free.", 32.00, 42.00, "beauty", "serum", 200, 4.6, 4210, 1),
    ("Retinol Night Cream", "0.3% encapsulated retinol with peptides and ceramides.", 28.99, 38.99, "beauty", "cream", 160, 4.5, 2890, 0),
    ("Sonic Electric Toothbrush", "5 modes, pressure sensor, 4 brush heads, 30-day battery.", 44.99, 69.99, "beauty", "toothbrush", 130, 4.7, 3640, 0),
    ("Hair Dryer Ionic Pro", "1875W fast dry, diffuser and concentrator nozzles.", 59.99, 79.99, "beauty", "hairdryer", 64, 4.4, 1220, 0),
    ("Luxury Bath Bomb Gift Set", "12 handmade organic bombs with essential oils.", 36.99, 49.99, "beauty", "bathbomb", 88, 4.5, 1740, 0),
]


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(force=False):
    if force and os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()

    count = conn.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"]
    if count == 0:
        for name, slug in CATEGORIES:
            conn.execute("INSERT OR IGNORE INTO categories (name, slug) VALUES (?, ?)", (name, slug))
        cat_map = {r["slug"]: r["id"] for r in conn.execute("SELECT id, slug FROM categories")}
        for p in PRODUCTS:
            title, desc, price, cmp_at, slug, image, stock, rating, reviews, featured = p
            conn.execute(
                """INSERT INTO products
                   (title, description, price, compare_at, category_id, image, stock, rating, reviews_count, featured)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (title, desc, price, cmp_at, cat_map.get(slug), image, stock, rating, reviews, featured),
            )
        conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db(force=True)
    print("Database initialised at", DB_PATH)
