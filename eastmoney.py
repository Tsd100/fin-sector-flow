"""Thin client for EastMoney push2 sector-fund-flow snapshot.

We talk to push2 directly (instead of going through AKShare) so we can keep
the f12 (sector code) field, which AKShare's wrapper discards. f12 is used
as the stable join key when a sector is renamed mid-day.

Upstream caps each page at 100 rows regardless of pz, and the t:2/t:3
filters return ~496/~486 rows total, so we must paginate. We retry each
page individually; if any page fails after retries the whole call is
treated as failed (better to miss one minute than have a partial snapshot
with a gap in the middle of the rank list).
"""
from __future__ import annotations

import json
import logging
import math
import time
from typing import Literal

import requests

log = logging.getLogger(__name__)

PUSH2_URL = "https://push2.eastmoney.com/api/qt/clist/get"

# m:90 = sector market; t:2 = 行业 (industry), t:3 = 概念 (concept)
_FS = {"industry": "m:90 t:2", "concept": "m:90 t:3"}

# Field whitelist. f12=code, f14=name, f3=pct_chg, f62=main_net,
# f66/f72/f78/f84 = super/big/mid/small net. Trailing fields are kept
# for compatibility with the EastMoney UI's column set even if unused.
_FIELDS = "f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ),
    "Referer": "https://data.eastmoney.com/",
    "Accept": "*/*",
}

_RETRY_BACKOFFS = (0.5, 1.5, 3.0)
_PAGE_SIZE = 100  # upstream cap
_INTER_PAGE_SLEEP = 1.2  # seconds between page fetches; upstream rate-limits bursts


SectorType = Literal["industry", "concept"]


class EastMoneyError(RuntimeError):
    pass


def _request_page(sector_type: SectorType, page: int, *, timeout: float = 10.0) -> dict:
    """Fetch one page (1-indexed) with retry. Raises EastMoneyError on hard fail."""
    if sector_type not in _FS:
        raise ValueError(f"sector_type must be one of {list(_FS)}, got {sector_type!r}")
    params = {
        "pn": str(page),
        "pz": str(_PAGE_SIZE),
        "po": "1",
        "np": "1",
        "ut": "b2884a393a59ad64002292a3e90d46a5",
        "fltt": "2",
        "invt": "2",
        "fid": "f62",
        "fs": _FS[sector_type],
        "fields": _FIELDS,
        "_": int(time.time() * 1000),
    }
    last_err: Exception | None = None
    for i, backoff in enumerate((0.0,) + _RETRY_BACKOFFS):
        if backoff:
            time.sleep(backoff)
        try:
            r = requests.get(PUSH2_URL, params=params, headers=_HEADERS, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            last_err = e
            log.warning(
                "push2 %s page=%d attempt %d/%d failed: %s",
                sector_type, page, i + 1, len(_RETRY_BACKOFFS) + 1, e,
            )
    raise EastMoneyError(
        f"push2 {sector_type} page={page} failed after retries: {last_err}"
    ) from last_err


def _to_float(x):
    if x in (None, "-", ""):
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def fetch_sector_snapshot(sector_type: SectorType) -> list[dict]:
    """Return the current snapshot of sector fund flow (all pages).

    Each item:
        {sector_type, code, name, pct_chg, main_net, super_net, big_net,
         mid_net, small_net, raw}

    main_net / *_net are in **yuan** (元), not 亿. Convert at render time.

    EastMoney definition (verified empirically): main_net = super_net + big_net.
    Retail = mid_net + small_net = -main_net (every yuan flowing in must
    flow out from somewhere).
    """
    # Page 1 is mandatory: it tells us the total row count and contains the
    # highest-flow boards (most useful even on partial outages). If page 1
    # fails the whole call fails.
    first = _request_page(sector_type, page=1)
    data = first.get("data") or {}
    total = data.get("total") or 0
    pages = max(1, math.ceil(total / _PAGE_SIZE))

    diff = data.get("diff") or []
    if isinstance(diff, dict):
        diff = list(diff.values())
    all_diffs = list(diff)

    # Pages 2..N are best-effort: a single 502 should not nuke the whole
    # minute. Collector ffill handles transient gaps in the time series.
    failed_pages: list[int] = []
    for page in range(2, pages + 1):
        time.sleep(_INTER_PAGE_SLEEP)
        try:
            j = _request_page(sector_type, page=page)
        except EastMoneyError as e:
            failed_pages.append(page)
            log.warning("page %d skipped: %s", page, e)
            continue
        d = (j.get("data") or {}).get("diff") or []
        if isinstance(d, dict):
            d = list(d.values())
        all_diffs.extend(d)
    if failed_pages:
        log.warning(
            "%s: %d/%d pages missing %s — partial snapshot",
            sector_type, len(failed_pages), pages, failed_pages,
        )

    seen_codes: set[str] = set()
    out: list[dict] = []
    for row in all_diffs:
        code = row.get("f12")
        name = row.get("f14")
        if not code or not name:
            continue
        if code in seen_codes:  # defensive: drop dupes from page boundaries
            continue
        seen_codes.add(code)
        out.append(
            {
                "sector_type": sector_type,
                "code": code,
                "name": name,
                "pct_chg": _to_float(row.get("f3")),
                "main_net": _to_float(row.get("f62")),
                "super_net": _to_float(row.get("f66")),
                "big_net": _to_float(row.get("f72")),
                "mid_net": _to_float(row.get("f78")),
                "small_net": _to_float(row.get("f84")),
                "raw": json.dumps(row, ensure_ascii=False),
            }
        )
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
    for st in ("industry", "concept"):
        try:
            rows = fetch_sector_snapshot(st)
            print(f"{st}: {len(rows)} rows")
            for r in rows[:3]:
                print(f"  {r['code']} {r['name']:<12} pct={r['pct_chg']} main_net={r['main_net']:,.0f}")
        except EastMoneyError as e:
            print(f"{st}: FAILED {e}")
