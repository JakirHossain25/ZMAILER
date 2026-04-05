import sqlite3
import secrets
from datetime import date
import os

DATABASE_PATH = os.environ.get('DATABASE_PATH', 'data/users.db')

def init_db():
    os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)
    
def add_premium_user(username, email_limit=100000):
    """Add a new premium user"""
    api_key = f"premium_{secrets.token_hex(16)}"
    
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO premium_users (api_key, username, email_limit, emails_sent, last_reset_date)
        VALUES (?, ?, ?, 0, ?)
    ''', (api_key, username, email_limit, str(date.today())))
    
    conn.commit()
    conn.close()
    
    print(f"✅ Premium user created!")
    print(f"📝 Username: {username}")
    print(f"🔑 API Key: {api_key}")
    print(f"📧 Limit: {email_limit} emails/day")
    
    return api_key

def list_users():
    """List all premium users"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('SELECT api_key, username, email_limit, emails_sent, is_active FROM premium_users')
    users = cursor.fetchall()
    
    print("\n📊 Premium Users:")
    print("-" * 80)
    for user in users:
        status = "✅ Active" if user[4] else "❌ Inactive"
        print(f"User: {user[1]} | Limit: {user[2]} | Sent: {user[3]} | Status: {status}")
        print(f"API Key: {user[0]}")
        print("-" * 80)
    
    conn.close()

def deactivate_user(api_key):
    """Deactivate a premium user"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('UPDATE premium_users SET is_active = 0 WHERE api_key = ?', (api_key,))
    conn.commit()
    conn.close()
    
    print(f"❌ User deactivated")

if __name__ == '__main__':
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python manage_users.py add <username> [limit]")
        print("  python manage_users.py list")
        print("  python manage_users.py deactivate <api_key>")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == 'add':
        username = sys.argv[2]
        limit = int(sys.argv[3]) if len(sys.argv) > 3 else 100000
        add_premium_user(username, limit)
    elif command == 'list':
        list_users()
    elif command == 'deactivate':
        api_key = sys.argv[2]
        deactivate_user(api_key)