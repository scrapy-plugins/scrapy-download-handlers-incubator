"""Base classes and functions for HTTP mockservers."""

from __future__ import annotations

import argparse
import sys
from abc import ABC, abstractmethod
from subprocess import PIPE, Popen
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from twisted.web.server import Site

from tests.utils import get_script_run_env

from .utils import ssl_context_factory

if TYPE_CHECKING:
    from collections.abc import Callable

    from twisted.web import resource


class BaseMockServer(ABC):
    listen_http: bool = True
    listen_https: bool = True
    listen_h3: bool = False

    @property
    @abstractmethod
    def module_name(self) -> str:
        raise NotImplementedError

    def __init__(self) -> None:
        if not self.listen_http and not self.listen_https and not self.listen_h3:
            raise ValueError(
                "At least one of listen_http/listen_https/listen_h3 must be set"
            )

        self.proc: Popen[bytes] | None = None
        self.host: str = "127.0.0.1"
        self.http_port: int | None = None
        self.https_port: int | None = None
        self.h3_port: int | None = None

    def __enter__(self):
        self.proc = Popen(
            [sys.executable, "-u", "-m", self.module_name, *self.get_additional_args()],
            stdout=PIPE,
            env=get_script_run_env(),
        )
        if self.listen_http:
            self.http_port = urlparse(self._readline()).port
        if self.listen_https:
            self.https_port = urlparse(self._readline()).port
        if self.listen_h3:
            self.h3_port = urlparse(self._readline()).port
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.proc:
            self.proc.kill()
            self.proc.communicate()

    def _readline(self) -> str:
        assert self.proc is not None
        assert self.proc.stdout is not None
        return self.proc.stdout.readline().strip().decode("ascii")

    def get_additional_args(self) -> list[str]:
        args: list[str] = []
        if not self.listen_http:
            args.append("--no-listen-http")
        if not self.listen_https:
            args.append("--no-listen-https")
        if self.listen_h3:
            args.append("--listen-h3")
        return args

    def port(self, is_secure: bool = False) -> int:
        if not is_secure and not self.listen_http:
            raise ValueError("This server doesn't provide HTTP")
        if is_secure and not self.listen_https:
            raise ValueError("This server doesn't provide HTTPS")
        port = self.https_port if is_secure else self.http_port
        assert port is not None
        return port

    def url(self, path: str, is_secure: bool = False) -> str:
        port = self.port(is_secure)
        scheme = "https" if is_secure else "http"
        return f"{scheme}://{self.host}:{port}{path}"


def main_factory(
    resource_class: type[resource.Resource],
    *,
    listen_http: bool = True,
    listen_https: bool = True,
) -> Callable[[], None]:
    if not listen_http and not listen_https:
        raise ValueError("At least one of listen_http and listen_https must be set")

    def main() -> None:
        from twisted.internet import reactor

        root = resource_class()
        factory = Site(root)  # type: ignore[no-untyped-call]

        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--no-listen-http", dest="listen_http", action="store_false"
        )
        parser.add_argument(
            "--no-listen-https", dest="listen_https", action="store_false"
        )
        parser.add_argument("--listen-h3", action="store_true")
        parser.set_defaults(listen_http=listen_http, listen_https=listen_https)
        parser.add_argument("--keyfile", help="SSL key file")
        parser.add_argument("--certfile", help="SSL certificate file")
        parser.add_argument(
            "--cipher-string", default=None, help="SSL cipher string (optional)"
        )
        args = parser.parse_args()

        if args.listen_h3:
            raise RuntimeError(
                "HTTP/3 is not supported by main_factory (Twisted mock server)."
            )

        if args.listen_http:
            http_port = reactor.listenTCP(0, factory)

        if args.listen_https:
            context_factory_kw = {}
            if args.keyfile:
                context_factory_kw["keyfile"] = args.keyfile
            if args.certfile:
                context_factory_kw["certfile"] = args.certfile
            if args.cipher_string:
                context_factory_kw["cipher_string"] = args.cipher_string
            context_factory = ssl_context_factory(**context_factory_kw)
            https_port = reactor.listenSSL(0, factory, context_factory)

        def print_listening():
            if args.listen_http:
                http_host = http_port.getHost()
                print(f"http://{http_host.host}:{http_host.port}")
            if args.listen_https:
                https_host = https_port.getHost()
                print(f"https://{https_host.host}:{https_host.port}")

        reactor.callWhenRunning(print_listening)
        reactor.run()

    return main
