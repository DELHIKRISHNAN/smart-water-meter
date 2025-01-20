from flask import Flask, render_template, request, redirect, url_for, jsonify
from firebase_admin import credentials, firestore, initialize_app
from datetime import datetime
import firebase_admin
from apscheduler.schedulers.background import BackgroundScheduler
import uuid
from bcrypt import hashpw, gensalt, checkpw
from firebase_admin import credentials, firestore
app = Flask(__name__)

# Firebase setup
cred = credentials.Certificate("D:\Dust Bin\Projects\projects\serviceAccountKey.json.json")  # Path to your service account key JSON file
firebase_admin.initialize_app(cred)
db = firestore.client()

# Scheduler setup
scheduler = BackgroundScheduler()
scheduler.start()

# Generate a unique API key
def generate_api_key():
    return str(uuid.uuid4())

# Initialize admin user if not already in the database
admin_ref = db.collection('users').where("username", "==", "admin").stream()
if not any(admin_ref):
    db.collection('users').add({
        "username": "admin",
        "password": hashpw("admin123".encode('utf-8'), gensalt()).decode('utf-8'),
        "is_admin": True,
        "water_usage": [{"date": str(datetime.now().date()), "usage": 0}],
        "usage_history": []
    })

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user_ref = db.collection('users').where("username", "==", username).stream()
        user = next((doc.to_dict() for doc in user_ref), None)

        if user and checkpw(password.encode('utf-8'), user['password'].encode('utf-8')):
            if user.get('is_admin'):
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('user_dashboard', username=username))

        return "Invalid credentials! Please try again."
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # Check if the user already exists in Firebase Firestore
        user_ref = db.collection('users').where('username', '==', username).stream()

        # If user already exists
        if any(user.id for user in user_ref):
            return "Username already exists!"

        # Hash the password
        hashed_password = hashpw(password.encode('utf-8'), gensalt())

        # Generate a new API key
        api_key = generate_api_key()

        # Create new user document in Firestore
        new_user = {
            "username": username,
            "password": hashed_password.decode('utf-8'),
            "api_key": api_key,
            "water_usage": [{"date": str(datetime.now().date()), "usage": 0}],
            "usage_history": []
        }

        # Add new user to Firestore
        db.collection('users').add(new_user)

        return redirect(url_for('user_dashboard', username=username))

    return render_template('register.html')



@app.route('/admin_dashboard')
def admin_dashboard():
    # Fetch all users from Firestore excluding the admin
    users_ref = db.collection('users')
    users = users_ref.stream()

    user_data = []

    for user in users:
        user_info = user.to_dict()

        # Extract the latest water usage (if available)
        latest_usage = user_info['water_usage'][-1] if user_info['water_usage'] else {"date": "N/A", "usage": 0}

        # Handle missing 'api_key' field gracefully
        api_key = user_info.get('api_key', 'N/A')  # If 'api_key' doesn't exist, default to 'N/A'

        user_data.append({
            "username": user_info['username'],
            "api_key": api_key,
            "latest_usage": latest_usage['usage']
        })

    return render_template('admin_dashboard.html', users=user_data)


@app.route('/user_dashboard')
def user_dashboard():
    username = request.args.get('username')
    user_ref = db.collection('users').where("username", "==", username).stream()
    user = next((doc.to_dict() for doc in user_ref), None)

    if user:
        latest_usage = user['water_usage'][-1] if user['water_usage'] else {"date": "N/A", "usage": 0}
        return render_template('user_dashboard.html', user=user, latest_usage=latest_usage)
    return "User not found!"

@app.route('/update_water_usage', methods=['GET'])
def update_water_usage():
    api_key = request.args.get('apikey')
    new_usage = request.args.get('new_usage')

    if not api_key or not new_usage:
        return "Invalid request. API key and new usage are required."

    try:
        new_usage = int(new_usage)
    except ValueError:
        return "New usage must be a number."

    user_ref = db.collection('users').where("api_key", "==", api_key).stream()
    user_doc = next(user_ref, None)

    if user_doc:
        user = user_doc.to_dict()
        current_date = str(datetime.now().date())
        water_usage = user.get('water_usage', [])

        today_entry = next((entry for entry in water_usage if entry['date'] == current_date), None)

        if today_entry:
            today_entry['usage'] = new_usage
        else:
            water_usage.append({"date": current_date, "usage": new_usage})

        db.collection('users').document(user_doc.id).update({"water_usage": water_usage})
        return jsonify({"message": "Water usage updated successfully!"})

    return jsonify({"error": "User not found!"})

# Reset daily usage task
def reset_daily_usage():
    current_date = str(datetime.now().date())

    users_ref = db.collection('users').where("is_admin", "==", False).stream()
    for user_doc in users_ref:
        user = user_doc.to_dict()
        water_usage = user.get('water_usage', [])
        usage_history = user.get('usage_history', [])

        if water_usage:
            # Move the last day's usage to usage history
            last_entry = water_usage[-1]
            usage_history.append(last_entry)

        # Reset today's usage
        water_usage = [{"date": current_date, "usage": 0}]
        db.collection('users').document(user_doc.id).update({
            "water_usage": water_usage,
            "usage_history": usage_history
        })

scheduler.add_job(reset_daily_usage, 'cron', hour=0, minute=0)

# Graceful shutdown
first_request = True

@app.before_request
def initialize():
    global first_request
    if first_request:
        print("Starting Flask application...")
        first_request = False

@app.teardown_appcontext
def shutdown_scheduler(exception=None):
    if scheduler.running:
        scheduler.shutdown(wait=False)
        print("Scheduler shutdown completed.")

if __name__ == '__main__':
    app.run(debug=True)
