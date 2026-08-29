"""Provider selection for sector fund-flow snapshots."""
from __future__ import annotations

from typing import Literal, Mapping

import eastmoney
import sina
import ths

Provider = Literal["sina", "ths", "eastmoney"]


def fetch_sector_snapshot(
    sector_type: str,
    *,
    provider: Provider = "sina",
    config: Mapping | None = None,
) -> list[dict]:
    """Fetch one sector type through the selected provider."""
    if provider == "sina":
        sina_config = (config or {}).get("sina") or {}
        mapping = sina_config.get("fenlei")
        kwargs = {"fenlei_by_type": mapping} if mapping else {}
        return sina.fetch_board_snapshot(sector_type, **kwargs)
    if provider == "ths":
        return ths.fetch_board_snapshot(sector_type)
    if provider == "eastmoney":
        return eastmoney.fetch_sector_snapshot(sector_type)
    raise ValueError(f"provider must be one of ('sina', 'ths', 'eastmoney'), got {provider!r}")
