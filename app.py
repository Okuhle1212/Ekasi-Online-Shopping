import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
import stripe
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")
app.permanent_session_lifetime = timedelta(days=30)

FLASK_DEBUG = os.environ.get("FLASK_DEBUG", "true").lower() in ("1", "true", "yes")

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=not FLASK_DEBUG,
)

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
stripe.api_key = STRIPE_SECRET_KEY

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "owner@kotashop.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
DATABASE = os.environ.get("DATABASE_PATH", "database.db")

VALID_CATEGORIES = {"home", "kota", "chips"}
MAX_CART_QTY = 20

# Orders that are still "in progress" from the customer's / owner's point of view.
ACTIVE_STATUSES = ("Pending", "Paid", "Ready")

# Orders that count as a completed sale for reporting purposes.
SALE_STATUSES = ("Paid", "Ready", "Collected")

DEFAULT_PRODUCTS = [
    ("Coca-cola 2L",        25.0, "Refreshing 2L Coca-Cola bottle.",                          "drink.png",        "home"),
    ("Cheese Kota",         25.0, "Fresh bread filled with melted cheese.",                    "FlyingKota1.jpg",  "kota"),
    ("Russian",             35.0, "Kota stuffed with a juicy Russian sausage and chips.",      "russian.png",      "kota"),
    ("Eggs",                40.0, "Kota filled with fried egg, chips, and sauce.",             "eggs.bmp",         "kota"),
    ("Cheese & Russian Kota",50.0,"Kota packed with melted cheese and Russian sausage.",       "FlyingKota1.jpg",  "kota"),
    ("Deluxe Kota",         70.0, "A big kota with cheese, Russian, egg, and extra chips.",    "FlyingKota1.jpg",  "kota"),
    ("Small Chips",         15.0, "Crispy fried chips — small portion.",                       "fried chips.jfif", "chips"),
    ("Medium Chips",        25.0, "Crispy fried chips — medium portion.",                      "fried chips.jfif", "chips"),
    ("Large Chips",         35.0, "Crispy fried chips — large portion.",                       "fried chips.jfif", "chips"),
]


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

@contextmanager
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Auth decorators
# ---------------------------------------------------------------------------

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def owner_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("role") != "owner":
            flash("Owner access required.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


# ---------------------------------------------------------------------------
# CSRF protection (lightweight, session-token based)
# ---------------------------------------------------------------------------

def get_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)
    return session["csrf_token"]


@app.context_processor
def inject_csrf_token():
    return dict(csrf_token=get_csrf_token)


@app.before_request
def csrf_protect():
    if request.method == "POST":
        token = session.get("csrf_token")
        submitted = request.form.get("csrf_token")
        if not token or not submitted or not secrets.compare_digest(token, submitted):
            flash("Your form session expired. Please try again.", "error")
            return redirect(request.referrer or url_for("home"))


@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


# ---------------------------------------------------------------------------
# Database migrations
# ---------------------------------------------------------------------------

