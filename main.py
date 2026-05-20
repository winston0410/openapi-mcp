from __future__ import annotations

import logging
import math
from datetime import UTC, date, datetime
from enum import Enum
from typing import Annotated, Any, cast

import uvicorn
import yfinance as yf
from fastapi import FastAPI, HTTPException, Path, Query
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
from pydantic import AfterValidator, BaseModel, Field
from yfinance.const import SECTOR_INDUSTY_MAPPING_LC

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


class PeriodEnum(str, Enum):
    """Valid `period` values accepted by yfinance `Ticker.history`."""

    d1 = "1d"
    d5 = "5d"
    mo1 = "1mo"
    mo3 = "3mo"
    mo6 = "6mo"
    y1 = "1y"
    y2 = "2y"
    y5 = "5y"
    y10 = "10y"
    ytd = "ytd"
    max = "max"


class IntervalEnum(str, Enum):
    """Valid `interval` values accepted by yfinance `Ticker.history`."""

    m1 = "1m"
    m2 = "2m"
    m5 = "5m"
    m15 = "15m"
    m30 = "30m"
    m60 = "60m"
    m90 = "90m"
    h1 = "1h"
    d1 = "1d"
    d5 = "5d"
    wk1 = "1wk"
    mo1 = "1mo"
    mo3 = "3mo"


class MarketEnum(str, Enum):
    """The 8 Yahoo Finance markets accepted by `yfinance.Market`."""

    US = "US"
    GB = "GB"
    ASIA = "ASIA"
    EUROPE = "EUROPE"
    RATES = "RATES"
    COMMODITIES = "COMMODITIES"
    CURRENCIES = "CURRENCIES"
    CRYPTOCURRENCIES = "CRYPTOCURRENCIES"


class CalendarEventEnum(str, Enum):
    """Calendar event types supported by `yfinance.Calendars`."""

    earnings = "earnings"
    ipo = "ipo"
    economic = "economic"
    splits = "splits"


class SectorEnum(str, Enum):
    """The 11 sector keys accepted by `yfinance.Sector`."""

    basic_materials = "basic-materials"
    communication_services = "communication-services"
    consumer_cyclical = "consumer-cyclical"
    consumer_defensive = "consumer-defensive"
    energy = "energy"
    financial_services = "financial-services"
    healthcare = "healthcare"
    industrials = "industrials"
    real_estate = "real-estate"
    technology = "technology"
    utilities = "utilities"


_VALID_INDUSTRY_KEYS: frozenset[str] = frozenset(
    industry
    for industries in SECTOR_INDUSTY_MAPPING_LC.values()
    for industry in industries
)


def _validate_industry_key(value: str) -> str:
    if value not in _VALID_INDUSTRY_KEYS:
        raise ValueError(
            f"Unknown industry key '{value}'. "
            "See yfinance.const.SECTOR_INDUSTY_MAPPING_LC for accepted values."
        )
    return value


IndustryKey = Annotated[str, AfterValidator(_validate_industry_key)]


class TickerResponse(BaseModel):
    symbol: str
    period: str
    interval: str
    info: dict[str, Any] = Field(default_factory=dict)
    history: list[HistoryPoint] = Field(default_factory=list)


class MarketResponse(BaseModel):
    market: MarketEnum
    status: dict[str, Any] | None = None
    summary: dict[str, Any] | None = None


class CalendarResponse(BaseModel):
    event: CalendarEventEnum
    start: str
    end: str
    limit: int
    offset: int
    rows: list[dict[str, Any]] = Field(default_factory=list)


class SectorResponse(BaseModel):
    key: str
    name: str | None = None
    symbol: str | None = None
    overview: dict[str, Any] = Field(default_factory=dict)
    industries: list[dict[str, Any]] = Field(default_factory=list)
    top_companies: list[dict[str, Any]] = Field(default_factory=list)
    top_etfs: dict[str, str] = Field(default_factory=dict)
    top_mutual_funds: dict[str, str] = Field(default_factory=dict)


class IndustryResponse(BaseModel):
    key: str
    name: str | None = None
    symbol: str | None = None
    sector_key: str | None = None
    sector_name: str | None = None
    overview: dict[str, Any] = Field(default_factory=dict)
    top_companies: list[dict[str, Any]] = Field(default_factory=list)
    top_performing_companies: list[dict[str, Any]] = Field(default_factory=list)
    top_growth_companies: list[dict[str, Any]] = Field(default_factory=list)


def _df_to_records(df: Any) -> list[dict[str, Any]]:
    if df is None or getattr(df, "empty", True):
        return []
    out = df.reset_index().to_dict(orient="records")
    for row in out:
        for k, v in list(row.items()):
            if isinstance(v, float) and math.isnan(v):
                row[k] = None
            elif hasattr(v, "isoformat"):
                row[k] = v.isoformat()
    return out


@api_app.get(
    "/health",
    response_model=HealthResponse,
    tags=["system"],
    operation_id="get_health",
)
def health() -> HealthResponse:
    """Readiness probe.

    Returns a constant `"ok"` status alongside the current server time in UTC,
    so callers can confirm the API process is reachable and clocks are sane.
    """
    return HealthResponse(status="ok", timestamp=datetime.now(UTC))


