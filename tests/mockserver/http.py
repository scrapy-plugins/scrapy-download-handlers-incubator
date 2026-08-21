from __future__ import annotations

from typing import TYPE_CHECKING

from twisted.web.static import Data
from twisted.web.util import Redirect

from .http_base import BaseMockServer, main_factory
from .http_resources import (
    ArbitraryLengthPayloadResource,
    BaseResource,
    BrokenChunkedResource,
    BrokenDownloadResource,
    ChunkedResource,
    ClientIPResource,
    Compress,
    ContentLengthHeaderResource,
    Delay,
    Drop,
    DuplicateHeaderResource,
    Echo,
    EmptyContentTypeHeaderResource,
    ForeverTakingResource,
    HostHeaderResource,
    LargeChunkedFileResource,
    Partial,
    PayloadResource,
    ResponseHeadersResource,
    SetCookie,
    Status,
    UriResource,
    put_child,
)

if TYPE_CHECKING:
    from twisted.web.server import Request


class Root(BaseResource):
    def __init__(self) -> None:
        super().__init__()
        put_child(self, b"status", Status())
        put_child(self, b"delay", Delay())
        put_child(self, b"partial", Partial())
        put_child(self, b"drop", Drop())
        put_child(self, b"echo", Echo())
        put_child(self, b"payload", PayloadResource())
        put_child(self, b"alpayload", ArbitraryLengthPayloadResource())
        put_child(self, b"text", Data(b"Works", "text/plain"))
        put_child(self, b"redirect", Redirect(b"/redirected"))
        put_child(self, b"redirected", Data(b"Redirected here", "text/plain"))
        put_child(self, b"wait", ForeverTakingResource())
        put_child(self, b"hang-after-headers", ForeverTakingResource(write=True))
        put_child(self, b"host", HostHeaderResource())
        put_child(self, b"client-ip", ClientIPResource())
        put_child(self, b"broken", BrokenDownloadResource())
        put_child(self, b"chunked", ChunkedResource())
        put_child(self, b"broken-chunked", BrokenChunkedResource())
        put_child(self, b"contentlength", ContentLengthHeaderResource())
        put_child(self, b"nocontenttype", EmptyContentTypeHeaderResource())
        put_child(self, b"largechunkedfile", LargeChunkedFileResource())
        put_child(self, b"compress", Compress())
        put_child(self, b"duplicate-header", DuplicateHeaderResource())
        put_child(self, b"response-headers", ResponseHeadersResource())
        put_child(self, b"set-cookie", SetCookie())
        put_child(self, b"uri", UriResource())

    def getChild(self, path: bytes, request: Request) -> Root:
        return self

    def render(self, request: Request) -> bytes:
        return b"Scrapy mock HTTP server\n"


class MockServer(BaseMockServer):
    module_name = "tests.mockserver.http"


main = main_factory(Root)


if __name__ == "__main__":
    main()
