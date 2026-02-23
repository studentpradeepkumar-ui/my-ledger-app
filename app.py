import os
import io
import csv
import urllib.parse
from datetime import datetime, date

from flask import Flask, request, redirect, url_for, flash, send_file, render_template_string
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

# --------- SECRET KEY ---------
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")

# --------- DATABASE URL ---------
db_url = os.environ.get("DATABASE_URL")
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

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
    customers = db.relationship("Customer", backref="admin", lazy=True, cascade="all, delete-orphan")

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False) # LINKED TO ADMIN
    name = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(30), nullable=True)
    address = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    transactions = db.relationship("Transaction", backref="customer", lazy=True, cascade="all, delete-orphan")

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False)
    ttype = db.Column(db.String(20), nullable=False)  # CHARGE or PAYMENT
    amount = db.Column(db.Float, nullable=False)
    note = db.Column(db.String(255), nullable=True)
    ref_no = db.Column(db.String(100), nullable=True)  
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

# ---------------- Simple HTML ----------------
BASE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Manglam Online Services</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    .navbar-brand img { height: 40px; margin-right: 10px; border-radius: 5px; }
  </style>
</head>
<body class="bg-light">
<nav class="navbar navbar-dark bg-dark">
  <div class="container">
    <a class="navbar-brand d-flex align-items-center" href="{{ url_for('customers') }}">
      <img src="https://i.postimg.cc/rwVBbrCf/Chat-GPT-Image-Feb-23-2026-06-20-16-PM.png" alt="Manglam Logo">
      Manglam Online Services
    </a>
    {% if authed %}
      <div class="d-flex gap-2 align-items-center">
        <span class="text-light me-2">Welcome, {{ current_user.username }}</span>
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
    return render_template_string(BASE, body=body, authed=authed, current_user=current_user)

# ---------------- Setup/Login ----------------
@app.get("/setup")
def setup():
    body = """
    <div class="row justify-content-center">
      <div class="col-md-6 col-lg-5">
        <div class="card shadow-sm">
          <div class="card-body">
            <h4 class="mb-3">Register New Admin</h4>
            <form method="post">
              <div class="mb-3"><label class="form-label">Username</label><input class="form-control" name="username" required></div>
              <div class="mb-3"><label class="form-label">Password</label><input class="form-control" type="password" name="password" required></div>
              <button class="btn btn-primary w-100">Create Account</button>
            </form>
            <div class="mt-3"><a href="{{ url_for('login') }}">Already have an account? Login here</a></div>
          </div>
        </div>
      </div>
    </div>
    """
    return page(body)

@app.post("/setup")
def setup_post():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    if not username or not password:
        flash("Username and Password are required.", "danger")
        return redirect(url_for("setup"))
    if User.query.filter_by(username=username).first():
        flash("Username already exists. Choose another.", "danger")
        return redirect(url_for("setup"))
        
    u = User(username=username, password_hash=generate_password_hash(password))
    db.session.add(u)
    db.session.commit()
    flash("Account created! You can now log in.", "success")
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
              <div class="mb-3"><label class="form-label">Username</label><input class="form-control" name="username" required></div>
              <div class="mb-3"><label class="form-label">Password</label><input class="form-control" type="password" name="password" required></div>
              <button class="btn btn-primary w-100">Login</button>
            </form>
            <div class="mt-3"><a href="{{ url_for('setup') }}">Create a new Admin account</a></div>
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
        flash("Invalid username or password.", "danger")
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
    query = Customer.query.filter_by(user_id=current_user.id) # ONLY SHOW LOGGED IN USER'S CUSTOMERS
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
        rows.append(f'<tr><td>{c.id}</td><td>{c.name}</td><td>{c.phone or ""}</td><td>{badge}</td><td class="text-end"><a class="btn btn-sm btn-outline-primary" href="{url_for("customer_detail", customer_id=c.id)}">Open</a></td></tr>')

    body = f"""
    <div class="d-flex align-items-center justify-content-between mb-3">
      <h3 class="m-0">My Customers</h3>
      <a class="btn btn-success" href="{url_for('customer_add')}">+ Add Customer</a>
    </div>
    <form class="row g-2 mb-3" method="get">
      <div class="col-md-8"><input class="form-control" name="q" placeholder="Search: name / phone" value="{q}"></div>
      <div class="col-md-2"><button class="btn btn-primary w-100">Search</button></div>
      <div class="col-md-2"><a class="btn btn-outline-secondary w-100" href="{url_for('customers')}">Reset</a></div>
    </form>
    <div class="alert alert-info">Total Due (Your Customers): <strong>₹ {round(total_due,2)}</strong></div>
    <div class="card shadow-sm"><div class="table-responsive"><table class="table table-striped mb-0">
      <thead><tr><th>ID</th><th>Name</th><th>Phone</th><th>Balance/Due</th><th></th></tr></thead>
      <tbody>{''.join(rows) if rows else '<tr><td colspan="5" class="text-center text-muted py-4">No customers found</td></tr>'}</tbody>
    </table></div></div>
    """
    return page(body, authed=True)

