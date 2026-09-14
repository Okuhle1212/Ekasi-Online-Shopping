# Ekasi Online Shopping

Online ordering app for local township food vendors — browse the menu, add items to your cart, and place orders from your phone or computer.

## Features

- Product menu with categories (Kota, Chips, Home/Drinks)
- Site-wide search from the home page
- User registration and login, with session-based auth
- Cart with quantity controls and live order totals
- Checkout with optional notes for the shop, and two payment options:
  - **Pay with Card** (via Stripe Checkout)
  - **Pay on Collection** (order now, pay in person)
- Order tracking (Pending/Paid → Ready → Collected), with the ability to
  cancel an order while it's still awaiting prep
- Owner dashboard with live order counts, active order management, and
  order history (including cancelled orders)
- Owner sales dashboard with daily/weekly/monthly revenue and top-selling products
- Owner product management (add, edit, deactivate items, mark sold out)
- CSRF protection on all forms
- Mobile-friendly layout

## Setup

### 1. Clone and install dependencies

```bash
cd Ekasi-Online-Shopping
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # macOS/Linux
pip install -r requirements.txt
```

### 2. Configure environment (optional but recommended)

Copy `.env.example` to `.env` and update the values:

```bash
copy .env.example .env       # Windows
cp .env.example .env         # macOS/Linux
```

| Variable            | Description                                                        |
|---------------------|----------------------------------------------------------------------|
| `SECRET_KEY`        | Flask session secret (change in production)                        |
| `ADMIN_EMAIL`       | Owner login email                                                   |
| `ADMIN_PASSWORD`    | Owner login password                                                |
| `FLASK_DEBUG`       | Set to `false` when deploying                                       |
| `DATABASE_PATH`     | Path to SQLite database file                                        |
| `STRIPE_SECRET_KEY` | Your Stripe secret key. Leave blank to disable card payments — "Pay on Collection" still works without it |

If `python-dotenv` isn't installed, either `pip install python-dotenv` and
load it at the top of `app.py`, or just set these as real environment
variables before running the app.

### 3. Run the app

```bash
python app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser.

### Default owner account

On first run, an owner account is created automatically:

- Email: `owner@kotashop.com` (or your `ADMIN_EMAIL`)
- Password: `admin123` (or your `ADMIN_PASSWORD`)

**Change this password after first login** (Profile → Change Password).

## Product images

Place product images in `static/images/`. Reference the filename when
adding products in the owner dashboard (e.g. `kota.jpg`). If an image is
missing, `placeholder.svg` is shown automatically.

## Order flow

1. Customer browses the menu and adds items to the cart.
2. At checkout, the customer chooses **Pay with Card** or **Pay on
   Collection**, with an optional note for the shop.
   - Card payments create the order as **Paid** once Stripe confirms
     payment.
   - Pay-on-collection orders are created as **Pending**.
3. The owner sees both in **Active Orders** and marks the order **Ready**
   once it's prepared.
4. The customer collects the order; the owner marks it **Collected**.
5. Pending orders can be self-cancelled by the customer before the shop
   starts preparing them.

## Security notes

- All state-changing requests (POST forms) are protected with a
  session-bound CSRF token.
- Passwords are hashed with Werkzeug's `generate_password_hash`.
- Session cookies are `HttpOnly`, `SameSite=Lax`, and `Secure` when
  `FLASK_DEBUG=false`.
- Server-side validation exists for prices, quantities, and required
  fields so malformed input can't crash the app.

## Production notes

- Set `FLASK_DEBUG=false`
- Use a strong, random `SECRET_KEY`
- Run with a production WSGI server (e.g. Gunicorn) behind HTTPS
- Change the default owner password
- Set a real `STRIPE_SECRET_KEY` if you want card payments enabled

## Tech stack

- Python / Flask
- SQLite
- HTML / CSS (Jinja2 templates)
