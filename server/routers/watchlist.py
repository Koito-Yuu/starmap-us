from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from server.data import watchlist

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


@router.get("/analyze")
async def analyze(
    symbols: str = "",
    range: str = watchlist.DEFAULT_RANGE,
) -> dict[str, Any]:
    try:
        tickers = watchlist.parse_symbols(symbols)
        range_key = watchlist.normalize_range(range)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await watchlist.analyze(tickers, range_key)
