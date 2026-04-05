from flask import Flask, request, jsonify, send_from_directory
import sqlite3, os, datetime

app = Flask(__name__, static_folder='static', template_folder='templates')
DB = os.environ.get('DB_PATH', 'catering.db')

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS event (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                client_name TEXT NOT NULL,
                date TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS labour (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL REFERENCES event(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                rate_per_day REAL NOT NULL DEFAULT 0,
                days_worked REAL NOT NULL DEFAULT 0,
                total_pay REAL NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS expense (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL REFERENCES event(id) ON DELETE CASCADE,
                category TEXT NOT NULL,
                name TEXT NOT NULL,
                item TEXT,
                amount REAL NOT NULL DEFAULT 0,
                date TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                quantity REAL NOT NULL DEFAULT 0,
                unit TEXT NOT NULL DEFAULT 'piece',
                expiry_date TEXT,
                notes TEXT,
                added_date TEXT NOT NULL
            );
        """)
        # migrations — safe on existing DB
        def add_col(table, col, defn):
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            if col not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {defn}")

        add_col('expense', 'quantity', "TEXT DEFAULT ''")
        add_col('expense', 'status',   "TEXT DEFAULT 'due'")
        add_col('expense', 'timestamp',"TEXT DEFAULT ''")
        add_col('labour',  'status',   "TEXT DEFAULT 'due'")
        add_col('labour',  'timestamp',"TEXT DEFAULT ''")
        conn.commit()

init_db()

@app.route('/')
def index():
    return send_from_directory('templates', 'index.html')

# ---------- EVENTS ----------
@app.route('/api/events', methods=['GET'])
def list_events():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM event ORDER BY date DESC").fetchall()
        events = []
        for r in rows:
            e = dict(r)
            labour_total   = conn.execute("SELECT COALESCE(SUM(total_pay),0) FROM labour  WHERE event_id=?", (e['id'],)).fetchone()[0]
            expense_total  = conn.execute("SELECT COALESCE(SUM(amount),0)   FROM expense WHERE event_id=?", (e['id'],)).fetchone()[0]
            e['total_labour']   = labour_total
            e['total_expenses'] = expense_total
            e['total_cost']     = labour_total + expense_total
            events.append(e)
    return jsonify(events)

@app.route('/api/events', methods=['POST'])
def create_event():
    d = request.json
    with get_db() as conn:
        cur = conn.execute("INSERT INTO event (name, client_name, date) VALUES (?,?,?)",
                           (d['name'], d['client_name'], d['date']))
        conn.commit()
        row = conn.execute("SELECT * FROM event WHERE id=?", (cur.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201

@app.route('/api/events/<int:eid>', methods=['GET'])
def get_event(eid):
    with get_db() as conn:
        ev = conn.execute("SELECT * FROM event WHERE id=?", (eid,)).fetchone()
        if not ev: return jsonify({'error': 'Not found'}), 404

        all_labour   = [dict(r) for r in conn.execute(
            "SELECT * FROM labour WHERE event_id=? ORDER BY id", (eid,)).fetchall()]
        due_labour   = [l for l in all_labour if l.get('status','due') in ('due','')]

        due_expenses = [dict(r) for r in conn.execute(
            "SELECT * FROM expense WHERE event_id=? AND (status='due' OR status IS NULL OR status='') ORDER BY timestamp DESC, id DESC", (eid,)).fetchall()]
        all_expenses = [dict(r) for r in conn.execute(
            "SELECT * FROM expense WHERE event_id=? ORDER BY timestamp DESC, id DESC", (eid,)).fetchall()]

        # unified logs: labour + expenses, sorted by timestamp desc
        labour_logs = []
        for l in all_labour:
            labour_logs.append({
                'id': l['id'], 'type': 'labour',
                'name': l['name'], 'item': '',
                'quantity': '', 'category': 'labour',
                'amount': l['total_pay'],
                'status': l.get('status','due'),
                'timestamp': l.get('timestamp',''),
                'rate_per_day': l['rate_per_day'],
                'days_worked': l['days_worked'],
            })
        expense_logs = [dict(e, type='expense') for e in all_expenses]
        all_logs = sorted(labour_logs + expense_logs,
                          key=lambda x: x.get('timestamp',''), reverse=True)

        labour_total = sum(l['total_pay'] for l in all_labour)
        labour_due   = sum(l['total_pay'] for l in all_labour if l.get('status','due') in ('due',''))
        labour_paid  = sum(l['total_pay'] for l in all_labour if l.get('status') == 'paid')
        exp_paid     = sum(e['amount'] for e in all_expenses if e.get('status') == 'paid')
        exp_due      = sum(e['amount'] for e in all_expenses if e.get('status') in ('due', None, ''))
        expense_total = exp_paid + exp_due

        cat_totals = {}
        for ex in all_expenses:
            cat_totals[ex['category']] = cat_totals.get(ex['category'], 0) + ex['amount']

        return jsonify({
            'event':    dict(ev),
            'labour':   due_labour,
            'expenses': due_expenses,
            'logs':     all_logs,
            'summary': {
                'total_labour':   labour_total,
                'total_expenses': expense_total,
                'total_paid':     labour_paid + exp_paid,
                'total_due':      labour_due  + exp_due,
                'total_cost':     labour_total + expense_total,
                'category_totals': cat_totals
            }
        })

@app.route('/api/events/<int:eid>', methods=['DELETE'])
def delete_event(eid):
    with get_db() as conn:
        conn.execute("DELETE FROM labour  WHERE event_id=?", (eid,))
        conn.execute("DELETE FROM expense WHERE event_id=?", (eid,))
        conn.execute("DELETE FROM event   WHERE id=?",       (eid,))
        conn.commit()
    return jsonify({'ok': True})

# ---------- LABOUR ----------
@app.route('/api/events/<int:eid>/labour', methods=['POST'])
def add_labour(eid):
    d    = request.json
    rate = float(d.get('rate_per_day', 0))
    days = float(d.get('days_worked', 0))
    total= float(d.get('total_pay') or (rate * days))
    ts   = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO labour (event_id, name, rate_per_day, days_worked, total_pay, status, timestamp) VALUES (?,?,?,?,?,?,?)",
            (eid, d['name'], rate, days, total, 'due', ts))
        conn.commit()
        row = conn.execute("SELECT * FROM labour WHERE id=?", (cur.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201

@app.route('/api/labour/<int:lid>', methods=['DELETE'])
def delete_labour(lid):
    with get_db() as conn:
        conn.execute("DELETE FROM labour WHERE id=?", (lid,))
        conn.commit()
    return jsonify({'ok': True})

@app.route('/api/labour/<int:lid>/status', methods=['PATCH'])
def update_labour_status(lid):
    d = request.json
    with get_db() as conn:
        conn.execute("UPDATE labour SET status=? WHERE id=?", (d['status'], lid))
        conn.commit()
    return jsonify({'ok': True})

# ---------- EXPENSES ----------
@app.route('/api/events/<int:eid>/expenses', methods=['POST'])
def add_expense(eid):
    d  = request.json
    ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO expense (event_id, category, name, item, quantity, amount, status, timestamp, date) VALUES (?,?,?,?,?,?,?,?,?)",
            (eid, d['category'], d['name'], d.get('item',''), d.get('quantity',''),
             float(d['amount']), d.get('status','due'), ts, ts[:10]))
        conn.commit()
        row = conn.execute("SELECT * FROM expense WHERE id=?", (cur.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201

@app.route('/api/expenses/<int:xid>', methods=['DELETE'])
def delete_expense(xid):
    with get_db() as conn:
        conn.execute("DELETE FROM expense WHERE id=?", (xid,))
        conn.commit()
    return jsonify({'ok': True})

@app.route('/api/expenses/<int:xid>/status', methods=['PATCH'])
def update_expense_status(xid):
    d = request.json
    with get_db() as conn:
        conn.execute("UPDATE expense SET status=? WHERE id=?", (d['status'], xid))
        conn.commit()
    return jsonify({'ok': True})

# ---------- INVENTORY ----------
@app.route('/api/inventory', methods=['GET'])
def list_inventory():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM inventory ORDER BY name ASC").fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/inventory', methods=['POST'])
def add_inventory():
    d  = request.json
    ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO inventory (name, quantity, unit, expiry_date, notes, added_date) VALUES (?,?,?,?,?,?)",
            (d['name'], float(d.get('quantity',0)), d.get('unit','piece'),
             d.get('expiry_date') or None, d.get('notes',''), ts[:10]))
        conn.commit()
        row = conn.execute("SELECT * FROM inventory WHERE id=?", (cur.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201

@app.route('/api/inventory/<int:iid>', methods=['PATCH'])
def update_inventory(iid):
    d = request.json
    with get_db() as conn:
        conn.execute("UPDATE inventory SET quantity=?, unit=?, expiry_date=?, notes=? WHERE id=?",
                     (float(d['quantity']), d.get('unit','piece'),
                      d.get('expiry_date') or None, d.get('notes',''), iid))
        conn.commit()
        row = conn.execute("SELECT * FROM inventory WHERE id=?", (iid,)).fetchone()
    return jsonify(dict(row))

@app.route('/api/inventory/<int:iid>', methods=['DELETE'])
def delete_inventory(iid):
    with get_db() as conn:
        conn.execute("DELETE FROM inventory WHERE id=?", (iid,))
        conn.commit()
    return jsonify({'ok': True})

if __name__ == '__main__':
    import sys
    host = os.environ.get('HOST', '127.0.0.1')
    for arg in sys.argv[1:]:
        if arg.startswith('--host='):
            host = arg.split('=', 1)[1]
    app.run(debug=False, host=host, port=int(os.environ.get('PORT', 5000)))
