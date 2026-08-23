from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

import scrapy_download_handlers_incubator
from scrapy_download_handlers_incubator import handlers

if TYPE_CHECKING:
    from types import ModuleType

HANDLER_NAMES = [
    "AiohttpDownloadHandler",
    "CurlCffiDownloadHandler",
    "HttpxDownloadHandler",
    "NiquestsDownloadHandler",
    "PyreqwestDownloadHandler",
]

MODULES = [scrapy_download_handlers_incubator, handlers]


@pytest.mark.parametrize("module", MODULES)
def test_all(module: ModuleType) -> None:
    assert module.__all__ == HANDLER_NAMES
    assert set(module.__all__) <= set(dir(module))
    for name in module.__all__:
        cls = getattr(module, name)
        assert isinstance(cls, type)
        assert cls.__name__ == name
        assert (
            cls.__module__ == f"{handlers.__name__}.{handlers._HANDLER_MODULES[name]}"
        )


@pytest.mark.parametrize("module", MODULES)
def test_unknown_attribute(module: ModuleType) -> None:
    with pytest.raises(
        AttributeError,
        match=f"^module '{module.__name__}' has no attribute 'DoesNotExist'$",
    ):
        module.DoesNotExist  # noqa: B018
    assert not hasattr(module, "DoesNotExist")
    assert "DoesNotExist" not in dir(module)


@pytest.mark.parametrize("name", HANDLER_NAMES)
def test_lazy(name: str) -> None:
    code = f"""
import sys
import scrapy_download_handlers_incubator as pkg
from scrapy_download_handlers_incubator import handlers

def loaded():
    all_modules = [f"{{handlers.__name__}}.{{m}}" for m in handlers._HANDLER_MODULES.values()]
    return sorted(m for m in all_modules if m in sys.modules)

assert loaded() == [], loaded()
cls = pkg.{name}
assert loaded() == [cls.__module__], loaded()
"""
    subprocess.run([sys.executable, "-c", code], check=True)
