"""Long-running collector: every trading minute, snapshot sector fund flow."""
from __future__ import annotations

import argparse
import logging
import random
import time
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path

import db
import export
import providers

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


def sleep_until_next_poll_with_jitter(
    *, interval_seconds: int = 60, max_jitter_s: float = 10.0
) -> None:
    now = now_cn()
    interval_seconds = max(1, int(interval_seconds))
    epoch = int(now.timestamp())
    next_epoch = ((epoch // interval_seconds) + 1) * interval_seconds
    next_poll = datetime.fromtimestamp(next_epoch, tz=CN)
    target = next_poll + timedelta(seconds=random.uniform(0, max_jitter_s))
    delay = (target - now_cn()).total_seconds()
    if delay > 0:
        time.sleep(delay)


def sleep_until_next_minute_with_jitter(*, max_jitter_s: float = 10.0) -> None:
    """Backward-compatible one-minute sleep helper."""
    sleep_until_next_poll_with_jitter(max_jitter_s=max_jitter_s)


def run_once(
    *,
    db_path: Path,
    config: dict | None = None,
    config_path: Path = Path("config.yaml"),
    output_dir: Path = Path("data"),
    provider: str | None = None,
    now: datetime | None = None,
) -> int:
    """Collect one tick. Returns rows written, or 0 if outside trading window."""
    config = config if config is not None else export.load_config(config_path)
    provider_name = provider or config.get("provider", "sina")
    ts = (now or now_cn()).replace(second=0, microsecond=0)
    sm = to_session_minute(ts)
    if sm is None:
        return 0

    db.init(db_path)
    rows: list[dict] = []
    for st in ("industry", "concept"):
        rows.extend(
            providers.fetch_sector_snapshot(
                st,
                provider=provider_name,
                config=config,
            )
        )
    n = db.upsert(
        rows,
        trade_date=ts.date().isoformat(),
        ts=ts.strftime("%Y-%m-%d %H:%M:%S"),
        session_min=sm,
        db_path=db_path,
    )
    if n:
        payload = export.build(
            trade_date=ts.date().isoformat(),
            db_path=db_path,
            config=config,
        )
        export.write_payload(payload, output_dir / f"{ts.date().isoformat()}.json")
    return n


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(db.DEFAULT_DB_PATH), help="SQLite path")
    parser.add_argument(
        "--until",
        default=COLLECTOR_HARD_STOP.strftime("%H:%M"),
        help="HH:MM (CN time) hard stop. Default 15:05.",
    )
    parser.add_argument("--config", default="config.yaml", help="YAML config path")
    parser.add_argument(
        "--provider",
        choices=("sina", "ths", "eastmoney"),
        default=None,
        help="Data provider; default comes from config.yaml (ths, sina, eastmoney)",
    )
    parser.add_argument("--output-dir", default="data", help="Export JSON directory")
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=None,
        help="Polling interval; default comes from config.yaml",
    )
    args = parser.parse_args()
    db_path = Path(args.db)
    config = export.load_config(Path(args.config))
    provider = args.provider or config.get("provider", "sina")
    interval_seconds = args.interval_seconds or int(config.get("poll_interval_seconds", 300))
    until_h, until_m = (int(x) for x in args.until.split(":"))
    until_dt = dtime(until_h, until_m)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    log = logging.getLogger("collector")

    db.init(db_path)
    log.info(
        "collector started, provider=%s, db=%s, interval=%ss, hard_stop=%s CN",
        provider,
        db_path,
        interval_seconds,
        until_dt,
    )

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
                n = run_once(
                    db_path=db_path,
                    config=config,
                    output_dir=Path(args.output_dir),
                    provider=provider,
                )
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

        sleep_until_next_poll_with_jitter(interval_seconds=interval_seconds)


if __name__ == "__main__":
    main()
