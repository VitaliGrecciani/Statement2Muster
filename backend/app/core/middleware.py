import json
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from app.core.config import settings
from app.core.security import decode_access_token
from fastapi import HTTPException

class EarlyAuthAndBudgetMiddleware(BaseHTTPMiddleware):
    """
    Architect requirement (Zero Retention & DoS protection):
    Rejects unauthenticated requests and oversized payloads BEFORE
    Starlette's multipart form parser reads or spools files into disk/RAM.
    """
    async def dispatch(self, request: Request, call_next):
        # We enforce early rejection on protected conversion endpoints
        if request.url.path.startswith("/api/v1/convert"):
            # 1. Early Content-Length check (DoS budget)
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    length_val = int(content_length)
                    if length_val > settings.MAX_BATCH_SIZE_BYTES:
                        return Response(
                            content=json.dumps({
                                "error": "payload_too_large",
                                "detail": f"Batch exceeds maximum limit of {settings.MAX_BATCH_SIZE_BYTES // (1024*1024)} MiB"
                            }),
                            status_code=413,
                            media_type="application/json"
                        )
                except ValueError:
                    pass

            # 2. Early Authorization verification before multipart stream is consumed
            auth_header = request.headers.get("authorization")
            if not auth_header or not auth_header.startswith("Bearer "):
                return Response(
                    content=json.dumps({
                        "error": "unauthorized",
                        "detail": "Bearer token required for conversion"
                    }),
                    status_code=401,
                    media_type="application/json"
                )

            token = auth_header[7:].strip()
            try:
                payload = decode_access_token(token)
                # Store tenant info in request state for downstream handlers
                request.state.tenant = payload
            except HTTPException as exc:
                return Response(
                    content=json.dumps({
                        "error": "unauthorized",
                        "detail": exc.detail
                    }),
                    status_code=exc.status_code,
                    media_type="application/json"
                )

            # 3. Wrap request._receive to count actual incoming stream bytes (A18 chunked DoS protection)
            request.state.batch_size_exceeded = False
            original_receive = request._receive
            received_bytes = 0

            async def counting_receive():
                nonlocal received_bytes
                msg = await original_receive()
                if msg["type"] == "http.request":
                    chunk = msg.get("body", b"")
                    received_bytes += len(chunk)
                    if received_bytes > settings.MAX_BATCH_SIZE_BYTES:
                        request.state.batch_size_exceeded = True
                        raise ValueError(f"Batch payload exceeds limit of {settings.MAX_BATCH_SIZE_BYTES} bytes")
                return msg

            request._receive = counting_receive

        try:
            response = await call_next(request)
            if getattr(request.state, "batch_size_exceeded", False):
                return Response(
                    content=json.dumps({
                        "error": "payload_too_large",
                        "detail": f"Batch payload exceeds limit of {settings.MAX_BATCH_SIZE_BYTES} bytes"
                    }),
                    status_code=413,
                    media_type="application/json"
                )
            return response
        except Exception as exc:
            if getattr(request.state, "batch_size_exceeded", False):
                return Response(
                    content=json.dumps({
                        "error": "payload_too_large",
                        "detail": f"Batch payload exceeds limit of {settings.MAX_BATCH_SIZE_BYTES} bytes"
                    }),
                    status_code=413,
                    media_type="application/json"
                )
            if isinstance(exc, HTTPException):
                return Response(
                    content=json.dumps({
                        "error": "error",
                        "detail": exc.detail
                    }),
                    status_code=exc.status_code,
                    media_type="application/json"
                )
            raise
