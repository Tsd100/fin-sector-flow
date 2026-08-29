"""Client for Sina Finance sector money-flow snapshots."""
from __future__ import annotations

import json
import logging
import time
from typing import Literal, Mapping

import requests

log = logging.getLogger(__name__)

SINA_BOARD_FLOW_URL = (
    "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "MoneyFlow.ssl_bkzj_bk"
)
SINA_BOARD_FLOW_REFERER = "https://vip.stock.finance.sina.com.cn/moneyflow/"
FENLEI_BY_TYPE = {"industry": 0, "concept": 1}
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ),
    "Referer": SINA_BOARD_FLOW_REFERER,
    "Accept": "application/json,text/plain,*/*",
}
_RETRY_BACKOFFS = (0.5, 1.5, 3.0)
_PAGE_SIZE = 100
_MAX_PAGES = 20

SectorType = Literal["industry", "concept"]


class SinaError(RuntimeError):
    """Raised when Sina cannot provide the first page of a snapshot."""


def _to_float(value):
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_board_row(row: Mapping, sector_type: SectorType) -> dict:
    """Normalize one Sina board row to the project's storage shape."""
    if sector_type not in FENLEI_BY_TYPE:
        raise ValueError(f"sector_type must be one of {list(FENLEI_BY_TYPE)}, got {sector_type!r}")

    code = str(row.get("category") or "").strip()
    name = str(row.get("name") or "").strip()
    if not code or not name:
        raise ValueError(f"Sina board row has no category/name: {row!r}")

    pct_chg = _to_float(row.get("avg_changeratio"))
    return {
        "sector_type": sector_type,
        "code": code,
        "name": name,
        "pct_chg": pct_chg * 100 if pct_chg is not None else None,
        # Compatibility field: Sina's board netamount is total board net flow,
        # not EastMoney's main_net definition.
        "main_net": _to_float(row.get("netamount")),
        "super_net": None,
        "big_net": None,
        "mid_net": None,
        "small_net": None,
        "raw": json.dumps(row, ensure_ascii=False, separators=(",", ":")),
    }


def _request_page(
    sector_type: SectorType,
    page: int,
    *,
    session: requests.Session,
    timeout: float = 10.0,
    page_size: int = _PAGE_SIZE,
) -> list[dict]:
    if sector_type not in FENLEI_BY_TYPE:
        raise ValueError(f"sector_type must be one of {list(FENLEI_BY_TYPE)}, got {sector_type!r}")

    params = {
        "page": str(page),
        "num": str(page_size),
        "sort": "netamount",
        "asc": "0",
        "fenlei": str(FENLEI_BY_TYPE[sector_type]),
    }
    last_err: Exception | None = None
    for attempt, backoff in enumerate((0.0,) + _RETRY_BACKOFFS, start=1):
        if backoff:
            time.sleep(backoff)
        try:
            response = session.get(
                SINA_BOARD_FLOW_URL,
                params=params,
                headers=_HEADERS,
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise ValueError(f"expected JSON list, got {type(payload).__name__}")
            return payload
        except (requests.RequestException, ValueError, TypeError) as exc:
            last_err = exc
            log.warning(
                "Sina %s page=%d attempt %d/%d failed: %s",
                sector_type,
                page,
                attempt,
                len(_RETRY_BACKOFFS) + 1,
                exc,
            )

    raise SinaError(
        f"Sina {sector_type} page={page} failed after retries: {last_err}"
    ) from last_err


def fetch_board_snapshot(
    sector_type: SectorType,
    *,
    session: requests.Session | None = None,
    timeout: float = 10.0,
    page_size: int = _PAGE_SIZE,
    max_pages: int = _MAX_PAGES,
) -> list[dict]:
    """Return the current Sina board-flow snapshot with pagination."""
    client = session or requests.Session()
    first = _request_page(
        sector_type,
        1,
        session=client,
        timeout=timeout,
        page_size=page_size,
    )

    pages = [first]
    for page in range(2, max_pages + 1):
        if not pages[-1] or len(pages[-1]) < page_size:
            break
        try:
            current = _request_page(
                sector_type,
                page,
                session=client,
                timeout=timeout,
                page_size=page_size,
            )
        except SinaError as exc:
            log.warning("Sina %s partial snapshot: page %d skipped: %s", sector_type, page, exc)
            break
        if not current:
            break
        pages.append(current)

    seen_codes: set[str] = set()
    normalized: list[dict] = []
    for page_rows in pages:
        new_codes = 0
        for row in page_rows:
            try:
                item = normalize_board_row(row, sector_type)
            except ValueError as exc:
                log.warning("Sina %s row skipped: %s", sector_type, exc)
                continue
            if item["code"] in seen_codes:
                continue
            seen_codes.add(item["code"])
            normalized.append(item)
            new_codes += 1
        if page_rows is not first and new_codes == 0:
            break

    return normalized
