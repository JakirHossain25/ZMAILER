from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_cors import CORS
import json
import os
import base64
import random
import string
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from email.header import Header
from email.utils import formataddr
from datetime import datetime, date, timedelta
import pickle
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import threading
import shutil
from werkzeug.utils import secure_filename
import mimetypes
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
from dotenv import load_dotenv
import time
import secrets

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== APP INITIALIZATION ====================
app = Flask(__name__)

# Secret Key - Production ready
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))

# Configuration
app.config['MAX_CONTENT_LENGTH'] = int(os.environ.get('MAX_CONTENT_LENGTH', 100 * 1024 * 1024))
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=int(os.environ.get('SESSION_LIFETIME_HOURS', 24)))
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE', 'False').lower() == 'true'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

CORS(app, origins=os.environ.get('CORS_ORIGINS', '*').split(','))

# ==================== CONSTANTS ====================
# Data directory - Render persistent disk or local
DATA_DIR = os.environ.get('DATA_DIR', '/app/data') if os.environ.get('RENDER') else os.getcwd()
os.makedirs(DATA_DIR, exist_ok=True)

CREDITS_FILE = os.path.join(DATA_DIR, 'user_credits.json')
TOKEN_FILE = os.path.join(DATA_DIR, 'token.pickle')
CLIENT_SECRET_FILE = os.path.join(DATA_DIR, 'client_secret.json')

MAX_EMAILS_PER_DAY = int(os.environ.get('MAX_EMAILS_PER_DAY', 10000))
TEMP_FOLDER = 'temp_attachments'
UPLOAD_FOLDER = 'uploads'
MAX_WORKERS = int(os.environ.get('MAX_WORKERS', 5))
EMAIL_SEND_DELAY = float(os.environ.get('EMAIL_SEND_DELAY', 0.2))

SCOPES = ['https://www.googleapis.com/auth/gmail.send', 'https://www.googleapis.com/auth/gmail.modify']

# ==================== USER DATABASE ====================
VALID_USERS = {}
users_env = os.environ.get('VALID_USERS', '')
if users_env:
    for user_entry in users_env.split(','):
        if ':' in user_entry:
            username, password = user_entry.split(':', 1)
            VALID_USERS[username.strip()] = password.strip()
else:
    VALID_USERS = {
        "Padma": os.environ.get('PADMA_PASSWORD', "pd1234#"),
        "Jamuna": os.environ.get('JAMUNA_PASSWORD', "jm809"),
        "Brahmputra": os.environ.get('BRAHMPUTRA_PASSWORD', "Br123@")
    }

DEVELOPER_NAME = os.environ.get('DEVELOPER_NAME', "MD. JAKIR HOSSAIN")
WHATSAPP_NUMBER = os.environ.get('WHATSAPP_NUMBER', "+8801307731628")

TERMS = """ZMALER - TERMS AND CONDITIONS OF USE:

1. This software is intended solely for marketing or promotional purposes.
2. Users are requested not to use this software for any illegal activities.
3. The developer or publisher shall not be held responsible for any illegal activities.
4. The software must not be used to send spam or unsolicited messages.
5. Sending fake, fraudulent, or illegal messages is strictly prohibited.
6. Do not send viruses, malware, or harmful links.
7. Users must not harass, deceive, or harm others in any way.
8. Your activity may be monitored and terminated if anything suspicious is found.
9. All sending activities are logged for security purposes.
10. Violation of these terms will result in immediate account termination."""

# Create necessary folders
for folder in [TEMP_FOLDER, UPLOAD_FOLDER, 'templates']:
    os.makedirs(folder, exist_ok=True)

# ==================== HELPER FUNCTIONS ====================

def generate_random_filename(extension=''):
    random_string = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
    return f"{random_string}{extension}"

def generate_random_bill_number():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=13))

