from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from server.data import funds

router = APIRouter(prefix="/api/funds", tags=["funds"])

TICKER_RE = re.compile(r"[A-Z][A-Z0-9.\-]{0,9}")


@router.get("/{ticker}")
async def fund(ticker: str, watch: str = Query("", max_length=600)) -> dict[str, Any]:
    """基金/ETF 一页档：档案净值、N-PORT 持仓集中度、497K 费率与业绩、与自选的重叠。"""

    query = ticker.strip().upper()
    if not TICKER_RE.fullmatch(query):
        raise HTTPException(status_code=400, detail="基金代码格式不正确")
    symbols = [item.strip().upper() for item in re.split(r"[,\s]+", watch) if item.strip()][:60]
    try:
        return await funds.fund_report(query, watch=symbols)
    except funds.FundNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail=f"{query} 没有可解析的基金档案：份额代码需能在 SEC EDGAR 或 Nasdaq 查到",
        ) from exc
