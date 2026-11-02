from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from server.config import MACRO_SERIES
from server.data import fomc, fred

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/macro", tags=["macro"])


@router.get("/overview")
async def overview() -> dict[str, Any]:
    macro = await fred.macro_overview()
    try:
        fed = await asyncio.wait_for(fomc.briefing(), timeout=12)
    except Exception as exc:
        logger.warning("FOMC briefing unavailable: %s", exc)
        fed = {
            "available": False,
            "source": "Federal Reserve Board",
            "error": str(exc),
            "upcoming": [],
            "latest_statement": None,
        }
    fed["policy"] = macro.get("policy") or {}
    macro["fomc"] = fed
    return macro


@router.get("/fomc")
async def fomc_briefing() -> dict[str, Any]:
    return await fomc.briefing()


@router.get("/series/{series_id}")
async def series(series_id: str, years: int = Query(10, ge=1, le=40)) -> dict[str, Any]:
    series_id = series_id.upper()
    meta = MACRO_SERIES.get(series_id)
    if not meta:
        raise HTTPException(status_code=404, detail=f"不支持的宏观序列 {series_id}")
    points = await fred.series_raw(series_id, years=years)
    yoy = bool(meta.get("yoy"))
    if yoy:
        periods = fred.YOY_PERIODS.get(meta["freq"], 12)
        points = fred._yoy(points, periods)
    return {
        "id": series_id,
        "label": meta["label"],
        "unit": "%" if yoy else meta["unit"],
        "freq": meta["freq"],
        "yoy": yoy,
        "points": fred._sample(points, 420),
    }
