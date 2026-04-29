"""``aiohttp``-based HTTP(S) download handler. Currently not recommended for production use."""

from __future__ import annotations

import asyncio
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
from scrapy.utils.ssl import _make_ssl_context

from scrapy_download_handlers_incubator.handlers._base import (
    BaseStreamingDownloadHandler,
    _BaseResponseArgs,
)
from scrapy_download_handlers_incubator.utils import log_sslobj_debug_info

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from scrapy import Request
    from scrapy.crawler import Crawler


try:
    import aiohttp
except ImportError:
    aiohttp = None  # type: ignore[assignment]


if TYPE_CHECKING:
    _Base = BaseStreamingDownloadHandler[aiohttp.ClientResponse]
else:
    _Base = BaseStreamingDownloadHandler


class AiohttpDownloadHandler(_Base):
    def __init__(self, crawler: Crawler):
        super().__init__(crawler)
        self._ssl_context: ssl.SSLContext = _make_ssl_context(crawler.settings)
        connector = aiohttp.TCPConnector(
            local_addr=self._bind_address,
            # hard limit on simultaneous connections
            limit=self._pool_size_total,
            # hard limit on simultaneous connections per host
            limit_per_host=self._pool_size_per_host,
        )
        self._session: aiohttp.ClientSession = aiohttp.ClientSession(
            connector=connector,
            cookie_jar=aiohttp.DummyCookieJar(),
            auto_decompress=False,
            skip_auto_headers=(
                "Accept",
                "Accept-Encoding",
                "Content-Type",
                "User-Agent",
            ),
        )

    @staticmethod
    def _check_deps_installed() -> None:
        if aiohttp is None:  # pragma: no cover
            raise NotConfigured(
                "AiohttpDownloadHandler requires the aiohttp library to be installed."
            )

    @asynccontextmanager
    async def _make_request(
        self, request: Request, timeout: float
    ) -> AsyncIterator[aiohttp.ClientResponse]:
        proxy = self._extract_proxy_url_with_creds(request)
        try:
            async with await self._session.request(
                request.method,
                request.url,
                data=request.body,
                headers=request.headers.to_tuple_list(),
                timeout=aiohttp.ClientTimeout(total=timeout),
                ssl=self._ssl_context,
                allow_redirects=False,
                proxy=proxy,
            ) as response:
                yield response
        except (TimeoutError, asyncio.TimeoutError) as e:
            raise DownloadTimeoutError(
                f"Getting {request.url} took longer than {timeout} seconds."
            ) from e
        except (
            aiohttp.InvalidUrlClientError,
            aiohttp.NonHttpUrlClientError,
        ) as e:
            raise UnsupportedURLSchemeError(str(e)) from e
        except aiohttp.ClientConnectorError as e:
            if (
                # os_error is absent on ClientConnectorCertificateError before aiohttp 3.13.4
                hasattr(e, "os_error")
                and isinstance(e.os_error, OSError)
                and e.os_error.strerror
                and (
                    "Name or service not known" in e.os_error.strerror
                    or "getaddrinfo failed" in e.os_error.strerror
                    or "nodename nor servname" in e.os_error.strerror
                )
            ):
                raise CannotResolveHostError(str(e)) from e
            raise DownloadConnectionRefusedError(str(e)) from e
        except aiohttp.ClientError as e:
            raise DownloadFailedError(str(e)) from e

    @staticmethod
    def _extract_headers(response: aiohttp.ClientResponse) -> Headers:
        return Headers(list(response.headers.items()))

    @staticmethod
    def _build_base_response_args(
        response: aiohttp.ClientResponse,
        request: Request,
        headers: Headers,
    ) -> _BaseResponseArgs:
        version = response.version
        protocol_version = (
            f"HTTP/{version.major}.{version.minor}" if version else "HTTP/1.1"
        )
        ip_address = cert = None
        conn = response.connection
        if conn is not None and conn.transport is not None:
            # This only work for large responses, where the connection
            # is not closed right in ClientResponse.start().
            # We can subclass ClientResponse to capture peername and
            # ssl_object early if we really want.
            peername = conn.transport.get_extra_info("peername")
            if peername:
                ip_address = ipaddress.ip_address(peername[0])
            ssl_object = conn.transport.get_extra_info("ssl_object")
            if isinstance(ssl_object, ssl.SSLObject):
                cert = ssl_object.getpeercert(binary_form=True)
        return {
            "status": response.status,
            "url": request.url,
            "headers": headers,
            "certificate": cert,
            "ip_address": ip_address,
            "protocol": protocol_version,
        }

    def _log_tls_info(self, response: aiohttp.ClientResponse, request: Request) -> None:
        conn = response.connection
        if conn is None or conn.transport is None:
            return
        ssl_object = conn.transport.get_extra_info("ssl_object")
        if isinstance(ssl_object, ssl.SSLObject):
            log_sslobj_debug_info(ssl_object)

    @staticmethod
    def _iter_body_chunks(response: aiohttp.ClientResponse) -> AsyncIterator[bytes]:
        return response.content.iter_any()

    @staticmethod
    def _is_dataloss_exception(exc: Exception) -> bool:
        return isinstance(exc, aiohttp.ClientPayloadError)

    async def close(self) -> None:
        await self._session.close()
