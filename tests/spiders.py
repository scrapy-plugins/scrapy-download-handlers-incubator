from __future__ import annotations

from typing import TYPE_CHECKING, Any

from scrapy import signals
from scrapy.exceptions import StopDownload
from scrapy.http import Headers, Request, Response
from scrapy.spiders import Spider

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from scrapy.crawler import Crawler
    from twisted.python.failure import Failure

    # typing.Self requires Python 3.11
    from typing_extensions import Self

    from tests.mockserver.http import MockServer


class MockServerSpider(Spider):
    def __init__(
        self,
        *args: Any,
        mockserver: MockServer | None = None,
        is_secure: bool = False,
        **kwargs: Any,
    ):
        super().__init__(*args, **kwargs)
        self.mockserver = mockserver
        self.is_secure = is_secure


class MetaSpider(MockServerSpider):
    name = "meta"

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.meta: dict[str, Any] = {}

    def closed(self, reason: str) -> None:
        self.meta["close_reason"] = reason


class SingleRequestSpider(MetaSpider):
    seed: Request | str | None = None
    callback_func: Callable[[Response], Any] | None = None
    errback_func: Callable[[Failure], Any] | None = None

    async def start(self) -> AsyncIterator[Any]:
        if isinstance(self.seed, Request):
            yield self.seed.replace(callback=self.parse, errback=self.on_error)
        else:
            assert self.seed
            yield Request(self.seed, callback=self.parse, errback=self.on_error)

    def parse(self, response: Response) -> Any:
        self.meta.setdefault("responses", []).append(response)
        if callable(self.callback_func):
            return self.callback_func(response)
        if "next" in response.meta:
            return response.meta["next"]
        return None

    def on_error(self, failure: Failure) -> Any:
        self.meta["failure"] = failure
        if callable(self.errback_func):
            return self.errback_func(failure)
        return None


class BytesReceivedCallbackSpider(MetaSpider):
    full_response_length = 2**18

    @classmethod
    def from_crawler(cls, crawler: Crawler, *args: Any, **kwargs: Any) -> Self:
        spider = super().from_crawler(crawler, *args, **kwargs)
        crawler.signals.connect(spider.bytes_received, signals.bytes_received)
        return spider

    async def start(self) -> AsyncIterator[Any]:
        body = b"a" * self.full_response_length
        assert self.mockserver
        url = self.mockserver.url("/alpayload", is_secure=self.is_secure)
        yield Request(url, method="POST", body=body, errback=self.errback)

    def parse(self, response: Response) -> None:
        self.meta["response"] = response

    def errback(self, failure: Failure) -> None:
        self.meta["failure"] = failure

    def bytes_received(self, data: bytes, request: Request, spider: Spider) -> None:
        self.meta["bytes_received"] = data
        raise StopDownload(fail=False)


class BytesReceivedErrbackSpider(BytesReceivedCallbackSpider):
    def bytes_received(self, data: bytes, request: Request, spider: Spider) -> None:
        self.meta["bytes_received"] = data
        raise StopDownload(fail=True)


class HeadersReceivedCallbackSpider(MetaSpider):
    @classmethod
    def from_crawler(cls, crawler: Crawler, *args: Any, **kwargs: Any) -> Self:
        spider = super().from_crawler(crawler, *args, **kwargs)
        crawler.signals.connect(spider.headers_received, signals.headers_received)
        return spider

    async def start(self) -> AsyncIterator[Any]:
        assert self.mockserver
        yield Request(
            self.mockserver.url("/status", is_secure=self.is_secure),
            errback=self.errback,
        )

    def parse(self, response: Response) -> None:
        self.meta["response"] = response

    def errback(self, failure: Failure) -> None:
        self.meta["failure"] = failure

    def headers_received(
        self, headers: Headers, body_length: int, request: Request, spider: Spider
    ) -> None:
        self.meta["headers_received"] = headers
        raise StopDownload(fail=False)


class HeadersReceivedErrbackSpider(HeadersReceivedCallbackSpider):
    def headers_received(
        self, headers: Headers, body_length: int, request: Request, spider: Spider
    ) -> None:
        self.meta["headers_received"] = headers
        raise StopDownload(fail=True)


class SimpleSpider(MetaSpider):
    name = "simple"

    def __init__(self, url: str, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.start_urls = [url]

    def parse(self, response: Response) -> Any:
        self.logger.info(f"Got response {response.status}")
