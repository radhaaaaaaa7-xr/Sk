from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
import requests
import urllib.parse
import urllib3
import psycopg2
from psycopg2 import IntegrityError
import hashlib

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
app.secret_key = 'super_secret_key_change_this_later'

# Database URL
DB_URL = "postgresql://neondb_owner:npg_If5NuxsG1wRt@ep-wandering-darkness-ahrzvfsm-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

def get_db_connection():
    return psycopg2.connect(DB_URL)

def init_db():
    try:
        with get_db_connection() as conn:
            with conn.cursor() as c:
                c.execute('''CREATE TABLE IF NOT EXISTS users 
                             (id SERIAL PRIMARY KEY, 
                              name TEXT, email TEXT UNIQUE, password TEXT, 
                              coins INTEGER DEFAULT 0, is_admin INTEGER DEFAULT 0)''')
                
                c.execute('SELECT * FROM users WHERE email=%s', ("admin@afsar.com",))
                if not c.fetchone():
                    hashed_pw = generate_password_hash("admin123")
                    c.execute('INSERT INTO users (name, email, password, coins, is_admin) VALUES (%s, %s, %s, %s, %s)', 
                              ("Admin Afsar", "admin@afsar.com", hashed_pw, 9999, 1))
            conn.commit()
    except Exception as e:
        print("Database Init Error:", e)

init_db()

# ----------------- COIN CHECK HELPER -----------------
def deduct_coin(user_id, cost=1):
    with get_db_connection() as conn:
        with conn.cursor() as c:
            c.execute('SELECT coins FROM users WHERE id=%s', (user_id,))
            coins = c.fetchone()[0]
            if coins < cost: return False
            c.execute('UPDATE users SET coins = coins - %s WHERE id=%s', (cost, user_id))
        conn.commit()
        return True

# ----------------- LOGIN / SIGNUP / ADMIN -----------------
@app.route('/')
def home():
    if 'user_id' in session:
        if session.get('is_admin') == 1: return redirect(url_for('admin_panel'))
        return redirect(url_for('tool'))
    return redirect(url_for('login_page'))

@app.route('/login', methods=['GET', 'POST'])
def login_page():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        with get_db_connection() as conn:
            with conn.cursor() as c:
                c.execute('SELECT id, name, email, password, is_admin FROM users WHERE email=%s', (email,))
                user = c.fetchone()
                if user and check_password_hash(user[3], password):
                    session['user_id'] = user[0]
                    session['name'] = user[1]
                    session['email'] = user[2]
                    session['is_admin'] = user[4]
                    if user[4] == 1: return redirect(url_for('admin_panel'))
                    return redirect(url_for('tool'))
                return render_template('login.html', error="गलत ईमेल या पासवर्ड!")
    return render_template('login.html')

@app.route('/signup', methods=['POST'])
def signup():
    name = request.form.get('name')
    email = request.form.get('email')
    password = request.form.get('password')
    hashed_pw = generate_password_hash(password)
    try:
        with get_db_connection() as conn:
            with conn.cursor() as c:
                c.execute('INSERT INTO users (name, email, password, coins, is_admin) VALUES (%s, %s, %s, 0, 0)', (name, email, hashed_pw))
            conn.commit()
        return render_template('login.html', success="अकाउंट बन गया! कृपया Admin से कॉइन लें।")
    except IntegrityError:
        return render_template('login.html', error="यह ईमेल पहले से रजिस्टर है!")

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_page'))

@app.route('/api/change_password', methods=['POST'])
def change_password():
    if 'user_id' not in session: return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    old_pw, new_pw = data.get('old_password'), data.get('new_password')
    if not old_pw or not new_pw: return jsonify({"error": "पासवर्ड खाली नहीं हो सकता!"}), 400
    with get_db_connection() as conn:
        with conn.cursor() as c:
            c.execute('SELECT password FROM users WHERE id=%s', (session['user_id'],))
            user_pw = c.fetchone()[0]
            if not check_password_hash(user_pw, old_pw): return jsonify({"error": "पुराना पासवर्ड गलत है!"}), 400
            c.execute('UPDATE users SET password = %s WHERE id=%s', (generate_password_hash(new_pw), session['user_id']))
        conn.commit()
    return jsonify({"success": True})

