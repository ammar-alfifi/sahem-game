"""
سهم — إعداد قاعدة البيانات (SQLite)
الجداول وفق القسم 6 من GAME_DESIGN.md
"""
import sqlite3
import os

DB_PATH = os.getenv("DB_PATH", "sahem.db")

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  telegram_id INTEGER UNIQUE NOT NULL,
  username TEXT,
  coins_balance REAL NOT NULL DEFAULT 100000,
  level INTEGER NOT NULL DEFAULT 1,
  xp INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS positions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  symbol TEXT NOT NULL,
  market TEXT NOT NULL,
  quantity REAL NOT NULL DEFAULT 0,
  avg_cost REAL NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(user_id, symbol, market)
);

CREATE TABLE IF NOT EXISTS prices (
  symbol TEXT NOT NULL,
  market TEXT NOT NULL,
  price REAL NOT NULL,
  prev_close REAL,
  change_pct REAL,
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (symbol, market)
);

CREATE TABLE IF NOT EXISTS candles (
  symbol TEXT NOT NULL,
  market TEXT NOT NULL,
  ts TEXT NOT NULL,
  open REAL, high REAL, low REAL, close REAL, volume REAL,
  PRIMARY KEY (symbol, market, ts)
);

CREATE TABLE IF NOT EXISTS predictions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  symbol TEXT NOT NULL,
  market TEXT NOT NULL,
  direction TEXT NOT NULL,          -- up / down / flat
  predicted_at TEXT NOT NULL DEFAULT (datetime('now')),
  resolves_at TEXT NOT NULL,
  result TEXT,                      -- win / lose / pending
  points REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS arcade_rounds (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  scenario_seed TEXT,
  start_ts TEXT NOT NULL,
  end_ts TEXT NOT NULL,
  capital REAL NOT NULL DEFAULT 100000,
  final_value REAL,
  rank TEXT,
  played_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS transactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  symbol TEXT NOT NULL,
  market TEXT NOT NULL,
  side TEXT NOT NULL,               -- buy / sell
  quantity REAL NOT NULL,
  price REAL NOT NULL,
  fee REAL NOT NULL DEFAULT 0,
  executed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS leagues (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  scope TEXT NOT NULL,
  period_start TEXT NOT NULL,
  period_end TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_predictions_resolve ON predictions(resolves_at, result);
CREATE INDEX IF NOT EXISTS idx_arcade_user ON arcade_rounds(user_id, played_at);
"""


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"DB initialized at {DB_PATH}")
