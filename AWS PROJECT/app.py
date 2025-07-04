import os
import uuid
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash

import boto3
from botocore.exceptions import NoCredentialsError, ClientError

# --- Flask Setup ---
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'supersecretkey')

# --- AWS Setup ---
use_dynamo = False
sns = None
users_table = None
orders_table = None
local_users = {}
local_orders = []

# Read SNS Topic ARN from environment variable
sns_topic_arn = os.environ.get('SNS_TOPIC_ARN')

try:
    session_boto = boto3.Session()
    dynamodb = session_boto.resource('dynamodb', region_name='ap-south-1')
    sns = session_boto.client('sns', region_name='ap-south-1')

    dynamodb.meta.client.list_tables()  # Test DynamoDB connection
    users_table = dynamodb.Table('Users')
    orders_table = dynamodb.Table('Orders')

    use_dynamo = True
except (NoCredentialsError, ClientError) as e:
    print(f"AWS error or credentials not found: {e}")

# Temporary store for password reset codes
reset_codes = {}

# ------------------- ROUTES -------------------

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/home')
def home():
    return render_template('home.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('username')
        password = request.form.get('password')

        user = users_table.get_item(Key={'email': email}).get('Item') if use_dynamo else local_users.get(email)
        if user and check_password_hash(user['password'], password):
            session['user'] = email
            flash('Login successful', 'success')
            return redirect(url_for('shop'))
        else:
            flash('Invalid credentials', 'error')
            return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        fullname = request.form.get('fullname')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm = request.form.get('confirm')

        if password != confirm:
            flash('Passwords do not match.', 'error')
            return redirect(url_for('signup'))

        hashed_pw = generate_password_hash(password)

        if use_dynamo:
            existing = users_table.get_item(Key={'email': email}).get('Item')
            if existing:
                flash('Email already registered', 'error')
                return redirect(url_for('signup'))

            users_table.put_item(Item={
                'email': email,
                'fullname': fullname,
                'password': hashed_pw
            })
        else:
            if email in local_users:
                flash('Email already registered', 'error')
                return redirect(url_for('signup'))

            local_users[email] = {
                'email': email,
                'fullname': fullname,
                'password': hashed_pw
            }

        flash('Signup successful. Please login.', 'success')
        return redirect(url_for('login'))

    return render_template('signup.html')

@app.route('/shop')
def shop():
    return render_template('shop.html')

@app.route('/cart')
def cart():
    return render_template('cart.html')

@app.route('/buynow', methods=['GET', 'POST'])
def buynow():
    if request.method == 'POST':
        if 'user' not in session:
            flash('Please login to place an order.', 'error')
            return redirect(url_for('login'))

        name = request.form['name']
        phone = request.form['phone']
        address = request.form['address']
        total = request.form['total']

        if not phone.isdigit() or len(phone) != 10:
            flash('Invalid phone number.', 'error')
            return redirect(url_for('buynow'))

        order_id = str(uuid.uuid4())
        email = session['user']

        order = {
            'order_id': order_id,
            'email': email,
            'name': name,
            'phone': phone,
            'address': address,
            'total': total
        }

        if use_dynamo:
            try:
                orders_table.put_item(Item=order)
                message = f"Hi {name}, your order {order_id} is confirmed. Total ₹{total}."

                if sns_topic_arn:
                    sns.publish(
                        TopicArn=sns_topic_arn,
                        Message=message,
                        Subject='Order Confirmation'
                    )
                else:
                    print("SNS_TOPIC_ARN not set. Skipping SNS publish.")
            except ClientError as e:
                print("Error sending SNS notification or saving order:", e)
        else:
            local_orders.append(order)

        return render_template('buynow.html', order_id=order_id)

    return render_template('buynow.html')

@app.route('/feedback', methods=['GET', 'POST'])
def feedback():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        message = request.form.get('message')
        print(f"Feedback received from {name} ({email}): {message}")
        return redirect(url_for('thanku'))
    return render_template('feedback.html')

@app.route('/thanku')
def thanku():
    return render_template('thanku.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

# -------------------- Run App --------------------

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
