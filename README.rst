Overview
========

This is a collection of semi-official download handlers for Scrapy_. See the
`Scrapy download handler`_ documentation for more information.

They should work and some of them may be later promoted to the official status,
but here they are provided as-is and no support or stability promises are
given. The documentation, including limitations and unsupported features, is
also provided as-is and may be incomplete.

As this code may intentionally use private Scrapy APIs, it specifies a tight
dependency on Scrapy. Currently only the 2.15.x versions are supported.

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

HttpxDownloadHandler
--------------------

This is a copy of the official
``scrapy.core.downloader.handlers._httpx.HttpxDownloadHandler`` handler. It
supports HTTP/1.1 and uses the httpx_ library.

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

PyreqwestDownloadHandler
------------------------

This handler supports HTTP/1.1 and uses the pyreqwest_ library.

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
