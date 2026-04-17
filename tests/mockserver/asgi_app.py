"""ASGI resources mirroring tests/mockserver/http_resources.py.

Served by Hypercorn to support HTTP/1.1, HTTP/2 and HTTP/3 with one codebase.
Raw-ASGI handlers (not Starlette) so that we can control framing and truncation
as needed by the mock-server's error-injection endpoints.
"""

from __future__ import annotations

import asyncio
import contextvars
import gzip
import json
import os
import socket
import struct
from typing import Any
from urllib.parse import parse_qs

Scope = dict[str, Any]


# Populated by http.py's TCPServer monkey-patch so /drop?abort=1 can RST the socket.
current_writer: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "current_writer", default=None
)

_HTML = [(b"content-type", b"text/html")]
_TEXT = [(b"content-type", b"text/plain")]
_JSON = [(b"content-type", b"application/json")]


def _qs(scope: Scope) -> dict[str, list[str]]:
    return parse_qs((scope.get("query_string") or b"").decode(), keep_blank_values=True)


def _arg(
    qs: dict[str, list[str]], name: str, default: Any = None, type_: Any = None
) -> Any:
    values = qs.get(name)
    if not values:
        return default
    value = values[0]
    if type_ is not None:
        value = type_(value)
    return value


def _header(scope: Scope, name: bytes) -> bytes:
    for n, v in scope["headers"]:
        if n == name:
            return v
    return b""


def _title_case(name: str) -> str:
    # ASGI lowercases headers; Twisted preserves casing. Tests compare names like
    # "Accept-Charset" and "X-Custom-Header", so title-case each hyphen segment.
    return "-".join(part.capitalize() for part in name.split("-"))


async def _read_body(receive: Any) -> bytes:
    body = b""
    while True:
        message = await receive()
        if message["type"] == "http.request":
            body += message.get("body") or b""
            if not message.get("more_body", False):
                return body
        elif message["type"] == "http.disconnect":
            raise _ClientDisconnect


class _ClientDisconnect(Exception):
    pass


async def _respond(
    send: Any,
    *,
    status: int = 200,
    headers: list[tuple[bytes, bytes]] = _HTML,
    body: bytes = b"",
) -> None:
    # Always set Content-Length so Hypercorn doesn't fall back to chunked encoding.
    if not any(name.lower() == b"content-length" for name, _ in headers):
        headers = [*headers, (b"content-length", str(len(body)).encode())]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


async def _wait_disconnect(receive: Any) -> None:
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            return


# --- Handlers ---


async def root(scope: Scope, receive: Any, send: Any) -> None:
    await _respond(send, body=b"Scrapy mock HTTP server\n")


async def text(scope: Scope, receive: Any, send: Any) -> None:
    await _respond(send, headers=_TEXT, body=b"Works")


async def redirect(scope: Scope, receive: Any, send: Any) -> None:
    headers = [*_HTML, (b"location", b"/redirected")]
    await _respond(send, status=302, headers=headers)


async def redirected(scope: Scope, receive: Any, send: Any) -> None:
    await _respond(send, headers=_TEXT, body=b"Redirected here")


async def status(scope: Scope, receive: Any, send: Any) -> None:
    n = _arg(_qs(scope), "n", 200, int)
    await _respond(send, status=n)


async def delay(scope: Scope, receive: Any, send: Any) -> None:
    qs = _qs(scope)
    n = _arg(qs, "n", 1, float)
    send_headers_first = _arg(qs, "b", 1, int)
    body = f"Response delayed for {n:.3f} seconds\n".encode()
    if send_headers_first:
        await send({"type": "http.response.start", "status": 200, "headers": _HTML})
        await send({"type": "http.response.body", "body": b"", "more_body": True})
        await asyncio.sleep(n)
        await send({"type": "http.response.body", "body": body})
    else:
        await asyncio.sleep(n)
        await _respond(send, body=body)


async def wait_forever(scope: Scope, receive: Any, send: Any) -> None:
    # Client connects, no data is ever sent.
    await _wait_disconnect(receive)


async def hang_after_headers(scope: Scope, receive: Any, send: Any) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": _HTML})
    await send({"type": "http.response.body", "body": b"some bytes", "more_body": True})
    await _wait_disconnect(receive)


async def host(scope: Scope, receive: Any, send: Any) -> None:
    await _respond(send, body=_header(scope, b"host"))


async def client_ip(scope: Scope, receive: Any, send: Any) -> None:
    client = scope.get("client")
    ip = client[0].encode() if client and client[0] else b""
    await _respond(send, body=ip)


async def partial(scope: Scope, receive: Any, send: Any) -> None:
    # Content-Length advertised as 1024, only a short body sent, then close.
    headers = [*_HTML, (b"content-length", b"1024")]
    await send({"type": "http.response.start", "status": 200, "headers": headers})
    await send(
        {"type": "http.response.body", "body": b"partial content\n", "more_body": True}
    )
    # Force the server to close the stream without sending the remaining bytes.
    raise RuntimeError("partial: forced close")


async def drop(scope: Scope, receive: Any, send: Any) -> None:
    # ?abort=0 (default) = graceful close mid-response -> ResponseDataLossError.
    # ?abort=1 = TCP RST -> DownloadFailedError. For abort=1 we bypass asyncio
    # entirely (SO_LINGER=0 + os.close on the raw fd) before any response is
    # sent, so the client gets a pure RST rather than a partial body + close.
    abort = _arg(_qs(scope), "abort", 0, int)
    if abort:
        writer = current_writer.get()
        if writer is not None:
            sock = writer.get_extra_info("socket")
            if sock is not None:
                sock.setsockopt(
                    socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0)
                )
                os.close(sock.fileno())
        raise RuntimeError("drop: aborted")
    headers = [*_HTML, (b"content-length", b"1024")]
    await send({"type": "http.response.start", "status": 200, "headers": headers})
    await send(
        {
            "type": "http.response.body",
            "body": b"this connection will be dropped\n",
            "more_body": True,
        }
    )
    raise RuntimeError("drop: forced close")


