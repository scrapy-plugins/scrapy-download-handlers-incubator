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


class BaseStreamingDownloadHandler(_BaseStreamingDownloadHandler[_ResponseT]):
    pass