@api_app.get(
    "/ticker/{symbol}",
    response_model=TickerResponse,
    tags=["market"],
    operation_id="get_ticker",
)
def get_ticker(
    symbol: Annotated[
        str,
        Path(min_length=1, max_length=20, description="Yahoo Finance symbol, e.g. AAPL."),
    ],
    period: Annotated[
        PeriodEnum, Query(description="History range, e.g. 1mo, 1y, ytd, max.")
    ] = PeriodEnum.mo1,
    interval: Annotated[
        IntervalEnum, Query(description="Candle interval, e.g. 1d, 1h, 5m.")
    ] = IntervalEnum.d1,
) -> TickerResponse:
    """Look up a single Yahoo Finance ticker.

    Returns the ticker's static `info` payload alongside an OHLC history series
    bounded by `period` / `interval`. Symbols are passed through to yfinance
    verbatim, supporting suffixes like `AAPL`, `BRK-B`, or `RDSA.AS`.
    """
    try:
        t = yf.Ticker(symbol)
        info = dict(t.info or {})
        hist = t.history(period=period.value, interval=interval.value)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"yfinance error: {e}") from e

    if hist is None or hist.empty:
        raise HTTPException(
            status_code=404,
            detail=f"No history for symbol '{symbol}' at period={period.value} interval={interval.value}",
        )

    points = [
        HistoryPoint(
            date=idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else cast(datetime, idx),
            open=float(row["Open"]),
            high=float(row["High"]),
            low=float(row["Low"]),
            close=float(row["Close"]),
            volume=int(row["Volume"]),
        )
        for idx, row in hist.iterrows()
    ]
    return TickerResponse(
        symbol=symbol.upper(),
        period=period.value,
        interval=interval.value,
        info=info,
        history=points,
    )


@api_app.get(
    "/market/{market}",
    response_model=MarketResponse,
    tags=["market"],
    operation_id="get_market",
)
def get_market(market: MarketEnum) -> MarketResponse:
    """Get a Yahoo Finance market's status and summary.

    `market` must be one of the eight identifiers yfinance recognises
    (US, GB, ASIA, EUROPE, RATES, COMMODITIES, CURRENCIES, CRYPTOCURRENCIES).
    """
    try:
        m = yf.Market(market.value)
        summary = m.summary
        status = m.status
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"yfinance error: {e}") from e
    return MarketResponse(market=market, status=status, summary=summary)


@api_app.get(
    "/calendars/{event}",
    response_model=CalendarResponse,
    tags=["market"],
    operation_id="get_calendar",
)
def get_calendar(
    event: CalendarEventEnum,
    start: Annotated[
        date | None, Query(description="Start date YYYY-MM-DD (defaults to today).")
    ] = None,
    end: Annotated[
        date | None, Query(description="End date YYYY-MM-DD (defaults to start + 7 days).")
    ] = None,
    limit: Annotated[
        int, Query(ge=1, le=100, description="Result count (yfinance caps at 100).")
    ] = 25,
    offset: Annotated[int, Query(ge=0, description="Pagination offset.")] = 0,
) -> CalendarResponse:
    """Fetch an event calendar from Yahoo Finance.

    Supported `event` values map to `yfinance.Calendars` methods:
    `earnings` -> `get_earnings_calendar`, `ipo` -> `get_ipo_info_calendar`,
    `economic` -> `get_economic_events_calendar`, `splits` -> `get_splits_calendar`.
    """
    try:
        cal = yf.Calendars(
            start=start.isoformat() if start else None,
            end=end.isoformat() if end else None,
        )
        if event is CalendarEventEnum.earnings:
            df = cal.get_earnings_calendar(limit=limit, offset=offset)
        elif event is CalendarEventEnum.ipo:
            df = cal.get_ipo_info_calendar(limit=limit, offset=offset)
        elif event is CalendarEventEnum.economic:
            df = cal.get_economic_events_calendar(limit=limit, offset=offset)
        else:
            df = cal.get_splits_calendar(limit=limit, offset=offset)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"yfinance error: {e}") from e

    return CalendarResponse(
        event=event,
        start=cal._start,
        end=cal._end,
        limit=limit,
        offset=offset,
        rows=_df_to_records(df),
    )


@api_app.get(
    "/sector/{key}",
    response_model=SectorResponse,
    tags=["market"],
    operation_id="get_sector",
)
def get_sector(key: SectorEnum) -> SectorResponse:
    """Get a Yahoo Finance sector's overview, industries and top constituents.

    `key` is restricted to the 11 sector slugs yfinance accepts (see
    `SectorEnum`). The response bundles the sector overview, member
    industries, top companies, top ETFs and top mutual funds.
    """
    try:
        s = yf.Sector(key.value)
        return SectorResponse(
            key=s.key,
            name=s.name,
            symbol=s.symbol,
            overview=dict(s.overview or {}),
            industries=_df_to_records(s.industries),
            top_companies=_df_to_records(s.top_companies),
            top_etfs=dict(s.top_etfs or {}),
            top_mutual_funds=dict(s.top_mutual_funds or {}),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"yfinance error: {e}") from e


@api_app.get(
    "/industry/{key}",
    response_model=IndustryResponse,
    tags=["market"],
    operation_id="get_industry",
)
def get_industry(key: IndustryKey) -> IndustryResponse:
    """Get a Yahoo Finance industry's overview and top constituents.

    `key` is validated against `yfinance.const.SECTOR_INDUSTY_MAPPING_LC`
    (e.g. `semiconductors`, `biotechnology`, `reit—industrial`). The response
    includes the parent sector identifiers plus top, top-performing and
    top-growth companies in the industry.
    """
    try:
        ind = yf.Industry(key)
        return IndustryResponse(
            key=ind.key,
            name=ind.name,
            symbol=ind.symbol,
            sector_key=ind.sector_key,
            sector_name=ind.sector_name,
            overview=dict(ind.overview or {}),
            top_companies=_df_to_records(ind.top_companies),
            top_performing_companies=_df_to_records(ind.top_performing_companies),
            top_growth_companies=_df_to_records(ind.top_growth_companies),
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"yfinance error: {e}") from e


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
