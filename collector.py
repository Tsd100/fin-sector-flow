"""Long-running collector: every trading minute, snapshot sector fund flow."""
from __future__ import annotations

import argparse
import logging
import random
import time
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path

import db
import eastmoney

CN = timezone(timedelta(hours=8))

# Trading sessions: morning 09:30-11:30, afternoon 13:00-15:00.
# We sample at the *end* of each minute, so the first sample is 09:31 and the
# last is 15:00. session_min indexes 0..239 (240 samples per day, no gap).
SESSION_OPEN = dtime(9, 31)
MORNING_CLOSE = dtime(11, 30)
AFTERNOON_OPEN = dtime(13, 1)
SESSION_CLOSE = dtime(15, 0)
COLLECTOR_HARD_STOP = dtime(15, 5)


def now_cn() -> datetime:
    return datetime.now(tz=CN)


def to_session_minute(ts: datetime) -> int | None:
    """Map a wall-clock minute to a session-minute index in [0, 239].

    09:31 -> 0 ... 11:30 -> 119
    13:01 -> 120 ... 15:00 -> 239
    """
    t = dtime(ts.hour, ts.minute)
    if SESSION_OPEN <= t <= MORNING_CLOSE:
        return (ts.hour - 9) * 60 + ts.minute - 31
    if AFTERNOON_OPEN <= t <= SESSION_CLOSE:
        return 120 + (ts.hour - 13) * 60 + ts.minute - 1
    return None


def sleep_until_next_minute_with_jitter(*, max_jitter_s: float = 10.0) -> None:
    now = now_cn()
    next_minute = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
    target = next_minute + timedelta(seconds=random.uniform(0, max_jitter_s))
    delay = (target - now_cn()).total_seconds()
    if delay > 0:
        time.sleep(delay)


def run_once(*, db_path: Path) -> int:
    """Collect one tick. Returns rows written, or 0 if outside trading window."""
    ts = now_cn().replace(second=0, microsecond=0)
    sm = to_session_minute(ts)
    if sm is None:
        return 0

    rows: list[dict] = []
    for st in ("industry", "concept"):
        rows.extend(eastmoney.fetch_sector_snapshot(st))
    n = db.upsert(
        rows,
        trade_date=ts.date().isoformat(),
        ts=ts.strftime("%Y-%m-%d %H:%M:%S"),
        session_min=sm,
        db_path=db_path,
    )
    return n


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(db.DEFAULT_DB_PATH), help="SQLite path")
    parser.add_argument(
        "--until",
        default=COLLECTOR_HARD_STOP.strftime("%H:%M"),
        help="HH:MM (CN time) hard stop. Default 15:05.",
    )
    args = parser.parse_args()
    db_path = Path(args.db)
    until_h, until_m = (int(x) for x in args.until.split(":"))
    until_dt = dtime(until_h, until_m)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    log = logging.getLogger("collector")

    db.init(db_path)
    log.info("collector started, db=%s, hard_stop=%s CN", db_path, until_dt)

    consecutive_failures = 0
    while True:
        ts = now_cn()
        if ts.time() >= until_dt:
            log.info("reached hard stop %s, exiting", until_dt)
            return

        sm = to_session_minute(ts.replace(second=0, microsecond=0))
        if sm is None:
            log.info("%s | outside trading window, sleep", ts.strftime("%H:%M"))
        else:
            try:
                n = run_once(db_path=db_path)
                consecutive_failures = 0
                log.info("%s sm=%d | saved %d rows", ts.strftime("%H:%M"), sm, n)
            except Exception as e:
                consecutive_failures += 1
                log.warning(
                    "%s sm=%d | FETCH FAIL #%d: %s",
                    ts.strftime("%H:%M"),
                    sm,
                    consecutive_failures,
                    e,
                )
                if consecutive_failures >= 5:
                    log.error(
                        "5 consecutive failures — main loop continues but check the network/API"
                    )

        sleep_until_next_minute_with_jitter()


if __name__ == "__main__":
    main()
