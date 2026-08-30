"""Generate a synthetic JSON file matching the shape of export.py output.

Used for offline frontend development before any real intraday data is
captured. The 20 sectors and their close-of-day values are synthetic demo
values for exercising the configured watchlist.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path

# (name, close_main_net_in_yi). Close values approximated from ss4.png.
DEFAULT_SECTORS: list[tuple[str, float]] = [
    ("人形机器人", 54.20),
    ("光模块", 43.50),
    ("CPO概念", 23.99),
    ("消费电子", 12.34),
    ("商业航天", 6.77),
    ("PCB概念", -38.04),
    ("算力芯片", -56.41),
    ("有色金属", -73.62),
    ("人工智能", -119.36),
    ("存储芯片", -134.26),
    ("固态电池", -178.56),
    ("电力设备", -199.76),
    ("储能", -211.50),
    ("创新药", 18.40),
    ("半导体设备", 34.10),
    ("半导体", 28.80),
    ("芯片", 16.50),
    ("黄金", 11.20),
    ("白银", -4.80),
    ("石油", -18.60),
]

INFLOW_COLOR = "#d62728"
OUTFLOW_COLOR = "#1f77b4"

SESSION_MINUTES = 240
TICKS = [
    {"value": 0, "label": "9:30"},
    {"value": 60, "label": "10:30"},
    {"value": 119, "label": "11:30"},
    {"value": 180, "label": "14:00"},
    {"value": 239, "label": "15:00"},
]


def synth_walk(close_target: float, *, rng: random.Random) -> list[float]:
    """A noisy walk that starts near 0 and lands at close_target."""
    n = SESSION_MINUTES
    # Drift component: sigmoid-ish ramp so the bulk of motion happens in the
    # second half of the day — mirrors how the original ss1→ss4 fans out.
    drift = []
    for i in range(n):
        # Logistic from 0 to 1, midpoint ~ 60% through the session.
        t = (i - n * 0.6) / (n * 0.18)
        drift.append(close_target / (1 + math.exp(-t)))
    # Anchor drift to start at exactly 0 (first sample sits at the origin).
    zero = drift[0]
    drift = [d - zero for d in drift]

    # Brownian noise scaled to target magnitude.
    noise_amp = max(abs(close_target) * 0.06, 0.5)
    walk = []
    cum = 0.0
    for i in range(n):
        step = rng.gauss(0, noise_amp / math.sqrt(n)) * 4
        cum += step
        walk.append(drift[i] + cum)

    # Force the last point to land exactly on the target by linearly
    # absorbing the residual back across the series.
    residual = walk[-1] - close_target
    walk = [v - residual * (i + 1) / n for i, v in enumerate(walk)]
    return [round(v, 3) for v in walk]


def build(seed: int = 42) -> dict:
    rng = random.Random(seed)
    series = []
    for i, (name, close) in enumerate(DEFAULT_SECTORS):
        color = INFLOW_COLOR if close >= 0 else OUTFLOW_COLOR
        series.append(
            {
                "name": name,
                "code": f"MOCK{i:04d}",
                "color": color,
                "data": synth_walk(close, rng=rng),
            }
        )
    return {
        "trade_date": "mock",
        "title": "资金实时分时流向 (mock)",
        "session_minutes": SESSION_MINUTES,
        "ticks": TICKS,
        "series": series,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("-o", "--out", default="data/mock.json")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = build(seed=args.seed)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"wrote {out}: {len(payload['series'])} series × {payload['session_minutes']} points")


if __name__ == "__main__":
    main()
