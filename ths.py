"""Direct client for Tonghuashun (THS) sector fund-flow snapshots."""
from __future__ import annotations

import logging
import re
import time
from html.parser import HTMLParser
from typing import Literal

import requests

log = logging.getLogger(__name__)

THS_BASE_URL = "https://data.10jqka.com.cn"
THS_PATH_BY_TYPE = {
    "industry": "/funds/hyzjl/field/tradezdf/order/desc/ajax/1/free/1/",
    "concept": "/funds/gnzjl/field/tradezdf/order/desc/ajax/1/free/1/",
}
THS_REFERER_BY_TYPE = {
    "industry": "https://data.10jqka.com.cn/funds/hyzjl/",
    "concept": "https://data.10jqka.com.cn/funds/gnzjl/",
}
_HEADERS = {
    "Accept": "text/html, */*; q=0.01",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "X-Requested-With": "XMLHttpRequest",
}
_RETRY_BACKOFFS = (0.5, 1.5, 3.0)
_MAX_PAGES = 20

SectorType = Literal["industry", "concept"]


class ThsError(RuntimeError):
    """Raised when THS cannot provide the first page of a snapshot."""


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[dict] = []
        self._row: list[dict] | None = None
        self._cell_text: list[str] | None = None
        self._cell_href: str | None = None

    def handle_starttag(self, tag: str, attrs):
        attrs_dict = dict(attrs)
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell_text = []
            self._cell_href = None
        elif tag == "a" and self._cell_text is not None:
            self._cell_href = attrs_dict.get("href")

    def handle_data(self, data: str):
        if self._cell_text is not None:
            self._cell_text.append(data)

    def handle_endtag(self, tag: str):
        if tag in {"td", "th"} and self._row is not None and self._cell_text is not None:
            self._row.append({
                "text": "".join(self._cell_text).strip(),
                "href": self._cell_href,
            })
            self._cell_text = None
            self._cell_href = None
        elif tag == "tr" and self._row:
            self.rows.append({"cells": self._row})
            self._row = None


def _to_float(value: str):
    text = str(value or "").strip().replace(",", "").replace("%", "")
    if text in {"", "-", "--"}:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _extract_board_code(row: dict, sector_type: SectorType, name: str) -> str:
    for cell in row["cells"]:
        href = cell.get("href") or ""
        match = re.search(r"/detail/code/(\d+)", href)
        if match:
            return match.group(1)
    return f"ths:{sector_type}:{name}"


def parse_page(html: str, sector_type: SectorType) -> tuple[list[dict], int]:
    """Parse one decoded THS table page into the project's row shape."""
    if sector_type not in THS_PATH_BY_TYPE:
        raise ValueError(f"sector_type must be one of {list(THS_PATH_BY_TYPE)}, got {sector_type!r}")

    page_match = re.search(r'class=["\'][^"\']*page_info[^"\']*["\'][^>]*>\s*(\d+)\s*/\s*(\d+)', html)
    total_pages = int(page_match.group(2)) if page_match else 1
    parser = _TableParser()
    parser.feed(html)

    rows: list[dict] = []
    for parsed in parser.rows:
        cells = parsed["cells"]
        values = [cell["text"] for cell in cells]
        if len(values) < 11 or not values[0].isdigit():
            continue
        name = values[1].strip()
        if not name:
            continue
        net_yi = _to_float(values[6])
        rows.append({
            "sector_type": sector_type,
            "code": _extract_board_code(parsed, sector_type, name),
            "name": name,
            "pct_chg": _to_float(values[3]),
            "main_net": net_yi * 100_000_000 if net_yi is not None else None,
            "super_net": None,
            "big_net": None,
            "mid_net": None,
            "small_net": None,
            "raw": ",".join(values[4:7]),
        })
    return rows, total_pages


def _page_url(sector_type: SectorType, page: int) -> str:
    base = THS_BASE_URL + THS_PATH_BY_TYPE[sector_type]
    if page == 1:
        return base
    marker = "/ajax/1/free/1/"
    return base.replace(marker, f"/page/{page}{marker}")


def _request_page(
    sector_type: SectorType,
    page: int,
    *,
    session: requests.Session,
    timeout: float = 10.0,
) -> tuple[list[dict], int]:
    if sector_type not in THS_PATH_BY_TYPE:
        raise ValueError(f"sector_type must be one of {list(THS_PATH_BY_TYPE)}, got {sector_type!r}")

    headers = {**_HEADERS, "Referer": THS_REFERER_BY_TYPE[sector_type]}
    last_err: Exception | None = None
    for attempt, backoff in enumerate((0.0,) + _RETRY_BACKOFFS, start=1):
        if backoff:
            time.sleep(backoff)
        try:
            response = session.get(
                _page_url(sector_type, page),
                headers=headers,
                timeout=timeout,
            )
            response.raise_for_status()
            response.encoding = "gbk"
            return parse_page(response.text, sector_type)
        except (requests.RequestException, UnicodeError, ValueError, TypeError) as exc:
            last_err = exc
            log.warning(
                "THS %s page=%d attempt %d/%d failed: %s",
                sector_type,
                page,
                attempt,
                len(_RETRY_BACKOFFS) + 1,
                exc,
            )

    raise ThsError(
        f"THS {sector_type} page={page} failed after retries: {last_err}"
    ) from last_err


def fetch_board_snapshot(
    sector_type: SectorType,
    *,
    session: requests.Session | None = None,
    timeout: float = 10.0,
    max_pages: int = _MAX_PAGES,
) -> list[dict]:
    """Return the current THS industry or concept fund-flow snapshot."""
    client = session or requests.Session()
    first, reported_pages = _request_page(
        sector_type,
        1,
        session=client,
        timeout=timeout,
    )
    pages = [first]
    total_pages = min(max(1, reported_pages), max_pages)
    for page in range(2, total_pages + 1):
        try:
            current, _ = _request_page(
                sector_type,
                page,
                session=client,
                timeout=timeout,
            )
        except ThsError as exc:
            log.warning("THS %s partial snapshot: page %d skipped: %s", sector_type, page, exc)
            break
        if not current:
            break
        pages.append(current)

    seen_codes: set[str] = set()
    normalized: list[dict] = []
    for page_rows in pages:
        for row in page_rows:
            if row["code"] in seen_codes:
                continue
            seen_codes.add(row["code"])
            normalized.append(row)
    return normalized
