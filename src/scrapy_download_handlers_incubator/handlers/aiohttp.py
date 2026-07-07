"""``aiohttp``-based HTTP(S) download handler. Currently not recommended for production use."""

from __future__ import annotations

import asyncio
import ipaddress
import ssl
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, ClassVar, cast

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

from ._base_streaming import BaseStreamingDownloadHandler, _BaseResponseArgs

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from scrapy import Request
    from scrapy.crawler import Crawler


try:
    import aiohttp
    import aiohttp.connector
except ImportError:
    aiohttp = None  # type: ignore[assignment]


if aiohttp is not None:

    class _ClientResponse(aiohttp.ClientResponse):
        """Captures transport data that can be lost after parent ``start()``.

        Workaround for https://github.com/aio-libs/aiohttp/issues/2205.
        """

        _peername: tuple[str, int] | None = None
        _ssl_object: ssl.SSLObject | None = None

        async def start(
            self, connection: aiohttp.connector.Connection
        ) -> aiohttp.ClientResponse:
            transport = connection.transport
            if transport is not None:
                self._peername = transport.get_extra_info("peername")
                ssl_object = transport.get_extra_info("ssl_object")
                if isinstance(ssl_object, ssl.SSLObject):
                    self._ssl_object = ssl_object
            return await super().start(connection)


if TYPE_CHECKING:
    _Base = BaseStreamingDownloadHandler[_ClientResponse]
else:
    _Base = BaseStreamingDownloadHandler


class AiohttpDownloadHandler(_Base):
    experimental: ClassVar[bool] = True

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
            response_class=_ClientResponse,
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
    ) -> AsyncIterator[_ClientResponse]:
        proxy = self._extract_proxy_url_with_creds(request)
        headers = self._request_headers(request).to_tuple_list()
        try:
            async with await self._session.request(
                request.method,
                request.url,
                data=request.body,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
                ssl=self._ssl_context,
                allow_redirects=False,
                proxy=proxy,
            ) as response:
                yield cast("_ClientResponse", response)
        except (TimeoutError, asyncio.TimeoutError) as e:
            raise DownloadTimeoutError(
                f"Getting {request.url} took longer than {timeout} seconds."
            ) from e
        except (
            aiohttp.InvalidUrlClientError,
            aiohttp.NonHttpUrlClientError,
        ) as e:
            raise UnsupportedURLSchemeError(str(e)) from e
        except aiohttp.ClientConnectorDNSError as e:
            raise CannotResolveHostError(str(e)) from e
        except aiohttp.ClientConnectorError as e:
            raise DownloadConnectionRefusedError(str(e)) from e
        except aiohttp.ClientError as e:
            raise DownloadFailedError(str(e)) from e

    @staticmethod
    def _extract_headers(response: _ClientResponse) -> Headers:
        return Headers(list(response.headers.items()))

    @staticmethod
    def _build_base_response_args(
        response: _ClientResponse,
        request: Request,
        headers: Headers,
    ) -> _BaseResponseArgs:
        version = response.version
        protocol_version = (
            f"HTTP/{version.major}.{version.minor}" if version else "HTTP/1.1"
        )
        ip_address = cert = None
        if response._peername:
            ip_address = ipaddress.ip_address(response._peername[0])
        if response._ssl_object:
            cert = response._ssl_object.getpeercert(binary_form=True)
        return {
            "status": response.status,
            "url": request.url,
            "headers": headers,
            "certificate": cert,
            "ip_address": ip_address,
            "protocol": protocol_version,
        }

    def _log_tls_info(self, response: _ClientResponse, request: Request) -> None:
        if response._ssl_object:
            _log_sslobj_debug_info(response._ssl_object)

    @staticmethod
    def _iter_body_chunks(response: _ClientResponse) -> AsyncIterator[bytes]:
        return response.content.iter_any()

    @staticmethod
    def _is_dataloss_exception(exc: Exception) -> bool:
        return isinstance(exc, aiohttp.ClientPayloadError)

    async def close(self) -> None:
        await self._session.close()