@app.route('/admin')
def admin_panel():
    if session.get('is_admin') != 1: return redirect(url_for('home'))
    with get_db_connection() as conn:
        with conn.cursor() as c:
            c.execute('SELECT id, name, email, coins FROM users WHERE is_admin=0 ORDER BY id DESC')
            users = c.fetchall()
    return render_template('admin.html', name=session['name'], users=users)

@app.route('/api/manage_coins', methods=['POST'])
def manage_coins():
    if session.get('is_admin') != 1: return jsonify({"error": "Unauthorized"}), 403
    data = request.json
    user_id, amount, action = data.get('user_id'), int(data.get('amount', 0)), data.get('action')
    with get_db_connection() as conn:
        with conn.cursor() as c:
            if action == 'add': c.execute('UPDATE users SET coins = coins + %s WHERE id=%s', (amount, user_id))
            elif action == 'deduct':
                c.execute('SELECT coins FROM users WHERE id=%s', (user_id,))
                new_coins = max(0, c.fetchone()[0] - amount)
                c.execute('UPDATE users SET coins = %s WHERE id=%s', (new_coins, user_id))
            c.execute('SELECT coins FROM users WHERE id=%s', (user_id,))
            updated_balance = c.fetchone()[0]
        conn.commit()
    return jsonify({"success": True, "new_balance": updated_balance})

@app.route('/tool')
def tool():
    if 'user_id' not in session or session.get('is_admin') == 1: return redirect(url_for('login_page'))
    with get_db_connection() as conn:
        with conn.cursor() as c:
            c.execute('SELECT coins FROM users WHERE id=%s', (session['user_id'],))
            coins = c.fetchone()[0]
    return render_template('tool.html', name=session['name'], coins=coins)

# ----------------- GARENA VERCEL APIs (Bypass Render Block) -----------------

@app.route('/api/player_info', methods=['POST'])
def player_info():
    if 'user_id' not in session: return jsonify({"error": "Unauthorized"}), 401
    if not deduct_coin(session['user_id']): return jsonify({"error": "Insufficient Coins"}), 403
    try:
        res = requests.get(f"https://api-otrss.garena.com/support/callback/?access_token={request.json.get('access_token')}", headers={"User-Agent": "Mozilla/5.0"}, allow_redirects=True, timeout=15)
        q = urllib.parse.parse_qs(urllib.parse.urlparse(res.url).query)
        return jsonify({"result": 0, "account_id": q.get('account_id', ['Unknown'])[0], "nickname": q.get('nickname', ['Unknown'])[0], "region": q.get('region', ['Unknown'])[0]})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/api/bound_accounts', methods=['POST'])
def bound_accounts():
    if 'user_id' not in session: return jsonify({"error": "Unauthorized"}), 401
    if not deduct_coin(session['user_id']): return jsonify({"error": "Insufficient Coins"}), 403
    try:
        d = requests.get("https://100067.connect.garena.com/bind/app/platform/info/get", params={"access_token": request.json.get('access_token')}, headers={"User-Agent": "GarenaMSDK/4.0.30"}).json()
        P_MAP = {1: "Garena", 3: "Facebook", 4: "Guest", 5: "VK", 8: "Google", 11: "X (Twitter)", 13: "Apple ID"}
        accounts = [P_MAP.get(p_id, f"Unknown ({p_id})") for p_id in d.get("bounded_accounts", [])]
        return jsonify({"result": 0, "bound_platforms": accounts})
    except: return jsonify({"error": "Failed to fetch accounts"}), 500

