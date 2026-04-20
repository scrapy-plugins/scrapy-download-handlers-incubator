"""Starlette ASGI app mirroring tests/mockserver/http_resources.py.

Trivial endpoints are plain ``async def f(request) -> Response`` handlers
that use Starlette's Response shortcuts. The framing-abuse and hold-open
endpoints need direct control over ``http.response.body`` framing, so they
are ASGI-callable class instances (``__call__`` on an instance isn't a
``function``/``method`` so Starlette's Route plumbs them through as raw
ASGI apps without the Request/Response wrapping).

``/drop?abort=1`` uses the same socket-level SO_LINGER+os.close hack as
the raw-ASGI and Falcon variants — Hypercorn's StreamWriter is stashed in
a ContextVar by http.py.
"""

from __future__ import annotations

import asyncio
import contextvars
import gzip
import json
import os
import socket
import struct
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs

from starlette.applications import Starlette
from starlette.responses import RedirectResponse, Response, StreamingResponse
from starlette.routing import Route

if TYPE_CHECKING:
    from starlette.requests import Request

# Populated by http.py's TCPServer monkey-patch so /drop?abort=1 can RST the socket.
current_writer: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "current_writer", default=None
)


_HTML = "text/html"
_TEXT = "text/plain"
_JSON = "application/json"


def _title_case(name: str) -> str:
    # ASGI lowercases header names; Twisted preserves casing. /echo's tests
    # compare against names like "Accept-Charset" and "X-Custom-Header".
    return "-".join(part.capitalize() for part in name.split("-"))


# --- Request-based endpoints ---


async def root(request: Request) -> Response:
    return Response(b"Scrapy mock HTTP server\n", media_type=_HTML)


async def text(request: Request) -> Response:
    return Response(b"Works", media_type=_TEXT)


async def redirect(request: Request) -> Response:
    return RedirectResponse("/redirected", status_code=302)


async def redirected(request: Request) -> Response:
    return Response(b"Redirected here", media_type=_TEXT)


async def status(request: Request) -> Response:
    n = int(request.query_params.get("n", 200))
    return Response(b"", status_code=n, media_type=_HTML)


async def delay(request: Request) -> Response:
    n = float(request.query_params.get("n", 1))
    send_headers_first = int(request.query_params.get("b", 1))
    body = f"Response delayed for {n:.3f} seconds\n".encode()
    if send_headers_first:

        async def gen():
            await asyncio.sleep(n)
            yield body

        return StreamingResponse(gen(), media_type=_HTML)
    await asyncio.sleep(n)
    return Response(body, media_type=_HTML)


async def host(request: Request) -> Response:
    return Response(request.headers.get("host", "").encode(), media_type=_HTML)


async def client_ip(request: Request) -> Response:
    client = request.client
    ip = client.host.encode() if client and client.host else b""
    return Response(ip, media_type=_HTML)


async def content_length_header(request: Request) -> Response:
    return Response(
        request.headers.get("content-length", "").encode(), media_type=_HTML
    )


async def empty_content_type(request: Request) -> Response:
    body = await request.body()
    # Hypercorn rejects an empty header value; a single space is
    # effectively empty for Scrapy's response-class detection.
    return Response(body, media_type=" ")


async def chunked(request: Request) -> Response:
    async def gen():
        yield b"chunked "
        yield b"content\n"

    return StreamingResponse(gen(), media_type=_HTML)


async def large_chunked_file(request: Request) -> Response:
    async def gen():
        chunk = b"x" * 1024
        for _ in range(1024):
            yield chunk

    return StreamingResponse(gen(), media_type=_HTML)


async def duplicate_header(request: Request) -> Response:
    response = Response(b"", media_type=_HTML)
    response.headers.append("set-cookie", "a=b")
    response.headers.append("set-cookie", "c=d")
    return response


async def echo(request: Request) -> Response:
    body = await request.body()
    headers: dict[str, list[str]] = {}
    for name, value in request.scope["headers"]:
        headers.setdefault(_title_case(name.decode()), []).append(value.decode())
    payload = json.dumps({"headers": headers, "body": body.decode()}).encode()
    return Response(payload, media_type=_HTML)


async def payload(request: Request) -> Response:
    body = await request.body()
    cl = request.headers.get("content-length")
    if len(body) != 100 or cl != "100":
        return Response(b"ERROR", media_type=_HTML)
    return Response(body, media_type=_HTML)


async def alpayload(request: Request) -> Response:
    body = await request.body()
    return Response(body, media_type=_HTML)


async def response_headers(request: Request) -> Response:
    body = await request.body()
    body_json: dict[str, str] = json.loads(body.decode()) if body else {}
    explicit_ct = any(k.lower() == "content-type" for k in body_json)
    response = Response(
        json.dumps(body_json).encode(),
        media_type=None if explicit_ct else _JSON,
    )
    for name, value in body_json.items():
        # MutableHeaders.append keeps duplicates for Set-Cookie; other header
        # names overwrite rather than accumulate commas if already present.
        if name.lower() == "content-type":
            response.headers["content-type"] = value
        elif name.lower() == "set-cookie":
            response.headers.append(name, value)
        else:
            response.headers[name] = value
    return response


