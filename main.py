from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated, Any, cast

import uvicorn
import yfinance as yf
from fastapi import FastAPI, HTTPException, Query
from fastapi.openapi.docs import (
    get_redoc_html,
    get_swagger_ui_html,
    get_swagger_ui_oauth2_redirect_html,
)
from pydantic import BaseModel, Field

OPENAPI_URL = "/openapi.json"
OAUTH2_REDIRECT_URL = "/docs/oauth2-redirect"

app = FastAPI(
    title="Trade API",
    description="A FastAPI service exposing market data via yfinance.",
    version="0.1.0",
    openapi_url=OPENAPI_URL,
    docs_url=None,
    redoc_url=None,
    swagger_ui_oauth2_redirect_url=OAUTH2_REDIRECT_URL,
)


@app.get("/docs", include_in_schema=False)
async def swagger_ui_html():
    return get_swagger_ui_html(
        openapi_url=OPENAPI_URL,
        title=f"{app.title} - Swagger UI",
        oauth2_redirect_url=OAUTH2_REDIRECT_URL,
    )


@app.get(OAUTH2_REDIRECT_URL, include_in_schema=False)
async def swagger_ui_redirect():
    return get_swagger_ui_oauth2_redirect_html()


@app.get("/redoc", include_in_schema=False)
async def redoc_html():
    return get_redoc_html(
        openapi_url=OPENAPI_URL,
        title=f"{app.title} - ReDoc",
    )


class HealthResponse(BaseModel):
    status: str = Field(..., examples=["ok"])
    timestamp: datetime


class Quote(BaseModel):
    symbol: str = Field(..., examples=["AAPL"])
    price: float
    currency: str | None = None
    market_state: str | None = None
    short_name: str | None = None
    timestamp: datetime


class HistoryPoint(BaseModel):
    date: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


class HistoryResponse(BaseModel):
    symbol: str
    period: str
    interval: str
    points: list[HistoryPoint]


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse(status="ok", timestamp=datetime.now(UTC))


@app.get("/quote/{symbol}", response_model=Quote, tags=["market"])
def get_quote(symbol: str) -> Quote:
    ticker = yf.Ticker(symbol)
    info = ticker.fast_info
    price = getattr(info, "last_price", None)
    if price is None:
        raise HTTPException(status_code=404, detail=f"No quote available for {symbol!r}")
    full_info: dict[str, Any] = {}
    try:
        full_info = ticker.info or {}
    except Exception:
        full_info = {}
    return Quote(
        symbol=symbol.upper(),
        price=float(price),
        currency=getattr(info, "currency", None),
        market_state=full_info.get("marketState"),
        short_name=full_info.get("shortName"),
        timestamp=datetime.now(UTC),
    )


@app.get("/history/{symbol}", response_model=HistoryResponse, tags=["market"])
def get_history(
    symbol: str,
    period: Annotated[str, Query(description="yfinance period, e.g. 1d, 5d, 1mo, 1y, max")] = "1mo",
    interval: Annotated[str, Query(description="yfinance interval, e.g. 1m, 5m, 1h, 1d")] = "1d",
) -> HistoryResponse:
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period, interval=interval)
    if df.empty:
        raise HTTPException(status_code=404, detail=f"No history for {symbol!r}")
    points: list[HistoryPoint] = []
    for idx, row in df.iterrows():
        r = cast(Any, row)
        points.append(
            HistoryPoint(
                date=cast(Any, idx).to_pydatetime(),
                open=float(r["Open"]),
                high=float(r["High"]),
                low=float(r["Low"]),
                close=float(r["Close"]),
                volume=int(r["Volume"]),
            )
        )
    return HistoryResponse(symbol=symbol.upper(), period=period, interval=interval, points=points)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Trade API")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("trade-api")
    log.info("Starting Trade API on http://%s:%d", args.host, args.port)
    log.info("Swagger UI: http://%s:%d/docs", args.host, args.port)
    log.info("ReDoc:      http://%s:%d/redoc", args.host, args.port)
    log.info("OpenAPI:    http://%s:%d/openapi.json", args.host, args.port)

    uvicorn.run("main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