@app.route('/api/check_info', methods=['POST'])
def check_info():
    if 'user_id' not in session: return jsonify({"error": "Unauthorized"}), 401
    if not deduct_coin(session['user_id']): return jsonify({"error": "Insufficient Coins"}), 403
    try:
        res = requests.get("https://bindinfocrownx612.vercel.app/check", params={'access_token': request.json.get('access_token')}, timeout=15).json()
        return jsonify(res)
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/api/cancel_bind', methods=['POST'])
def cancel_bind():
    if 'user_id' not in session: return jsonify({"error": "Unauthorized"}), 401
    if not deduct_coin(session['user_id']): return jsonify({"error": "Insufficient Coins"}), 403
    try:
        res = requests.get("https://bindcnclcrownx34.vercel.app/cancelbind", params={'access_token': request.json.get("access_token")}, timeout=15).json()
        return jsonify(res)
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/api/send_otp', methods=['POST'])
def send_otp():
    if 'user_id' not in session: return jsonify({"error": "Unauthorized"}), 401
    if not deduct_coin(session['user_id']): return jsonify({"error": "Insufficient Coins"}), 403
    try:
        res = requests.get("https://chngemailcode48.vercel.app/send_otp", params={'access_token': request.json.get("access_token"), 'email': request.json.get("email")}, timeout=15).json()
        return jsonify(res)
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/api/verify_otp', methods=['POST'])
def verify_otp():
    if 'user_id' not in session: return jsonify({"error": "Unauthorized"}), 401
    if not deduct_coin(session['user_id']): return jsonify({"error": "Insufficient Coins"}), 403
    try:
        res = requests.get("https://chngemailcode48.vercel.app/verify_otp", params={'access_token': request.json.get("access_token"), 'email': request.json.get("email"), 'otp': request.json.get("otp")}, timeout=15).json()
        return jsonify(res)
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/api/verify_identity', methods=['POST'])
def verify_identity():
    if 'user_id' not in session: return jsonify({"error": "Unauthorized"}), 401
    if not deduct_coin(session['user_id']): return jsonify({"error": "Insufficient Coins"}), 403
    try:
        res = requests.get("https://chngemailcode48.vercel.app/verify_identity", params={'access_token': request.json.get("access_token"), 'code': request.json.get("sec_code")}, timeout=15).json()
        return jsonify(res)
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/api/bind_email', methods=['POST'])
def bind_email():
    if 'user_id' not in session: return jsonify({"error": "Unauthorized"}), 401
    if not deduct_coin(session['user_id']): return jsonify({"error": "Insufficient Coins"}), 403
    try:
        res = requests.get("https://bindcnclcrownx34.vercel.app/confirmbind", params={'access_token': request.json.get("access_token"), 'email': request.json.get("email"), 'otp': request.json.get("otp"), 'security_code': request.json.get("sec_code")}, timeout=15).json()
        return jsonify(res)
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/api/change_email', methods=['POST'])
def change_email():
    if 'user_id' not in session: return jsonify({"error": "Unauthorized"}), 401
    if not deduct_coin(session['user_id']): return jsonify({"error": "Insufficient Coins"}), 403
    try:
        res = requests.get("https://chngemailcode48.vercel.app/create_rebind", params={'access_token': request.json.get("access_token"), 'email': request.json.get("new_email"), 'identity_token': request.json.get("id_token"), 'verifier_token': request.json.get("v_token")}, timeout=15).json()
        return jsonify(res)
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/api/unbind_email', methods=['POST'])
def unbind_email():
    if 'user_id' not in session: return jsonify({"error": "Unauthorized"}), 401
    if not deduct_coin(session['user_id']): return jsonify({"error": "Insufficient Coins"}), 403
    try:
        res = requests.get("https://crownxnewkey10010.vercel.app/securityunbind", params={'access_token': request.json.get("access_token"), 'security_code': request.json.get("sec_code")}, timeout=15).json()
        return jsonify(res)
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/api/eat_token', methods=['POST'])
def eat_token():
    if 'user_id' not in session: return jsonify({"error": "Unauthorized"}), 401
    if not deduct_coin(session['user_id']): return jsonify({"error": "Insufficient Coins"}), 403
    eat_url = request.json.get('eat_url', '')
    if "?" in eat_url: eat_url = urllib.parse.parse_qs(urllib.parse.urlparse(eat_url).query).get('eat', [''])[0]
    try:
        res = requests.get(f"https://api-otrss.garena.com/support/callback/?access_token={eat_url}", headers={"User-Agent": "Mozilla/5.0"}, allow_redirects=True)
        token = urllib.parse.parse_qs(urllib.parse.urlparse(res.url).query).get('access_token', [''])[0]
        if token: return jsonify({"result": 0, "access_token": token})
        return jsonify({"error": "Token Expired or Invalid!"}), 400
    except: return jsonify({"error": "Failed to extract token"}), 500

if __name__ == '__main__':
    app.run(debug=True)
        
