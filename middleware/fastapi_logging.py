# fastapi_logging.py
from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Iterable
from typing import Any

from starlette.datastructures import Headers, MutableHeaders, QueryParams
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from logging_config import request_id_var


logger = logging.getLogger("app.http")


class FastAPIRequestLoggingMiddleware:
    """
    JSON request logging middleware for FastAPI / Starlette.

    Register with:

        app.add_middleware(
            FastAPIRequestLoggingMiddleware,
            exclude_path_prefixes=("/mcp",),
        )
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        exclude_path_prefixes: tuple[str, ...] = (),
        safe_query_keys: Iterable[str] = ("page", "limit", "sort"),
        trust_x_forwarded_for: bool = True,
        logger_: logging.Logger | None = None,
    ) -> None:
        self.app = app
        self.exclude_path_prefixes = exclude_path_prefixes
        self.safe_query_keys = set(safe_query_keys)
        self.trust_x_forwarded_for = trust_x_forwarded_for
        self.logger = logger_ or logger

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        if path.startswith(self.exclude_path_prefixes):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        request_id = headers.get("x-request-id") or str(uuid.uuid4())

        token = request_id_var.set(request_id)

        # Makes request_id available as request.state.request_id in endpoints.
        scope.setdefault("state", {})
        scope["state"]["request_id"] = request_id

        start = time.perf_counter()
        status_code = 500
        error: BaseException | None = None

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code

            if message["type"] == "http.response.start":
                status_code = int(message["status"])

                response_headers = MutableHeaders(scope=message)
                response_headers["x-request-id"] = request_id

            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except BaseException as exc:
            error = exc
            raise
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 3)

            route = scope.get("route")
            route_path = getattr(route, "path", None)

            log_payload: dict[str, Any] = {
                "event": "http.request",
                "http": {
                    "method": scope.get("method"),
                    "path": path,
                    "route": route_path,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                    "content_length": headers.get("content-length"),
                },
                "client": {
                    "ip": self._client_ip(scope, headers),
                    "user_agent": headers.get("user-agent"),
                },
            }

            safe_query = self._safe_query(scope)
            if safe_query:
                log_payload["http"]["query"] = safe_query

            if error is None:
                self.logger.info(
                    "HTTP request completed",
                    extra=log_payload,
                )
            else:
                self.logger.error(
                    "HTTP request failed",
                    extra=log_payload,
                    exc_info=(type(error), error, error.__traceback__),
                )

            request_id_var.reset(token)

    def _client_ip(self, scope: Scope, headers: Headers) -> str | None:
        if self.trust_x_forwarded_for:
            forwarded_for = headers.get("x-forwarded-for")
            if forwarded_for:
                return forwarded_for.split(",")[0].strip()

        client = scope.get("client")
        if client:
            host, _port = client
            return host

        return None

    def _safe_query(self, scope: Scope) -> dict[str, str]:
        raw_query = scope.get("query_string", b"")
        query_params = QueryParams(raw_query.decode("latin-1"))

        return {
            key: query_params[key]
            for key in self.safe_query_keys
            if key in query_params
        }
