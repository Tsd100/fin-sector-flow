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


def load_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_config(path: Path) -> dict:
    """Backward-compatible private alias for callers using the old helper."""
    return load_config(path)


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


def write_payload(payload: dict, out: Path) -> Path:
    """Write an exported payload as UTF-8 JSON and return its path."""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out


def build(*, trade_date: str, db_path: Path, config: dict) -> dict:
    rows = db.fetch_for_date(trade_date, db_path=db_path)
    if not rows:
        raise SystemExit(f"no data in DB for trade_date={trade_date}")

    df = pd.DataFrame(rows)
    df["main_net_yi"] = df["main_net"] / 1e8

    watchlist = _normalize_watchlist(config["watchlist"])
    name_to_color = {w["name"]: w["color"] for w in watchlist}
    target_names = [w["name"] for w in watchlist]
    last_observed_session = int(df["session_min"].max())

    # Pivot by the stable board code, not the display name. This keeps a line
    # continuous when Sina changes a board name during the trading day.
    wide = (
        df.pivot_table(
            index="session_min",
            columns="sector_code",
            values="main_net_yi",
            aggfunc="last",
        )
        .reindex(range(SESSION_MINUTES))
        .ffill()
    )
    wide.loc[wide.index > last_observed_session, :] = float("nan")

    inflow_color = config.get("inflow_color", "#d62728")
    outflow_color = config.get("outflow_color", "#1f77b4")

    series = []
    missing = []
    for name in target_names:
        candidates = df.loc[df["sector_name"] == name, ["sector_code", "main_net_yi"]]
        if candidates.empty:
            missing.append(name)
            continue

        # If the same display name exists in industry and concept data, use
        # the board code whose latest available absolute value is largest.
        scores = {}
        for code, group in candidates.groupby("sector_code", sort=False):
            values = group["main_net_yi"].dropna().tolist()
            scores[code] = abs(values[-1]) if values else float("-inf")
        code = max(scores, key=scores.get)
        if code not in wide.columns:
            missing.append(name)
            continue
        col = wide[code]
        # Replace NaN with None so JSON serializes as null.
        data = [None if pd.isna(v) else round(float(v), 3) for v in col.tolist()]
        # Color: explicit override > sign of close > default
        explicit = name_to_color.get(name)
        if explicit:
            color = explicit
        else:
            close = next((v for v in reversed(data) if v is not None), None)
            color = inflow_color if (close is not None and close >= 0) else outflow_color
        series.append({"name": name, "code": code, "color": color, "data": data})

    if missing:
        log.warning("watchlist sectors not found in DB: %s", missing)

    return {
        "trade_date": trade_date,
        "title": config.get("title", "资金实时分时流向"),
        "provider": config.get("provider", "sina"),
        "metric_label": config.get("metric_label", "板块净流入"),
        "updated_at": str(df["ts"].max()) if "ts" in df else None,
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

    config = load_config(Path(args.config))
    payload = build(trade_date=args.date, db_path=Path(args.db), config=config)

    out = Path(args.out) if args.out else Path("data") / f"{args.date}.json"
    write_payload(payload, out)
    print(f"wrote {out}: {len(payload['series'])} series × {payload['session_minutes']} points")


if __name__ == "__main__":
    main()
