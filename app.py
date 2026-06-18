from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "secret123"  # session key

# --- Database helper ---
def get_db():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    return conn

# --- Initialize database tables if not exist ---
def init_db():
    conn = get_db()
    cursor = conn.cursor()

    # Users table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        phone TEXT,
        password TEXT NOT NULL
    );
    """)

    # Orders table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        items TEXT NOT NULL,
        status TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    """)

    # --- Create default admin account if not exists ---
    admin_email = "owner@kotashop.com"
    admin_password = generate_password_hash("admin123")  # default password

    cursor.execute("SELECT * FROM users WHERE email=?", (admin_email,))
    existing_admin = cursor.fetchone()

    if not existing_admin:
        cursor.execute(
            "INSERT INTO users (name,email,phone,password) VALUES (?,?,?,?)",
            ("Shop Owner", admin_email, "0000000000", admin_password)
        )
        print("✅ Default admin account created: owner@kotashop.com / admin123")

    conn.commit()
    conn.close()

# --- Routes ---
@app.route("/")
def home():
    return render_template("Home.html")

@app.route("/kota")
def kota():
    return render_template("Kota.html")

@app.route("/chips")
def chips():
    return render_template("Chips.html")

@app.route("/cart")
def cart():
    if "user_id" not in session:
        return redirect(url_for("login"))
    conn = get_db()
    orders = conn.execute(
        "SELECT * FROM orders WHERE user_id=? AND status='Pending'",
        (session["user_id"],)
    ).fetchall()
    return render_template("Cart.html", orders=orders)

@app.route("/orders")
def orders():
    if "user_id" not in session:
        return redirect(url_for("login"))
    conn = get_db()
    orders = conn.execute(
        "SELECT * FROM orders WHERE user_id=?",
        (session["user_id"],)
    ).fetchall()
    return render_template("Orders.html", orders=orders)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()

        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            flash("Login successful!", "success")

            # Redirect admin straight to dashboard
            if user["email"] == "owner@kotashop.com":
                return redirect(url_for("owner_dashboard"))
            return redirect(url_for("orders"))
        else:
            flash("Invalid email or password", "error")
            return redirect(url_for("login"))

    return render_template("Login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        phone = request.form["phone"]
        password = request.form["password"]

        hashed_pw = generate_password_hash(password)

        conn = get_db()
        conn.execute(
            "INSERT INTO users (name,email,phone,password) VALUES (?,?,?,?)",
            (name, email, phone, hashed_pw)
        )
        conn.commit()
        flash("Account created successfully! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("Register.html")

@app.route("/place_order", methods=["POST"])
def place_order():
    if "user_id" not in session:
        return redirect(url_for("login"))
    items = request.form["items"]

    conn = get_db()
    conn.execute(
        "INSERT INTO orders (user_id,items,status) VALUES (?,?,?)",
        (session["user_id"], items, "Pending")
    )
    conn.commit()
    flash("Order placed successfully!", "success")
    return redirect(url_for("cart"))

@app.route("/cancel_order/<int:order_id>", methods=["POST"])
def cancel_order(order_id):
    if "user_id" not in session:
        return redirect(url_for("login"))
    conn = get_db()
    conn.execute(
        "UPDATE orders SET status='Cancelled' WHERE id=? AND user_id=?",
        (order_id, session["user_id"])
    )
    conn.commit()
    flash("Order cancelled.", "success")
    return redirect(url_for("orders"))

@app.route("/owner_dashboard")
def owner_dashboard():
    conn = get_db()
    orders = conn.execute("SELECT * FROM orders").fetchall()
    return render_template("OwnerDashboard.html", orders=orders)

@app.route("/mark_ready/<int:order_id>", methods=["POST"])
def mark_ready(order_id):
    conn = get_db()
    conn.execute("UPDATE orders SET status='Ready' WHERE id=?", (order_id,))
    conn.commit()
    flash("Order marked as ready.", "success")
    return redirect(url_for("owner_dashboard"))

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))

# --- Profile Route ---
@app.route("/profile", methods=["GET", "POST"])
def profile():
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()

    if request.method == "POST":
        # Password change
        if "current_password" in request.form:
            current_pw = request.form["current_password"]
            new_pw = request.form["new_password"]
            confirm_pw = request.form["confirm_password"]

            if not check_password_hash(user["password"], current_pw):
                flash("Current password is incorrect", "error")
                return redirect(url_for("profile"))

            if new_pw != confirm_pw:
                flash("New passwords do not match", "error")
                return redirect(url_for("profile"))

            hashed_pw = generate_password_hash(new_pw)
            conn.execute("UPDATE users SET password=? WHERE id=?", (hashed_pw, session["user_id"]))
            conn.commit()
            flash("Password updated successfully", "success")
            return redirect(url_for("profile"))

        # Profile update
        else:
            name = request.form["name"]
            email = request.form["email"]
            phone = request.form["phone"]

            conn.execute(
                "UPDATE users SET name=?, email=?, phone=? WHERE id=?",
                (name, email, phone, session["user_id"])
            )
            conn.commit()
            flash("Profile updated successfully", "success")
            return redirect(url_for("profile"))

    return render_template("Profile.html", user=user)

# --- Run the app ---
if __name__ == "__main__":
    init_db()  # ✅ Auto-create tables and admin account if missing
    app.run(debug=True)
