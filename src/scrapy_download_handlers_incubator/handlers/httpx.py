"""``httpx``-based HTTP(S) download handler. Currently not recommended for production use."""

from __future__ import annotations

import ipaddress
import ssl
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from scrapy.exceptions import (
    CannotResolveHostError,
    DownloadConnectionRefusedError,
    DownloadFailedError,
    DownloadTimeoutError,
    NotConfigured,
    UnsupportedURLSchemeError,
)
from scrapy.http import Headers
from scrapy.utils.ssl import _log_sslobj_debug_info, _make_ssl_context

from scrapy_download_handlers_incubator.handlers._base import (
    BaseIncubatorDownloadHandler,
    _BaseResponseArgs,
)
from scrapy_download_handlers_incubator.utils import NullCookieJar

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from httpcore import AsyncNetworkStream
    from scrapy import Request
    from scrapy.crawler import Crawler


try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]


if TYPE_CHECKING:
    _Base = BaseIncubatorDownloadHandler[httpx.Response]
else:
    _Base = BaseIncubatorDownloadHandler


class HttpxDownloadHandler(_Base):
    def __init__(self, crawler: Crawler):
        super().__init__(crawler)
        enable_h2 = crawler.settings.getbool("HTTPX_HTTP2_ENABLED")
        self._client = httpx.AsyncClient(
            cookies=NullCookieJar(),
            transport=httpx.AsyncHTTPTransport(
                verify=_make_ssl_context(crawler.settings),
                local_address=self._get_bind_address_host(),
                http2=enable_h2,
                limits=httpx.Limits(
                    # hard limit on simultaneous connections
                    max_connections=self._pool_size_total,
                    # total number of idle connections in the pool (extra ones are closed)
                    max_keepalive_connections=self._pool_size_total,
                ),
            ),
        )
        # https://github.com/encode/httpx/discussions/1566
        for header_name in ("accept", "accept-encoding", "connection", "user-agent"):
            self._client.headers.pop(header_name, None)

    @staticmethod
    def _check_deps_installed() -> None:
        if httpx is None:  # pragma: no cover
            raise NotConfigured(
                "HttpxDownloadHandler requires the httpx library to be installed."
            )

    @asynccontextmanager
    async def _make_request(
        self, request: Request, timeout: float
    ) -> AsyncIterator[httpx.Response]:
        try:
            async with self._client.stream(
                request.method,
                request.url,
                content=request.body,
                headers=request.headers.to_tuple_list(),
                timeout=timeout,
            ) as response:
                yield response
        except httpx.TimeoutException as e:
            raise DownloadTimeoutError(
                f"Getting {request.url} took longer than {timeout} seconds."
            ) from e
        except httpx.UnsupportedProtocol as e:
            raise UnsupportedURLSchemeError(str(e)) from e
        except httpx.ConnectError as e:
            error_message = str(e)
            if (
                "Name or service not known" in error_message
                or "getaddrinfo failed" in error_message
                or "nodename nor servname" in error_message
                or "Temporary failure in name resolution" in error_message
            ):
                raise CannotResolveHostError(error_message) from e
            raise DownloadConnectionRefusedError(str(e)) from e
        except (httpx.NetworkError, httpx.RemoteProtocolError) as e:
            raise DownloadFailedError(str(e)) from e

    @staticmethod
    def _extract_headers(response: httpx.Response) -> Headers:
        return Headers(response.headers.multi_items())

    @staticmethod
    def _build_base_response_args(
        response: httpx.Response,
        request: Request,
        headers: Headers,
    ) -> _BaseResponseArgs:
        network_stream: AsyncNetworkStream = response.extensions["network_stream"]
        extra_server_addr = network_stream.get_extra_info("server_addr")
        ip_address = ipaddress.ip_address(extra_server_addr[0])
        return {
            "status": response.status_code,
            "url": request.url,
            "headers": headers,
            "ip_address": ip_address,
            "protocol": response.http_version,
        }

    @staticmethod
    def _iter_body_chunks(response: httpx.Response) -> AsyncIterator[bytes]:
        return response.aiter_raw()

    @staticmethod
    def _is_dataloss_exception(exc: Exception) -> bool:
        return isinstance(
            exc, httpx.RemoteProtocolError
        ) and "peer closed connection without sending complete message body" in str(exc)

    def _log_tls_info(self, response: httpx.Response, request: Request) -> None:
        network_stream: AsyncNetworkStream = response.extensions["network_stream"]
        extra_ssl_object = network_stream.get_extra_info("ssl_object")
        if isinstance(extra_ssl_object, ssl.SSLObject):
            _log_sslobj_debug_info(extra_ssl_object)

    async def close(self) -> None:
        await self._client.aclose()
