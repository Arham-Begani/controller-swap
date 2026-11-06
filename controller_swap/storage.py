import json
import sqlite3
from pathlib import Path
from threading import RLock


class Store:
    def __init__(self, path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS predictions (run_id TEXT, method TEXT, view TEXT, payload TEXT NOT NULL, PRIMARY KEY(run_id,method,view))")
        self.db.execute("CREATE TABLE IF NOT EXISTS evaluation_attempts (payload TEXT NOT NULL)")
        self.db.commit()

    def put(self, run):
        with self.lock, self.db:
            self.db.execute("INSERT INTO runs VALUES (?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", (run["id"], json.dumps(run)))

    def get(self, run_id):
        with self.lock:
            row = self.db.execute("SELECT payload FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            raise KeyError("Session not found")
        return json.loads(row[0])

    def runs(self):
        with self.lock:
            return [json.loads(r[0]) for r in self.db.execute("SELECT payload FROM runs ORDER BY rowid")]

    def predictions(self):
        with self.lock:
            return [json.loads(r[0]) for r in self.db.execute("SELECT payload FROM predictions ORDER BY rowid")]

    def put_predictions(self, predictions):
        with self.lock, self.db:
            for p in predictions:
                self.db.execute("INSERT INTO predictions VALUES (?,?,?,?) ON CONFLICT(run_id,method,view) DO UPDATE SET payload=excluded.payload", (p["run_id"], p["method"], p["view"], json.dumps(p)))

    def put_attempt(self, attempt):
        with self.lock, self.db:
            self.db.execute("INSERT INTO evaluation_attempts VALUES (?)", (json.dumps(attempt),))

    def attempts(self):
        with self.lock:
            return [json.loads(r[0]) for r in self.db.execute("SELECT payload FROM evaluation_attempts ORDER BY rowid")]

    def close(self):
        self.db.close()
