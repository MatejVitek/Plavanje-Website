from flask import Flask, render_template, request, redirect, url_for
from datetime import datetime, timedelta
import numpy as np
from pathlib import Path
import threading
import yaml
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).absolute().parent
CONFIG_FILE = BASE_DIR/'config.yaml'
HISTORY_FILE = BASE_DIR/'data/history.yaml'
SIGNUPS_FILE = BASE_DIR/'data/signups.yaml'

app = Flask(__name__)
rng = np.random.default_rng()
lock = threading.Lock()

def load_yaml(file):
	try:
		with file.open() as f:
			return yaml.safe_load(f) or {}
	except FileNotFoundError:
		return {}

def save_yaml(file, data):
	with file.open('w') as f:
		yaml.safe_dump(data, f)

def get_config():
	return load_yaml(CONFIG_FILE)

def weekday_index(name):
	return ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'].index(name.lower())

def now():
	return datetime.now(tz=ZoneInfo('Europe/Ljubljana'))

def str2time(s):
	return datetime.strptime(s, '%H:%M').time()

def in_signup_window():
	cfg = get_config()
	t = now()
	if t.weekday() != weekday_index(cfg['signup']['weekday']):
		return False
	start = str2time(cfg['signup']['start'])
	end = str2time(cfg['signup']['end'])
	print(t.time(), start, end)
	return start <= t.time() <= end

def allowed_email(email):
	cfg = get_config()
	return any(email.endswith(f"@{d}") for d in cfg['email'])

def select_participants():
	cfg = get_config()
	signups = load_yaml(SIGNUPS_FILE).get('signups', [])
	history = load_yaml(HISTORY_FILE).get('history', {})

	if not signups:
		return []

	cap = cfg['lesson']['capacity']
	algo = cfg['algorithm']['name'].lower()

	if algo == 'fcfs':
		return signups[:cap]

	if algo == 'weighted_random':
		exp = cfg['algorithm'].get('weight_exponent', 1)
	else:
		exp = 99 if algo == 'lpv' else 0

	weights = []
	for s in signups:
		v = visits.get(s['email'], 0)
		weights.append((1 / (v + 1)) ** exp)
	weights = np.array(weights)
	weights /= weights.sum()
	indices = rng.choice(signups, p=weights, size=min(cap, len(signups)), replace=False)
	return [signups[i] for i in indices]

@app.route('/', methods=['GET', 'POST'])
def index():
	if in_signup_window():
		if request.method == 'POST':
			first = request.form['first_name']
			last = request.form['last_name']
			email = request.form['email']
			if not allowed_email(email):
				return "Invalid email domain", 400
			with lock:
				signups = load_yaml(SIGNUPS_FILE).get('signups', [])
				signups.append({'first_name': first, 'last_name': last, 'email': email})
				save_yaml(SIGNUPS_FILE, {'signups': signups})
			return redirect('/')
		return render_template('signup.html')
	else:
		with lock:
			chosen = select_participants()
		return render_template('results.html', chosen=chosen)

@app.route('/cancel', methods=['GET','POST'])
def cancel():
	if request.method == 'POST':
		email = request.form['email']
		with lock:
			signups_data = load_yaml(SIGNUPS_FILE)
			signups = signups_data.get('signups', [])
			signups = [s for s in signups if s['email'] != email]
			save_yaml(SIGNUPS_FILE, {'signups': signups})
		return redirect('/')
	return render_template('cancel.html')

if __name__ == '__main__':
	app.run(host='0.0.0.0', port=8000)