def load_users():
    today = str(date.today())
    try:
        if os.path.exists(CREDITS_FILE):
            with open(CREDITS_FILE, "r") as f:
                data = json.load(f)
                for user, info in data.items():
                    if info.get("last_date") != today:
                        info["credits_used"] = 0
                        info["last_date"] = today
                return data
    except Exception as e:
        logger.error(f"Error loading users: {e}")
    
    data = {}
    for user, password in VALID_USERS.items():
        data[user] = {
            "password": password, 
            "credits_used": 0, 
            "last_date": today
        }
    
    try:
        with open(CREDITS_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        logger.error(f"Error saving users: {e}")
    return data

users = load_users()

def save_users():
    try:
        with open(CREDITS_FILE, "w") as f:
            json.dump(users, f)
        return True
    except Exception as e:
        logger.error(f"Error saving users: {e}")
        return False

def generate_random_name():
    first_names = ["James", "John", "Robert", "Michael", "William", "David", "Richard", "Joseph", "Thomas", "Charles",
                   "Mohammad", "Abdul", "Rahman", "Karim", "Hasan", "Hossain", "Islam", "Ahmed"]
    last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
                  "Khan", "Rahman", "Hossain", "Islam", "Ahmed", "Ali", "Hasan"]
    return f"{random.choice(first_names)} {random.choice(last_names)}"

def replace_placeholders(text, email, custom_data=None):
    if not text:
        return text
    
    name_part = email.split("@")[0]
    name = re.sub(r'[^a-zA-Z]', ' ', name_part)
    name = ' '.join([part.capitalize() for part in name.split() if part])
    if not name:
        name = "Valued Customer"
    
    replacements = {
        "#EMAIL#": email,
        "#NAME#": name,
        "#DATE#": datetime.now().strftime("%Y-%m-%d"),
        "#TIME#": datetime.now().strftime("%H:%M:%S"),
        "#RAND#": ''.join(random.choices(string.digits, k=6)),
        "#BILL#": generate_random_bill_number(),
        "#YEAR#": datetime.now().strftime("%Y"),
        "#MONTH#": datetime.now().strftime("%B"),
        "#DAY#": datetime.now().strftime("%d")
    }
    
    if custom_data:
        for key, value in custom_data.items():
            replacements[f"#{key}#"] = value
    
    for placeholder, value in replacements.items():
        text = text.replace(placeholder, value)
    return text

def send_via_smtp(sender_email, sender_password, smtp_host, smtp_port, to_email, subject, body, html_body, attachments, sender_name):
    try:
        msg = MIMEMultipart('mixed')
        
        if sender_name and sender_name.strip():
            try:
                encoded_name = Header(sender_name, 'utf-8').encode()
                msg['From'] = formataddr((encoded_name, sender_email))
            except:
                msg['From'] = f"{sender_name} <{sender_email}>"
        else:
            msg['From'] = sender_email
        
        msg['To'] = to_email
        msg['Subject'] = Header(subject or '', 'utf-8').encode()
        
        if html_body:
            msg.attach(MIMEText(html_body, 'html', 'utf-8'))
        elif body:
            msg.attach(MIMEText(body, 'plain', 'utf-8'))
        
        for file_path in attachments:
            if os.path.exists(file_path):
                try:
                    with open(file_path, 'rb') as f:
                        mime_type = mimetypes.guess_type(file_path)[0] or 'application/octet-stream'
                        main_type, sub_type = mime_type.split('/', 1)
                        part = MIMEBase(main_type, sub_type)
                        part.set_payload(f.read())
                        encoders.encode_base64(part)
                        filename = os.path.basename(file_path)
                        part.add_header('Content-Disposition', f'attachment; filename="{filename}"')
                        msg.attach(part)
                except Exception as e:
                    logger.error(f"Error attaching {file_path}: {e}")
        
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as server:
                server.login(sender_email, sender_password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
                server.starttls()
                server.login(sender_email, sender_password)
                server.send_message(msg)
        
        return True, "Sent via SMTP"
        
    except Exception as e:
        logger.error(f"SMTP error: {e}")
        return False, str(e)

def send_via_gmail_api(service, sender_name, sender_email, to_email, subject, body, html_body, attachments):
    try:
        message = MIMEMultipart('mixed')
        message['to'] = to_email
        
        if sender_name and sender_name.strip():
            try:
                encoded_name = Header(sender_name, 'utf-8').encode()
                message['from'] = formataddr((encoded_name, sender_email))
            except:
                message['from'] = f"{sender_name} <{sender_email}>"
        else:
            message['from'] = sender_email
        
        message['subject'] = Header(subject or '', 'utf-8').encode()
        
        if html_body:
            message.attach(MIMEText(html_body, 'html', 'utf-8'))
        elif body:
            message.attach(MIMEText(body, 'plain', 'utf-8'))
        
        for file_path in attachments:
            if os.path.exists(file_path):
                try:
                    with open(file_path, 'rb') as f:
                        file_data = f.read()
                    
                    mime_type = mimetypes.guess_type(file_path)[0] or 'application/octet-stream'
                    main_type, sub_type = mime_type.split('/', 1)
                    
                    part = MIMEBase(main_type, sub_type)
                    part.set_payload(file_data)
                    encoders.encode_base64(part)
                    
                    filename = os.path.basename(file_path)
                    part.add_header('Content-Disposition', f'attachment; filename="{filename}"')
                    message.attach(part)
                    
                except Exception as e:
                    logger.error(f"Error attaching {file_path}: {e}")
        
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
        
        send_message = service.users().messages().send(
            userId='me',
            body={'raw': raw_message}
        ).execute()
        
        return True, f"Sent via Gmail API"
        
    except HttpError as error:
        error_details = error._get_reason() if hasattr(error, '_get_reason') else str(error)
        logger.error(f"Gmail API error: {error_details}")
        return False, f"Gmail API Error: {error_details}"
    except Exception as e:
        logger.error(f"Gmail API error: {e}")
        return False, str(e)

def get_gmail_service():
    """Get Gmail API service - Server compatible (No local browser)"""
    if not os.path.exists(CLIENT_SECRET_FILE):
        logger.warning("Client secret file not found")
        return None
    
    creds = None
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, 'rb') as token:
                creds = pickle.load(token)
        except Exception as e:
            logger.error(f"Error loading token: {e}")
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                logger.info("Token refreshed successfully")
                with open(TOKEN_FILE, 'wb') as token:
                    pickle.dump(creds, token)
            except Exception as e:
                logger.error(f"Error refreshing token: {e}")
                return None
        else:
            logger.error("No valid credentials found. Please upload token.pickle generated locally.")
            return None
    
    return build('gmail', 'v1', credentials=creds)

