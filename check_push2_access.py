#!/usr/bin/env python3
"""Standalone EastMoney push2 connectivity probe.

This script intentionally does not import project modules or third-party
packages, so it can be copied to a server and run with plain Python 3.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


PUSH2_URL = "https://push2.eastmoney.com/api/qt/clist/get"

# Same sector filters and fields used by eastmoney.py in this project.
SECTOR_FS = {
    "industry": "m:90 t:2",
    "concept": "m:90 t:3",
}
FIELDS = "f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ),
    "Referer": "https://data.eastmoney.com/",
    "Accept": "application/json,text/plain,*/*",
}


def build_url(sector_type: str) -> str:
    params = {
        "pn": "1",
        "pz": "500",
        "po": "1",
        "np": "1",
        "ut": "b2884a393a59ad64002292a3e90d46a5",
        "fltt": "2",
        "invt": "2",
        "fid": "f62",
        "fs": SECTOR_FS[sector_type],
        "fields": FIELDS,
        "_": int(time.time() * 1000),
    }
    return f"{PUSH2_URL}?{urllib.parse.urlencode(params)}"


def fetch_json(sector_type: str, timeout: float) -> tuple[dict, int, float, int, str]:
    url = build_url(sector_type)
    req = urllib.request.Request(url, headers=HEADERS)
    started = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
        elapsed_ms = (time.perf_counter() - started) * 1000
        charset = resp.headers.get_content_charset() or "utf-8"
        text = body.decode(charset, errors="replace")
        return json.loads(text), resp.status, elapsed_ms, len(body), url


def normalize_diff(payload: dict) -> list[dict]:
    data = payload.get("data") or {}
    diff = data.get("diff") or []
    if isinstance(diff, dict):
        return list(diff.values())
    if isinstance(diff, list):
        return diff
    return []


def probe(sector_type: str, timeout: float, samples: int) -> bool:
    print(f"\n== {sector_type} ==")
    try:
        payload, status, elapsed_ms, body_size, url = fetch_json(sector_type, timeout)
    except urllib.error.HTTPError as exc:
        body = exc.read(500).decode("utf-8", errors="replace")
        print(f"FAIL http_status={exc.code} reason={exc.reason}")
        print(f"url={build_url(sector_type)}")
        if body:
            print(f"body_head={body!r}")
        return False
    except urllib.error.URLError as exc:
        print(f"FAIL network_error={exc.reason!r}")
        print(f"url={build_url(sector_type)}")
        return False
    except TimeoutError as exc:
        print(f"FAIL timeout={exc!r}")
        print(f"url={build_url(sector_type)}")
        return False
    except json.JSONDecodeError as exc:
        print(f"FAIL json_decode_error={exc}")
        print(f"url={build_url(sector_type)}")
        return False

    rows = normalize_diff(payload)
    print(f"OK http_status={status} elapsed_ms={elapsed_ms:.0f} body_bytes={body_size}")
    print(f"rows={len(rows)} rc={payload.get('rc')} rt={payload.get('rt')}")
    print(f"url={url}")

    if not rows:
        print("WARN JSON returned, but data.diff is empty or missing.")
        print(f"top_level_keys={sorted(payload.keys())}")
        return False

    print("samples:")
    for row in rows[:samples]:
        code = row.get("f12")
        name = row.get("f14")
        pct_chg = row.get("f3")
        main_net = row.get("f62")
        print(f"  {code} {name} pct_chg={pct_chg} main_net_yuan={main_net}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Test EastMoney push2 API access.")
    parser.add_argument(
        "--sector",
        choices=("industry", "concept", "all"),
        default="all",
        help="Which sector endpoint to test. Default: all.",
    )
    parser.add_argument("--timeout", type=float, default=10.0, help="Request timeout seconds.")
    parser.add_argument("--samples", type=int, default=3, help="Number of sample rows to print.")
    args = parser.parse_args()

    sectors = ("industry", "concept") if args.sector == "all" else (args.sector,)
    results = [probe(sector, args.timeout, args.samples) for sector in sectors]
    if all(results):
        print("\nRESULT: push2 reachable and returned sector rows.")
        return 0
    print("\nRESULT: push2 probe failed or returned no rows. Check network, DNS, TLS, or market-time behavior.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
