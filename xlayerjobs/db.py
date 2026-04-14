import sqlite3
import time
from pathlib import Path
from typing import Optional


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def initialize(db_path: Path) -> None:
    conn = _connect(db_path)
    with conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                poster TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                reward_usdt REAL NOT NULL,
                deadline INTEGER NOT NULL,
                required_skills TEXT NOT NULL DEFAULT '',
                state TEXT NOT NULL DEFAULT 'open',
                assigned_to TEXT,
                escrow_id INTEGER,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS bids (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL REFERENCES jobs(id),
                bidder TEXT NOT NULL,
                message TEXT NOT NULL DEFAULT '',
                delivery_time_hours INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS reputation (
                address TEXT PRIMARY KEY,
                jobs_completed INTEGER NOT NULL DEFAULT 0,
                jobs_failed INTEGER NOT NULL DEFAULT 0,
                jobs_disputed INTEGER NOT NULL DEFAULT 0,
                avg_delivery_hours REAL NOT NULL DEFAULT 0.0,
                total_earned_usd REAL NOT NULL DEFAULT 0.0,
                total_spent_usd REAL NOT NULL DEFAULT 0.0
            );
        """)
    conn.close()


def insert_job(db_path: Path, data: dict) -> int:
    conn = _connect(db_path)
    with conn:
        cur = conn.execute(
            """INSERT INTO jobs (poster, title, description, reward_usdt, deadline,
               required_skills, state, created_at)
               VALUES (:poster, :title, :description, :reward_usdt, :deadline,
               :required_skills, :state, :created_at)""",
            {
                "poster": data["poster"],
                "title": data["title"],
                "description": data["description"],
                "reward_usdt": data["reward_usdt"],
                "deadline": data["deadline"],
                "required_skills": data.get("required_skills", ""),
                "state": data.get("state", "open"),
                "created_at": data.get("created_at", int(time.time())),
            },
        )
        return cur.lastrowid
    conn.close()


def get_job(db_path: Path, job_id: int) -> Optional[dict]:
    conn = _connect(db_path)
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_jobs(db_path: Path, state: Optional[str] = None) -> list[dict]:
    conn = _connect(db_path)
    if state:
        rows = conn.execute("SELECT * FROM jobs WHERE state = ? ORDER BY created_at DESC", (state,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_job(db_path: Path, job_id: int, data: dict) -> None:
    if not data:
        return
    conn = _connect(db_path)
    fields = ", ".join(f"{k} = :{k}" for k in data)
    data["_id"] = job_id
    with conn:
        conn.execute(f"UPDATE jobs SET {fields} WHERE id = :_id", data)
    conn.close()


def insert_bid(db_path: Path, data: dict) -> int:
    conn = _connect(db_path)
    with conn:
        cur = conn.execute(
            """INSERT INTO bids (job_id, bidder, message, delivery_time_hours, created_at)
               VALUES (:job_id, :bidder, :message, :delivery_time_hours, :created_at)""",
            {
                "job_id": data["job_id"],
                "bidder": data["bidder"],
                "message": data.get("message", ""),
                "delivery_time_hours": data["delivery_time_hours"],
                "created_at": data.get("created_at", int(time.time())),
            },
        )
        return cur.lastrowid
    conn.close()


def get_bids_for_job(db_path: Path, job_id: int) -> list[dict]:
    conn = _connect(db_path)
    rows = conn.execute(
        "SELECT * FROM bids WHERE job_id = ? ORDER BY created_at ASC", (job_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def upsert_reputation(db_path: Path, data: dict) -> None:
    conn = _connect(db_path)
    with conn:
        existing = conn.execute(
            "SELECT * FROM reputation WHERE address = ?", (data["address"],)
        ).fetchone()
        if existing:
            fields = ", ".join(f"{k} = :{k}" for k in data if k != "address")
            data_copy = dict(data)
            conn.execute(
                f"UPDATE reputation SET {fields} WHERE address = :address", data_copy
            )
        else:
            conn.execute(
                """INSERT INTO reputation (address, jobs_completed, jobs_failed,
                   jobs_disputed, avg_delivery_hours, total_earned_usd, total_spent_usd)
                   VALUES (:address, :jobs_completed, :jobs_failed, :jobs_disputed,
                   :avg_delivery_hours, :total_earned_usd, :total_spent_usd)""",
                {
                    "address": data["address"],
                    "jobs_completed": data.get("jobs_completed", 0),
                    "jobs_failed": data.get("jobs_failed", 0),
                    "jobs_disputed": data.get("jobs_disputed", 0),
                    "avg_delivery_hours": data.get("avg_delivery_hours", 0.0),
                    "total_earned_usd": data.get("total_earned_usd", 0.0),
                    "total_spent_usd": data.get("total_spent_usd", 0.0),
                },
            )
    conn.close()


def get_reputation(db_path: Path, address: str) -> Optional[dict]:
    conn = _connect(db_path)
    row = conn.execute(
        "SELECT * FROM reputation WHERE address = ?", (address,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_reputations(db_path: Path) -> list[dict]:
    conn = _connect(db_path)
    rows = conn.execute("SELECT * FROM reputation").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_leaderboard(db_path: Path, limit: int = 10) -> list[dict]:
    conn = _connect(db_path)
    rows = conn.execute(
        """SELECT * FROM reputation ORDER BY jobs_completed DESC, total_earned_usd DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
