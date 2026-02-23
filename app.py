import os
import io
import csv
import urllib.parse
from datetime import datetime, date

from flask import Flask, request, redirect, url_for, flash, send_file, render_template_string, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

# ==========================================
# 🛑 यहाँ अपनी दुकान की डिटेल्स डालें 🛑
# ==========================================
SHOP_UPI_ID = "9415712175@ybl"  # उदाहरण: 9876543210@paytm या okicici
SHOP_WHATSAPP = "919415712175"              # अपना WhatsApp नंबर डालें (शुरुआत में 91 जरूर लगाएं)
# ==========================================

# --------- SECRET KEY & DB ---------
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
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
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    name = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(30), nullable=False) 
    pin = db.Column(db.String(10), nullable=False, default="1234") 
    address = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    transactions = db.relationship("Transaction", backref="customer", lazy=True, cascade="all, delete-orphan")

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False)
    total_amount = db.Column(db.Float, nullable=False, default=0.0) 
    paid_amount = db.Column(db.Float, nullable=False, default=0.0)  
    note = db.Column(db.String(255), nullable=True)                 
    ref_no = db.Column(db.String(100), nullable=True)  
    tracking_url = db.Column(db.String(500), nullable=True) 
    txn_date = db.Column(db.Date, default=date.today, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

def customer_balance(c: Customer) -> float:
    total_billed = sum(t.total_amount for t in c.transactions)
    total_paid = sum(t.paid_amount for t in c.transactions)
    return round(total_billed - total_paid, 2)

def running_balances(transactions):
    txns = sorted(transactions, key=lambda x: (x.txn_date, x.id))
    bal = 0.0
    out = []
    for t in txns:
        entry_due = t.total_amount - t.paid_amount
        bal += entry_due
        out.append((t, entry_due, round(bal, 2)))
    return out

with app.app_context():
    db.create_all()

# ---------------- Simple HTML ----------------
BASE = """
<!doctype html>
<html lang="hi">
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
    <a class="navbar-brand d-flex align-items-center" href="/">
      <img src="https://i.postimg.cc/placeholder-logo.png" alt="Manglam Logo">
      Manglam Online Services
    </a>
    <div class="d-flex gap-2 align-items-center">
      {% if current_user.is_authenticated %}
        <a class="btn btn-info btn-sm text-white fw-bold" href="{{ url_for('daily_report') }}">📈 Daily Report</a>
        <a class="btn btn-outline-warning btn-sm" href="{{ url_for('export_customers') }}">Export CSV</a>
        <a class="btn btn-outline-danger btn-sm" href="{{ url_for('logout') }}">Logout</a>
      {% elif session.get('customer_id') %}
        <span class="text-light me-2 d-none d-md-inline">Customer Portal</span>
        <a class="btn btn-outline-danger btn-sm" href="{{ url_for('portal_logout') }}">Logout</a>
      {% endif %}
    </div>
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

def page(body):
    return render_template_string(BASE, body=body, current_user=current_user, session=session)

@app.get("/force-reset-db")
def force_reset_db():
    db.drop_all()
    db.create_all()
    return "<h3>✅ Database Successfully Reset!</h3><p>Your 500 Error is fixed. <a href='/setup'>Click here to create your Admin account again.</a></p>"

# ---------------- Daily Report ----------------
@app.get("/report")
@login_required
def daily_report():
    today = date.today()
    customers = Customer.query.filter_by(user_id=current_user.id).all()
    customer_ids = [c.id for c in customers]
    today_txns = Transaction.query.filter(Transaction.customer_id.in_(customer_ids), Transaction.txn_date == today).all()
    
    total_kaam = sum(t.total_amount for t in today_txns)
    total_cash_aaya = sum(t.paid_amount for t in today_txns)
    total_udhar_aaj = total_kaam - total_cash_aaya
    
    body = f"""
    <div class="card shadow-sm border-info mb-4">
      <div class="card-header bg-info text-white"><h4 class="mb-0">📈 आज की रिपोर्ट ({today.strftime('%d-%m-%Y')})</h4></div>
      <div class="card-body text-center">
        <div class="row">
          <div class="col-md-4"><h5 class="text-muted">कुल काम हुआ</h5><h2 class="text-primary">₹ {total_kaam:.2f}</h2></div>
          <div class="col-md-4"><h5 class="text-muted">आज कैश/ऑनलाइन आया</h5><h2 class="text-success">₹ {total_cash_aaya:.2f}</h2></div>
          <div class="col-md-4"><h5 class="text-muted">आज का उधार</h5><h2 class="text-danger">₹ {total_udhar_aaj:.2f}</h2></div>
        </div>
      </div>
    </div>
    <a class="btn btn-outline-secondary" href="{url_for('customers')}">Back to Dashboard</a>
    """
    return page(body)

# ---------------- Setup/Login (Admin) ----------------
@app.get("/setup")
def setup():
    body = """
    <div class="row justify-content-center"><div class="col-md-6 col-lg-5"><div class="card shadow-sm"><div class="card-body">
      <h4 class="mb-3">Register New Admin</h4>
      <form method="post">
        <div class="mb-3"><label class="form-label">Username</label><input class="form-control" name="username" required></div>
        <div class="mb-3"><label class="form-label">Password</label><input class="form-control" type="password" name="password" required></div>
        <button class="btn btn-primary w-100">Create Account</button>
      </form>
      <div class="mt-3"><a href="{{ url_for('login') }}">Already have an account? Login here</a></div>
    </div></div></div></div>
    """
    return page(body)

@app.post("/setup")
def setup_post():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    if User.query.filter_by(username=username).first():
        flash("Username already exists.", "danger")
        return redirect(url_for("setup"))
    u = User(username=username, password_hash=generate_password_hash(password))
    db.session.add(u)
    db.session.commit()
    flash("Account created! Log in below.", "success")
    return redirect(url_for("login"))

@app.get("/login")
def login():
    body = """
    <div class="row justify-content-center"><div class="col-md-6 col-lg-5">
      <div class="card shadow-sm mb-4"><div class="card-body">
        <h4 class="mb-3">Admin Login</h4>
        <form method="post">
          <div class="mb-3"><label class="form-label">Username</label><input class="form-control" name="username" required></div>
          <div class="mb-3"><label class="form-label">Password</label><input class="form-control" type="password" name="password" required></div>
          <button class="btn btn-primary w-100">Admin Login</button>
        </form>
        <div class="mt-3"><a href="{{ url_for('setup') }}">Create Admin Account</a></div>
      </div></div>
      <div class="card shadow-sm bg-primary text-white"><div class="card-body text-center">
        <h5>Are you a Customer?</h5>
        <p class="mb-2">अपना बकाया बिल और खाते की जानकारी देखें।</p>
        <a href="{{ url_for('portal_login') }}" class="btn btn-light w-100 fw-bold">Customer Login</a>
      </div></div>
    </div></div>
    """
    return page(body)

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

# ---------------- Customer Portal ----------------
@app.route("/portal/login", methods=["GET", "POST"])
def portal_login():
    if request.method == "POST":
        phone = request.form.get("phone", "").strip()
        pin = request.form.get("pin", "").strip()
        c = Customer.query.filter_by(phone=phone, pin=pin).first()
        if c:
            session['customer_id'] = c.id
            return redirect(url_for("portal_dashboard"))
        else:
            flash("Invalid Mobile Number or PIN. Please ask shop owner.", "danger")
    body = """
    <div class="row justify-content-center"><div class="col-md-6 col-lg-5"><div class="card shadow-sm border-primary"><div class="card-body">
      <h4 class="mb-3 text-primary text-center">Customer Portal Login</h4>
      <form method="post">
        <div class="mb-3"><label class="form-label">Mobile Number</label><input class="form-control" name="phone" placeholder="e.g. 9876543210" required></div>
        <div class="mb-3"><label class="form-label">4-Digit PIN</label><input class="form-control" type="password" name="pin" placeholder="Default is usually 1234" required></div>
        <button class="btn btn-primary w-100 fw-bold">View My Khata</button>
      </form>
      <div class="mt-3 text-center"><a href="{{ url_for('login') }}">Back to Admin Login</a></div>
    </div></div></div></div>
    """
    return page(body)

@app.get("/portal")
def portal_dashboard():
    c_id = session.get("customer_id")
    if not c_id: return redirect(url_for("portal_login"))
    c = db.session.get(Customer, c_id)
    if not c:
        session.pop("customer_id", None)
        return redirect(url_for("portal_login"))

    bal = customer_balance(c)
    
    # --- ONLINE PAYMENT BUTTON LOGIC ---
    pay_btn = ""
    if bal > 0:
        # Generate UPI Link
        upi_link = f"upi://pay?pa={SHOP_UPI_ID}&pn=Manglam%20Online%20Services&am={bal}&cu=INR"
        pay_btn = f'<a href="{upi_link}" class="btn btn-success fw-bold px-4 py-2 mt-2 shadow-sm"><img src="https://upload.wikimedia.org/wikipedia/commons/e/e1/UPI-Logo-vector.svg" height="20" class="me-2"> Pay ₹{bal} Online</a>'
        badge = f'<span class="badge text-bg-danger fs-5">Amount Due: ₹ {bal}</span><br>{pay_btn}'
    elif bal < 0:
        badge = f'<span class="badge text-bg-success fs-5">Advance: ₹ {-bal}</span>'
    else:
        badge = f'<span class="badge text-bg-secondary fs-5">Balanced: ₹ 0</span>'

    # --- UPLOAD DOCS / NEW WORK LOGIC ---
    doc_msg = urllib.parse.quote(f"नमस्ते मंगलम ऑनलाइन, मैं {c.name} हूँ। मुझे एक नया काम कराना है। मैं अपने डाक्यूमेंट्स (आधार/फोटो) भेज रहा/रही हूँ।")
    doc_link = f"https://wa.me/{SHOP_WHATSAPP}?text={doc_msg}"
    doc_btn = f'<a href="{doc_link}" target="_blank" class="btn btn-outline-primary fw-bold mt-3"><span style="font-size:1.2rem;">📝</span> नया काम दें & डाक्यूमेंट्स (Aadhaar/Photo) अपलोड करें</a>'

    txns_rb = running_balances(c.transactions)
    rows = []
    for t, entry_due, rb in txns_rb:
        ref_display = t.ref_no or "-"
        if t.ref_no and t.tracking_url:
            ref_display = f'<a href="{t.tracking_url}" target="_blank" class="text-primary fw-bold" title="Click to Track Status">{t.ref_no} 🔗</a>'
        rows.append(f'<tr><td>{t.txn_date}</td><td>{t.note or "-"}</td><td>{ref_display}</td><td>₹ {t.total_amount:.2f}</td><td class="text-success">₹ {t.paid_amount:.2f}</td><td class="text-danger">₹ {entry_due:.2f}</td><td><strong>₹ {rb}</strong></td></tr>')

    body = f"""
    <div class="card shadow-sm mb-4 bg-light border-0">
      <div class="card-body text-center">
        <h2 class="mb-1">Namaste, {c.name}</h2>
        <p class="text-muted mb-3">Shop: {c.admin.username}</p>
        <div class="mb-3">{badge}</div>
        <div>{doc_btn}</div>
      </div>
    </div>
    <h4 class="mb-3">Your Transaction History</h4>
    <div class="card shadow-sm"><div class="table-responsive"><table class="table table-striped mb-0">
      <thead><tr><th>Date</th><th>Work Done</th><th>Ref No (Status)</th><th>Total Bill</th><th>Paid</th><th>Entry Due</th><th>Total Balance</th></tr></thead>
      <tbody>{''.join(rows) if rows else '<tr><td colspan="7" class="text-center text-muted py-4">No transactions yet</td></tr>'}</tbody>
    </table></div></div>
    """
    return page(body)

@app.get("/portal/logout")
def portal_logout():
    session.pop("customer_id", None)
    return redirect(url_for("portal_login"))

# ---------------- Admin Customers ----------------
@app.get("/")
def home():
    if current_user.is_authenticated: return redirect(url_for("customers"))
    if session.get('customer_id'): return redirect(url_for("portal_dashboard"))
    return redirect(url_for("login"))

@app.get("/customers")
@login_required
def customers():
    q = request.args.get("q", "").strip()
    query = Customer.query.filter_by(user_id=current_user.id)
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(Customer.name.ilike(like), Customer.phone.ilike(like)))
    customers_list = query.order_by(Customer.created_at.desc()).all()

    rows = []
    total_due = 0.0
    for c in customers_list:
        bal = customer_balance(c)
        total_due += bal
        badge = (f'<span class="badge text-bg-danger">₹ {bal}</span>' if bal > 0 else f'<span class="badge text-bg-success">Advance ₹ {-bal}</span>' if bal < 0 else f'<span class="badge text-bg-secondary">₹ 0</span>')
        rows.append(f'<tr><td>{c.name}</td><td>{c.phone}</td><td>{badge}</td><td class="text-end"><a class="btn btn-sm btn-outline-primary" href="{url_for("customer_detail", customer_id=c.id)}">Open</a></td></tr>')

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
    <div class="alert alert-info">Total Market Due: <strong>₹ {round(total_due,2)}</strong></div>
    <div class="card shadow-sm"><div class="table-responsive"><table class="table table-striped mb-0">
      <thead><tr><th>Name</th><th>Phone</th><th>Balance/Due</th><th></th></tr></thead>
      <tbody>{''.join(rows) if rows else '<tr><td colspan="4" class="text-center text-muted py-4">No customers found</td></tr>'}</tbody>
    </table></div></div>
    """
    return page(body)

@app.get("/customer/add")
@login_required
def customer_add():
    body = f"""
    <div class="card shadow-sm"><div class="card-body"><h4 class="mb-3">Add Customer</h4>
    <form method="post">
      <div class="mb-3"><label class="form-label">Name *</label><input class="form-control" name="name" required></div>
      <div class="mb-3"><label class="form-label">Phone (Login ID) *</label><input class="form-control" name="phone" required></div>
      <div class="mb-3"><label class="form-label">4-Digit PIN (For Customer Login) *</label><input class="form-control" name="pin" value="1234" required></div>
      <div class="mb-3"><label class="form-label">Address</label><input class="form-control" name="address"></div>
      <div class="d-flex gap-2"><button class="btn btn-primary">Create</button><a class="btn btn-outline-secondary" href="{url_for('customers')}">Back</a></div>
    </form></div></div>
    """
    return page(body)

@app.post("/customer/add")
@login_required
def customer_add_post():
    name = request.form.get("name", "").strip()
    phone = request.form.get("phone", "").strip()
    pin = request.form.get("pin", "1234").strip()
    address = request.form.get("address", "").strip()
    if not name or not phone:
        flash("Name and Phone are required.", "danger")
        return redirect(url_for("customer_add"))
    c = Customer(name=name, phone=phone, pin=pin, address=address or None, user_id=current_user.id)
    db.session.add(c)
    db.session.commit()
    flash("Customer added successfully.", "success")
    return redirect(url_for("customer_detail", customer_id=c.id))

@app.get("/customer/<int:customer_id>")
@login_required
def customer_detail(customer_id):
    c = Customer.query.filter_by(id=customer_id, user_id=current_user.id).first()
    if not c: return redirect(url_for("customers"))

    bal = customer_balance(c)
    badge = (f'<span class="badge text-bg-danger fs-6">Due: ₹ {bal}</span>' if bal > 0 else f'<span class="badge text-bg-success fs-6">Advance: ₹ {-bal}</span>' if bal < 0 else f'<span class="badge text-bg-secondary fs-6">Balanced: ₹ 0</span>')

    phone_clean = ""
    if c.phone:
        phone_clean = ''.join(filter(str.isdigit, c.phone))
        if len(phone_clean) == 10: phone_clean = "91" + phone_clean

    wa_btn = ""
    if bal > 0 and phone_clean:
        msg = f"नमस्ते {c.name} जी,\n\nमंगलम ऑनलाइन सर्विसेज पर आने के लिए आपका बहुत-बहुत धन्यवाद। 🙏\n\nआपके खाते की कुल बकाया राशि: *₹{bal}* है।\n\nआप नीचे दिए गए लिंक पर अपना पिन डालकर अपना पूरा खाता चेक कर सकते हैं और वहीं से ऑनलाइन पेमेंट भी कर सकते हैं:\n🔗 लिंक: {request.host_url}portal/login\n🔐 आपका पिन (PIN): {c.pin}\n\nकृपया समय पर भुगतान करें।\n\nधन्यवाद,\n*मंगलम ऑनलाइन सर्विसेज*"
        wa_link = f"https://wa.me/{phone_clean}?text={urllib.parse.quote(msg)}"
        wa_btn = f'<a class="btn btn-sm btn-success ms-2" href="{wa_link}" target="_blank">📲 Send Total Due</a>'

    txns_rb = running_balances(c.transactions)
    rows = []
    for t, entry_due, rb in txns_rb:
        entry_wa_btn = ""
        if phone_clean:
            entry_msg = f"नमस्ते {c.name} जी,\n\nमंगलम ऑनलाइन सर्विसेज पर आने के लिए आपका बहुत-बहुत धन्यवाद। 🙏\n\nआपका कार्य सफलतापूर्वक कर दिया गया है। कार्य का विवरण:\n\n📝 *कार्य (Work):* {t.note or 'N/A'}\n🧾 *कुल बिल (Total Bill):* ₹{t.total_amount}\n✅ *जमा राशि (Paid):* ₹{t.paid_amount}\n⏳ *इस कार्य का बकाया (Due):* ₹{entry_due}\n🔖 *रेफरेंस नंबर (Ref No):* {t.ref_no or 'N/A'}"
            if t.tracking_url:
                entry_msg += f"\n🌐 *स्टेटस चेक करें:* {t.tracking_url}"
            entry_msg += f"\n\n📊 *आपका कुल बकाया (Total Balance):* ₹{rb}\n\nअपना पूरा खाता यहाँ देखें और ऑनलाइन पेमेंट करें:\n🔗 लिंक: {request.host_url}portal/login\n🔐 आपका पिन: {c.pin}\n\nधन्यवाद,\n*मंगलम ऑनलाइन सर्विसेज*"
            e_wa_link = f"https://wa.me/{phone_clean}?text={urllib.parse.quote(entry_msg)}"
            entry_wa_btn = f'<a class="btn btn-sm btn-outline-success mt-1 w-100" href="{e_wa_link}" target="_blank">📲 WhatsApp Slip</a>'
            
        ref_display = t.ref_no or "-"
        if t.ref_no and t.tracking_url:
            ref_display = f'<a href="{t.tracking_url}" target="_blank" title="Check Status">{t.ref_no}</a>'
            
        rows.append(f'<tr><td>{t.txn_date}</td><td>{t.note or "-"}</td><td>{ref_display}</td><td>₹ {t.total_amount:.2f}</td><td class="text-success">₹ {t.paid_amount:.2f}</td><td class="text-danger">₹ {entry_due:.2f}</td><td><strong>₹ {rb}</strong></td><td class="text-end"><form method="post" action="{url_for("txn_delete", txn_id=t.id)}" onsubmit="return confirm(\'Delete this entry?\');"><button class="btn btn-sm btn-outline-danger w-100">Del</button></form>{entry_wa_btn}</td></tr>')

    body = f"""
    <div class="d-flex align-items-center justify-content-between mb-3">
      <div>
        <h3 class="m-0">{c.name}</h3>
        <div class="text-muted">Phone: {c.phone} | PIN: <strong>{c.pin}</strong></div>
      </div>
      <div class="text-end"><div class="mb-2">{badge} {wa_btn}</div><a class="btn btn-sm btn-primary" href="{url_for('txn_add', customer_id=c.id)}">+ Add Entry / Work</a></div>
    </div>
    <div class="card shadow-sm"><div class="table-responsive"><table class="table table-striped align-middle mb-0">
      <thead><tr><th>Date</th><th>Work Done</th><th>Ref No (Status)</th><th>Total Bill</th><th>Paid</th><th>Due</th><th>Total Balance</th><th>Actions</th></tr></thead>
      <tbody>{''.join(rows) if rows else '<tr><td colspan="8" class="text-center text-muted py-4">No entries yet</td></tr>'}</tbody>
    </table></div></div>
    <div class="mt-3"><a class="btn btn-outline-secondary" href="{url_for('customers')}">Back</a></div>
    """
    return page(body)

@app.post("/customer/<int:customer_id>/delete")
@login_required
def customer_delete(customer_id):
    c = Customer.query.filter_by(id=customer_id, user_id=current_user.id).first()
    if c:
        db.session.delete(c)
        db.session.commit()
    return redirect(url_for("customers"))

@app.get("/customer/<int:customer_id>/txn/add")
@login_required
def txn_add(customer_id):
    c = Customer.query.filter_by(id=customer_id, user_id=current_user.id).first()
    if not c: return redirect(url_for("customers"))
    body = f"""
    <div class="card shadow-sm"><div class="card-body"><h4 class="mb-3">Add Entry - {c.name}</h4>
    <form method="post">
      <div class="row g-3">
        <div class="col-md-12"><label class="form-label">Work Done (क्या काम कराया?)</label><input class="form-control" name="note" placeholder="e.g. Pan Card Apply" required></div>
        <div class="col-md-6"><label class="form-label text-danger">Total Bill (कुल बिल ₹) *</label><input class="form-control" name="total_amount" value="0" required></div>
        <div class="col-md-6"><label class="form-label text-success">Amount Paid (कितना जमा किया ₹) *</label><input class="form-control" name="paid_amount" value="0" required></div>
        <div class="col-md-6"><label class="form-label">Reference / App No (Optional)</label><input class="form-control" name="ref_no" placeholder="e.g. ACK-123456"></div>
        <div class="col-md-6"><label class="form-label">Status Check Website URL (Optional)</label><input class="form-control" name="tracking_url" placeholder="e.g. https://tin.tin.nsdl.com/pantan/StatusTrack.html"></div>
        <div class="col-md-6"><label class="form-label">Date</label><input class="form-control" type="date" name="txn_date"></div>
      </div>
      <div class="d-flex gap-2 mt-4"><button class="btn btn-primary">Save Entry</button><a class="btn btn-outline-secondary" href="{url_for('customer_detail', customer_id=c.id)}">Back</a></div>
    </form></div></div>
    """
    return page(body)

@app.post("/customer/<int:customer_id>/txn/add")
@login_required
def txn_add_post(customer_id):
    c = Customer.query.filter_by(id=customer_id, user_id=current_user.id).first()
    if not c: return redirect(url_for("customers"))
    try:
        total_amount = float(request.form.get("total_amount", 0))
        paid_amount = float(request.form.get("paid_amount", 0))
        txn_date = datetime.strptime(request.form.get("txn_date", ""), "%Y-%m-%d").date() if request.form.get("txn_date") else date.today()
        tracking_url = request.form.get("tracking_url", "").strip() or None
        t = Transaction(customer_id=c.id, total_amount=total_amount, paid_amount=paid_amount, note=request.form.get("note"), ref_no=request.form.get("ref_no"), tracking_url=tracking_url, txn_date=txn_date)
        db.session.add(t)
        db.session.commit()
    except Exception: pass
    return redirect(url_for("customer_detail", customer_id=customer_id))

@app.post("/txn/<int:txn_id>/delete")
@login_required
def txn_delete(txn_id):
    t = db.session.get(Transaction, txn_id)
    if t and t.customer.user_id == current_user.id:
        c_id = t.customer_id
        db.session.delete(t)
        db.session.commit()
        return redirect(url_for("customer_detail", customer_id=c_id))
    return redirect(url_for("customers"))

@app.get("/export/customers.csv")
@login_required
def export_customers():
    customers_list = Customer.query.filter_by(user_id=current_user.id).order_by(Customer.created_at.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Name", "Phone", "PIN", "Balance(Due)"])
    for c in customers_list: writer.writerow([c.name, c.phone, c.pin, customer_balance(c)])
    mem = io.BytesIO()
    mem.write(output.getvalue().encode("utf-8-sig"))
    mem.seek(0)
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name="my_customers.csv")
