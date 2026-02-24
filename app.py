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
SHOP_UPI_ID = "9415712175@ybl"  # उदाहरण: 9876543210@paytm
SHOP_WHATSAPP = "919415712175"              # अपना WhatsApp नंबर डालें
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
    body { background-color: #f4f7f6; }
    .navbar-brand img { height: 40px; margin-right: 10px; border-radius: 5px; }
    .srv-cb:checked + label { background-color: #d1e7dd; border-color: #0f5132; }
    .hover-shadow:hover { transform: translateY(-3px); box-shadow: 0 .5rem 1rem rgba(0,0,0,.15)!important; transition: all .3s ease; }
  </style>
</head>
<body>
<nav class="navbar navbar-dark bg-dark sticky-top shadow-sm">
  <div class="container">
    <a class="navbar-brand d-flex align-items-center" href="/">
      <img src="https://i.postimg.cc/placeholder-logo.png" alt="Manglam Logo">
      Manglam Online Services
    </a>
    <div class="d-flex gap-2 align-items-center">
      {% if current_user.is_authenticated %}
        <a class="btn btn-info btn-sm text-white fw-bold shadow-sm" href="{{ url_for('daily_report') }}">📈 Daily Report</a>
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
        <div class="alert alert-{{category}} shadow-sm">{{ msg }}</div>
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
    <a class="btn btn-outline-secondary shadow-sm" href="/customers">Back to Dashboard</a>
    """
    return page(body)

# ---------------- Setup/Login (Admin) ----------------
@app.get("/setup")
def setup():
    body = """
    <div class="row justify-content-center"><div class="col-md-6 col-lg-5"><div class="card shadow border-0 rounded-4"><div class="card-body p-4">
      <h4 class="mb-3 fw-bold text-primary">Register New Admin</h4>
      <form method="post">
        <div class="mb-3"><label class="form-label fw-bold">Username</label><input class="form-control form-control-lg" name="username" required></div>
        <div class="mb-3"><label class="form-label fw-bold">Password</label><input class="form-control form-control-lg" type="password" name="password" required></div>
        <button class="btn btn-primary btn-lg w-100 fw-bold shadow-sm">Create Account</button>
      </form>
      <div class="mt-3 text-center"><a href="/login" class="text-decoration-none">Already have an account? Login here</a></div>
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
      <div class="card shadow border-0 rounded-4 mb-4"><div class="card-body p-4">
        <h4 class="mb-4 fw-bold text-primary text-center">Admin Login</h4>
        <form method="post">
          <div class="mb-3"><label class="form-label fw-bold text-muted">Username</label><input class="form-control form-control-lg bg-light" name="username" required></div>
          <div class="mb-4"><label class="form-label fw-bold text-muted">Password</label><input class="form-control form-control-lg bg-light" type="password" name="password" required></div>
          <button class="btn btn-primary btn-lg w-100 fw-bold shadow-sm">🔑 Secure Login</button>
        </form>
        <div class="mt-3 text-center"><a href="/setup" class="text-decoration-none">Create Admin Account</a></div>
      </div></div>
      <div class="card shadow border-0 bg-primary text-white rounded-4 hover-shadow"><div class="card-body text-center p-4">
        <h4 class="fw-bold">Are you a Customer?</h4>
        <p class="mb-3 text-white-50">अपना बकाया बिल और खाते की जानकारी देखें।</p>
        <a href="/portal/login" class="btn btn-light btn-lg w-100 fw-bold text-primary shadow-sm">📱 Customer Login</a>
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
        c = Customer.query.filter_by(phone=phone).first()
        if c:
            session['customer_id'] = c.id
            return redirect(url_for("portal_dashboard"))
        else:
            flash("यह मोबाइल नंबर हमारे सिस्टम में दर्ज नहीं है। कृपया दुकानदार से संपर्क करें।", "danger")
            
    body = """
    <div class="row align-items-center mb-5">
      <div class="col-lg-7 mb-4 mb-lg-0">
        <div class="pe-lg-4 text-center text-lg-start">
          <h1 class="display-5 fw-bolder text-primary mb-3">मंगलम ऑनलाइन सर्विसेज</h1>
          <p class="fs-5 text-muted mb-4">आपका भरोसेमंद डिजिटल सेवा केंद्र। हम नीचे दी गई सभी सरकारी और ऑनलाइन सुविधाएँ बहुत ही उचित रेट पर प्रदान करते हैं:</p>
          
          <div class="row g-3">
            <div class="col-sm-6"><div class="p-3 border rounded-3 bg-white shadow-sm fw-bold text-dark hover-shadow">📄 पैन कार्ड (PAN Card)</div></div>
            <div class="col-sm-6"><div class="p-3 border rounded-3 bg-white shadow-sm fw-bold text-dark hover-shadow">🏡 आय/जाति/निवास प्रमाण पत्र</div></div>
            <div class="col-sm-6"><div class="p-3 border rounded-3 bg-white shadow-sm fw-bold text-dark hover-shadow">🆔 आधार कार्ड संशोधन</div></div>
            <div class="col-sm-6"><div class="p-3 border rounded-3 bg-white shadow-sm fw-bold text-dark hover-shadow">🛂 पासपोर्ट (Passport)</div></div>
            <div class="col-sm-6"><div class="p-3 border rounded-3 bg-white shadow-sm fw-bold text-dark hover-shadow">🌾 पीएम किसान & फार्मर रजिस्ट्री</div></div>
            <div class="col-sm-6"><div class="p-3 border rounded-3 bg-white shadow-sm fw-bold text-dark hover-shadow">🚗 ड्राइविंग लाइसेंस & वोटर आईडी</div></div>
          </div>
          
          <div class="mt-4 p-3 bg-success bg-opacity-10 text-success rounded-3 fw-bold border border-success d-inline-block">
            ✅ 100% सुरक्षित &nbsp; ✅ फास्ट सर्विस &nbsp; ✅ ऑनलाइन पेमेंट सुविधा
          </div>
        </div>
      </div>

      <div class="col-lg-5">
        <div class="card shadow-lg border-0 rounded-4" style="background: linear-gradient(to bottom right, #ffffff, #f8f9fa);">
          <div class="card-body p-4 p-md-5">
            <div class="text-center mb-4">
              <div class="bg-primary text-white rounded-circle d-inline-flex align-items-center justify-content-center shadow mb-3" style="width: 70px; height: 70px;">
                <span style="font-size: 2rem;">📱</span>
              </div>
              <h3 class="fw-bolder text-dark">अपना खाता देखें</h3>
              <p class="text-muted small">अपना मोबाइल नंबर डालकर अपनी रसीदें और बकाया चेक करें।</p>
            </div>
            
            <form method="post">
              <div class="mb-4">
                <label class="form-label fw-bold text-secondary">आपका 10-अंकों का मोबाइल नंबर</label>
                <div class="input-group input-group-lg shadow-sm rounded-3">
                  <span class="input-group-text bg-white border-end-0 text-muted fw-bold">+91</span>
                  <input class="form-control border-start-0 ps-0 fw-bold" name="phone" placeholder="9876543210" required maxlength="10" pattern="\d{10}">
                </div>
              </div>
              <button class="btn btn-primary btn-lg w-100 fw-bold shadow">➡️ खाता खोलें (View Khata)</button>
            </form>
            <hr class="my-4">
            <div class="text-center">
                <a href="/login" class="text-decoration-none text-muted small fw-bold">⚙️ दुकानदार लॉगिन (Admin Login)</a>
            </div>
          </div>
        </div>
      </div>
    </div>
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
    
    pay_btn = ""
    if bal > 0:
        upi_link = f"upi://pay?pa={SHOP_UPI_ID}&pn=Manglam%20Online%20Services&am={bal}&cu=INR"
        pay_btn = f'<a href="{upi_link}" class="btn btn-success fw-bold px-4 py-2 mt-2 shadow-sm rounded-pill"><img src="https://upload.wikimedia.org/wikipedia/commons/e/e1/UPI-Logo-vector.svg" height="20" class="me-2"> Pay ₹{bal} Online</a>'
        badge = f'<span class="badge text-bg-danger fs-5 shadow-sm">Amount Due: ₹ {bal}</span><br>{pay_btn}'
    elif bal < 0:
        badge = f'<span class="badge text-bg-success fs-5 shadow-sm">Advance: ₹ {-bal}</span>'
    else:
        badge = f'<span class="badge text-bg-secondary fs-5 shadow-sm">Balanced: ₹ 0</span>'

    doc_msg = urllib.parse.quote(f"नमस्ते मंगलम ऑनलाइन, मैं {c.name} हूँ। मुझे एक नया काम कराना है। मैं अपने डाक्यूमेंट्स (आधार/फोटो) भेज रहा/रही हूँ।")
    doc_link = f"https://wa.me/{SHOP_WHATSAPP}?text={doc_msg}"
    doc_btn = f'<a href="{doc_link}" target="_blank" class="btn btn-outline-primary fw-bold mt-3 shadow-sm rounded-pill"><span style="font-size:1.2rem;">📝</span> नया काम दें / Documents भेजें</a>'

    txns_rb = running_balances(c.transactions)
    rows = []
    for t, entry_due, rb in txns_rb:
        ref_display = t.ref_no or "-"
        if t.ref_no and t.tracking_url:
            ref_display = f'<span class="user-select-all fw-bold text-dark border p-1 rounded bg-white shadow-sm" title="Copy Number">{t.ref_no}</span><br><a href="{t.tracking_url}" target="_blank" class="badge bg-primary text-decoration-none mt-2 shadow-sm" title="Click to Track Status">Track Status 🔗</a>'
        rows.append(f'<tr><td class="fw-bold text-muted">{t.txn_date}</td><td class="fw-bold">{t.note or "-"}</td><td>{ref_display}</td><td class="text-dark fw-bold">₹ {t.total_amount:.2f}</td><td class="text-success fw-bold">₹ {t.paid_amount:.2f}</td><td class="text-danger fw-bold">₹ {entry_due:.2f}</td><td class="bg-light"><strong>₹ {rb}</strong></td></tr>')

    body = f"""
    <div class="card shadow border-0 rounded-4 mb-4">
      <div class="card-body text-center p-4 p-md-5">
        <h2 class="mb-1 fw-bolder text-dark">Namaste, {c.name} 🙏</h2>
        <p class="text-muted mb-4 fw-bold">Welcome to Manglam Online Services</p>
        <div class="mb-3">{badge}</div>
        <div>{doc_btn}</div>
      </div>
    </div>
    <h4 class="mb-3 fw-bold text-primary">🧾 Your Transaction History</h4>
    <div class="card shadow border-0 rounded-4 overflow-hidden"><div class="table-responsive"><table class="table table-hover mb-0 align-middle">
      <thead class="table-dark"><tr><th>Date</th><th>Work Done</th><th>Ref No (Status)</th><th>Total Bill</th><th>Paid</th><th>Entry Due</th><th>Total Balance</th></tr></thead>
      <tbody>{''.join(rows) if rows else '<tr><td colspan="7" class="text-center text-muted py-5 fw-bold">No transactions yet</td></tr>'}</tbody>
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
        badge = (f'<span class="badge text-bg-danger shadow-sm">₹ {bal}</span>' if bal > 0 else f'<span class="badge text-bg-success shadow-sm">Advance ₹ {-bal}</span>' if bal < 0 else f'<span class="badge text-bg-secondary shadow-sm">₹ 0</span>')
        rows.append(f'<tr class="align-middle"><td class="fw-bold text-dark">{c.name}</td><td class="text-muted fw-bold">{c.phone}</td><td>{badge}</td><td class="text-end"><a class="btn btn-sm btn-primary fw-bold shadow-sm rounded-pill px-3" href="{url_for("customer_detail", customer_id=c.id)}">Open</a></td></tr>')

    body = f"""
    <div class="d-flex align-items-center justify-content-between mb-4 mt-2">
      <h3 class="m-0 fw-bold text-dark">👥 My Customers</h3>
      <a class="btn btn-success fw-bold shadow-sm rounded-pill px-4" href="{url_for('customer_add')}">+ Add Customer</a>
    </div>
    <div class="card shadow border-0 rounded-4 mb-4"><div class="card-body bg-light rounded-4">
        <form class="row g-2" method="get">
          <div class="col-md-8"><input class="form-control form-control-lg border-0 shadow-sm" name="q" placeholder="🔍 Search: Name or Phone" value="{q}"></div>
          <div class="col-md-2"><button class="btn btn-primary btn-lg w-100 fw-bold shadow-sm">Search</button></div>
          <div class="col-md-2"><a class="btn btn-outline-secondary btn-lg w-100 fw-bold shadow-sm bg-white" href="{url_for('customers')}">Reset</a></div>
        </form>
    </div></div>
    
    <div class="alert alert-danger shadow-sm border-0 fw-bold fs-5 text-center rounded-4">📉 Total Market Due: <span class="text-dark">₹ {round(total_due,2)}</span></div>
    
    <div class="card shadow border-0 rounded-4 overflow-hidden"><div class="table-responsive"><table class="table table-hover mb-0">
      <thead class="table-dark"><tr><th>Name</th><th>Phone</th><th>Balance/Due</th><th></th></tr></thead>
      <tbody>{''.join(rows) if rows else '<tr><td colspan="4" class="text-center text-muted py-5 fw-bold">No customers found</td></tr>'}</tbody>
    </table></div></div>
    """
    return page(body)

@app.get("/customer/add")
@login_required
def customer_add():
    body = f"""
    <div class="card shadow border-0 rounded-4"><div class="card-body p-4 p-md-5"><h4 class="mb-4 fw-bold text-primary">➕ Add New Customer</h4>
    <form method="post">
      <div class="row g-3">
          <div class="col-md-6 mb-3"><label class="form-label fw-bold text-muted">Full Name *</label><input class="form-control form-control-lg bg-light" name="name" required></div>
          <div class="col-md-6 mb-3"><label class="form-label fw-bold text-muted">Phone Number (Login ID) *</label><input class="form-control form-control-lg bg-light" name="phone" required maxlength="10"></div>
          <div class="col-md-12 mb-4"><label class="form-label fw-bold text-muted">Address (Optional)</label><input class="form-control form-control-lg bg-light" name="address"></div>
      </div>
      <div class="d-flex gap-2"><button class="btn btn-primary btn-lg px-5 fw-bold shadow-sm">Create Profile</button><a class="btn btn-outline-secondary btn-lg fw-bold" href="{url_for('customers')}">Cancel</a></div>
    </form></div></div>
    """
    return page(body)

@app.post("/customer/add")
@login_required
def customer_add_post():
    name = request.form.get("name", "").strip()
    phone = request.form.get("phone", "").strip()
    address = request.form.get("address", "").strip()
    if not name or not phone:
        flash("Name and Phone are required.", "danger")
        return redirect(url_for("customer_add"))
    c = Customer(name=name, phone=phone, address=address or None, user_id=current_user.id)
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
    badge = (f'<span class="badge text-bg-danger fs-5 shadow-sm">Due: ₹ {bal}</span>' if bal > 0 else f'<span class="badge text-bg-success fs-5 shadow-sm">Advance: ₹ {-bal}</span>' if bal < 0 else f'<span class="badge text-bg-secondary fs-5 shadow-sm">Balanced: ₹ 0</span>')

    phone_clean = ""
    if c.phone:
        phone_clean = ''.join(filter(str.isdigit, c.phone))
        if len(phone_clean) == 10: phone_clean = "91" + phone_clean

    wa_btn = ""
    if bal > 0 and phone_clean:
        msg = f"नमस्ते {c.name} जी,\n\nमंगलम ऑनलाइन सर्विसेज पर आने के लिए आपका बहुत-बहुत धन्यवाद। 🙏\n\nआपके खाते की कुल बकाया राशि: *₹{bal}* है।\n\nआप नीचे दिए गए लिंक पर अपना मोबाइल नंबर डालकर अपना पूरा खाता चेक कर सकते हैं और वहीं से ऑनलाइन पेमेंट भी कर सकते हैं:\n🔗 लिंक: {request.host_url}portal/login\n\nकृपया समय पर भुगतान करें।\n\nधन्यवाद,\n*मंगलम ऑनलाइन सर्विसेज*"
        wa_link = f"https://wa.me/{phone_clean}?text={urllib.parse.quote(msg)}"
        wa_btn = f'<a class="btn btn-sm btn-success ms-2 fw-bold shadow-sm rounded-pill px-3 py-2" href="{wa_link}" target="_blank">📲 WhatsApp Total Due</a>'

    txns_rb = running_balances(c.transactions)
    rows = []
    for t, entry_due, rb in txns_rb:
        entry_wa_btn = ""
        if phone_clean:
            entry_msg = f"नमस्ते {c.name} जी,\n\nमंगलम ऑनलाइन सर्विसेज पर आने के लिए आपका बहुत-बहुत धन्यवाद। 🙏\n\nआपका कार्य सफलतापूर्वक कर दिया गया है। कार्य का विवरण:\n\n📝 *कार्य (Work):* {t.note or 'N/A'}\n🧾 *कुल बिल (Total Bill):* ₹{t.total_amount}\n✅ *जमा राशि (Paid):* ₹{t.paid_amount}\n⏳ *इस कार्य का बकाया (Due):* ₹{entry_due}\n🔖 *रेफरेंस नंबर (Ref No):* {t.ref_no or 'N/A'}"
            if t.tracking_url:
                entry_msg += f"\n🌐 *स्टेटस चेक करें:* {t.tracking_url}\n(वेबसाइट पर यह रेफरेंस नंबर डालें)"
            entry_msg += f"\n\n📊 *आपका कुल बकाया (Total Balance):* ₹{rb}\n\nअपना पूरा खाता यहाँ देखें और ऑनलाइन पेमेंट करें:\n🔗 लिंक: {request.host_url}portal/login\n\nधन्यवाद,\n*मंगलम ऑनलाइन सर्विसेज*"
            e_wa_link = f"https://wa.me/{phone_clean}?text={urllib.parse.quote(entry_msg)}"
            entry_wa_btn = f'<a class="btn btn-sm btn-outline-success mt-2 w-100 fw-bold rounded-pill shadow-sm" href="{e_wa_link}" target="_blank">📲 Send Slip</a>'
            
        ref_display = t.ref_no or "-"
        if t.ref_no and t.tracking_url:
            ref_display = f'<span class="user-select-all fw-bold text-dark border p-1 rounded bg-white shadow-sm" title="Copy Number">{t.ref_no}</span><br><a href="{t.tracking_url}" target="_blank" class="badge bg-primary text-decoration-none mt-2 shadow-sm" title="Check Status">Track Status 🔗</a>'
            
        rows.append(f'<tr class="align-middle"><td class="text-muted fw-bold">{t.txn_date}</td><td class="fw-bold">{t.note or "-"}</td><td>{ref_display}</td><td class="text-dark fw-bold">₹ {t.total_amount:.2f}</td><td class="text-success fw-bold">₹ {t.paid_amount:.2f}</td><td class="text-danger fw-bold">₹ {entry_due:.2f}</td><td class="bg-light"><strong>₹ {rb}</strong></td><td class="text-end"><form method="post" action="{url_for("txn_delete", txn_id=t.id)}" onsubmit="return confirm(\'Delete this entry?\');"><button class="btn btn-sm btn-outline-danger w-100 fw-bold rounded-pill shadow-sm">🗑️ Delete</button></form>{entry_wa_btn}</td></tr>')

    body = f"""
    <div class="card shadow border-0 rounded-4 mb-4 bg-white">
      <div class="card-body p-4 d-flex flex-column flex-md-row align-items-center justify-content-between">
        <div class="text-center text-md-start mb-3 mb-md-0">
          <h2 class="m-0 fw-bolder text-primary">{c.name}</h2>
          <div class="text-muted fw-bold mt-1">📞 Phone: {c.phone}</div>
        </div>
        <div class="text-center text-md-end">
          <div class="mb-3">{badge} {wa_btn}</div>
          <a class="btn btn-primary fw-bold shadow-sm rounded-pill px-4 py-2" href="{url_for('txn_add', customer_id=c.id)}">➕ Add New Work / Entry</a>
        </div>
      </div>
    </div>
    <div class="card shadow border-0 rounded-4 overflow-hidden"><div class="table-responsive"><table class="table table-hover align-middle mb-0">
      <thead class="table-dark"><tr><th>Date</th><th>Work Done</th><th>Ref No (Status)</th><th>Total Bill</th><th>Paid</th><th>Due</th><th>Total Balance</th><th>Actions</th></tr></thead>
      <tbody>{''.join(rows) if rows else '<tr><td colspan="8" class="text-center text-muted py-5 fw-bold">No entries yet</td></tr>'}</tbody>
    </table></div></div>
    <div class="mt-4"><a class="btn btn-outline-secondary fw-bold shadow-sm rounded-pill px-4" href="{url_for('customers')}">⬅️ Back to All Customers</a></div>
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
    
    services = [
        ("आय प्रमाण पत्र", 100, "https://edistrict.up.gov.in/edistrict/showStatushome.aspx?application_no="),
        ("जाति प्रमाण पत्र", 100, "https://edistrict.up.gov.in/edistrict/showStatushome.aspx?application_no="),
        ("निवास प्रमाण पत्र", 100, "https://edistrict.up.gov.in/edistrict/showStatushome.aspx?application_no="),
        ("वोटर आईडी", 150, "https://voters.eci.gov.in/home/track/"),
        ("पैन कार्ड", 200, "https://trackpan.utiitsl.com/PANONLINE/forms/TrackPan/trackApp"),
        ("पासपोर्ट", 1700, "https://portal1.passportindia.gov.in/AppOnlineProject/statusTracker/trackStatusInpNew"),
        ("पीएम किसान सम्मान निधि", 100, "https://pmkisan.gov.in/"),
        ("फार्मर रजिस्ट्री", 100, "https://upfr.agristack.gov.in/farmer-registry-up/#/checkEnrolmentStatus/"),
        ("आधार कार्ड संशोधन", 150, "https://myaadhaar.uidai.gov.in/CheckAadhaarStatus/en"),
        ("वरासत", 150, "https://rccms.up.gov.in/Varasat/searchApplication/"),
        ("राशन कार्ड", 100, "https://nfsa.up.gov.in/Food/TrackingRationCard/TrackApplication.aspx/"),
        ("ड्राइविंग लाइसेंस", 3500, "https://parivahan.gov.in/rcdlstatus/?pur_cd=101/")
    ]
    
    cb_html = ""
    for i, (name, price, url) in enumerate(services):
        cb_html += f'''
        <div class="col-md-6 col-lg-4">
          <div class="form-check border p-3 rounded-3 bg-white shadow-sm h-100 position-relative hover-shadow">
            <input class="form-check-input srv-cb ms-1 mt-2" type="checkbox" value="{name}" data-price="{price}" data-url="{url}" id="cb_{i}" style="transform: scale(1.4); cursor: pointer;">
            <label class="form-check-label w-100 ms-2 fw-bold text-dark d-flex justify-content-between align-items-center" for="cb_{i}" style="cursor: pointer;">
              <span>{name}</span>
              <span class="badge bg-success fs-6 rounded-pill">₹{price}</span>
            </label>
          </div>
        </div>
        '''

    body = f"""
    <div class="card shadow-lg border-0 rounded-4"><div class="card-body p-4 p-md-5">
    <div class="d-flex align-items-center mb-4 border-bottom pb-3">
        <h3 class="m-0 fw-bold text-primary">📝 Add Work for: <span class="text-dark">{c.name}</span></h3>
    </div>
    
    <form method="post" id="txnForm">
      
      <div class="mb-5 bg-light p-4 rounded-4 border">
        <label class="form-label fw-bolder text-dark fs-4 mb-4">1. क्या काम कराया? (Select Services)</label>
        <div class="row g-3 mb-4">
          {cb_html}
        </div>
        <div class="mt-2">
            <label class="fw-bold text-muted mb-2">कोई अन्य काम (Other Work)</label>
            <input type="text" class="form-control form-control-lg shadow-sm" id="custom_note" placeholder="✍️ यहाँ टाइप करें...">
        </div>
      </div>

      <input type="hidden" name="note" id="final_note" required>
      <input type="hidden" name="tracking_url" id="final_url">

      <div class="row g-4 bg-light p-4 rounded-4 border mx-0 mb-4">
        <div class="col-12"><label class="form-label fw-bolder text-dark fs-4 mb-2">2. पेमेंट और डिटेल्स</label></div>
        
        <div class="col-md-6">
            <label class="form-label text-danger fw-bolder fs-5">Total Bill (कुल बिल ₹) *</label>
            <input class="form-control form-control-lg fw-bold border-danger text-danger bg-white shadow-sm" type="number" step="0.01" name="total_amount" id="total_amount_input" value="0" required style="font-size:1.5rem;">
        </div>
        
        <div class="col-md-6">
            <label class="form-label text-success fw-bolder fs-5">Amount Paid (जमा किया ₹) *</label>
            <input class="form-control form-control-lg fw-bold border-success text-success bg-white shadow-sm" type="number" step="0.01" name="paid_amount" value="0" required style="font-size:1.5rem;">
        </div>
        
        <div class="col-md-6">
            <label class="form-label fw-bold text-secondary mt-3">Reference / App No (Optional)</label>
            <input class="form-control form-control-lg shadow-sm" name="ref_no" placeholder="e.g. ACK-123456">
        </div>
        
        <div class="col-md-6">
            <label class="form-label fw-bold text-secondary mt-3">Date</label>
            <input class="form-control form-control-lg shadow-sm" type="date" name="txn_date" value="{date.today().strftime('%Y-%m-%d')}">
        </div>
      </div>
      
      <div class="d-flex gap-3 mt-4">
        <button type="submit" class="btn btn-primary btn-lg px-5 fw-bold shadow rounded-pill">💾 Save Entry</button>
        <a class="btn btn-outline-secondary btn-lg fw-bold rounded-pill px-4 bg-white" href="{url_for('customer_detail', customer_id=c.id)}">Cancel</a>
      </div>
    </form>
    </div></div>

    <script>
      const checkboxes = document.querySelectorAll('.srv-cb');
      const totalInput = document.getElementById('total_amount_input');
      const finalNote = document.getElementById('final_note');
      const finalUrl = document.getElementById('final_url');
      const customNote = document.getElementById('custom_note');
      const form = document.getElementById('txnForm');

      function updateForm() {{
          let total = 0;
          let notes = [];
          let urls = [];

          checkboxes.forEach(cb => {{
              if(cb.checked) {{
                  total += parseFloat(cb.dataset.price);
                  notes.push(cb.value);
                  if(cb.dataset.url && urls.length === 0) {{
                       urls.push(cb.dataset.url);
                  }}
              }}
          }});

          if (customNote.value.trim() !== "") {{
              notes.push(customNote.value.trim());
          }}

          totalInput.value = total;
          finalNote.value = notes.join(" + ");
          finalUrl.value = urls.length > 0 ? urls[0] : "";
      }}

      checkboxes.forEach(cb => cb.addEventListener('change', updateForm));
      customNote.addEventListener('input', updateForm);

      form.addEventListener('submit', function(e) {{
          updateForm();
          if(finalNote.value.trim() === "") {{
              e.preventDefault();
              alert("कृपया कम से कम एक काम चुनें या 'अन्य काम' बॉक्स में काम का नाम लिखें!");
          }}
      }});
    </script>
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
    writer.writerow(["Name", "Phone", "Balance(Due)"])
    for c in customers_list: writer.writerow([c.name, c.phone, customer_balance(c)])
    mem = io.BytesIO()
    mem.write(output.getvalue().encode("utf-8-sig"))
    mem.seek(0)
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name="my_customers.csv")

