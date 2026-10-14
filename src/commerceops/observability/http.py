"""ASGI observation without consuming bodies or recording unbounded URLs."""

import time
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from commerceops.observability import metrics
from commerceops.observability.logging import IDENTITY, event


class ObservationMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] == "/metrics":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        request_id = str(uuid4())
        status = 500
        context_token = IDENTITY.set({"request_id": request_id})

        async def observed_send(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message["headers"] = [
                    *message.get("headers", []),
                    (b"x-request-id", request_id.encode("ascii")),
                ]
            await send(message)

        try:
            await self.app(scope, receive, observed_send)
        finally:
            route = getattr(scope.get("route"), "path", "unmatched")
            elapsed = time.perf_counter() - started
            metrics.HTTP_REQUESTS.labels(route, str(status)).inc()
            metrics.HTTP_LATENCY.labels(route).observe(elapsed)
            event(
                "http_finished",
                request_id=request_id,
                route=route,
                http_status=status,
                duration_seconds=elapsed,
            )
            IDENTITY.reset(context_token)
