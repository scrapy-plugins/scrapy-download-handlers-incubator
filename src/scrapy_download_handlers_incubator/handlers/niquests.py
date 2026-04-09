"""``niquests``-based HTTP(S) download handler. Currently not recommended for production use."""

from __future__ import annotations

import ipaddress
import logging
from io import BytesIO
from typing import TYPE_CHECKING, Any, NoReturn, TypedDict
from urllib.parse import urlparse

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

from scrapy_download_handlers_incubator.utils import NullCookieJar

if TYPE_CHECKING:
    from ipaddress import IPv4Address, IPv6Address

    from scrapy.crawler import Crawler


try:
    import niquests
    import niquests.exceptions
    import urllib3
    import urllib3.exceptions
except ImportError:
    niquests = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class _BaseResponseArgs(TypedDict):
    status: int
    url: str
    headers: Headers
    ip_address: IPv4Address | IPv6Address | None
    protocol: str | None


class NiquestsDownloadHandler(BaseHttpDownloadHandler):
    _DEFAULT_CONNECT_TIMEOUT = 10

    def __init__(self, crawler: Crawler):
        if not is_asyncio_available():  # pragma: no cover
            raise NotConfigured(
                f"{type(self).__name__} requires the asyncio support. Make"
                f" sure that you have either enabled the asyncio Twisted"
                f" reactor in the TWISTED_REACTOR setting or disabled the"
                f" TWISTED_REACTOR_ENABLED setting. See the asyncio"
                f" documentation of Scrapy for more information."
            )
        if niquests is None:  # pragma: no cover
            raise NotConfigured(
                f"{type(self).__name__} requires the niquests library to be installed."
            )
        super().__init__(crawler)
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        logger.warning(
            "NiquestsDownloadHandler is experimental and is not recommented for production use."
        )
        bind_address = crawler.settings.get("DOWNLOAD_BIND_ADDRESS")
        bind_address = normalize_bind_address(bind_address)

        self._bind_address: str | None = None

        if bind_address is not None:
            host, port = bind_address
            if port != 0:
                logger.warning(
                    "DOWNLOAD_BIND_ADDRESS specifies a port (%s), but %s does not "
                    "support binding to a specific local port. Ignoring the port "
                    "and binding only to %r.",
                    port,
                    type(self).__name__,
                    host,
                )
            self._bind_address = host

        self._verify_certificates: bool = crawler.settings.getbool(
            "DOWNLOAD_VERIFY_CERTIFICATES"
        )

        self._session = niquests.AsyncSession(
            source_address=bind_address,
            disable_http2=True,
            disable_http3=True,
        )
        self._session.cookies = NullCookieJar()

    async def download_request(self, request: Request) -> Response:
        self._warn_unsupported_meta(request.meta)

        timeout: float = request.meta.get(
            "download_timeout", self._DEFAULT_CONNECT_TIMEOUT
        )

        nq_response: niquests.AsyncResponse | None = None
        try:
            nq_response = await self._get_nq_response(request, timeout)
            return await self._read_response(nq_response, request)
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
        finally:
            if nq_response:
                await nq_response.close()

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

    async def _get_nq_response(
        self, request: Request, timeout: float
    ) -> niquests.AsyncResponse:
        headers = request.headers.to_unicode_dict()
        for k in list(headers):
            if headers[k] == "":
                del headers[k]
        return await self._session.request(
            method=request.method,
            url=request.url,
            data=request.body,
            headers=headers,
            timeout=timeout,
            allow_redirects=False,
            stream=True,
            verify=self._verify_certificates,
        )

    async def _read_response(
        self, nq_response: niquests.AsyncResponse, request: Request
    ) -> Response:
        maxsize: int = request.meta.get("download_maxsize", self._default_maxsize)
        warnsize: int = request.meta.get("download_warnsize", self._default_warnsize)

        content_length = nq_response.headers.get("Content-Length")
        expected_size = int(content_length) if content_length is not None else None
        if maxsize and expected_size and expected_size > maxsize:
            self._cancel_maxsize(expected_size, maxsize, request, expected=True)

        reached_warnsize = False
        if warnsize and expected_size and expected_size > warnsize:
            reached_warnsize = True
            logger.warning(
                get_warnsize_msg(expected_size, warnsize, request, expected=True)
            )

        headers = Headers(nq_response.headers.items())  # type: ignore[no-untyped-call]

        assert nq_response.conn_info is not None
        make_response_base_args: _BaseResponseArgs = {
            "status": nq_response.status_code or 0,
            "url": request.url,
            "headers": headers,
            "ip_address": self._get_server_ip(nq_response.conn_info),
            "protocol": nq_response.conn_info.http_version.value
            if nq_response.conn_info.http_version
            else None,
        }

        self._log_tls_info(nq_response.conn_info, request.url)

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
            async for chunk in await nq_response.iter_raw():
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
        except niquests.exceptions.ChunkedEncodingError as e:
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

    @staticmethod
    def _get_server_ip(
        conn_info: urllib3.ConnectionInfo,
    ) -> IPv4Address | IPv6Address | None:
        if conn_info.destination_address:
            return ipaddress.ip_address(conn_info.destination_address[0])
        return None

    def _log_tls_info(self, conn_info: urllib3.ConnectionInfo, url: str) -> None:
        if not self._tls_verbose_logging:
            return
        if conn_info.tls_version:
            logger.debug(
                f"SSL connection to {urlparse(url).hostname}"
                f" using protocol {conn_info.tls_version.name},"
                f" cipher {conn_info.cipher}"
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
        await self._session.close()