async def compress(request: Request) -> Response:
    data = request.query_params.get("data", "")
    data_bytes = data.encode() if isinstance(data, str) else data
    if request.headers.get("accept-encoding") == "gzip":
        return Response(
            gzip.compress(data_bytes),
            media_type=_HTML,
            headers={"content-encoding": "gzip"},
        )
    return Response(
        b"Did not receive a valid accept-encoding header",
        status_code=500,
        media_type=_HTML,
    )


async def set_cookie(request: Request) -> Response:
    response = Response(b"", media_type=_HTML)
    for name, value in request.query_params.multi_items():
        response.headers.append("set-cookie", f"{name}={value}")
    return response


# --- Raw-ASGI endpoints (class instances so Starlette's Route plumbs them
#     through as ASGI apps without the Request/Response wrapping) ---


class _Wait:
    async def __call__(self, scope, receive, send) -> None:
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return


class _HangAfterHeaders:
    async def __call__(self, scope, receive, send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/html")],
            }
        )
        await send(
            {"type": "http.response.body", "body": b"some bytes", "more_body": True}
        )
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return


class _Partial:
    async def __call__(self, scope, receive, send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"text/html"),
                    (b"content-length", b"1024"),
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": b"partial content\n",
                "more_body": True,
            }
        )
        raise RuntimeError("partial: forced close")


class _Broken:
    async def __call__(self, scope, receive, send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"text/html"),
                    (b"content-length", b"20"),
                ],
            }
        )
        await send(
            {"type": "http.response.body", "body": b"partial", "more_body": True}
        )
        raise RuntimeError("broken: forced close")


class _BrokenChunked:
    async def __call__(self, scope, receive, send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/html")],
            }
        )
        await send(
            {"type": "http.response.body", "body": b"chunked ", "more_body": True}
        )
        await send(
            {"type": "http.response.body", "body": b"content\n", "more_body": True}
        )
        raise RuntimeError("broken-chunked: forced close")


class _Drop:
    async def __call__(self, scope, receive, send) -> None:
        qs = parse_qs((scope.get("query_string") or b"").decode())
        abort = int(qs.get("abort", ["0"])[0])
        if abort:
            writer = current_writer.get()
            if writer is not None:
                sock = writer.get_extra_info("socket")
                if sock is not None:
                    sock.setsockopt(
                        socket.SOL_SOCKET,
                        socket.SO_LINGER,
                        struct.pack("ii", 1, 0),
                    )
                    os.close(sock.fileno())
            raise RuntimeError("drop: aborted")
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"text/html"),
                    (b"content-length", b"1024"),
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": b"this connection will be dropped\n",
                "more_body": True,
            }
        )
        raise RuntimeError("drop: forced close")


# Catch-all for unknown paths (mirrors Twisted's Root.getChild returning self).
async def catchall(request: Request) -> Response:
    return Response(b"Scrapy mock HTTP server\n", media_type=_HTML)


_ALL_METHODS = ["GET", "HEAD", "POST", "PUT", "DELETE"]

routes = [
    Route("/", root, methods=_ALL_METHODS),
    Route("/text", text, methods=_ALL_METHODS),
    Route("/redirect", redirect, methods=["GET", "HEAD"]),
    Route("/redirected", redirected, methods=["GET", "HEAD"]),
    Route("/status", status, methods=["GET", "HEAD"]),
    Route("/delay", delay, methods=["GET", "HEAD"]),
    Route("/host", host, methods=["GET", "HEAD"]),
    Route("/client-ip", client_ip, methods=["GET", "HEAD"]),
    Route("/contentlength", content_length_header, methods=_ALL_METHODS),
    Route("/nocontenttype", empty_content_type, methods=_ALL_METHODS),
    Route("/chunked", chunked, methods=["GET", "HEAD"]),
    Route("/largechunkedfile", large_chunked_file, methods=["GET", "HEAD"]),
    Route("/duplicate-header", duplicate_header, methods=["GET", "HEAD"]),
    Route("/echo", echo, methods=_ALL_METHODS),
    Route("/payload", payload, methods=_ALL_METHODS),
    Route("/alpayload", alpayload, methods=_ALL_METHODS),
    Route("/response-headers", response_headers, methods=_ALL_METHODS),
    Route("/compress", compress, methods=["GET", "HEAD"]),
    Route("/set-cookie", set_cookie, methods=["GET", "HEAD"]),
    Route("/wait", _Wait()),
    Route("/hang-after-headers", _HangAfterHeaders()),
    Route("/partial", _Partial()),
    Route("/broken", _Broken()),
    Route("/broken-chunked", _BrokenChunked()),
    Route("/drop", _Drop()),
    Route("/{rest:path}", catchall, methods=_ALL_METHODS),
]


app = Starlette(routes=routes)
