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
        # Enforce early DoS and size checks on conversion endpoints
        is_primary_convert = request.url.path.startswith("/api/v1/convert")
        is_gpt_convert = request.url.path in ("/v1/gpt/convert", "/api/v1/gpt/convert") or request.url.path.startswith("/v1/gpt/") or request.url.path.startswith("/api/v1/gpt/")

        if is_primary_convert or is_gpt_convert:
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

            # 2. Authorization verification
            auth_header = request.headers.get("authorization")
            if is_primary_convert:
                # Primary convert endpoint REQUIRES Bearer token
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
                    request.state.tenant = payload
                except HTTPException as exc:
                    err_type = "unauthorized" if exc.status_code == 401 else "service_unavailable" if exc.status_code == 503 else "error"
                    return Response(
                        content=json.dumps({
                            "error": err_type,
                            "detail": exc.detail
                        }),
                        status_code=exc.status_code,
                        media_type="application/json"
                    )
            elif is_gpt_convert and auth_header and auth_header.startswith("Bearer "):
                # GPT convert endpoint optionally accepts Bearer token
                token = auth_header[7:].strip()
                try:
                    payload = decode_access_token(token)
                    request.state.tenant = payload
                except HTTPException as exc:
                    err_type = "unauthorized" if exc.status_code == 401 else "service_unavailable" if exc.status_code == 503 else "error"
                    return Response(
                        content=json.dumps({
                            "error": err_type,
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
