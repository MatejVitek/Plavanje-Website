from flask import Flask, render_template, request, redirect, flash
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
SELECTION_FILE = BASE_DIR/'data/selection.yaml'

def get_key():
	key_file = BASE_DIR/'key'
	if not key_file.is_file():
		import uuid
		key = str(uuid.uuid4().hex)
		with key_file.open('w') as f:
			f.write(key)
	else:
		with key_file.open('r') as f:
			key = f.read()
	return key

app = Flask(__name__)
app.secret_key = get_key()
rng = np.random.default_rng()
lock = threading.Lock()

def load_yaml(file):
	try:
		with file.open() as f:
			return yaml.safe_load(f) or {}
	except FileNotFoundError:
		return {}

def save_yaml(file, data):
	file.parent.mkdir(parents=True, exist_ok=True)
	with file.open('w') as f:
		yaml.safe_dump(data, f, sort_keys=False, default_flow_style=False)

def get_config():
	return load_yaml(CONFIG_FILE)

def weekday_index(name):
	return ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'].index(name.lower())

def now():
	return datetime.now(tz=ZoneInfo('UTC'))

def str2time(weekday, time, allow_today=True):
	now = datetime.now(tz=ZoneInfo('Europe/Ljubljana'))

	target_weekday = weekday_index(weekday)
	current_weekday = now.weekday()

	days_ahead = target_weekday - current_weekday

	if not allow_today and days_ahead == 0 or days_ahead < 0:
		days_ahead += 7

	target_date = (now + timedelta(days=days_ahead)).date()

	hour, minute = map(int, time.split(':'))
	cet_dt = datetime(
		year=target_date.year,
		month=target_date.month,
		day=target_date.day,
		hour=hour,
		minute=minute,
		tzinfo=ZoneInfo('Europe/Ljubljana'),
	)

	return cet_dt.astimezone(ZoneInfo('UTC'))

def in_signup_window():
	cfg = get_config()
	t = now()
	start = str2time(cfg['signup']['weekday'], cfg['signup']['start'])
	end = str2time(cfg['signup']['weekday'], cfg['signup']['end'])
	return start <= t <= end

def over_cancel_deadline():
	cfg = get_config()
	lesson_time = str2time(cfg['lesson']['weekday'], cfg['lesson']['time'])
	cutoff = lesson_time - timedelta(hours=cfg['lesson']['cancel_deadline_hours'])
	return now() > cutoff

def allowed_email(email):
	cfg = get_config()
	return any(email.endswith(f'@{d}') for d in cfg['email'])

def choose_indices(items, capacity):
	cfg = get_config()
	history = load_yaml(HISTORY_FILE).get('visits', {})

	if not items or capacity <= 0:
		return []

	algo = cfg['algorithm']['name'].lower()

	if algo == 'fcfs':
		return list(range(min(capacity, len(items))))

	if algo == 'weighted_random':
		exp = cfg['algorithm'].get('weight_exponent', 1)
	else:
		exp = 99 if algo == 'lpv' else 0

	weights = []
	for item in items:
		visits = history.get(item['email'], 0)
		weights.append((1 / (visits + 1)) ** exp)

	weights = np.array(weights)
	weights /= weights.sum()

	return rng.choice(
		len(items),
		size=min(capacity, len(items)),
		replace=False,
		p=weights,
	).tolist()

def finalize_selection():
	signups = load_yaml(SIGNUPS_FILE).get('signups', [])

	cap = get_config()['lesson']['capacity']
	indices = choose_indices(signups, cap)
	chosen = [signups[i] for i in indices]
	waiting = [s for i, s in enumerate(signups) if i not in indices]

	save_yaml(SELECTION_FILE, {
		'chosen': chosen,
		'waiting': waiting,
		'history_saved': False,
	})
	save_yaml(SIGNUPS_FILE, {'signups': []})

def add_to_history(chosen):
	data = load_yaml(HISTORY_FILE)
	if 'visits' not in data:
		data['visits'] = {}
	for p in chosen:
		email = p['email']
		data['visits'][email] = data['visits'].get(email, 0) + 1
	save_yaml(HISTORY_FILE, data)

@app.route('/', methods=['GET', 'POST'])
def index():
	with lock:
		# ────────────── SIGNUP PHASE ──────────────
		if in_signup_window():
			# Reset state for new cycle
			if SELECTION_FILE.exists():
				SELECTION_FILE.unlink()

			if request.method == 'POST':
				first = request.form['first_name']
				last = request.form['last_name']
				email = request.form['email'].lower()

				if not allowed_email(email):
					flash("Invalid email domain.")
					return redirect('/')

				signups = load_yaml(SIGNUPS_FILE).get('signups', [])

				if any(p['email'].lower() == email for p in signups):
					flash("You are already signed up.")
					return redirect('/')

				signups.append({
					'first_name': first,
					'last_name': last,
					'email': email,
				})
				save_yaml(SIGNUPS_FILE, {'signups': signups})
				flash("Successfully signed up.")
				return redirect('/')

			return render_template('signup.html')

		# ────────────── SIGNUP CLOSED ──────────────
		selection = load_yaml(SELECTION_FILE)

		# Freeze selection exactly once
		if not selection.get('chosen'):
			finalize_selection()
			selection = load_yaml(SELECTION_FILE)

		# Persist history exactly once
		if over_cancel_deadline() and not selection.get('history_saved'):
			add_to_history(selection['chosen'])
			selection['history_saved'] = True
			save_yaml(SELECTION_FILE, selection)

		return render_template(
			'results.html',
			chosen=selection.get('chosen', []),
			waiting=selection.get('waiting', []),
		)

