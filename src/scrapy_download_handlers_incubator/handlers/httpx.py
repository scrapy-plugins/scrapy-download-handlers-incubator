"""``httpx``-based HTTP(S) download handler. Currently not recommended for production use."""

from __future__ import annotations

import ipaddress
import ssl
from typing import TYPE_CHECKING, Any

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
)
from scrapy_download_handlers_incubator.utils import NullCookieJar

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from contextlib import AbstractAsyncContextManager
    from ipaddress import IPv4Address, IPv6Address

    from httpcore import AsyncNetworkStream
    from scrapy import Request
    from scrapy.crawler import Crawler
    from scrapy.http import Response


try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]


class HttpxDownloadHandler(BaseIncubatorDownloadHandler):
    def __init__(self, crawler: Crawler):
        super().__init__(crawler)
        self._client = httpx.AsyncClient(
            cookies=NullCookieJar(),
            transport=httpx.AsyncHTTPTransport(
                verify=_make_ssl_context(crawler.settings),
                local_address=self._get_bind_address_host(),
            ),
        )

    @staticmethod
    def _check_deps_installed() -> None:
        if httpx is None:  # pragma: no cover
            raise NotConfigured(
                "HttpxDownloadHandler requires the httpx library to be installed."
            )

    def _get_httpx_response(
        self, request: Request, timeout: float
    ) -> AbstractAsyncContextManager[httpx.Response]:
        return self._client.stream(
            request.method,
            request.url,
            content=request.body,
            headers=request.headers.to_tuple_list(),
            timeout=timeout,
        )

    async def download_request(self, request: Request) -> Response:
        self._warn_unsupported_meta(request.meta)

        timeout: float = request.meta.get(
            "download_timeout", self._DEFAULT_CONNECT_TIMEOUT
        )

        try:
            async with self._get_httpx_response(request, timeout) as httpx_response:
                return await self._read_response(httpx_response, request)
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
        except httpx.NetworkError as e:
            raise DownloadFailedError(str(e)) from e
        except httpx.RemoteProtocolError as e:
            raise DownloadFailedError(str(e)) from e

    @staticmethod
    def _extract_headers(response: httpx.Response) -> Headers:
        return Headers(response.headers.multi_items())

    @staticmethod
    def _build_base_response_args(
        response: httpx.Response,
        request: Request,
        headers: Headers,
    ) -> dict[str, Any]:
        network_stream: AsyncNetworkStream = response.extensions["network_stream"]
        return {
            "status": response.status_code,
            "url": request.url,
            "headers": headers,
            "ip_address": HttpxDownloadHandler._get_server_ip(network_stream),
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

    @staticmethod
    def _get_server_ip(
        network_stream: AsyncNetworkStream,
    ) -> IPv4Address | IPv6Address:
        extra_server_addr = network_stream.get_extra_info("server_addr")
        return ipaddress.ip_address(extra_server_addr[0])

    def _log_tls_info(self, response: httpx.Response, request: Request) -> None:
        network_stream: AsyncNetworkStream = response.extensions["network_stream"]
        extra_ssl_object = network_stream.get_extra_info("ssl_object")
        if isinstance(extra_ssl_object, ssl.SSLObject):
            _log_sslobj_debug_info(extra_ssl_object)

    async def close(self) -> None:
        await self._client.aclose()
