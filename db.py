"""SQLite storage for sector fund flow ticks."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Mapping

DEFAULT_DB_PATH = Path(__file__).parent / "data" / "sector_fund_flow.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sector_fund_flow_tick (
    trade_date    TEXT    NOT NULL,
    ts            TEXT    NOT NULL,
    session_min   INTEGER NOT NULL,
    sector_type   TEXT    NOT NULL,
    sector_code   TEXT    NOT NULL,
    sector_name   TEXT    NOT NULL,
    pct_chg       REAL,
    main_net      REAL,
    super_net     REAL,
    big_net       REAL,
    mid_net       REAL,
    small_net     REAL,
    raw_json      TEXT,
    PRIMARY KEY (trade_date, session_min, sector_type, sector_code)
);
CREATE INDEX IF NOT EXISTS idx_date_name
    ON sector_fund_flow_tick (trade_date, sector_name);
"""


@contextmanager
def connect(db_path: str | Path = DEFAULT_DB_PATH):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def upsert(
    rows: Iterable[Mapping],
    *,
    trade_date: str,
    ts: str,
    session_min: int,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    """Insert rows for a single (trade_date, ts, session_min) tick.

    Each row dict must have: sector_type, code, name, pct_chg, main_net,
    super_net, big_net, mid_net, small_net, raw.
    """
    payload = [
        (
            trade_date,
            ts,
            session_min,
            r["sector_type"],
            r["code"],
            r["name"],
            r.get("pct_chg"),
            r.get("main_net"),
            r.get("super_net"),
            r.get("big_net"),
            r.get("mid_net"),
            r.get("small_net"),
            r.get("raw"),
        )
        for r in rows
    ]
    if not payload:
        return 0
    with connect(db_path) as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO sector_fund_flow_tick (
                trade_date, ts, session_min, sector_type,
                sector_code, sector_name, pct_chg, main_net,
                super_net, big_net, mid_net, small_net, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            payload,
        )
    return len(payload)


def fetch_for_date(
    trade_date: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
):
    with connect(db_path) as conn:
        cur = conn.execute(
            """
            SELECT session_min, sector_type, sector_code, sector_name,
                   pct_chg, main_net
              FROM sector_fund_flow_tick
             WHERE trade_date = ?
             ORDER BY session_min, sector_code
            """,
            (trade_date,),
        )
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