@app.route('/cancel', methods=['GET', 'POST'])
def cancel():
	if request.method == 'POST':
		email = request.form['email'].lower()

		with lock:
			# ────────────── SIGNUP PHASE ──────────────
			if in_signup_window():
				signups = load_yaml(SIGNUPS_FILE).get('signups', [])
				new_signups = [s for s in signups if s['email'].lower() != email]

				if len(new_signups) == len(signups):
					flash("Email not found in signup list.")
				else:
					save_yaml(SIGNUPS_FILE, {'signups': new_signups})
					flash("You have been removed from the signup list.")

				return redirect('/')

			# ────────────── POST-SIGNUP PHASE ──────────────
			if over_cancel_deadline():
				flash("Cancellation deadline passed.")
				return redirect('/')

			selection = load_yaml(SELECTION_FILE)
			chosen = selection.get('chosen', [])
			waiting = selection.get('waiting', [])

			for p in chosen:
				if p['email'].lower() == email:
					chosen.remove(p)
					if waiting:
						idx = choose_indices(waiting, 1)
						promoted = waiting.pop(idx[0])
						chosen.append(promoted)
						flash(f"{p['first_name']} cancelled. {promoted['email']} promoted from waitlist. Please inform them of your cancellation.")
					else:
						flash(f"{p['first_name']} cancelled.")
					save_yaml(SELECTION_FILE, {
						'chosen': chosen,
						'waiting': waiting,
						'history_saved': selection.get('history_saved', False),
					})
					return redirect('/')

			for p in waiting:
				if p['email'].lower() == email:
					waiting.remove(p)
					save_yaml(SELECTION_FILE, {
						'chosen': chosen,
						'waiting': waiting,
						'history_saved': selection.get('history_saved', False),
					})
					flash("You have been removed from the waiting list.")
					return redirect('/')

			flash("Email not found in signup list.")
			return redirect('/')

	return render_template('cancel.html')

@app.route('/admin', methods=['GET'])
def admin():
	with lock:
		cfg = get_config()
	return render_template('admin.html', cfg=cfg)

@app.route('/admin/rerun', methods=['POST'])
def admin_rerun():
	with lock:
		# Load selection
		selection = load_yaml(SELECTION_FILE)
		chosen = selection.get('chosen', [])
		waiting = selection.get('waiting', [])
		history_saved = selection.get('history_saved', False)

		# Only allow rerun if signup window is closed and cancel deadline not reached
		if in_signup_window():
			flash("Cannot rerun selection during signup window.")
			return redirect('/admin')
		if over_cancel_deadline():
			flash("Cannot rerun selection after cancellation deadline.")
			return redirect('/admin')

		# Combine current chosen + waiting for rerun
		all_candidates = chosen + waiting
		if not all_candidates:
			flash("No participants to rerun selection.")
			return redirect('/admin')

		# Select new participants
		cap = get_config()['lesson']['capacity']
		indices = choose_indices(all_candidates, cap)
		new_chosen = [all_candidates[i] for i in indices]
		new_waiting = [all_candidates[i] for i in range(len(all_candidates)) if i not in indices]

		# Save updated selection, keep history_saved flag
		save_yaml(SELECTION_FILE, {
			'chosen': new_chosen,
			'waiting': new_waiting,
			'history_saved': history_saved,
		})

	flash("Selection rerun successfully.")
	return redirect('/admin')

@app.route('/admin/config', methods=['POST'])
def admin_update_config():
	with lock:
		cfg = get_config()

		cfg['signup']['weekday'] = request.form['signup_weekday'].strip()
		cfg['signup']['start'] = request.form['signup_start'].strip()
		cfg['signup']['end'] = request.form['signup_end'].strip()

		cfg['lesson']['weekday'] = request.form['lesson_weekday'].strip()
		cfg['lesson']['time'] = request.form['lesson_time'].strip()
		cfg['lesson']['capacity'] = int(request.form['lesson_capacity'])
		cfg['lesson']['cancel_deadline_hours'] = int(request.form['cancel_deadline_hours'])

		cfg['email'] = [d.strip() for d in request.form['email_domains'].splitlines() if d.strip()]

		cfg['algorithm']['name'] = request.form['algorithm_name']
		cfg['algorithm']['weight_exponent'] = float(request.form['weight_exponent'])

		save_yaml(CONFIG_FILE, cfg)

	flash("Configuration updated successfully.")
	return redirect('/admin')

if __name__ == '__main__':
	app.run(host='0.0.0.0', port=8000)