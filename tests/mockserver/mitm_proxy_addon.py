def response(flow):
    # add a custom header to be able to check that the request went through the proxy
    flow.response.headers["X-Via-Mitmproxy"] = "1"
