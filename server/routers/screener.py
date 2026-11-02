from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from server.data import eastmoney

router = APIRouter(prefix="/api/screener", tags=["screener"])

PRESETS: list[dict[str, Any]] = [
    {
        "id": "quality_growth",
        "title": "高质量成长",
        "description": "大市值、盈利为正、年内上涨的成长型公司",
        "tone": "positive",
        "filters": {"mcapMin": 5e10, "peMin": 0, "peMax": 40, "chgYtdMin": 0},
    },
    {
        "id": "value",
        "title": "低估值价值",
        "description": "PE 低于 18、PB 低于 3 的盈利公司",
        "tone": "neutral",
        "filters": {"peMin": 0, "peMax": 18, "pbMax": 3, "mcapMin": 1e10},
    },
    {
        "id": "momentum",
        "title": "强势动量",
        "description": "近 60 日与年内涨幅领先的中大型公司",
        "tone": "positive",
        "filters": {"chg60Min": 10, "chgYtdMin": 15, "mcapMin": 5e9},
    },
    {
        "id": "dividend",
        "title": "股息收益",
        "description": "股息率高于 2% 的现金回报型公司",
        "tone": "neutral",
        "filters": {"yieldMin": 2, "mcapMin": 5e9},
    },
    {
        "id": "oversold",
        "title": "超跌观察",
        "description": "近 60 日回撤超过 15% 的中大型公司，留意反转机会",
        "tone": "caution",
        "filters": {"chg60Max": -15, "mcapMin": 2e9},
    },
    {
        "id": "mega_cap",
        "title": "巨头俱乐部",
        "description": "市值超过 2000 亿美元的行业龙头",
        "tone": "neutral",
        "filters": {"mcapMin": 2e11},
    },
]


@router.get("/universe")
async def universe(limit: int = Query(14000, ge=300, le=15000)) -> dict[str, Any]:
    payload = await eastmoney.universe(limit)
    return payload


@router.get("/presets")
async def presets() -> dict[str, Any]:
    return {"items": PRESETS}
