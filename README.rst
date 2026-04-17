Overview
========

This is a collection of semi-official download handlers for Scrapy_. See the
`Scrapy download handler`_ documentation for more information.

They should work and some of them may be later promoted to the official status,
but here they are provided as-is and no support or stability promises are
given. The documentation, including limitations and unsupported features, is
also provided as-is and may be incomplete.

As this code may intentionally use private Scrapy APIs, it specifies a tight
dependency on Scrapy. Currently only the unreleased 2.15.0 version is
supported.

.. _Scrapy: https://scrapy.org/
.. _Scrapy download handler: https://docs.scrapy.org/en/latest/topics/download-handlers.html

Handlers
========

AiohttpDownloadHandler
----------------------

This handler supports HTTP/1.1 and uses the aiohttp_ library.

Install it with:

.. code:: bash

    pip install scrapy-download-handlers-incubator[aiohttp]

Enable it with:

.. code-block:: python

    DOWNLOAD_HANDLERS = {
        "http": "scrapy_download_handlers_incubator.AiohttpDownloadHandler",
        "https": "scrapy_download_handlers_incubator.AiohttpDownloadHandler",
    }

.. _aiohttp: https://docs.aiohttp.org/en/stable/

CurlCffiDownloadHandler
-----------------------

This handler supports HTTP/1.1 and HTTP/2 (with
``CURL_CFFI_HTTP_VERSION="v2"``) and uses the curl_cffi_ library.

Install it with:

.. code:: bash

    pip install scrapy-download-handlers-incubator[curl-cffi]

Enable it with:

.. code-block:: python

    DOWNLOAD_HANDLERS = {
        "http": "scrapy_download_handlers_incubator.CurlCffiDownloadHandler",
        "https": "scrapy_download_handlers_incubator.CurlCffiDownloadHandler",
    }

.. _curl_cffi: https://curl-cffi.readthedocs.io/en/latest/

HttpxDownloadHandler
--------------------

This is an updated copy of the official
``scrapy.core.downloader.handlers._httpx.HttpxDownloadHandler`` handler. It
supports HTTP/1.1 and HTTP/2 (with ``HTTPX_HTTP2_ENABLED=True``) and uses the
httpx_ library.

Install it with:

.. code:: bash

    pip install scrapy-download-handlers-incubator[httpx]

Enable it with:

.. code-block:: python

    DOWNLOAD_HANDLERS = {
        "http": "scrapy_download_handlers_incubator.HttpxDownloadHandler",
        "https": "scrapy_download_handlers_incubator.HttpxDownloadHandler",
    }

.. _httpx: https://www.python-httpx.org/

NiquestsDownloadHandler
-----------------------

This handler supports HTTP/1.1 and HTTP/2 (with
``NIQUESTS_HTTP2_ENABLED=True``) and uses the niquests_ library.

Install it with:

.. code:: bash

    pip install scrapy-download-handlers-incubator[niquests]

Enable it with:

.. code-block:: python

    DOWNLOAD_HANDLERS = {
        "http": "scrapy_download_handlers_incubator.NiquestsDownloadHandler",
        "https": "scrapy_download_handlers_incubator.NiquestsDownloadHandler",
    }

.. _niquests: https://niquests.readthedocs.io/en/latest/

PyreqwestDownloadHandler
------------------------

This handler supports HTTP/1.1 and HTTP/2 (with
``PYREQWEST_HTTP2_ENABLED=True``) and uses the pyreqwest_ library.

Install it with:

.. code:: bash

    pip install scrapy-download-handlers-incubator[pyreqwest]

Enable it with:

.. code-block:: python

    DOWNLOAD_HANDLERS = {
        "http": "scrapy_download_handlers_incubator.PyreqwestDownloadHandler",
        "https": "scrapy_download_handlers_incubator.PyreqwestDownloadHandler",
    }

.. _pyreqwest: https://markussintonen.github.io/pyreqwest/pyreqwest.html
