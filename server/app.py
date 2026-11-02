from __future__ import annotations

import argparse
import asyncio
import logging
import mimetypes
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from server.config import WEB_DIR
from server.data import eastmoney
from server.data.http import UpstreamError, http
from server.routers import compare, funds, macro, market, portfolio, screener, stocks, watchlist

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("starmap")

mimetypes.add_type("font/woff2", ".woff2")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async def warm() -> None:
        try:
            await eastmoney.universe(3000)
            logger.info("全市场快照预热完成")
        except Exception as exc:
            logger.warning("全市场快照预热失败：%s", exc)

    task = asyncio.create_task(warm())
    logger.info("星图启动：http://127.0.0.1:8000")
    yield
    task.cancel()
    await http.close()


app = FastAPI(
    title="Starmap US Equity Terminal",
    description="集行情、基本面、筛选、对比、组合与宏观于一体的美股投研终端",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(GZipMiddleware, minimum_size=1200)

for module in (market, stocks, screener, compare, portfolio, macro, funds, watchlist):
    app.include_router(module.router)


@app.exception_handler(eastmoney.SymbolNotFound)
async def handle_symbol_not_found(request: Request, exc: eastmoney.SymbolNotFound) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc), "code": "symbol_not_found"})


@app.exception_handler(UpstreamError)
async def handle_upstream_error(request: Request, exc: UpstreamError) -> JSONResponse:
    logger.warning("upstream error on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=502,
        content={"detail": "上游数据源暂时不可用，请稍后重试", "code": "upstream_error"},
    )


@app.exception_handler(ValueError)
async def handle_value_error(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc), "code": "bad_request"})


@app.middleware("http")
async def static_cache_policy(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/assets/vendor/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif path.startswith("/assets/fonts/"):
        response.headers["Cache-Control"] = "public, max-age=2592000"
    elif path == "/" or path.endswith((".html", ".js", ".css")):
        response.headers["Cache-Control"] = "no-cache"
    return response


app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api", include_in_schema=False)
async def api_index() -> dict:
    return {
        "service": "starmap-us-terminal",
        "commit": os.getenv("RENDER_GIT_COMMIT", "")[:7],
        "docs": "/docs",
        "health": "/api/health",
    }


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="星图 · 美股投研终端")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run("server.app:app", host=args.host, port=args.port, log_level="info")