@app.get("/customer/add")
@login_required
def customer_add():
    body = f"""
    <div class="card shadow-sm"><div class="card-body"><h4 class="mb-3">Add Customer</h4>
    <form method="post">
      <div class="mb-3"><label class="form-label">Name *</label><input class="form-control" name="name" required></div>
      <div class="mb-3"><label class="form-label">Phone</label><input class="form-control" name="phone"></div>
      <div class="mb-3"><label class="form-label">Address</label><input class="form-control" name="address"></div>
      <div class="d-flex gap-2"><button class="btn btn-primary">Create</button><a class="btn btn-outline-secondary" href="{url_for('customers')}">Back</a></div>
    </form></div></div>
    """
    return page(body, authed=True)

@app.post("/customer/add")
@login_required
def customer_add_post():
    name = request.form.get("name", "").strip()
    phone = request.form.get("phone", "").strip()
    address = request.form.get("address", "").strip()
    if not name:
        flash("Customer name is required.", "danger")
        return redirect(url_for("customer_add"))
    # LINK THE CUSTOMER TO THE CURRENT LOGGED-IN USER
    c = Customer(name=name, phone=phone or None, address=address or None, user_id=current_user.id)
    db.session.add(c)
    db.session.commit()
    flash("Customer added successfully.", "success")
    return redirect(url_for("customer_detail", customer_id=c.id))

@app.get("/customer/<int:customer_id>")
@login_required
def customer_detail(customer_id):
    # SECURITY: Ensure this customer belongs to the logged-in user
    c = Customer.query.filter_by(id=customer_id, user_id=current_user.id).first()
    if not c:
        flash("Customer not found or access denied.", "danger")
        return redirect(url_for("customers"))

    bal = customer_balance(c)
    badge = (f'<span class="badge text-bg-danger fs-6">Due: ₹ {bal}</span>' if bal > 0 else f'<span class="badge text-bg-success fs-6">Advance: ₹ {-bal}</span>' if bal < 0 else f'<span class="badge text-bg-secondary fs-6">Balanced: ₹ 0</span>')

    wa_btn = ""
    if bal > 0 and c.phone:
        phone_clean = ''.join(filter(str.isdigit, c.phone))
        if len(phone_clean) == 10: phone_clean = "91" + phone_clean
        msg = f"Namaste {c.name},\nManglam Online Services par aapka bakaya balance ₹ {bal} hai. Kripya samay par jama karein. \nDhanyawad!"
        wa_link = f"https://wa.me/{phone_clean}?text={urllib.parse.quote(msg)}"
        wa_btn = f'<a class="btn btn-sm btn-success ms-2" href="{wa_link}" target="_blank">📲 WhatsApp Karein</a>'

    txns_rb = running_balances(c.transactions)
    rows = []
    for t, rb in txns_rb:
        tbadge = '<span class="badge text-bg-warning">CHARGE</span>' if t.ttype == "CHARGE" else '<span class="badge text-bg-info">PAYMENT</span>'
        rows.append(f'<tr><td>{t.txn_date}</td><td>{tbadge}</td><td>₹ {t.amount:.2f}</td><td>{t.ref_no or ""}</td><td>{t.note or ""}</td><td>₹ {rb}</td><td class="text-end"><form method="post" action="{url_for("txn_delete", txn_id=t.id)}" onsubmit="return confirm(\'Delete this entry?\');"><button class="btn btn-sm btn-outline-danger">Delete</button></form></td></tr>')

    body = f"""
    <div class="d-flex align-items-center justify-content-between mb-3">
      <div><h3 class="m-0">{c.name}</h3><div class="text-muted">{c.phone or ""}{" | " + c.address if c.address else ""}</div></div>
      <div class="text-end"><div class="mb-2">{badge} {wa_btn}</div><a class="btn btn-sm btn-success" href="{url_for('txn_add', customer_id=c.id)}">+ Add Entry</a>
        <form class="d-inline" method="post" action="{url_for('customer_delete', customer_id=c.id)}" onsubmit="return confirm('Delete customer? All transactions will be deleted.');">
          <button class="btn btn-sm btn-outline-danger">Delete</button>
        </form>
      </div>
    </div>
    <div class="card shadow-sm"><div class="table-responsive"><table class="table table-striped mb-0">
      <thead><tr><th>Date</th><th>Type</th><th>Amount</th><th>Ref/App No</th><th>Note</th><th>Running Balance</th><th></th></tr></thead>
      <tbody>{''.join(rows) if rows else '<tr><td colspan="7" class="text-center text-muted py-4">No entries yet</td></tr>'}</tbody>
    </table></div></div>
    <div class="mt-3"><a class="btn btn-outline-secondary" href="{url_for('customers')}">Back</a></div>
    """
    return page(body, authed=True)

