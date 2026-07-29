# Ekasi Online Shopping

Online ordering app for Nkosana's Kota Shop — browse the menu, add items to your cart, and place orders from your phone or computer.

## Features

- Product menu with categories (Kota, Chips, Drinks)
- Search products on the home page
- User registration and login
- Cart with quantity controls and order totals
- Checkout with optional delivery notes
- Order tracking (Pending → Ready → Collected)
- Owner dashboard with order management
- Owner product management (add, edit, remove items)
- Mobile-friendly layout

## Setup

### 1. Clone and install dependencies

```bash
cd Ekasi-Online-Shopping
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

### 2. Configure environment (optional)

Copy `.env.example` to `.env` and update the values:

```bash
copy .env.example .env
```

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | Flask session secret (change in production) |
| `ADMIN_EMAIL` | Owner login email |
| `ADMIN_PASSWORD` | Owner login password |
| `FLASK_DEBUG` | Set to `false` when deploying |
| `DATABASE_PATH` | Path to SQLite database file |

### 3. Run the app

```bash
python app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser.

### Default owner account

On first run, an owner account is created automatically:

- Email: `owner@kotashop.com` (or your `ADMIN_EMAIL`)
- Password: `admin123` (or your `ADMIN_PASSWORD`)

**Change this password after first login.**

## Product images

Place product images in `static/images/`. Reference the filename when adding products in the owner dashboard (e.g. `kota.jpg`). If an image is missing, a placeholder is shown automatically.

## Order flow

1. Customer browses menu and adds items to cart
2. Customer confirms order at checkout → status **Pending**
3. Owner marks order **Ready** on the dashboard
4. Customer collects order → owner marks **Collected**

## Production notes

- Set `FLASK_DEBUG=false`
- Use a strong `SECRET_KEY`
- Run with a production WSGI server (e.g. Gunicorn)
- Change the default owner password

## Tech stack

- Python / Flask
- SQLite
- HTML / CSS (Jinja2 templates)
