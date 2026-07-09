from __future__ import annotations

from twisted.web import resource
from twisted.web.static import Data
from twisted.web.util import Redirect

from .http_base import BaseMockServer, main_factory
from .http_resources import (
    ArbitraryLengthPayloadResource,
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
)


class Root(resource.Resource):
    def __init__(self):
        super().__init__()
        self.putChild(b"status", Status())
        self.putChild(b"delay", Delay())
        self.putChild(b"partial", Partial())
        self.putChild(b"drop", Drop())
        self.putChild(b"echo", Echo())
        self.putChild(b"payload", PayloadResource())
        self.putChild(b"alpayload", ArbitraryLengthPayloadResource())
        self.putChild(b"text", Data(b"Works", "text/plain"))
        self.putChild(b"redirect", Redirect(b"/redirected"))
        self.putChild(b"redirected", Data(b"Redirected here", "text/plain"))
        self.putChild(b"wait", ForeverTakingResource())
        self.putChild(b"hang-after-headers", ForeverTakingResource(write=True))
        self.putChild(b"host", HostHeaderResource())
        self.putChild(b"client-ip", ClientIPResource())
        self.putChild(b"broken", BrokenDownloadResource())
        self.putChild(b"chunked", ChunkedResource())
        self.putChild(b"broken-chunked", BrokenChunkedResource())
        self.putChild(b"contentlength", ContentLengthHeaderResource())
        self.putChild(b"nocontenttype", EmptyContentTypeHeaderResource())
        self.putChild(b"largechunkedfile", LargeChunkedFileResource())
        self.putChild(b"compress", Compress())
        self.putChild(b"duplicate-header", DuplicateHeaderResource())
        self.putChild(b"response-headers", ResponseHeadersResource())
        self.putChild(b"set-cookie", SetCookie())
        self.putChild(b"uri", UriResource())

    def getChild(self, path, request):
        return self

    def render(self, request):
        return b"Scrapy mock HTTP server\n"


class MockServer(BaseMockServer):
    module_name = "tests.mockserver.http"


main = main_factory(Root)


if __name__ == "__main__":
    main()
