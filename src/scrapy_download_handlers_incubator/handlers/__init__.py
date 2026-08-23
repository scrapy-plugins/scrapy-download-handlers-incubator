"""Download handlers.

The handler classes are imported lazily, on first access, so that importing
this package doesn't import the libraries of all handlers.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .aiohttp import AiohttpDownloadHandler
    from .curl_cffi import CurlCffiDownloadHandler
    from .httpx import HttpxDownloadHandler
    from .niquests import NiquestsDownloadHandler
    from .pyreqwest import PyreqwestDownloadHandler

__all__ = [
    "AiohttpDownloadHandler",
    "CurlCffiDownloadHandler",
    "HttpxDownloadHandler",
    "NiquestsDownloadHandler",
    "PyreqwestDownloadHandler",
]

_HANDLER_MODULES = {
    "AiohttpDownloadHandler": "aiohttp",
    "CurlCffiDownloadHandler": "curl_cffi",
    "HttpxDownloadHandler": "httpx",
    "NiquestsDownloadHandler": "niquests",
    "PyreqwestDownloadHandler": "pyreqwest",
}


def __getattr__(name: str) -> Any:
    try:
        module_name = _HANDLER_MODULES[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    return getattr(import_module(f".{module_name}", __name__), name)


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})
