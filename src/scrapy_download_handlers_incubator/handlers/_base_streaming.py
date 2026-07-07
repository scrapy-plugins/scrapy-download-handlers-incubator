# re-exporting Scrapy classes to be able to modify them here to support several Scrapy versions
from __future__ import annotations

from scrapy.core.downloader.handlers._base_streaming import (
    BaseStreamingDownloadHandler as _BaseStreamingDownloadHandler,
)
from scrapy.core.downloader.handlers._base_streaming import (
    _BaseResponseArgs,
    _ResponseT,
)

__all__ = ["BaseStreamingDownloadHandler", "_BaseResponseArgs"]

from typing import TYPE_CHECKING

from scrapy.utils.url import add_http_if_no_scheme

if TYPE_CHECKING:
    from scrapy import Request
    from scrapy.http import Headers


class BaseStreamingDownloadHandler(_BaseStreamingDownloadHandler[_ResponseT]):
    @staticmethod
    def _request_headers(request: Request) -> Headers:
        """Get a prepared copy of the request headers.

        This removes the Proxy-Authorization header.
        """
        headers = request.headers.copy()
        headers.pop(b"Proxy-Authorization", None)
        return headers

    @staticmethod
    def _extract_proxy(request: Request) -> tuple[str | None, str | None]:
        """Return a tuple of the proxy URL with a scheme and the value of the
        Proxy-Authorization header.

        This is useful for handlers that take the proxy headers separately.
        """
        proxy: str | None = request.meta.get("proxy")
        if not proxy:
            return None, None
        proxy = add_http_if_no_scheme(proxy)
        auth_header: bytes | None = request.headers.get(b"Proxy-Authorization")
        return proxy, auth_header.decode("ascii") if auth_header else None
