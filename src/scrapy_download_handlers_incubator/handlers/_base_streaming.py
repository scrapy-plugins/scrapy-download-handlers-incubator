# re-exporting Scrapy classes to be able to modify them here to support several Scrapy versions
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from scrapy.core.downloader.handlers._base_streaming import (
    BaseStreamingDownloadHandler as _BaseStreamingDownloadHandler,
)
from scrapy.core.downloader.handlers._base_streaming import (
    _BaseResponseArgs,
    _ResponseT,
)

if TYPE_CHECKING:
    from scrapy import Request

__all__ = ["BaseStreamingDownloadHandler", "_BaseResponseArgs"]


logger = logging.getLogger(__name__)


class BaseStreamingDownloadHandler(_BaseStreamingDownloadHandler[_ResponseT]):
    # added in Scrapy 2.20
    def _utf8_request_headers(self, request: Request) -> list[tuple[str, str]]:
        """Get a prepared copy of the request headers as ``(name, value)`` str
        pairs, for libraries that can only send UTF-8.

        Bytes that are not valid UTF-8 are replaced with U+FFFD, with a
        warning.
        """
        pairs: list[tuple[str, str]] = []
        for name, values in self._request_headers(request).items():
            for value in values:
                try:
                    pairs.append((name.decode(), value.decode()))
                except UnicodeDecodeError:
                    str_name = name.decode(errors="replace")
                    logger.warning(
                        f"The {str_name} header of {request} is not valid UTF-8,"
                        f" which {type(self).__name__} cannot send. Sending it"
                        f" with U+FFFD in place of the invalid bytes."
                    )
                    pairs.append((str_name, value.decode(errors="replace")))
        return pairs
