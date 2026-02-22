import os
import io
import csv
from datetime import datetime, date

from flask import Flask, request, redirect, url_for, flash, send_file, render_template_string
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

# --------- SECRET KEY ---------
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")

# --------- DATABASE URL (Postgres for online) ---------
db_url = os.environ.get("DATABASE_URL")
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

# Local test fallback: SQLite
app.config["SQLALCHEMY_DATABASE_URI"] = db_url or "sqlite:///ledger.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.init_app(app)

# ---------------- Models ----------------
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(30), nullable=True)
    address = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    transactions = db.relationship(
        "Transaction", backref="customer", lazy=True, cascade="all, delete-orphan"
    )

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False)
    ttype = db.Column(db.String(20), nullable=False)  # CHARGE or PAYMENT
    amount = db.Column(db.Float, nullable=False)
    note = db.Column(db.String(255), nullable=True)
    ref_no = db.Column(db.String(100), nullable=True)  # optional application/ref no
    txn_date = db.Column(db.Date, default=date.today, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

def customer_balance(c: Customer) -> float:
    charges = sum(t.amount for t in c.transactions if t.ttype == "CHARGE")
    payments = sum(t.amount for t in c.transactions if t.ttype == "PAYMENT")
    return round(charges - payments, 2)

def running_balances(transactions):
    txns = sorted(transactions, key=lambda x: (x.txn_date, x.id))
    bal = 0.0
    out = []
    for t in txns:
        bal += t.amount if t.ttype == "CHARGE" else -t.amount
        out.append((t, round(bal, 2)))
    return out

with app.app_context():
    db.create_all()

# ---------------- Simple HTML (Bootstrap) ----------------
BASE = """
<!doctype html>
<html lang="hi">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Customer Ledger</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light">
<nav class="navbar navbar-dark bg-dark">
  <div class="container">
    <a class="navbar-brand" href="{{ url_for('customers') }}">Customer Ledger</a>
    {% if authed %}
      <div class="d-flex gap-2">
        <a class="btn btn-outline-warning btn-sm" href="{{ url_for('export_customers') }}">Export CSV</a>
        <a class="btn btn-outline-danger btn-sm" href="{{ url_for('logout') }}">Logout</a>
      </div>
    {% endif %}
  </div>
</nav>
<div class="container py-4">
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      {% for category, msg in messages %}
        <div class="alert alert-{{category}}">{{ msg }}</div>
      {% endfor %}
    {% endif %}
  {% endwith %}
  {{ body|safe }}
</div>
</body>
</html>
"""

def page(body, authed=False):
    return render_template_string(BASE, body=body, authed=authed)

# ---------------- Setup/Login ----------------
@app.get("/setup")
def setup():
    if User.query.first():
        return redirect(url_for("login"))
    body = """
    <div class="row justify-content-center">
      <div class="col-md-6 col-lg-5">
        <div class="card shadow-sm">
          <div class="card-body">
            <h4 class="mb-3">First-time Setup (Admin)</h4>
            <form method="post">
              <div class="mb-3">
                <label class="form-label">Username</label>
                <input class="form-control" name="username" required>
              </div>
              <div class="mb-3">
                <label class="form-label">Password</label>
                <input class="form-control" type="password" name="password" required>
              </div>
              <button class="btn btn-primary w-100">Create Admin</button>
            </form>
            <p class="text-muted mt-3 mb-0">Setup सिर्फ 1 बार होगा।</p>
          </div>
        </div>
      </div>
    </div>
    """
    return page(body)

@app.post("/setup")
def setup_post():
    if User.query.first():
        return redirect(url_for("login"))
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    if not username or not password:
        flash("Username और Password दोनों जरूरी हैं।", "danger")
        return redirect(url_for("setup"))
    u = User(username=username, password_hash=generate_password_hash(password))
    db.session.add(u)
    db.session.commit()
    flash("Admin user बन गया। अब Login करें।", "success")
    return redirect(url_for("login"))

@app.get("/login")
def login():
    body = """
    <div class="row justify-content-center">
      <div class="col-md-6 col-lg-5">
        <div class="card shadow-sm">
          <div class="card-body">
            <h4 class="mb-3">Login</h4>
            <form method="post">
              <div class="mb-3">
                <label class="form-label">Username</label>
                <input class="form-control" name="username" required>
              </div>
              <div class="mb-3">
                <label class="form-label">Password</label>
                <input class="form-control" type="password" name="password" required>
              </div>
              <button class="btn btn-primary w-100">Login</button>
            </form>
            <div class="mt-3">
              <a href="{{ url_for('setup') }}">पहली बार use कर रहे हैं? Setup करें</a>
            </div>
          </div>
        </div>
      </div>
    </div>
    """
    return page(render_template_string(body), authed=False)

@app.post("/login")
def login_post():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    u = User.query.filter_by(username=username).first()
    if not u or not check_password_hash(u.password_hash, password):
        flash("गलत username/password", "danger")
        return redirect(url_for("login"))
    login_user(u)
    return redirect(url_for("customers"))

@app.get("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

# ---------------- Customers ----------------
@app.get("/")
@login_required
def home():
    return redirect(url_for("customers"))

@app.get("/customers")
@login_required
def customers():
    q = request.args.get("q", "").strip()
    query = Customer.query
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(Customer.name.ilike(like), Customer.phone.ilike(like)))
    customers_list = query.order_by(Customer.created_at.desc()).all()

    rows = []
    total_due = 0.0
    for c in customers_list:
        bal = customer_balance(c)
        total_due += bal
        badge = (
            f'<span class="badge text-bg-danger">₹ {bal}</span>' if bal > 0 else
            f'<span class="badge text-bg-success">Advance ₹ {-bal}</span>' if bal < 0 else
            f'<span class="badge text-bg-secondary">₹ 0</span>'
        )
        rows.append(f"""
        <tr>
          <td>{c.id}</td>
          <td>{c.name}</td>
          <td>{c.phone or ""}</td>
          <td>{badge}</td>
          <td class="text-end"><a class="btn btn-sm btn-outline-primary" href="{url_for('customer_detail', customer_id=c.id)}">Open</a></td>
        </tr>
        """)

    body = f"""
    <div class="d-flex align-items-center justify-content-between mb-3">
      <h3 class="m-0">Customers</h3>
      <a class="btn btn-success" href="{url_for('customer_add')}">+ Add Customer</a>
    </div>

    <form class="row g-2 mb-3" method="get">
      <div class="col-md-8">
        <input class="form-control" name="q" placeholder="Search: name / phone" value="{q}">
      </div>
      <div class="col-md-2"><button class="btn btn-primary w-100">Search</button></div>
      <div class="col-md-2"><a class="btn btn-outline-secondary w-100" href="{url_for('customers')}">Reset</a></div>
    </form>

    <div class="alert alert-info">Total Due (all customers): <strong>₹ {round(total_due,2)}</strong></div>

    <div class="card shadow-sm">
      <div class="table-responsive">
        <table class="table table-striped mb-0">
          <thead><tr><th>ID</th><th>Name</th><th>Phone</th><th>Balance/Due</th><th></th></tr></thead>
          <tbody>
            {''.join(rows) if rows else '<tr><td colspan="5" class="text-center text-muted py-4">No customers</td></tr>'}
          </tbody>
        </table>
      </div>
    </div>
    """
    return page(body, authed=True)

@app.get("/customer/add")
@login_required
def customer_add():
    body = f"""
    <div class="card shadow-sm">
      <div class="card-body">
        <h4 class="mb-3">Add Customer</h4>
        <form method="post">
          <div class="mb-3">
            <label class="form-label">Name *</label>
            <input class="form-control" name="name" required>
          </div>
          <div class="mb-3">
            <label class="form-label">Phone</label>
            <input class="form-control" name="phone">
          </div>
          <div class="mb-3">
            <label class="form-label">Address</label>
            <input class="form-control" name="address">
          </div>
          <div class="d-flex gap-2">
            <button class="btn btn-primary">Create</button>
            <a class="btn btn-outline-secondary" href="{url_for('customers')}">Back</a>
          </div>
        </form>
      </div>
    </div>
    """
    return page(body, authed=True)

@app.post("/customer/add")
@login_required
def customer_add_post():
    name = request.form.get("name", "").strip()
    phone = request.form.get("phone", "").strip()
    address = request.form.get("address", "").strip()
    if not name:
        flash("Customer name जरूरी है।", "danger")
        return redirect(url_for("customer_add"))
    c = Customer(name=name, phone=phone or None, address=address or None)
    db.session.add(c)
    db.session.commit()
    flash("Customer add हो गया।", "success")
    return redirect(url_for("customer_detail", customer_id=c.id))

@app.get("/customer/<int:customer_id>")
@login_required
def customer_detail(customer_id):
    c = db.session.get(Customer, customer_id)
    if not c:
        flash("Customer नहीं मिला।", "danger")
        return redirect(url_for("customers"))

    bal = customer_balance(c)
    badge = (
        f'<span class="badge text-bg-danger fs-6">Due: ₹ {bal}</span>' if bal > 0 else
        f'<span class="badge text-bg-success fs-6">Advance: ₹ {-bal}</span>' if bal < 0 else
        f'<span class="badge text-bg-secondary fs-6">Balanced: ₹ 0</span>'
    )

    txns_rb = running_balances(c.transactions)
    rows = []
    for t, rb in txns_rb:
        tbadge = '<span class="badge text-bg-warning">CHARGE</span>' if t.ttype == "CHARGE" else '<span class="badge text-bg-info">PAYMENT</span>'
        rows.append(f"""
        <tr>
          <td>{t.txn_date}</td>
          <td>{tbadge}</td>
          <td>₹ {t.amount:.2f}</td>
          <td>{t.ref_no or ""}</td>
          <td>{t.note or ""}</td>
          <td>₹ {rb}</td>
          <td class="text-end">
            <form method="post" action="{url_for('txn_delete', txn_id=t.id)}" onsubmit="return confirm('Delete this entry?');">
              <button class="btn btn-sm btn-outline-danger">Delete</button>
            </form>
          </td>
        </tr>
        """)

    body = f"""
    <div class="d-flex align-items-center justify-content-between mb-3">
      <div>
        <h3 class="m-0">{c.name}</h3>
        <div class="text-muted">{c.phone or ""}{" | " + c.address if c.address else ""}</div>
      </div>
      <div class="text-end">
        <div class="mb-2">{badge}</div>
        <a class="btn btn-sm btn-success" href="{url_for('txn_add', customer_id=c.id)}">+ Add Entry</a>
        <form class="d-inline" method="post" action="{url_for('customer_delete', customer_id=c.id)}" onsubmit="return confirm('Delete customer? All transactions will be deleted.');">
          <button class="btn btn-sm btn-outline-danger">Delete</button>
        </form>
      </div>
    </div>

    <div class="card shadow-sm">
      <div class="table-responsive">
        <table class="table table-striped mb-0">
          <thead><tr><th>Date</th><th>Type</th><th>Amount</th><th>Ref/Application No</th><th>Note</th><th>Running Balance</th><th></th></tr></thead>
          <tbody>
            {''.join(rows) if rows else '<tr><td colspan="7" class="text-center text-muted py-4">No entries yet</td></tr>'}
          </tbody>
        </table>
      </div>
    </div>
    <div class="mt-3"><a class="btn btn-outline-secondary" href="{url_for('customers')}">Back</a></div>
    """
    return page(body, authed=True)

@app.post("/customer/<int:customer_id>/delete")
@login_required
def customer_delete(customer_id):
    c = db.session.get(Customer, customer_id)
    if not c:
        flash("Customer नहीं मिला।", "danger")
        return redirect(url_for("customers"))
    db.session.delete(c)
    db.session.commit()
    flash("Customer delete हो गया।", "success")
    return redirect(url_for("customers"))

# ---------------- Transactions ----------------
@app.get("/customer/<int:customer_id>/txn/add")
@login_required
def txn_add(customer_id):
    c = db.session.get(Customer, customer_id)
    if not c:
        flash("Customer नहीं मिला।", "danger")
        return redirect(url_for("customers"))
    body = f"""
    <div class="card shadow-sm">
      <div class="card-body">
        <h4 class="mb-3">Add Entry - {c.name}</h4>
        <form method="post">
          <div class="row g-3">
            <div class="col-md-4">
              <label class="form-label">Type</label>
              <select class="form-select" name="ttype" required>
                <option value="CHARGE">CHARGE (काम/उधार)</option>
                <option value="PAYMENT">PAYMENT (जमा)</option>
              </select>
            </div>
            <div class="col-md-4">
              <label class="form-label">Amount (₹)</label>
              <input class="form-control" name="amount" placeholder="e.g. 500" required>
            </div>
            <div class="col-md-4">
              <label class="form-label">Date</label>
              <input class="form-control" type="date" name="txn_date">
            </div>
            <div class="col-md-6">
              <label class="form-label">Ref / Application No (optional)</label>
              <input class="form-control" name="ref_no" placeholder="e.g. ED123456">
            </div>
            <div class="col-md-6">
              <label class="form-label">Note (optional)</label>
              <input class="form-control" name="note" placeholder="e.g. Pan card correction fee">
            </div>
          </div>
          <div class="d-flex gap-2 mt-4">
            <button class="btn btn-primary">Save</button>
            <a class="btn btn-outline-secondary" href="{url_for('customer_detail', customer_id=c.id)}">Back</a>
          </div>
        </form>
      </div>
    </div>
    """
    return page(body, authed=True)

@app.post("/customer/<int:customer_id>/txn/add")
@login_required
def txn_add_post(customer_id):
    c = db.session.get(Customer, customer_id)
    if not c:
        flash("Customer नहीं मिला।", "danger")
        return redirect(url_for("customers"))

    ttype = request.form.get("ttype", "").strip().upper()
    amount_raw = request.form.get("amount", "").strip()
    note = request.form.get("note", "").strip()
    ref_no = request.form.get("ref_no", "").strip()
    date_raw = request.form.get("txn_date", "").strip()

    if ttype not in {"CHARGE", "PAYMENT"}:
        flash("Type गलत है।", "danger")
        return redirect(url_for("txn_add", customer_id=customer_id))

    try:
        amount = float(amount_raw)
        if amount <= 0:
            raise ValueError()
    except Exception:
        flash("Amount सही डालें (positive number).", "danger")
        return redirect(url_for("txn_add", customer_id=customer_id))

    try:
        txn_date = datetime.strptime(date_raw, "%Y-%m-%d").date() if date_raw else date.today()
    except Exception:
        flash("Date format गलत है।", "danger")
        return redirect(url_for("txn_add", customer_id=customer_id))

    t = Transaction(
        customer_id=customer_id,
        ttype=ttype,
        amount=amount,
        note=note or None,
        ref_no=ref_no or None,
        txn_date=txn_date,
    )
    db.session.add(t)
    db.session.commit()
    flash("Entry add हो गई।", "success")
    return redirect(url_for("customer_detail", customer_id=customer_id))

@app.post("/txn/<int:txn_id>/delete")
@login_required
def txn_delete(txn_id):
    t = db.session.get(Transaction, txn_id)
    if not t:
        flash("Transaction नहीं मिला।", "danger")
        return redirect(url_for("customers"))
    customer_id = t.customer_id
    db.session.delete(t)
    db.session.commit()
    flash("Transaction delete हो गई।", "success")
    return redirect(url_for("customer_detail", customer_id=customer_id))

# ---------------- Export ----------------
@app.get("/export/customers.csv")
@login_required
def export_customers():
    customers_list = Customer.query.order_by(Customer.created_at.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["CustomerID", "Name", "Phone", "Address", "Balance(Due)"])
    for c in customers_list:
        writer.writerow([c.id, c.name, c.phone or "", c.address or "", customer_balance(c)])
    mem = io.BytesIO()
    mem.write(output.getvalue().encode("utf-8-sig"))
    mem.seek(0)
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name="customers_ledger.csv")