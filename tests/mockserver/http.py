from __future__ import annotations

import argparse
import asyncio
import contextlib
from pathlib import Path

from hypercorn.asyncio import wrap_app
from hypercorn.asyncio.run import worker_serve
from hypercorn.asyncio.tcp_server import TCPServer
from hypercorn.config import Config

from .http_base import BaseMockServer
from .starlette_app import app, current_writer


class MockServer(BaseMockServer):
    module_name = "tests.mockserver.http"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keyfile", default=None)
    parser.add_argument("--certfile", default=None)
    parser.add_argument("--cipher-string", default=None)
    parser.add_argument("--no-listen-http", dest="listen_http", action="store_false")
    parser.add_argument("--no-listen-https", dest="listen_https", action="store_false")
    parser.add_argument("--listen-h3", action="store_true")
    parser.set_defaults(listen_http=True, listen_https=True, listen_h3=False)
    args = parser.parse_args()

    # Expose the per-connection writer to ASGI handlers via a contextvar, so
    # /drop?abort=1 can force a TCP RST. TaskGroup children inherit the context.
    _original_run = TCPServer.run

    async def _run_with_writer(self):  # type: ignore[no-untyped-def]
        current_writer.set(self.writer)
        await _original_run(self)

    TCPServer.run = _run_with_writer  # type: ignore[method-assign]

    config = Config()
    config.accesslog = None
    config.errorlog = None
    config.graceful_timeout = 0.5
    # Don't auto-add Date so handlers that set their own produce a single Date header.
    config.include_date_header = False

    keys_dir = Path(__file__).parent.parent / "keys"
    config.certfile = args.certfile or str(keys_dir / "localhost.crt")
    config.keyfile = args.keyfile or str(keys_dir / "localhost.key")
    if args.cipher_string:
        config.ciphers = args.cipher_string

    config.insecure_bind = ["127.0.0.1:0"] if args.listen_http else []
    config.bind = ["127.0.0.1:0"] if args.listen_https else []
    config.quic_bind = ["127.0.0.1:0"] if args.listen_h3 else []
    config.alpn_protocols = ["h2", "http/1.1"]

    sockets = config.create_sockets()

    # BaseMockServer reads addresses in this exact order: http, https, h3.
    for sock in sockets.insecure_sockets:
        host_, port_ = sock.getsockname()[:2]
        print(f"http://{host_}:{port_}", flush=True)
    for sock in sockets.secure_sockets:
        host_, port_ = sock.getsockname()[:2]
        print(f"https://{host_}:{port_}", flush=True)
    for sock in sockets.quic_sockets:
        host_, port_ = sock.getsockname()[:2]
        print(f"https+h3://{host_}:{port_}", flush=True)

    async def _run() -> None:
        await worker_serve(
            wrap_app(app, config.wsgi_max_body_size, None),
            config,
            sockets=sockets,
        )

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_run())


if __name__ == "__main__":
    main()
