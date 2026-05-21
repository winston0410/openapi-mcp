# fastmcp_logging.py
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Awaitable, Callable

from fastmcp.server.middleware import Middleware, MiddlewareContext

from logging_config import request_id_var


logger = logging.getLogger("app.mcp")


class FastMCPStructuredLoggingMiddleware(Middleware):
    """
    Logs semantic MCP operations:
    - initialize
    - tool calls
    - resource reads
    - prompt retrieval
    - list tools/resources/prompts
    """

    def __init__(
        self,
        *,
        include_arguments: bool = False,
        logger_: logging.Logger | None = None,
    ) -> None:
        self.include_arguments = include_arguments
        self.logger = logger_ or logger

    async def on_initialize(self, context: MiddlewareContext, call_next):
        return await self._log_operation(
            context,
            call_next,
            operation="initialize",
            fields=self._initialize_fields(context),
        )

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        fields = {
            "tool_name": getattr(context.message, "name", None),
        }

        if self.include_arguments:
            fields["arguments"] = getattr(context.message, "arguments", None)

        return await self._log_operation(
            context,
            call_next,
            operation="tool_call",
            fields=fields,
        )

    async def on_read_resource(self, context: MiddlewareContext, call_next):
        return await self._log_operation(
            context,
            call_next,
            operation="resource_read",
            fields={
                "resource_uri": str(getattr(context.message, "uri", "")),
            },
        )

    async def on_get_prompt(self, context: MiddlewareContext, call_next):
        fields = {
            "prompt_name": getattr(context.message, "name", None),
        }

        if self.include_arguments:
            fields["arguments"] = getattr(context.message, "arguments", None)

        return await self._log_operation(
            context,
            call_next,
            operation="prompt_get",
            fields=fields,
        )

    async def on_list_tools(self, context: MiddlewareContext, call_next):
        return await self._log_operation(
            context,
            call_next,
            operation="tools_list",
            fields={},
        )

    async def on_list_resources(self, context: MiddlewareContext, call_next):
        return await self._log_operation(
            context,
            call_next,
            operation="resources_list",
            fields={},
        )

    async def on_list_prompts(self, context: MiddlewareContext, call_next):
        return await self._log_operation(
            context,
            call_next,
            operation="prompts_list",
            fields={},
        )

    async def _log_operation(
        self,
        context: MiddlewareContext,
        call_next: Callable[[MiddlewareContext], Awaitable[Any]],
        *,
        operation: str,
        fields: dict[str, Any],
    ) -> Any:
        request_id = self._request_id(context)
        token = request_id_var.set(request_id)

        start = time.perf_counter()
        error: BaseException | None = None

        try:
            result = await call_next(context)
            return result
        except BaseException as exc:
            error = exc
            raise
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 3)

            payload = {
                "event": "mcp.operation",
                "mcp": {
                    "operation": operation,
                    "method": getattr(context, "method", None),
                    "type": getattr(context, "type", None),
                    "source": getattr(context, "source", None),
                    "request_id": self._safe_ctx_attr(context, "request_id"),
                    "session_id": self._safe_ctx_attr(context, "session_id"),
                    "client_id": self._safe_ctx_attr(context, "client_id"),
                    "duration_ms": duration_ms,
                    **fields,
                },
            }

            if error is None:
                self.logger.info("MCP operation completed", extra=payload)
            else:
                self.logger.error(
                    "MCP operation failed",
                    extra=payload,
                    exc_info=(type(error), error, error.__traceback__),
                )

            request_id_var.reset(token)

    def _request_id(self, context: MiddlewareContext) -> str:
        header_request_id = self._header("x-request-id")
        if header_request_id:
            return header_request_id

        mcp_request_id = self._safe_ctx_attr(context, "request_id")
        if mcp_request_id:
            return str(mcp_request_id)

        return f"mcp-{uuid.uuid4()}"

    def _header(self, name: str) -> str | None:
        try:
            from fastmcp.server.dependencies import get_http_headers

            headers = get_http_headers()
            return headers.get(name)
        except Exception:
            return None

    def _safe_ctx_attr(self, context: MiddlewareContext, attr: str) -> Any:
        ctx = getattr(context, "fastmcp_context", None)
        if ctx is None:
            return None

        try:
            return getattr(ctx, attr, None)
        except Exception:
            return None

    def _initialize_fields(self, context: MiddlewareContext) -> dict[str, Any]:
        params = getattr(context.message, "params", None)

        if isinstance(params, dict):
            client_info = params.get("clientInfo") or {}
            protocol_version = params.get("protocolVersion")
        else:
            client_info = getattr(params, "clientInfo", {}) or {}
            protocol_version = getattr(params, "protocolVersion", None)

        return {
            "client_info": client_info,
            "protocol_version": protocol_version,
        }
