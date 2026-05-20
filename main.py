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
from fastapi.responses import Response
from fastmcp import FastMCP
from fastmcp.server.providers.openapi import RouteMap, MCPType
from opentelemetry import metrics, trace
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

OPENAPI_URL = "/openapi.json"
OAUTH2_REDIRECT_URL = "/docs/oauth2-redirect"

SERVICE_NAME_VALUE = "trade-api"
SERVICE_VERSION_VALUE = "0.1.0"

_otel_resource = Resource.create(
    {SERVICE_NAME: SERVICE_NAME_VALUE, SERVICE_VERSION: SERVICE_VERSION_VALUE}
)
metrics.set_meter_provider(
    MeterProvider(metric_readers=[PrometheusMetricReader()], resource=_otel_resource)
)
trace.set_tracer_provider(TracerProvider(resource=_otel_resource))

api_app = FastAPI(
    title="Trade API",
    description="A FastAPI service exposing market data via yfinance.",
    version=SERVICE_VERSION_VALUE,
    openapi_url=OPENAPI_URL,
    docs_url=None,
    redoc_url=None,
    swagger_ui_oauth2_redirect_url=OAUTH2_REDIRECT_URL,
)


@api_app.get("/metrics", include_in_schema=False)
def prometheus_metrics() -> Response:
    """Expose OpenTelemetry metrics in Prometheus text format for scraping."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@api_app.get("/docs", include_in_schema=False)
async def swagger_ui_html():
    """Serve the Swagger UI documentation page for this API."""
    return get_swagger_ui_html(
        openapi_url=OPENAPI_URL,
        title=f"{api_app.title} - Swagger UI",
        oauth2_redirect_url=OAUTH2_REDIRECT_URL,
    )


@api_app.get(OAUTH2_REDIRECT_URL, include_in_schema=False)
async def swagger_ui_redirect():
    """OAuth2 redirect helper used by the Swagger UI's interactive auth flow."""
    return get_swagger_ui_oauth2_redirect_html()


@api_app.get("/redoc", include_in_schema=False)
async def redoc_html():
    """Serve the ReDoc documentation page for this API."""
    return get_redoc_html(
        openapi_url=OPENAPI_URL,
        title=f"{api_app.title} - ReDoc",
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


@api_app.get(
    "/health",
    response_model=HealthResponse,
    tags=["system"],
    operation_id="get_health",
)
def health() -> HealthResponse:
    """Liveness probe.

    Returns a constant `"ok"` status alongside the current server time in UTC,
    so callers can confirm the API process is reachable and clocks are sane.
    """
    return HealthResponse(status="ok", timestamp=datetime.now(UTC))


@api_app.get(
    "/quote/{symbol}",
    response_model=Quote,
    tags=["market"],
    operation_id="get_quote",
)
def get_quote(symbol: str) -> Quote:
    """Get the latest market quote for a stock ticker symbol.

    Looks up `symbol` on Yahoo Finance and returns the most recent traded price,
    the listing currency, the current market state (e.g. `REGULAR`, `CLOSED`,
    `PRE`, `POST`), and the company's short name. Use this when you need a
    point-in-time price snapshot rather than a time series.

    Raises `404` if no quote data is available for the symbol.
    """
    ticker = yf.Ticker(symbol)
    info = ticker.fast_info
    price = getattr(info, "last_price", None)
    if price is None:
        raise HTTPException(
            status_code=404, detail=f"No quote available for {symbol!r}"
        )
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


@api_app.get(
    "/history/{symbol}",
    response_model=HistoryResponse,
    tags=["market"],
    operation_id="get_price_history",
)
def get_history(
    symbol: str,
    period: Annotated[
        str, Query(description="yfinance period, e.g. 1d, 5d, 1mo, 1y, max")
    ] = "1mo",
    interval: Annotated[
        str, Query(description="yfinance interval, e.g. 1m, 5m, 1h, 1d")
    ] = "1d",
) -> HistoryResponse:
    """Get historical OHLCV candles for a stock ticker symbol.

    Returns a time-ordered series of open / high / low / close / volume points
    for `symbol` from Yahoo Finance. `period` controls the lookback window
    (e.g. `1d`, `5d`, `1mo`, `1y`, `max`) and `interval` controls the candle
    granularity (e.g. `1m`, `5m`, `1h`, `1d`). Use this for charting, backtests,
    or trend analysis rather than a single live price.

    Raises `404` if no history is available for the symbol.
    """
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
    return HistoryResponse(
        symbol=symbol.upper(), period=period, interval=interval, points=points
    )


mcp = FastMCP.from_fastapi(
    app=api_app,
    name="Trade API MCP",
    route_maps=[
        # Exclude one exact route from MCP tool generation
        RouteMap(
            methods=["GET"],
            pattern=r"^/health$",
            mcp_type=MCPType.EXCLUDE,
        ),
    ],
)
mcp_app = mcp.http_app(path="/mcp")

app = FastAPI(
    title="Trade API with MCP",
    description="A FastAPI service exposing market data via yfinance, with an MCP interface for LLMs.",
    version=SERVICE_VERSION_VALUE,
    routes=[*mcp_app.routes, *api_app.routes],
    lifespan=mcp_app.lifespan,
)

FastAPIInstrumentor.instrument_app(app)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Trade API")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    log = logging.getLogger("trade-api")
    log.info("Starting Trade API on http://%s:%d", args.host, args.port)
    log.info("Swagger UI: http://%s:%d/docs", args.host, args.port)
    log.info("ReDoc:      http://%s:%d/redoc", args.host, args.port)
    log.info("OpenAPI:    http://%s:%d/openapi.json", args.host, args.port)
    log.info("MCP:        http://%s:%d/mcp", args.host, args.port)
    log.info("Metrics:    http://%s:%d/metrics", args.host, args.port)

    uvicorn.run("main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
