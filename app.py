from flask import Flask, request, jsonify, send_from_directory
import sqlite3, os, datetime

app = Flask(__name__, static_folder='static', template_folder='templates')
DB = 'catering.db'

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
        """)
        # V2 migrations — safe to run on existing DB
        existing_cols = [r[1] for r in conn.execute("PRAGMA table_info(expense)").fetchall()]
        if 'quantity' not in existing_cols:
            conn.execute("ALTER TABLE expense ADD COLUMN quantity TEXT DEFAULT ''")
        if 'status' not in existing_cols:
            conn.execute("ALTER TABLE expense ADD COLUMN status TEXT DEFAULT 'due'")
        if 'timestamp' not in existing_cols:
            conn.execute("ALTER TABLE expense ADD COLUMN timestamp TEXT DEFAULT ''")
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
            labour_total = conn.execute("SELECT COALESCE(SUM(total_pay),0) FROM labour WHERE event_id=?", (e['id'],)).fetchone()[0]
            expense_total = conn.execute("SELECT COALESCE(SUM(amount),0) FROM expense WHERE event_id=?", (e['id'],)).fetchone()[0]
            e['total_labour'] = labour_total
            e['total_expenses'] = expense_total
            e['total_cost'] = labour_total + expense_total
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

        labour = [dict(r) for r in conn.execute(
            "SELECT * FROM labour WHERE event_id=? ORDER BY id", (eid,)).fetchall()]

        due_expenses = [dict(r) for r in conn.execute(
            "SELECT * FROM expense WHERE event_id=? AND (status='due' OR status IS NULL OR status='') ORDER BY timestamp DESC, id DESC", (eid,)).fetchall()]

        all_expenses = [dict(r) for r in conn.execute(
            "SELECT * FROM expense WHERE event_id=? ORDER BY timestamp DESC, id DESC", (eid,)).fetchall()]

        labour_total = sum(l['total_pay'] for l in labour)
        total_paid = sum(e['amount'] for e in all_expenses if e.get('status') == 'paid')
        total_due = sum(e['amount'] for e in all_expenses if e.get('status') in ('due', None, ''))
        expense_total = total_paid + total_due

        cat_totals = {}
        for ex in all_expenses:
            cat_totals[ex['category']] = cat_totals.get(ex['category'], 0) + ex['amount']

        return jsonify({
            'event': dict(ev),
            'labour': labour,
            'expenses': due_expenses,
            'logs': all_expenses,
            'summary': {
                'total_labour': labour_total,
                'total_expenses': expense_total,
                'total_paid': total_paid,
                'total_due': total_due,
                'total_cost': labour_total + expense_total,
                'category_totals': cat_totals
            }
        })

@app.route('/api/events/<int:eid>', methods=['DELETE'])
def delete_event(eid):
    with get_db() as conn:
        conn.execute("DELETE FROM labour WHERE event_id=?", (eid,))
        conn.execute("DELETE FROM expense WHERE event_id=?", (eid,))
        conn.execute("DELETE FROM event WHERE id=?", (eid,))
        conn.commit()
    return jsonify({'ok': True})

# ---------- LABOUR ----------
@app.route('/api/events/<int:eid>/labour', methods=['POST'])
def add_labour(eid):
    d = request.json
    rate = float(d.get('rate_per_day', 0))
    days = float(d.get('days_worked', 0))
    total = float(d.get('total_pay') or (rate * days))
    with get_db() as conn:
        cur = conn.execute("INSERT INTO labour (event_id, name, rate_per_day, days_worked, total_pay) VALUES (?,?,?,?,?)",
                           (eid, d['name'], rate, days, total))
        conn.commit()
        row = conn.execute("SELECT * FROM labour WHERE id=?", (cur.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201

@app.route('/api/labour/<int:lid>', methods=['DELETE'])
def delete_labour(lid):
    with get_db() as conn:
        conn.execute("DELETE FROM labour WHERE id=?", (lid,))
        conn.commit()
    return jsonify({'ok': True})

# ---------- EXPENSES ----------
@app.route('/api/events/<int:eid>/expenses', methods=['POST'])
def add_expense(eid):
    d = request.json
    ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    status = d.get('status', 'due')
    quantity = d.get('quantity', '')
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO expense (event_id, category, name, item, quantity, amount, status, timestamp, date) VALUES (?,?,?,?,?,?,?,?,?)",
            (eid, d['category'], d['name'], d.get('item',''), quantity,
             float(d['amount']), status, ts, ts[:10]))
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

if __name__ == '__main__':
    app.run(debug=True, port=5000)
