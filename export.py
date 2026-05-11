"""Read collected ticks from SQLite and emit JSON for the ECharts viewer."""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pandas as pd
import yaml

import db

log = logging.getLogger("export")

SESSION_MINUTES = 240
TICKS = [
    {"value": 0, "label": "9:30"},
    {"value": 60, "label": "10:30"},
    {"value": 119, "label": "11:30"},
    {"value": 180, "label": "14:00"},
    {"value": 239, "label": "15:00"},
]


def _load_config(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f)


def _normalize_watchlist(raw) -> list[dict]:
    """Accept either ['name', ...] or [{'name': ..., 'color': ...}, ...]."""
    items = []
    for w in raw:
        if isinstance(w, str):
            items.append({"name": w, "color": None})
        elif isinstance(w, dict) and "name" in w:
            items.append({"name": w["name"], "color": w.get("color")})
        else:
            raise ValueError(f"bad watchlist entry: {w!r}")
    return items


def build(*, trade_date: str, db_path: Path, config: dict) -> dict:
    rows = db.fetch_for_date(trade_date, db_path=db_path)
    if not rows:
        raise SystemExit(f"no data in DB for trade_date={trade_date}")

    df = pd.DataFrame(rows)
    df["main_net_yi"] = df["main_net"] / 1e8

    watchlist = _normalize_watchlist(config["watchlist"])
    name_to_color = {w["name"]: w["color"] for w in watchlist}
    target_names = [w["name"] for w in watchlist]

    # Pivot: rows = session_min, columns = sector_name, values = main_net_yi.
    # If the same name appears under both industry+concept, keep the one with
    # the larger absolute close value (typically what users mean).
    df = df.drop_duplicates(subset=["session_min", "sector_name"], keep="last")
    wide = (
        df.pivot(index="session_min", columns="sector_name", values="main_net_yi")
        .reindex(range(SESSION_MINUTES))
        .ffill()
    )

    inflow_color = config.get("inflow_color", "#d62728")
    outflow_color = config.get("outflow_color", "#1f77b4")

    series = []
    missing = []
    for name in target_names:
        if name not in wide.columns:
            missing.append(name)
            continue
        col = wide[name]
        # Replace NaN with None so JSON serializes as null.
        data = [None if pd.isna(v) else round(float(v), 3) for v in col.tolist()]
        # Color: explicit override > sign of close > default
        explicit = name_to_color.get(name)
        if explicit:
            color = explicit
        else:
            close = next((v for v in reversed(data) if v is not None), None)
            color = inflow_color if (close is not None and close >= 0) else outflow_color
        # Find sector_code for stability/display
        codes = df.loc[df["sector_name"] == name, "sector_code"].unique().tolist()
        code = codes[0] if codes else ""
        series.append({"name": name, "code": code, "color": color, "data": data})

    if missing:
        log.warning("watchlist sectors not found in DB: %s", missing)

    return {
        "trade_date": trade_date,
        "title": config.get("title", "资金实时分时流向"),
        "session_minutes": SESSION_MINUTES,
        "ticks": TICKS,
        "series": series,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="trade date YYYY-MM-DD")
    parser.add_argument("-o", "--out", default=None, help="output JSON path (default data/<date>.json)")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--db", default=str(db.DEFAULT_DB_PATH))
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

    config = _load_config(Path(args.config))
    payload = build(trade_date=args.date, db_path=Path(args.db), config=config)

    out = Path(args.out) if args.out else Path("data") / f"{args.date}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"wrote {out}: {len(payload['series'])} series × {payload['session_minutes']} points")


if __name__ == "__main__":
    main()