def send_single_email(email_data):
    try:
        if email_data['send_method'] == 'gmail_api':
            service = email_data.get('gmail_service')
            if not service:
                return False, email_data['email'], "Gmail service not available"
            
            success, message = send_via_gmail_api(
                service,
                email_data['sender_name'],
                email_data['sender_email'],
                email_data['email'],
                email_data['subject'],
                email_data['body'],
                email_data['html_body'],
                email_data['attachments']
            )
        else:
            success, message = send_via_smtp(
                email_data['sender_email'],
                email_data['smtp_password'],
                email_data['smtp_host'],
                email_data['smtp_port'],
                email_data['email'],
                email_data['subject'],
                email_data['body'],
                email_data['html_body'],
                email_data['attachments'],
                email_data['sender_name']
            )
        
        return success, email_data['email'], message
    except Exception as e:
        logger.error(f"Error sending to {email_data['email']}: {e}")
        return False, email_data['email'], str(e)

# ==================== ROUTES ====================

@app.route('/')
def index():
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'Invalid request'})
        
        username = data.get('username', '').strip()
        password = data.get('password', '')
        
        if username in VALID_USERS and VALID_USERS[username] == password:
            session.clear()
            session['username'] = username
            session['logged_in'] = True
            session['terms_accepted'] = False
            session.permanent = True
            return jsonify({'success': True, 'message': 'Login successful'})
        
        return jsonify({'success': False, 'message': 'Invalid username or password'})
    except Exception as e:
        logger.error(f"Login error: {e}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('index'))
    return render_template('dashboard.html')

@app.route('/get_user_data')
def get_user_data():
    if 'username' not in session:
        return jsonify({'error': 'Not logged in'})
    
    username = session['username']
    credits_used = users.get(username, {}).get('credits_used', 0)
    return jsonify({
        'username': username,
        'credits_used': credits_used,
        'credits_left': MAX_EMAILS_PER_DAY - credits_used,
        'max_credits': MAX_EMAILS_PER_DAY,
        'developer_name': DEVELOPER_NAME,
        'whatsapp_number': WHATSAPP_NUMBER
    })

@app.route('/get_terms')
def get_terms():
    return jsonify({'terms': TERMS})

@app.route('/accept_terms', methods=['POST'])
def accept_terms():
    if 'username' in session:
        session['terms_accepted'] = True
        return jsonify({'success': True})
    return jsonify({'success': False})

@app.route('/check_auth')
def check_auth():
    if 'username' not in session:
        return jsonify({'authorized': False, 'logged_in': False})
    
    service = get_gmail_service()
    has_secret = os.path.exists(CLIENT_SECRET_FILE)
    
    if service:
        return jsonify({'authorized': True, 'has_client_secret': has_secret})
    return jsonify({'authorized': False, 'has_client_secret': has_secret})

@app.route('/upload_client_secret', methods=['POST'])
def upload_client_secret():
    if 'username' not in session:
        return jsonify({'error': 'Not logged in'})
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'})
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'})
    
    try:
        if os.path.exists(CLIENT_SECRET_FILE):
            os.remove(CLIENT_SECRET_FILE)
        if os.path.exists(TOKEN_FILE):
            os.remove(TOKEN_FILE)
        
        file.save(CLIENT_SECRET_FILE)
        return jsonify({'success': True, 'message': 'Client secret uploaded'})
    except Exception as e:
        logger.error(f"Upload error: {e}")
        return jsonify({'error': str(e)})

@app.route('/authorize_gmail', methods=['POST'])
def authorize_gmail():
    if 'username' not in session:
        return jsonify({'error': 'Not logged in'})
    
    if not os.path.exists(CLIENT_SECRET_FILE):
        return jsonify({'error': 'Upload client_secret.json first'})
    
    return jsonify({
        'error': 'OAuth flow must be completed on a local machine. Please generate token.pickle locally and upload it via /upload_token endpoint.'
    })

@app.route('/upload_token', methods=['POST'])
def upload_token():
    """Upload pre-generated token.pickle file"""
    if 'username' not in session:
        return jsonify({'error': 'Not logged in'})
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'})
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'})
    
    if not file.filename.endswith('.pickle'):
        return jsonify({'error': 'File must be a .pickle file'})
    
    try:
        if os.path.exists(TOKEN_FILE):
            os.remove(TOKEN_FILE)
        
        file.save(TOKEN_FILE)
        
        # Validate token
        try:
            with open(TOKEN_FILE, 'rb') as f:
                creds = pickle.load(f)
            return jsonify({'success': True, 'message': 'Token uploaded successfully'})
        except Exception as e:
            os.remove(TOKEN_FILE)
            return jsonify({'error': f'Invalid token file: {str(e)}'})
        
    except Exception as e:
        logger.error(f"Token upload error: {e}")
        return jsonify({'error': str(e)})

@app.route('/send_emails', methods=['POST'])
def send_emails():
    if 'username' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'})
    
    if not session.get('terms_accepted', False):
        return jsonify({'success': False, 'error': 'Please accept Terms and Conditions first'})
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Invalid request'})
        
        emails = data.get('emails', [])
        subject = data.get('subject', '')
        body = data.get('body', '')
        html_content = data.get('html_content', '')
        sender_name = data.get('sender_name', '')
        sender_email = data.get('sender_email', '')
        send_method = data.get('send_method', 'gmail_api')
        attachments = data.get('attachments', [])
        
        smtp_host = data.get('smtp_host', '')
        smtp_port = data.get('smtp_port', 587)
        smtp_password = data.get('smtp_password', '')
        
        if not emails:
            return jsonify({'success': False, 'error': 'No recipients provided'})
        
        if not sender_name or sender_name.strip() == '':
            sender_name = generate_random_name()
        
        username = session['username']
        credits_used = users.get(username, {}).get('credits_used', 0)
        
        if credits_used + len(emails) > MAX_EMAILS_PER_DAY:
            return jsonify({'success': False, 'error': f'Daily limit exceeded. You have {MAX_EMAILS_PER_DAY - credits_used} left.'})
        
        gmail_service = None
        if send_method == 'gmail_api':
            gmail_service = get_gmail_service()
            if not gmail_service:
                return jsonify({'success': False, 'error': 'Gmail API not authorized. Please upload token.pickle file.'})
        
        email_tasks = []
        for email in emails:
            processed_subject = replace_placeholders(subject, email)
            processed_body = replace_placeholders(body, email)
            processed_html = replace_placeholders(html_content, email) if html_content else None
            
            processed_attachments = [att for att in attachments if os.path.exists(att)]
            
            email_tasks.append({
                'email': email,
                'subject': processed_subject,
                'body': processed_body,
                'html_body': processed_html,
                'attachments': processed_attachments,
                'sender_name': sender_name,
                'sender_email': sender_email,
                'send_method': send_method,
                'gmail_service': gmail_service if send_method == 'gmail_api' else None,
                'smtp_host': smtp_host,
                'smtp_port': smtp_port,
                'smtp_password': smtp_password
            })
        
        success_count = 0
        failure_count = 0
        failed_emails = []
        
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_email = {executor.submit(send_single_email, task): task['email'] for task in email_tasks}
            
            for future in as_completed(future_to_email):
                success, email, message = future.result()
                if success:
                    success_count += 1
                else:
                    failure_count += 1
                    failed_emails.append({'email': email, 'error': message})
                
                if EMAIL_SEND_DELAY > 0:
                    time.sleep(EMAIL_SEND_DELAY)
        
        users[username]["credits_used"] = credits_used + success_count
        save_users()
        
        return jsonify({
            'success': True,
            'sent': success_count,
            'failed': failure_count,
            'failed_emails': failed_emails
        })
    except Exception as e:
        logger.error(f"Send emails error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/upload_emails', methods=['POST'])
def upload_emails():
    if 'username' not in session:
        return jsonify({'error': 'Not logged in'})
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'})
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'})
    
    try:
        content = file.read().decode('utf-8', errors='ignore')
        lines = content.split('\n')
        emails = []
        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        
        for line in lines:
            line = line.strip().lower()
            found_emails = re.findall(email_pattern, line)
            emails.extend(found_emails)
        
        unique_emails = []
        seen = set()
        for email in emails:
            if email not in seen:
                seen.add(email)
                unique_emails.append(email)
        
        return jsonify({'emails': unique_emails, 'count': len(unique_emails)})
    except Exception as e:
        logger.error(f"Upload emails error: {e}")
        return jsonify({'error': str(e)})

@app.route('/upload_attachment', methods=['POST'])
def upload_attachment():
    if 'username' not in session:
        return jsonify({'error': 'Not logged in'})
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'})
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'})
    
    try:
        file_ext = os.path.splitext(file.filename)[1].lower()
        random_filename = generate_random_filename(file_ext)
        filepath = os.path.join(TEMP_FOLDER, random_filename)
        file.save(filepath)
        
        return jsonify({'success': True, 'filename': file.filename, 'path': filepath})
    except Exception as e:
        logger.error(f"Upload attachment error: {e}")
        return jsonify({'error': str(e)})

@app.route('/clear_attachments', methods=['POST'])
def clear_attachments():
    try:
        if os.path.exists(TEMP_FOLDER):
            for file in os.listdir(TEMP_FOLDER):
                file_path = os.path.join(TEMP_FOLDER, file)
                try:
                    if os.path.isfile(file_path):
                        os.unlink(file_path)
                except Exception:
                    pass
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Clear attachments error: {e}")
        return jsonify({'error': str(e)})

@app.route('/generate_random_name')
def generate_random_name_route():
    return jsonify({'name': generate_random_name()})

@app.route('/spam_check')
def spam_check():
    return jsonify({'url': 'https://inbox-checker.emailtoolhub.com/'})

@app.route('/gmass_inbox')
def gmass_inbox():
    return jsonify({'url': 'https://www.gmass.co/inbox'})

@app.route('/health')
def health():
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'version': '1.0.0'
    })

# ==================== CLEANUP ====================
def cleanup_old_files():
    while True:
        try:
            now = time.time()
            for folder in [TEMP_FOLDER, UPLOAD_FOLDER]:
                if os.path.exists(folder):
                    for filename in os.listdir(folder):
                        filepath = os.path.join(folder, filename)
                        if os.path.isfile(filepath):
                            if now - os.path.getmtime(filepath) > 3600:
                                os.unlink(filepath)
            time.sleep(3600)
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
            time.sleep(3600)

cleanup_thread = threading.Thread(target=cleanup_old_files, daemon=True)
cleanup_thread.start()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    host = os.environ.get('HOST', '0.0.0.0')
    debug = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    
    print("=" * 70)
    print(" ZMALER - Professional Email Marketing Platform")
    print("=" * 70)
    print(f"\n🌐 Server running on {host}:{port}")
    print(f"🔧 Debug mode: {debug}")
    print(f"⚡ Max workers: {MAX_WORKERS}")
    print(f"📧 Max emails/day: {MAX_EMAILS_PER_DAY}")
    print("\n" + "=" * 70)
    
    app.run(host=host, port=port, debug=debug, threaded=True)