def migrate_users_role(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    if not cursor.fetchone():
        return
    cursor.execute("PRAGMA table_info(users)")
    columns = {row[1] for row in cursor.fetchall()}
    if "role" not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'customer'")
        cursor.execute("UPDATE users SET role='owner' WHERE email=?", (ADMIN_EMAIL,))
        print("Added role column to users table")


def migrate_legacy_orders(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='orders'")
    if not cursor.fetchone():
        return
    cursor.execute("PRAGMA table_info(orders)")
    columns = {row[1] for row in cursor.fetchall()}
    if "items" not in columns or "total" in columns:
        return
    cursor.execute("ALTER TABLE orders RENAME TO orders_legacy")
    print("Migrated legacy orders table to orders_legacy")


def migrate_orders_add_checkout_session_id(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='orders'")
    if not cursor.fetchone():
        return
    cursor.execute("PRAGMA table_info(orders)")
    columns = {row[1] for row in cursor.fetchall()}
    if "checkout_session_id" not in columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN checkout_session_id TEXT")
        print("Added checkout_session_id column to orders table")


def migrate_products_add_sold_out(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='products'")
    if not cursor.fetchone():
        return
    cursor.execute("PRAGMA table_info(products)")
    columns = {row[1] for row in cursor.fetchall()}
    if "sold_out" not in columns:
        cursor.execute("ALTER TABLE products ADD COLUMN sold_out INTEGER NOT NULL DEFAULT 0")
        print("Added sold_out column to products table")


# ---------------------------------------------------------------------------
# Database initialisation
# ---------------------------------------------------------------------------

def init_db():
    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                name     TEXT NOT NULL,
                email    TEXT UNIQUE NOT NULL,
                phone    TEXT,
                password TEXT NOT NULL,
                role     TEXT NOT NULL DEFAULT 'customer'
            )
        """)

        migrate_users_role(conn)
        migrate_legacy_orders(conn)
        migrate_orders_add_checkout_session_id(conn)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                price       REAL NOT NULL,
                description TEXT,
                image       TEXT DEFAULT 'placeholder.svg',
                category    TEXT NOT NULL,
                active      INTEGER NOT NULL DEFAULT 1,
                sold_out    INTEGER NOT NULL DEFAULT 0
            )
        """)

        migrate_products_add_sold_out(conn)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cart_items (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                quantity   INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY(user_id)    REFERENCES users(id),
                FOREIGN KEY(product_id) REFERENCES products(id),
                UNIQUE(user_id, product_id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id             INTEGER NOT NULL,
                status              TEXT NOT NULL DEFAULT 'Pending',
                total               REAL NOT NULL DEFAULT 0,
                notes               TEXT,
                created_at          TEXT NOT NULL,
                checkout_session_id TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS order_items (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id     INTEGER NOT NULL,
                product_id   INTEGER,
                product_name TEXT NOT NULL,
                price        REAL NOT NULL,
                quantity     INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY(order_id) REFERENCES orders(id)
            )
        """)

        cursor.execute("SELECT COUNT(*) FROM products")
        if cursor.fetchone()[0] == 0:
            for name, price, desc, image, category in DEFAULT_PRODUCTS:
                cursor.execute(
                    "INSERT INTO products (name, price, description, image, category) VALUES (?,?,?,?,?)",
                    (name, price, desc, image, category),
                )

        cursor.execute("SELECT * FROM users WHERE email=?", (ADMIN_EMAIL,))
        if not cursor.fetchone():
            hashed_pw = generate_password_hash(ADMIN_PASSWORD)
            cursor.execute(
                "INSERT INTO users (name, email, phone, password, role) VALUES (?,?,?,?,?)",
                ("Shop Owner", ADMIN_EMAIL, "0000000000", hashed_pw, "owner"),
            )
            print(f"Default owner account created: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_products(conn, category=None, search=None, order_by="category, name"):
    """
    If `search` is set, it searches across ALL active products (regardless of
    category) so the home search bar behaves like a real store search.
    Otherwise it filters to the given category.
    """
    query = "SELECT * FROM products WHERE active=1"
    params = []
    if search:
        query += " AND name LIKE ?"
        params.append(f"%{search}%")
    elif category:
        if category == "home":
            query += " AND (category=? OR category=?)"
            params.extend(["home", "drinks"])
        else:
            query += " AND category=?"
            params.append(category)
    query += f" ORDER BY {order_by}"
    return conn.execute(query, params).fetchall()


def get_cart_items(conn, user_id):
    """
    Returns rows with fields:
        id (cart_items.id), quantity, product_id,
        name, price, image, description
    These are the exact field names used in Cart.html.
    """
    return conn.execute("""
        SELECT
            cart_items.id        AS id,
            cart_items.quantity  AS quantity,
            products.id          AS product_id,
            products.name        AS name,
            products.price       AS price,
            products.image       AS image,
            products.description AS description
        FROM cart_items
        JOIN products ON cart_items.product_id = products.id
        WHERE cart_items.user_id = ?
    """, (user_id,)).fetchall()


def cart_total(cart_items):
    return sum(item["price"] * item["quantity"] for item in cart_items)


def parse_positive_int(raw, default=1, minimum=1, maximum=MAX_CART_QTY):
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


# ---------------------------------------------------------------------------
# Public routes
# ---------------------------------------------------------------------------

@app.route("/")
def home():
    search = request.args.get("q", "").strip()
    with get_db() as conn:
        products = get_products(conn, category="home", search=search or None)
    return render_template("Home.html", products=products, search=search)


@app.route("/kota")
def kota():
    with get_db() as conn:
        products = get_products(conn, category="kota", order_by="price ASC")
    return render_template("Kota.html", products=products)


@app.route("/chips")
def chips():
    with get_db() as conn:
        products = get_products(conn, category="chips", order_by="price ASC")
    return render_template("Chips.html", products=products)


# ---------------------------------------------------------------------------
# Cart routes  (synced with Cart.html)
# ---------------------------------------------------------------------------

@app.route("/cart")
@login_required
def cart():
    with get_db() as conn:
        items = get_cart_items(conn, session["user_id"])
        total = cart_total(items)
    return render_template("Cart.html", cart_items=items, total=total)


@app.route("/cart/add/<int:product_id>", methods=["POST"])
@login_required
def add_to_cart(product_id):
    quantity = parse_positive_int(request.form.get("quantity", 1))
    with get_db() as conn:
        product = conn.execute(
            "SELECT id, name FROM products WHERE id=? AND active=1 AND sold_out=0", (product_id,)
        ).fetchone()
        if not product:
            flash("Product not found or currently sold out.", "error")
            return redirect(request.referrer or url_for("home"))

        existing = conn.execute(
            "SELECT id, quantity FROM cart_items WHERE user_id=? AND product_id=?",
            (session["user_id"], product_id),
        ).fetchone()

        if existing:
            new_qty = min(MAX_CART_QTY, existing["quantity"] + quantity)
            conn.execute(
                "UPDATE cart_items SET quantity=? WHERE id=?",
                (new_qty, existing["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO cart_items (user_id, product_id, quantity) VALUES (?,?,?)",
                (session["user_id"], product_id, quantity),
            )

    flash(f"{product['name']} added to cart!", "success")
    return redirect(request.referrer or url_for("cart"))


@app.route("/cart/update/<int:cart_item_id>", methods=["POST"])
@login_required
def update_cart_item(cart_item_id):
    """
    Cart.html posts: name="quantity"
    URL param: cart_item_id  (matches url_for('update_cart_item', cart_item_id=item.id))
    """
    try:
        quantity = int(request.form.get("quantity", 1))
    except ValueError:
        flash("Please enter a valid quantity.", "error")
        return redirect(url_for("cart"))

    with get_db() as conn:
        if quantity <= 0:
            conn.execute(
                "DELETE FROM cart_items WHERE id=? AND user_id=?",
                (cart_item_id, session["user_id"]),
            )
            flash("Item removed from cart.", "success")
        else:
            quantity = min(quantity, MAX_CART_QTY)
            conn.execute(
                "UPDATE cart_items SET quantity=? WHERE id=? AND user_id=?",
                (quantity, cart_item_id, session["user_id"]),
            )
            flash("Cart updated.", "success")
    return redirect(url_for("cart"))


@app.route("/cart/remove/<int:cart_item_id>", methods=["POST"])
@login_required
def remove_cart_item(cart_item_id):
    """
    Cart.html posts to url_for('remove_cart_item', cart_item_id=item.id)
    No form fields needed — cart_item_id comes from the URL.
    """
    with get_db() as conn:
        conn.execute(
            "DELETE FROM cart_items WHERE id=? AND user_id=?",
            (cart_item_id, session["user_id"]),
        )
    flash("Item removed from cart.", "success")
    return redirect(url_for("cart"))


# ---------------------------------------------------------------------------
# Checkout routes  (synced with Cart.html)
# ---------------------------------------------------------------------------

@app.route("/create-checkout-session", methods=["POST"])
@login_required
def create_checkout_session():
    """
    Cart.html: <form action="{{ url_for('create_checkout_session') }}" method="POST">
    Reads cart from DB. Order notes (optional) are passed through as Stripe
    metadata and picked up again in /success once payment is confirmed.
    """
    if not stripe.api_key:
        flash("Card payment is not available right now — please pay on collection instead.", "error")
        return redirect(url_for("cart"))

    notes = request.form.get("notes", "").strip()[:500]

    with get_db() as conn:
        cart_items = get_cart_items(conn, session["user_id"])
        if not cart_items:
            flash("Your cart is empty.", "error")
            return redirect(url_for("cart"))

    line_items = []
    for item in cart_items:
        amount = int(round(item["price"] * 100))
        line_items.append({
            "price_data": {
                "currency": "zar",
                "product_data": {"name": item["name"]},
                "unit_amount": amount,
            },
            "quantity": item["quantity"],
        })

    try:
        stripe_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=line_items,
            mode="payment",
            success_url=url_for("success", _external=True) + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=url_for("cancel", _external=True),
            client_reference_id=str(session["user_id"]),
            metadata={"notes": notes},
        )
    except stripe.error.StripeError:
        flash("Could not start card payment right now. Please try again.", "error")
        return redirect(url_for("cart"))

    return redirect(stripe_session.url, code=303)


@app.route("/checkout", methods=["POST"])
@login_required
def checkout():
    """
    Cart.html: <form action="{{ url_for('checkout') }}" method="POST">
    "Pay on collection" flow — no card payment required. Order is placed
    as Pending and the shop prepares it; payment happens in person.
    """
    notes = request.form.get("notes", "").strip()[:500]

    with get_db() as conn:
        items = get_cart_items(conn, session["user_id"])
        if not items:
            flash("Your cart is empty.", "error")
            return redirect(url_for("cart"))

        total = cart_total(items)
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO orders (user_id, status, total, notes, created_at) VALUES (?,?,?,?,?)",
            (session["user_id"], "Pending", total, notes or None, created_at),
        )
        order_id = cursor.lastrowid

        for item in items:
            cursor.execute(
                "INSERT INTO order_items (order_id, product_id, product_name, price, quantity) VALUES (?,?,?,?,?)",
                (order_id, item["product_id"], item["name"], item["price"], item["quantity"]),
            )

        conn.execute("DELETE FROM cart_items WHERE user_id=?", (session["user_id"],))

    flash(f"Order #{order_id} placed! Pay R{total:.2f} on collection.", "success")
    return redirect(url_for("orders"))


# ---------------------------------------------------------------------------
# Order routes
# ---------------------------------------------------------------------------

@app.route("/orders")
@login_required
def orders():
    with get_db() as conn:
        order_rows = conn.execute(
            "SELECT * FROM orders WHERE user_id=? ORDER BY id DESC",
            (session["user_id"],),
        ).fetchall()

        orders_with_items = []
        for order in order_rows:
            items = conn.execute(
                "SELECT product_name, price, quantity FROM order_items WHERE order_id=?",
                (order["id"],),
            ).fetchall()
            orders_with_items.append({"order": order, "order_items": items})

    return render_template("Orders.html", orders=orders_with_items)


@app.route("/cancel_order/<int:order_id>", methods=["POST"])
@login_required
def cancel_order(order_id):
    with get_db() as conn:
        order = conn.execute(
            "SELECT status FROM orders WHERE id=? AND user_id=?",
            (order_id, session["user_id"]),
        ).fetchone()

        if not order:
            flash("Order not found.", "error")
        elif order["status"] != "Pending":
            flash("Only orders awaiting payment/prep can be cancelled. Contact the shop for paid orders.", "error")
        else:
            conn.execute(
                "UPDATE orders SET status='Cancelled' WHERE id=?", (order_id,)
            )
            flash("Order cancelled.", "success")

    return redirect(url_for("orders"))


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email    = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        with get_db() as conn:
            user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()

        if user and check_password_hash(user["password"], password):
            session.permanent = request.form.get("remember_me") is not None
            session["user_id"]   = user["id"]
            session["role"]      = user["role"]
            session["user_name"] = user["name"]
            flash("Login successful!", "success")
            if user["role"] == "owner":
                return redirect(url_for("owner_dashboard"))
            return redirect(url_for("home"))

        flash("Invalid email or password.", "error")
        return redirect(url_for("login"))

    return render_template("Login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name     = request.form.get("name", "").strip()
        email    = request.form.get("email", "").strip()
        phone    = request.form.get("phone", "").strip()
        password = request.form.get("password", "")

        if not name or not email or not password:
            flash("Please fill in all required fields.", "error")
            return redirect(url_for("register"))
        if phone and not (phone.isdigit() and len(phone) == 10):
            flash("Phone number must be exactly 10 digits.", "error")
            return redirect(url_for("register"))
        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return redirect(url_for("register"))

        hashed_pw = generate_password_hash(password)

        try:
            with get_db() as conn:
                conn.execute(
                    "INSERT INTO users (name, email, phone, password, role) VALUES (?,?,?,?,?)",
                    (name, email, phone, hashed_pw, "customer"),
                )
            flash("Account created successfully! Please log in.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("An account with this email already exists.", "error")
            return redirect(url_for("register"))

    return render_template("Register.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Profile route
# ---------------------------------------------------------------------------

@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    with get_db() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE id=?", (session["user_id"],)
        ).fetchone()

        if request.method == "POST":
            if "current_password" in request.form:
                current_pw  = request.form.get("current_password", "")
                new_pw      = request.form.get("new_password", "")
                confirm_pw  = request.form.get("confirm_password", "")

                if not check_password_hash(user["password"], current_pw):
                    flash("Current password is incorrect.", "error")
                    return redirect(url_for("profile"))
                if len(new_pw) < 6:
                    flash("New password must be at least 6 characters.", "error")
                    return redirect(url_for("profile"))
                if new_pw != confirm_pw:
                    flash("New passwords do not match.", "error")
                    return redirect(url_for("profile"))

                conn.execute(
                    "UPDATE users SET password=? WHERE id=?",
                    (generate_password_hash(new_pw), session["user_id"]),
                )
                flash("Password updated successfully.", "success")
                return redirect(url_for("profile"))

            name  = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip()
            phone = request.form.get("phone", "").strip()

            if not name or not email:
                flash("Name and email are required.", "error")
                return redirect(url_for("profile"))

            try:
                conn.execute(
                    "UPDATE users SET name=?, email=?, phone=? WHERE id=?",
                    (name, email, phone, session["user_id"]),
                )
                session["user_name"] = name
                flash("Profile updated successfully.", "success")
            except sqlite3.IntegrityError:
                flash("That email is already in use.", "error")

            return redirect(url_for("profile"))

    return render_template("Profile.html", user=user)


# ---------------------------------------------------------------------------
# Owner routes
# ---------------------------------------------------------------------------

@app.route("/dashboard")
@app.route("/owner_dashboard")
@owner_required
def owner_dashboard():
    with get_db() as conn:
        pending_count = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE status IN ('Pending','Paid')"
        ).fetchone()[0]
        ready_count = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE status='Ready'"
        ).fetchone()[0]
    return render_template("OwnerDashboard.html", pending_count=pending_count, ready_count=ready_count)


@app.route("/owner/products")
@owner_required
def owner_products():
    with get_db() as conn:
        products = conn.execute(
            "SELECT * FROM products ORDER BY category, name"
        ).fetchall()
    return render_template("OwnerProducts.html", products=products)


@app.route("/owner/active_orders")
@owner_required
def owner_active_orders():
    with get_db() as conn:
        order_rows = conn.execute("""
            SELECT orders.*, users.name AS name, users.email AS email, users.phone AS phone
            FROM orders
            JOIN users ON orders.user_id = users.id
            WHERE orders.status IN ('Pending', 'Paid', 'Ready')
            ORDER BY orders.id DESC
        """).fetchall()

        orders_with_items = []
        for order in order_rows:
            items = conn.execute(
                "SELECT product_name, price, quantity FROM order_items WHERE order_id=?",
                (order["id"],),
            ).fetchall()
            orders_with_items.append({"order": order, "order_items": items})

    return render_template("OwnerActiveOrders.html", orders=orders_with_items)


@app.route("/owner/order_history")
@owner_required
def owner_order_history():
    with get_db() as conn:
        order_rows = conn.execute("""
            SELECT orders.*, users.name AS name, users.email AS email, users.phone AS phone
            FROM orders
            JOIN users ON orders.user_id = users.id
            WHERE orders.status IN ('Collected', 'Cancelled')
            ORDER BY orders.id DESC
        """).fetchall()

        orders_with_items = []
        for order in order_rows:
            items = conn.execute(
                "SELECT product_name, price, quantity FROM order_items WHERE order_id=?",
                (order["id"],),
            ).fetchall()
            orders_with_items.append({"order": order, "order_items": items})

    return render_template("OwnerOrderHistory.html", orders=orders_with_items)


@app.route("/owner/sales")
@owner_required
def owner_sales():
    """
    Sales dashboard: today / this week / this month revenue and order counts,
    plus a top-selling products table. Counts orders that have actually been
    paid for or fulfilled (Paid, Ready, Collected) as sales — Pending and
    Cancelled orders are excluded so the numbers reflect real income.
    """
    now = datetime.now()
    today_start = now.strftime("%Y-%m-%d 00:00:00")
    week_start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d 00:00:00")
    month_start = now.strftime("%Y-%m-01 00:00:00")

    status_placeholders = ",".join("?" for _ in SALE_STATUSES)

    def period_stats(conn, since):
        row = conn.execute(
            f"""
            SELECT COUNT(*) AS order_count, COALESCE(SUM(total), 0) AS revenue
            FROM orders
            WHERE status IN ({status_placeholders}) AND created_at >= ?
            """,
            (*SALE_STATUSES, since),
        ).fetchone()
        return {"order_count": row["order_count"], "revenue": row["revenue"]}

    with get_db() as conn:
        today_stats = period_stats(conn, today_start)
        week_stats = period_stats(conn, week_start)
        month_stats = period_stats(conn, month_start)

        top_products = conn.execute(
            f"""
            SELECT
                order_items.product_name AS name,
                SUM(order_items.quantity) AS units_sold,
                SUM(order_items.price * order_items.quantity) AS revenue
            FROM order_items
            JOIN orders ON order_items.order_id = orders.id
            WHERE orders.status IN ({status_placeholders}) AND orders.created_at >= ?
            GROUP BY order_items.product_name
            ORDER BY units_sold DESC
            LIMIT 8
            """,
            (*SALE_STATUSES, month_start),
        ).fetchall()

        recent_sales = conn.execute(
            f"""
            SELECT id, total, created_at, status
            FROM orders
            WHERE status IN ({status_placeholders})
            ORDER BY id DESC
            LIMIT 10
            """,
            SALE_STATUSES,
        ).fetchall()

    return render_template(
        "OwnerSales.html",
        today_stats=today_stats,
        week_stats=week_stats,
        month_stats=month_stats,
        top_products=top_products,
        recent_sales=recent_sales,
    )


@app.route("/mark_ready/<int:order_id>", methods=["POST"])
@owner_required
def mark_ready(order_id):
    with get_db() as conn:
        conn.execute(
            "UPDATE orders SET status='Ready' WHERE id=? AND status IN ('Pending','Paid')",
            (order_id,),
        )
    flash("Order marked as ready for collection.", "success")
    return redirect(url_for("owner_active_orders"))


@app.route("/mark_collected/<int:order_id>", methods=["POST"])
@owner_required
def mark_collected(order_id):
    with get_db() as conn:
        conn.execute(
            "UPDATE orders SET status='Collected' WHERE id=? AND status='Ready'",
            (order_id,),
        )
    flash("Order marked as collected.", "success")
    return redirect(url_for("owner_active_orders"))


def _parse_product_form():
    """Shared validation for add/edit product forms. Returns (data, error)."""
    name = request.form.get("name", "").strip()
    if not name:
        return None, "Product name is required."

    try:
        price = float(request.form.get("price", ""))
    except ValueError:
        return None, "Please enter a valid price."
    if price < 0:
        return None, "Price cannot be negative."

    description = request.form.get("description", "").strip()
    category = (request.form.get("category", "home") or "home").strip().lower()
    if category not in VALID_CATEGORIES:
        category = "home"
    image = request.form.get("image", "").strip() or "placeholder.svg"

    return {
        "name": name,
        "price": price,
        "description": description,
        "category": category,
        "image": image,
    }, None


@app.route("/owner/products/add", methods=["POST"])
@owner_required
def add_product():
    data, error = _parse_product_form()
    if error:
        flash(error, "error")
        return redirect(url_for("owner_products"))

    with get_db() as conn:
        conn.execute(
            "INSERT INTO products (name, price, description, image, category) VALUES (?,?,?,?,?)",
            (data["name"], data["price"], data["description"], data["image"], data["category"]),
        )
    flash(f"Product '{data['name']}' added.", "success")
    return redirect(url_for("owner_products"))


@app.route("/owner/products/edit/<int:product_id>", methods=["POST"])
@owner_required
def edit_product(product_id):
    data, error = _parse_product_form()
    if error:
        flash(error, "error")
        return redirect(url_for("owner_products"))

    active = 1 if request.form.get("active") == "on" else 0
    sold_out = 1 if request.form.get("sold_out") == "on" else 0

    with get_db() as conn:
        conn.execute(
            "UPDATE products SET name=?, price=?, description=?, image=?, category=?, active=?, sold_out=? WHERE id=?",
            (data["name"], data["price"], data["description"], data["image"], data["category"], active, sold_out, product_id),
        )
    flash(f"Product '{data['name']}' updated.", "success")
    return redirect(url_for("owner_products"))


@app.route("/owner/products/toggle_sold_out/<int:product_id>", methods=["POST"])
@owner_required
def toggle_sold_out(product_id):
    """
    Quick one-click toggle for the owner to mark an item as sold out /
    back in stock without opening the full edit form. Product stays
    active on the menu, just shown as unavailable to order.
    """
    with get_db() as conn:
        product = conn.execute(
            "SELECT name, sold_out FROM products WHERE id=?", (product_id,)
        ).fetchone()
        if not product:
            flash("Product not found.", "error")
            return redirect(url_for("owner_products"))

        new_state = 0 if product["sold_out"] else 1
        conn.execute(
            "UPDATE products SET sold_out=? WHERE id=?", (new_state, product_id)
        )

    if new_state:
        flash(f"{product['name']} marked as sold out.", "success")
    else:
        flash(f"{product['name']} marked as back in stock.", "success")
    return redirect(url_for("owner_products"))


@app.route("/owner/products/delete/<int:product_id>", methods=["POST"])
@owner_required
def delete_product(product_id):
    with get_db() as conn:
        product = conn.execute(
            "SELECT name FROM products WHERE id=?", (product_id,)
        ).fetchone()
        conn.execute("UPDATE products SET active=0 WHERE id=?", (product_id,))
    name = product["name"] if product else "Product"
    flash(f"{name} removed from menu.", "success")
    return redirect(url_for("owner_products"))


# ---------------------------------------------------------------------------
# Stripe result pages
# ---------------------------------------------------------------------------

@app.route("/success")
@login_required
def success():
    session_id = request.args.get("session_id")
    if not session_id:
        flash("Payment session is missing.", "error")
        return redirect(url_for("cart"))

    if not stripe.api_key:
        flash("Stripe is not configured.", "error")
        return redirect(url_for("cart"))

    try:
        stripe_session = stripe.checkout.Session.retrieve(
            session_id,
            expand=["line_items"],
        )
    except Exception:
        flash("Unable to verify payment session.", "error")
        return redirect(url_for("cart"))

    if stripe_session.payment_status != "paid":
        flash("Payment was not completed.", "error")
        return redirect(url_for("cart"))

    if str(stripe_session.client_reference_id) != str(session["user_id"]):
        flash("Payment session does not belong to your account.", "error")
        return redirect(url_for("cart"))

    with get_db() as conn:
        existing_order = conn.execute(
            "SELECT id FROM orders WHERE checkout_session_id=?",
            (session_id,),
        ).fetchone()

        if not existing_order:
            total = stripe_session.amount_total / 100.0 if stripe_session.amount_total else 0.0
            created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            notes = None
            if stripe_session.metadata:
                notes = stripe_session.metadata.get("notes") or None

            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO orders (user_id, status, total, notes, created_at, checkout_session_id) VALUES (?,?,?,?,?,?)",
                (session["user_id"], "Paid", total, notes, created_at, session_id),
            )
            order_id = cursor.lastrowid

            for item in stripe_session.line_items.data:
                product_name = item.description or item.price.product_data.name or "Item"
                unit_amount = (item.price.unit_amount or 0) / 100.0
                quantity = item.quantity or 1
                cursor.execute(
                    "INSERT INTO order_items (order_id, product_id, product_name, price, quantity) VALUES (?,?,?,?,?)",
                    (order_id, None, product_name, unit_amount, quantity),
                )

            conn.execute(
                "DELETE FROM cart_items WHERE user_id=?",
                (session["user_id"],),
            )

    return render_template("success.html")


@app.route("/cancel")
@login_required
def cancel():
    return render_template("cancel.html")


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", code=404, message="We couldn't find that page."), 404


@app.errorhandler(500)
def server_error(_error):
    return render_template("error.html", code=500, message="Something went wrong on our end. Please try again."), 500


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    app.run(debug=FLASK_DEBUG)
