from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .handlers import (
        AiohttpDownloadHandler,
        CurlCffiDownloadHandler,
        HttpxDownloadHandler,
        NiquestsDownloadHandler,
        PyreqwestDownloadHandler,
    )

__all__ = [
    "AiohttpDownloadHandler",
    "CurlCffiDownloadHandler",
    "HttpxDownloadHandler",
    "NiquestsDownloadHandler",
    "PyreqwestDownloadHandler",
]


def __getattr__(name: str) -> Any:
    # The handler classes are imported lazily, see handlers/__init__.py.
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(".handlers", __name__), name)


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})
