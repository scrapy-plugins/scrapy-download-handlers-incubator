# re-exporting Scrapy classes to be able to modify them here to support several Scrapy versions
from __future__ import annotations

import logging

from scrapy.core.downloader.handlers._base_streaming import (
    BaseStreamingDownloadHandler as _BaseStreamingDownloadHandler,
)
from scrapy.core.downloader.handlers._base_streaming import (
    _BaseResponseArgs,
    _ResponseT,
)

__all__ = ["BaseStreamingDownloadHandler", "_BaseResponseArgs"]


logger = logging.getLogger(__name__)


class BaseStreamingDownloadHandler(_BaseStreamingDownloadHandler[_ResponseT]):
    pass