async def broken(scope: Scope, receive: Any, send: Any) -> None:
    # Content-Length: 20 but only 7 bytes written before close. Client sees dataloss.
    headers = [*_HTML, (b"content-length", b"20")]
    await send({"type": "http.response.start", "status": 200, "headers": headers})
    await send({"type": "http.response.body", "body": b"partial", "more_body": True})
    raise RuntimeError("broken: forced close")


async def broken_chunked(scope: Scope, receive: Any, send: Any) -> None:
    # No Content-Length -> Hypercorn uses chunked encoding on HTTP/1.1. Close mid-stream
    # to drop the terminating chunk. (On HTTP/2+ this becomes a stream reset.)
    await send({"type": "http.response.start", "status": 200, "headers": _HTML})
    await send({"type": "http.response.body", "body": b"chunked ", "more_body": True})
    await send({"type": "http.response.body", "body": b"content\n", "more_body": True})
    raise RuntimeError("broken-chunked: forced close")


async def chunked(scope: Scope, receive: Any, send: Any) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": _HTML})
    await send({"type": "http.response.body", "body": b"chunked ", "more_body": True})
    await send({"type": "http.response.body", "body": b"content\n"})


async def content_length_header(scope: Scope, receive: Any, send: Any) -> None:
    await _respond(send, body=_header(scope, b"content-length"))


async def empty_content_type(scope: Scope, receive: Any, send: Any) -> None:
    body = await _read_body(receive)
    # Hypercorn forbids empty header values in recent versions; send a single space
    # so the response still carries a (near-)empty Content-Type, which is what the
    # test cares about.
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b" ")],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def large_chunked_file(scope: Scope, receive: Any, send: Any) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": _HTML})
    chunk = b"x" * 1024
    for _ in range(1024):
        await send({"type": "http.response.body", "body": chunk, "more_body": True})
    await send({"type": "http.response.body", "body": b""})


async def duplicate_header(scope: Scope, receive: Any, send: Any) -> None:
    headers = [*_HTML, (b"set-cookie", b"a=b"), (b"set-cookie", b"c=d")]
    await _respond(send, headers=headers)


async def echo(scope: Scope, receive: Any, send: Any) -> None:
    body = await _read_body(receive)
    headers: dict[str, list[str]] = {}
    for name, value in scope["headers"]:
        headers.setdefault(_title_case(name.decode()), []).append(value.decode())
    payload = json.dumps({"headers": headers, "body": body.decode()}).encode()
    await _respond(send, headers=_HTML, body=payload)


async def payload(scope: Scope, receive: Any, send: Any) -> None:
    body = await _read_body(receive)
    cl = _header(scope, b"content-length")
    if len(body) != 100 or cl != b"100":
        await _respond(send, body=b"ERROR")
    else:
        await _respond(send, body=body)


async def alpayload(scope: Scope, receive: Any, send: Any) -> None:
    body = await _read_body(receive)
    await _respond(send, body=body)


async def response_headers(scope: Scope, receive: Any, send: Any) -> None:
    body = await _read_body(receive)
    body_json: dict[str, str] = json.loads(body.decode()) if body else {}
    explicit_ct = any(k.lower() == "content-type" for k in body_json)
    headers: list[tuple[bytes, bytes]] = []
    if not explicit_ct:
        headers.extend(_JSON)
    for name, value in body_json.items():
        headers.append((name.encode(), value.encode()))
    response_body = json.dumps(body_json).encode()
    await _respond(send, headers=headers, body=response_body)


async def compress(scope: Scope, receive: Any, send: Any) -> None:
    data = _arg(_qs(scope), "data", "")
    data_bytes = data.encode() if isinstance(data, str) else data
    if _header(scope, b"accept-encoding") == b"gzip":
        compressed = gzip.compress(data_bytes)
        headers = [*_HTML, (b"content-encoding", b"gzip")]
        await _respond(send, headers=headers, body=compressed)
    else:
        await _respond(
            send, status=500, body=b"Did not receive a valid accept-encoding header"
        )


async def set_cookie(scope: Scope, receive: Any, send: Any) -> None:
    headers: list[tuple[bytes, bytes]] = list(_HTML)
    for name, values in _qs(scope).items():
        for value in values:
            headers.append((b"set-cookie", f"{name}={value}".encode()))
    await _respond(send, headers=headers)


# --- Dispatch ---


_ROUTES = {
    "/": root,
    "/text": text,
    "/redirect": redirect,
    "/redirected": redirected,
    "/status": status,
    "/delay": delay,
    "/wait": wait_forever,
    "/hang-after-headers": hang_after_headers,
    "/host": host,
    "/client-ip": client_ip,
    "/partial": partial,
    "/drop": drop,
    "/broken": broken,
    "/broken-chunked": broken_chunked,
    "/chunked": chunked,
    "/contentlength": content_length_header,
    "/nocontenttype": empty_content_type,
    "/largechunkedfile": large_chunked_file,
    "/duplicate-header": duplicate_header,
    "/echo": echo,
    "/payload": payload,
    "/alpayload": alpayload,
    "/response-headers": response_headers,
    "/compress": compress,
    "/set-cookie": set_cookie,
}


async def app(scope: Scope, receive: Any, send: Any) -> None:
    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            t = message["type"]
            if t == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif t == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
    if scope["type"] != "http":
        return
    handler = _ROUTES.get(scope["path"], root)
    try:
        await handler(scope, receive, send)
    except _ClientDisconnect:
        pass
