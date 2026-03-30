# Catering Finance App

A simple web app to track labour and expenses for a catering business — event by event.

---

## Setup & Run (5 minutes)

### 1. Make sure Python is installed
```
python --version   # should be 3.8 or above
```

### 2. Install Flask
```
pip install flask
```

### 3. Run the app
```
cd catering-app
python app.py
```

### 4. Open in browser
```
http://localhost:5000
```

That's it. The database (`catering.db`) is created automatically in the same folder.

---

## Folder Structure

```
catering-app/
├── app.py              ← Backend (Flask API + server)
├── catering.db         ← SQLite database (auto-created)
├── requirements.txt    ← Python dependencies
└── templates/
    └── index.html      ← Full frontend (single file)
```

---

## How to Use

1. **Add an Event** — click "+ Add Event", enter event name, client name, date
2. **Open the Event** — click on it from the list
3. **Add Labour** — enter worker name, rate per day, days worked → total auto-calculates
4. **Add Expenses** — choose category (kirana/vendor/transport/etc.), name, amount
5. **See Summary** — scroll to bottom to see total labour, total expenses, and category breakdown
6. **Switch Language** — click EN / HI in the top right to toggle Hindi/English

---

## Language Support

- English and Hindi supported
- Toggle with the EN / HI button in the top bar
- All labels switch instantly

---

## Data

- All data is stored locally in `catering.db` (SQLite)
- No internet required after first load (fonts load from Google Fonts)
- No login or accounts needed
