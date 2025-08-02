from flask import Flask, render_template, request, redirect, url_for, send_file, session, make_response, jsonify
import random
import csv
import os
from datetime import datetime
import stripe
from dotenv import load_dotenv

app = Flask(__name__)
app.secret_key = 'Seeyounexttime'

load_dotenv()  # .envを読み込みます

stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
endpoint_secret = os.getenv('STRIPE_WEBHOOK_SECRET')


print("🔍 STRIPE_SECRET_KEY from .env:", os.getenv('STRIPE_SECRET_KEY'))
print("🔍 stripe.api_key set to:", stripe.api_key)

YOUR_DOMAIN = 'https://kicklotto.onrender.com'

print("Stripe API key:", stripe.api_key)

MAX_WINNERS = 50  # 最大当選数を定義（たとえば50）

def save_payment_info(email, payment_id):
    with open('payments.csv', 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([email, payment_id])

def count_winners():
    csv_file = 'winners.csv'
    if not os.path.isfile(csv_file):
        return 0
    with open(csv_file, newline='', encoding='cp932') as f:
        reader = csv.reader(f)
        next(reader, None)  # ヘッダーを飛ばす
        return sum(1 for _ in reader)  # 行数=当選者数

@app.route('/')
def index():
    winners_count = count_winners()
    remaining_stock = MAX_WINNERS - winners_count
    sold_out = remaining_stock <= 0

    return render_template('index.html', sold_out=sold_out, remaining_stock=remaining_stock)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form['password']
        if password == 'Seeyounexttime':
            session['logged_in'] = True
            return redirect(url_for('admin'))
        else:
            return render_template('login.html', error='パスワードが違います')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/confirm')
def confirm():
    if count_winners() >= MAX_WINNERS:
        return render_template('result.html', result='ガチャは終了しました。')
    if random.random() < 0.2:
        return render_template('winner_form.html')
    else:
        return render_template('result.html', result='ハズレ…また挑戦してね！')

@app.route('/gacha', methods=['POST'])
def gacha():
    if count_winners() >= MAX_WINNERS:
        return render_template('result.html', result='ガチャは終了しました。')
    if random.random() < 0.2:
        return render_template('winner_form.html')
    else:
        return render_template('result.html', result='ハズレ…')

@app.route('/winner_submit', methods=['POST'])
def winner_submit():
    name = request.form['name']
    address = request.form['address']
    email = request.form['email']
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    csv_file = 'winners.csv'
    file_exists = os.path.isfile(csv_file)

    with open(csv_file, 'a', newline='', encoding='cp932') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['日時', '名前', '住所', 'メール'])
        writer.writerow([timestamp, name, address, email])

    return render_template('winner_thanks.html')

@app.route('/admin')
def admin():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    winners = []
    csv_file = 'winners.csv'
    if os.path.isfile(csv_file):
        with open(csv_file, newline='', encoding='cp932') as f:
            reader = csv.reader(f)
            headers = next(reader, [])
            for row in reader:
                if len(row) < len(headers):
                    row.append('未発送')
                winners.append(row)
    else:
        headers = ['日時', '名前', '住所', 'メール', '発送状況']
    return render_template('admin.html', headers=headers, winners=winners)

@app.route('/download_csv')
def download_csv():
    csv_path = 'winners.csv'
    if not os.path.isfile(csv_path):
        return "CSVファイルが存在しません。", 404

    with open(csv_path, 'r', encoding='cp932') as f:
        csv_data = f.read()

    response = make_response(csv_data)
    response.headers['Content-Disposition'] = 'attachment; filename=winners.csv'
    response.headers['Content-Type'] = 'text/csv; charset=cp932'
    return response

@app.route('/update_status/<int:row_num>', methods=['POST'])
def update_status(row_num):
    csv_file = 'winners.csv'
    rows = []

    with open(csv_file, newline='', encoding='cp932') as f:
        reader = csv.reader(f)
        headers = next(reader)
        for r in reader:
            rows.append(r)

    if row_num < len(rows):
        current_status = rows[row_num][4] if len(rows[row_num]) > 4 else '未発送'
        new_status = '発送済み' if current_status == '未発送' else '未発送'

        while len(rows[row_num]) < 5:
            rows[row_num].append('')
        rows[row_num][4] = new_status

    with open(csv_file, 'w', newline='', encoding='cp932') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(headers)
        writer.writerows(rows)

    return redirect(url_for('admin'))

@app.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    if count_winners() >= MAX_WINNERS:
        return "ガチャは終了しました。", 403

    print("Stripe API key in create_checkout_session:", stripe.api_key)  # デバッグ用

    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'jpy',
                    'unit_amount': 1000,
                    'product_data': {'name': 'スニーカーガチャ'},
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=YOUR_DOMAIN + '/confirm',
            cancel_url=YOUR_DOMAIN + '/',
        )
        return redirect(checkout_session.url, code=303)
    except Exception as e:
        return str(e)

@app.route("/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature", None)

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
    except ValueError:
        print("⚠️  Invalid payload")
        return jsonify(success=False), 400
    except stripe.error.SignatureVerificationError:
        print("⚠️  Invalid signature")
        return jsonify(success=False), 400

    if event["type"] == "checkout.session.completed":
        session_data = event["data"]["object"]
        customer_email = session_data.get("customer_details", {}).get("email", "")
        customer_name = session_data.get("customer_details", {}).get("name", "")
        payment_intent = session_data.get("payment_intent", "")
        amount_total = session_data.get("amount_total", 0) / 100

        print("✅ 決済成功:", customer_email, customer_name)

        with open("payments.csv", mode="a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                customer_name,
                customer_email,
                payment_intent,
                amount_total
            ])

    return jsonify(success=True), 200

@app.route('/notice')
def notice():
    return render_template('notice.html')


@app.before_request
def before_request():
    if not request.is_secure and os.getenv('FLASK_ENV') == 'production':
        url = request.url.replace('http://', 'https://', 1)
        return redirect(url, code=301)




if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