@app.post("/customer/<int:customer_id>/delete")
@login_required
def customer_delete(customer_id):
    c = Customer.query.filter_by(id=customer_id, user_id=current_user.id).first()
    if c:
        db.session.delete(c)
        db.session.commit()
        flash("Customer deleted.", "success")
    return redirect(url_for("customers"))

# ---------------- Transactions ----------------
@app.get("/customer/<int:customer_id>/txn/add")
@login_required
def txn_add(customer_id):
    c = Customer.query.filter_by(id=customer_id, user_id=current_user.id).first()
    if not c: return redirect(url_for("customers"))
    body = f"""
    <div class="card shadow-sm"><div class="card-body"><h4 class="mb-3">Add Entry - {c.name}</h4>
    <form method="post">
      <div class="row g-3">
        <div class="col-md-4"><label class="form-label">Type</label><select class="form-select" name="ttype" required><option value="CHARGE">CHARGE</option><option value="PAYMENT">PAYMENT</option></select></div>
        <div class="col-md-4"><label class="form-label">Amount (₹)</label><input class="form-control" name="amount" required></div>
        <div class="col-md-4"><label class="form-label">Date</label><input class="form-control" type="date" name="txn_date"></div>
        <div class="col-md-6"><label class="form-label">Ref/App No (optional)</label><input class="form-control" name="ref_no"></div>
        <div class="col-md-6"><label class="form-label">Note (optional)</label><input class="form-control" name="note"></div>
      </div>
      <div class="d-flex gap-2 mt-4"><button class="btn btn-primary">Save</button><a class="btn btn-outline-secondary" href="{url_for('customer_detail', customer_id=c.id)}">Back</a></div>
    </form></div></div>
    """
    return page(body, authed=True)

@app.post("/customer/<int:customer_id>/txn/add")
@login_required
def txn_add_post(customer_id):
    c = Customer.query.filter_by(id=customer_id, user_id=current_user.id).first()
    if not c: return redirect(url_for("customers"))
    try:
        amount = float(request.form.get("amount", ""))
        txn_date = datetime.strptime(request.form.get("txn_date", ""), "%Y-%m-%d").date() if request.form.get("txn_date") else date.today()
        t = Transaction(customer_id=c.id, ttype=request.form.get("ttype").strip().upper(), amount=amount, note=request.form.get("note"), ref_no=request.form.get("ref_no"), txn_date=txn_date)
        db.session.add(t)
        db.session.commit()
        flash("Entry added.", "success")
    except Exception:
        flash("Invalid input. Please check your data.", "danger")
    return redirect(url_for("customer_detail", customer_id=customer_id))

@app.post("/txn/<int:txn_id>/delete")
@login_required
def txn_delete(txn_id):
    t = db.session.get(Transaction, txn_id)
    if t and t.customer.user_id == current_user.id: # Security check
        c_id = t.customer_id
        db.session.delete(t)
        db.session.commit()
        flash("Transaction deleted.", "success")
        return redirect(url_for("customer_detail", customer_id=c_id))
    return redirect(url_for("customers"))

# ---------------- Export ----------------
@app.get("/export/customers.csv")
@login_required
def export_customers():
    customers_list = Customer.query.filter_by(user_id=current_user.id).order_by(Customer.created_at.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["CustomerID", "Name", "Phone", "Address", "Balance(Due)"])
    for c in customers_list: writer.writerow([c.id, c.name, c.phone or "", c.address or "", customer_balance(c)])
    mem = io.BytesIO()
    mem.write(output.getvalue().encode("utf-8-sig"))
    mem.seek(0)
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name="my_customers_ledger.csv")
