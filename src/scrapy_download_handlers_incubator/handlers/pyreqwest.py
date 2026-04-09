"""``pyreqwest``-based HTTP(S) download handler. Currently not recommended for production use."""

from __future__ import annotations

import logging
from datetime import timedelta
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

if TYPE_CHECKING:
    from scrapy.crawler import Crawler


try:
    import pyreqwest.client
    import pyreqwest.exceptions
    import pyreqwest.request
    import pyreqwest.response
except ImportError:
    pyreqwest = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class _BaseResponseArgs(TypedDict):
    status: int
    url: str
    headers: Headers
    protocol: str


class PyreqwestDownloadHandler(BaseHttpDownloadHandler):
    _DEFAULT_CONNECT_TIMEOUT = 10
    _ITER_CHUNK_SIZE = 2048

    def __init__(self, crawler: Crawler):
        if not is_asyncio_available():  # pragma: no cover
            raise NotConfigured(
                f"{type(self).__name__} requires the asyncio support. Make"
                f" sure that you have either enabled the asyncio Twisted"
                f" reactor in the TWISTED_REACTOR setting or disabled the"
                f" TWISTED_REACTOR_ENABLED setting. See the asyncio"
                f" documentation of Scrapy for more information."
            )
        if pyreqwest is None:  # pragma: no cover
            raise NotConfigured(
                f"{type(self).__name__} requires the pyreqwest library to be installed."
            )
        super().__init__(crawler)
        logger.warning(
            "PyreqwestDownloadHandler is experimental and is not recommented for production use."
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

        builder: pyreqwest.client.ClientBuilder = (
            pyreqwest.client.ClientBuilder()
            .follow_redirects(False)
            .default_cookie_store(False)
            .gzip(False)
            .deflate(False)
            .brotli(False)
            .zstd(False)
        )

        if not crawler.settings.getbool("DOWNLOAD_VERIFY_CERTIFICATES"):
            builder = builder.danger_accept_invalid_certs(True)

        if bind_address is not None:
            builder = builder.local_address(self._bind_address)

        self._client: pyreqwest.client.Client = builder.build()

    async def download_request(self, request: Request) -> Response:
        self._warn_unsupported_meta(request.meta)

        timeout: float = request.meta.get(
            "download_timeout", self._DEFAULT_CONNECT_TIMEOUT
        )

        try:
            async with self._get_pyreqwest_response(
                request, timeout
            ) as pyreqwest_response:
                return await self._read_response(pyreqwest_response, request)
        except (
            pyreqwest.exceptions.ConnectTimeoutError,
            pyreqwest.exceptions.ReadTimeoutError,
        ) as e:
            raise DownloadTimeoutError(
                f"Getting {request.url} took longer than {timeout} seconds."
            ) from e
        except pyreqwest.exceptions.BuilderError as e:
            if _find_in_causes(e, "URL scheme is not allowed"):
                raise UnsupportedURLSchemeError(str(e)) from e
            raise
        except pyreqwest.exceptions.ConnectError as e:
            if _find_in_causes(e, "dns error"):
                raise CannotResolveHostError(str(e)) from e
            if _find_in_causes(e, "tcp connect error"):
                raise DownloadConnectionRefusedError(str(e)) from e
            raise DownloadFailedError(str(e)) from e

    def _warn_unsupported_meta(self, meta: dict[str, Any]) -> None:
        if meta.get("bindaddress"):
            # configurable only per-client:
            # https://github.com/encode/httpx/issues/755#issuecomment-2746121794
            logger.error(
                f"The 'bindaddress' request meta key is not supported by"
                f" {type(self).__name__} and will be ignored."
            )
        if meta.get("proxy"):
            # configurable only per-client:
            # https://github.com/encode/httpx/issues/486
            logger.error(
                f"The 'proxy' request meta key is not supported by"
                f" {type(self).__name__} and will be ignored."
            )

    def _get_pyreqwest_response(
        self, request: Request, timeout: float
    ) -> pyreqwest.request.StreamRequest:
        rb: pyreqwest.request.RequestBuilder = (
            self._client.request(request.method, request.url)
            .timeout(timedelta(seconds=timeout))
            .streamed_read_buffer_limit(0)
        )
        headers = request.headers.to_tuple_list()
        if request.body:
            rb = rb.body_bytes(request.body)
        elif request.method == "POST" and "Content-Length" not in request.headers:
            headers.append(("Content-Length", "0"))
        rb = rb.headers(headers)
        return rb.build_streamed()

    async def _read_response(
        self, pyreqwest_response: pyreqwest.response.Response, request: Request
    ) -> Response:
        maxsize: int = request.meta.get("download_maxsize", self._default_maxsize)
        warnsize: int = request.meta.get("download_warnsize", self._default_warnsize)

        content_length = pyreqwest_response.headers.get("Content-Length")
        expected_size = int(content_length) if content_length is not None else None
        if maxsize and expected_size and expected_size > maxsize:
            self._cancel_maxsize(expected_size, maxsize, request, expected=True)

        reached_warnsize = False
        if warnsize and expected_size and expected_size > warnsize:
            reached_warnsize = True
            logger.warning(
                get_warnsize_msg(expected_size, warnsize, request, expected=True)
            )

        headers = Headers(list(pyreqwest_response.headers.items()))

        make_response_base_args: _BaseResponseArgs = {
            "status": pyreqwest_response.status,
            "url": request.url,
            "headers": headers,
            "protocol": pyreqwest_response.version,
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
            while (
                chunk := await pyreqwest_response.body_reader.read(
                    self._ITER_CHUNK_SIZE
                )
            ) is not None:
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
        except pyreqwest.exceptions.RequestError as e:
            if not _find_in_causes(e, "error reading a body from connection"):
                raise
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
        await self._client.close()


def _find_in_causes(
    ex: pyreqwest.exceptions.DetailedPyreqwestError, substring: str
) -> bool:
    return any(substring in cause["message"] for cause in ex.details["causes"] or [])
