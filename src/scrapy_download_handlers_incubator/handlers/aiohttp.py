"""``aiohttp``-based HTTP(S) download handler. Currently not recommended for production use."""

from __future__ import annotations

import logging
from io import BytesIO
from typing import TYPE_CHECKING, Any, NoReturn, TypedDict

from scrapy import Request, signals
from scrapy.exceptions import (
    CannotResolveHostError,
    DownloadCancelledError,
    DownloadConnectionRefusedError,
    DownloadFailedError,
    DownloadTimeoutError,
    NotConfigured,
    ResponseDataLossError,
    UnsupportedURLSchemeError,
)
from scrapy.http import Headers, Response
from scrapy.utils._download_handlers import (
    BaseHttpDownloadHandler,
    check_stop_download,
    get_dataloss_msg,
    get_maxsize_msg,
    get_warnsize_msg,
    make_response,
    normalize_bind_address,
)
from scrapy.utils.asyncio import is_asyncio_available
from scrapy.utils.ssl import _make_ssl_context

if TYPE_CHECKING:
    from scrapy.crawler import Crawler


try:
    import aiohttp
except ImportError:
    aiohttp = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class _BaseResponseArgs(TypedDict):
    status: int
    url: str
    headers: Headers
    protocol: str


class AiohttpDownloadHandler(BaseHttpDownloadHandler):
    _DEFAULT_CONNECT_TIMEOUT = 10

    _ITER_CHUNK_SIZE = 2048

    def __init__(self, crawler: Crawler):
        if not is_asyncio_available():  # pragma: no cover
            raise NotConfigured(
                f"{type(self).__name__} requires the asyncio support. Make"
                f" sure that you have either enabled the asyncio Twisted"
                f" reactor in the TWISTED_REACTOR setting or disabled the"
                f" TWISTED_ENABLED setting. See the asyncio documentation"
                f" of Scrapy for more information."
            )
        if aiohttp is None:  # pragma: no cover
            raise NotConfigured(
                f"{type(self).__name__} requires the aiohttp library to be installed."
            )
        super().__init__(crawler)
        logger.warning(
            "AiohttpDownloadHandler is experimental and is not recommended for production use."
        )
        bind_address = crawler.settings.get("DOWNLOAD_BIND_ADDRESS")
        bind_address = normalize_bind_address(bind_address)
        self._ssl_context = _make_ssl_context(crawler.settings)
        self._connector = aiohttp.TCPConnector(local_addr=bind_address)
        self._session: aiohttp.ClientSession | None = None

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                connector=self._connector,
                connector_owner=False,
                cookie_jar=aiohttp.DummyCookieJar(),
                auto_decompress=False,
            )
        return self._session

    async def download_request(self, request: Request) -> Response:
        self._warn_unsupported_meta(request.meta)

        timeout_value: float = request.meta.get(
            "download_timeout", self._DEFAULT_CONNECT_TIMEOUT
        )
        timeout = aiohttp.ClientTimeout(total=timeout_value)

        try:
            session = self._get_session()
            aiohttp_response = await session._request(
                request.method,
                request.url,
                data=request.body,
                headers=request.headers.to_tuple_list(),
                timeout=timeout,
                ssl=self._ssl_context,
                allow_redirects=False,
            )
            try:
                return await self._read_response(
                    aiohttp_response,
                    request,
                )
            finally:
                aiohttp_response.release()
                await aiohttp_response.wait_for_close()
        except TimeoutError as e:
            raise DownloadTimeoutError(
                f"Getting {request.url} took longer than {timeout_value} seconds."
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

    def _warn_unsupported_meta(self, meta: dict[str, Any]) -> None:
        if meta.get("bindaddress"):
            logger.error(
                f"The 'bindaddress' request meta key is not supported by"
                f" {type(self).__name__} and will be ignored."
            )
        if meta.get("proxy"):
            logger.error(
                f"The 'proxy' request meta key is not supported by"
                f" {type(self).__name__} and will be ignored."
            )

    async def _read_response(
        self,
        aiohttp_response: aiohttp.ClientResponse,
        request: Request,
    ) -> Response:
        maxsize: int = request.meta.get("download_maxsize", self._default_maxsize)
        warnsize: int = request.meta.get("download_warnsize", self._default_warnsize)

        content_length = aiohttp_response.headers.get("Content-Length")
        expected_size = int(content_length) if content_length is not None else None
        if maxsize and expected_size and expected_size > maxsize:
            self._cancel_maxsize(expected_size, maxsize, request, expected=True)

        reached_warnsize = False
        if warnsize and expected_size and expected_size > warnsize:
            reached_warnsize = True
            logger.warning(
                get_warnsize_msg(expected_size, warnsize, request, expected=True)
            )

        headers = Headers(list(aiohttp_response.headers.items()))

        version = aiohttp_response.version
        protocol_version = (
            f"HTTP/{version.major}.{version.minor}" if version else "HTTP/1.1"
        )

        make_response_base_args: _BaseResponseArgs = {
            "status": aiohttp_response.status,
            "url": request.url,
            "headers": headers,
            "protocol": protocol_version,
        }

        if stop_download := check_stop_download(
            signals.headers_received,
            self.crawler,
            request,
            headers=headers,
            body_length=expected_size,
        ):
            return make_response(
                **make_response_base_args,
                stop_download=stop_download,
            )

        response_body = BytesIO()
        bytes_received = 0
        try:
            async for chunk in aiohttp_response.content.iter_chunked(
                self._ITER_CHUNK_SIZE
            ):
                response_body.write(chunk)
                bytes_received += len(chunk)

                if stop_download := check_stop_download(
                    signals.bytes_received, self.crawler, request, data=chunk
                ):
                    return make_response(
                        **make_response_base_args,
                        body=response_body.getvalue(),
                        stop_download=stop_download,
                    )

                if maxsize and bytes_received > maxsize:
                    response_body.truncate(0)
                    self._cancel_maxsize(
                        bytes_received, maxsize, request, expected=False
                    )

                if warnsize and bytes_received > warnsize and not reached_warnsize:
                    reached_warnsize = True
                    logger.warning(
                        get_warnsize_msg(
                            bytes_received, warnsize, request, expected=False
                        )
                    )
        except aiohttp.ClientPayloadError as e:
            fail_on_dataloss: bool = request.meta.get(
                "download_fail_on_dataloss", self._fail_on_dataloss
            )
            if not fail_on_dataloss:
                return make_response(
                    **make_response_base_args,
                    body=response_body.getvalue(),
                    flags=["dataloss"],
                )
            self._log_dataloss_warning(request.url)
            raise ResponseDataLossError(str(e)) from e

        return make_response(
            **make_response_base_args,
            body=response_body.getvalue(),
        )

    def _log_dataloss_warning(self, url: str) -> None:
        if self._fail_on_dataloss_warned:
            return
        logger.warning(get_dataloss_msg(url))
        self._fail_on_dataloss_warned = True

    @staticmethod
    def _cancel_maxsize(
        size: int, limit: int, request: Request, *, expected: bool
    ) -> NoReturn:
        warning_msg = get_maxsize_msg(size, limit, request, expected=expected)
        logger.warning(warning_msg)
        raise DownloadCancelledError(warning_msg)

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        if not self._connector.closed:
            await self._connector.close()
