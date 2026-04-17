"""``niquests``-based HTTP(S) download handler. Currently not recommended for production use."""

from __future__ import annotations

import ipaddress
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from scrapy.exceptions import (
    CannotResolveHostError,
    DownloadConnectionRefusedError,
    DownloadFailedError,
    DownloadTimeoutError,
    NotConfigured,
    UnsupportedURLSchemeError,
)
from scrapy.http import Headers

from scrapy_download_handlers_incubator.handlers._base import (
    BaseIncubatorDownloadHandler,
    _BaseResponseArgs,
)
from scrapy_download_handlers_incubator.utils import NullCookieJar

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from scrapy import Request
    from scrapy.crawler import Crawler


try:
    import niquests
    import niquests.exceptions
    import urllib3
    import urllib3.exceptions
except ImportError:
    niquests = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    _Base = BaseIncubatorDownloadHandler[niquests.AsyncResponse]
else:
    _Base = BaseIncubatorDownloadHandler


class NiquestsDownloadHandler(_Base):
    def __init__(self, crawler: Crawler):
        super().__init__(crawler)
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        self._verify_certificates: bool = crawler.settings.getbool(
            "DOWNLOAD_VERIFY_CERTIFICATES"
        )
        enable_h2 = crawler.settings.getbool("NIQUESTS_HTTP2_ENABLED")
        self._session = niquests.AsyncSession(
            headers={},
            source_address=self._bind_address,
            disable_http2=not enable_h2,
            disable_http3=True,
            # number of host buckets in the pool (older extra ones are discarded)
            pool_connections=self._pool_size_total,
            # number of connections per host in the pool (newer extra ones are not put there)
            pool_maxsize=self._pool_size_per_host,
        )
        self._session.cookies = NullCookieJar()
        self._session.trust_env = False

    @staticmethod
    def _check_deps_installed() -> None:
        if niquests is None:  # pragma: no cover
            raise NotConfigured(
                "NiquestsDownloadHandler requires the niquests library to be installed."
            )

    @asynccontextmanager
    async def _make_request(
        self, request: Request, timeout: float
    ) -> AsyncIterator[niquests.AsyncResponse]:
        headers = request.headers.to_unicode_dict()
        for k in list(headers):
            if headers[k] == "":
                del headers[k]
        try:
            async with await self._session.request(
                method=request.method,
                url=request.url,
                data=request.body,
                headers=headers,
                timeout=timeout,
                allow_redirects=False,
                stream=True,
                verify=self._verify_certificates,
            ) as nq_response:
                yield nq_response
        except niquests.exceptions.ReadTimeout as e:
            raise DownloadTimeoutError(
                f"Getting {request.url} took longer than {timeout} seconds."
            ) from e
        except niquests.exceptions.InvalidSchema as e:
            raise UnsupportedURLSchemeError(str(e)) from e
        except niquests.exceptions.ConnectionError as e:
            match e.__context__:
                case urllib3.exceptions.MaxRetryError():
                    match e.__context__.__context__:
                        case urllib3.exceptions.NameResolutionError():
                            raise CannotResolveHostError(str(e)) from e
                        case urllib3.exceptions.NewConnectionError():
                            raise DownloadConnectionRefusedError(str(e)) from e
                case urllib3.exceptions.ReadTimeoutError():
                    raise DownloadTimeoutError(str(e)) from e
            raise DownloadFailedError(str(e)) from e

    @staticmethod
    def _extract_headers(response: niquests.AsyncResponse) -> Headers:
        return Headers(response.headers.items())  # type: ignore[no-untyped-call]

    @staticmethod
    def _build_base_response_args(
        response: niquests.AsyncResponse,
        request: Request,
        headers: Headers,
    ) -> _BaseResponseArgs:
        assert response.conn_info is not None
        ip_address = None
        if response.conn_info.destination_address:
            ip_address = ipaddress.ip_address(response.conn_info.destination_address[0])
        protocol = None
        if response.conn_info.http_version:
            protocol = response.conn_info.http_version.value
        assert response.status_code is not None
        return {
            "status": response.status_code,
            "url": request.url,
            "headers": headers,
            "ip_address": ip_address,
            "protocol": protocol,
        }

    @staticmethod
    async def _iter_body_chunks(
        response: niquests.AsyncResponse,
    ) -> AsyncIterator[bytes]:
        async for chunk in await response.iter_raw():
            yield chunk

    @staticmethod
    def _is_dataloss_exception(exc: Exception) -> bool:
        return isinstance(exc, niquests.exceptions.ChunkedEncodingError)

    def _log_tls_info(self, response: niquests.AsyncResponse, request: Request) -> None:
        conn_info = response.conn_info
        if conn_info and conn_info.tls_version:
            logger.debug(
                f"SSL connection to {urlparse(request.url).hostname}"
                f" using protocol {conn_info.tls_version.name},"
                f" cipher {conn_info.cipher}"
            )

    async def close(self) -> None:
        await self._session.close()
