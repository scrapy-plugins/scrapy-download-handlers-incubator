"""``aiohttp``-based HTTP(S) download handler. Currently not recommended for production use."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
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
from scrapy.utils.ssl import _make_ssl_context

from scrapy_download_handlers_incubator.handlers._base import (
    BaseIncubatorDownloadHandler,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from scrapy import Request
    from scrapy.crawler import Crawler


try:
    import aiohttp
except ImportError:
    aiohttp = None  # type: ignore[assignment]


class AiohttpDownloadHandler(BaseIncubatorDownloadHandler):
    def __init__(self, crawler: Crawler):
        super().__init__(crawler)
        self._ssl_context = _make_ssl_context(crawler.settings)
        self._connector = aiohttp.TCPConnector(local_addr=self._bind_address)
        self._session: aiohttp.ClientSession | None = None

    @staticmethod
    def _check_deps_installed() -> None:
        if aiohttp is None:  # pragma: no cover
            raise NotConfigured(
                "AiohttpDownloadHandler requires the aiohttp library to be installed."
            )

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                connector=self._connector,
                connector_owner=False,
                cookie_jar=aiohttp.DummyCookieJar(),
                auto_decompress=False,
            )
        return self._session

    @asynccontextmanager
    async def _make_request(
        self, request: Request, timeout: float
    ) -> AsyncIterator[aiohttp.ClientResponse]:
        session = self._get_session()
        try:
            async with await session._request(
                request.method,
                request.url,
                data=request.body,
                headers=request.headers.to_tuple_list(),
                timeout=aiohttp.ClientTimeout(total=timeout),
                ssl=self._ssl_context,
                allow_redirects=False,
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
    ) -> dict[str, Any]:
        version = response.version
        protocol_version = (
            f"HTTP/{version.major}.{version.minor}" if version else "HTTP/1.1"
        )
        return {
            "status": response.status,
            "url": request.url,
            "headers": headers,
            "protocol": protocol_version,
        }

    @staticmethod
    def _iter_body_chunks(response: aiohttp.ClientResponse) -> AsyncIterator[bytes]:
        return response.content.iter_chunked(AiohttpDownloadHandler._ITER_CHUNK_SIZE)

    @staticmethod
    def _is_dataloss_exception(exc: Exception) -> bool:
        return isinstance(exc, aiohttp.ClientPayloadError)

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        if not self._connector.closed:
            await self._connector.close()
