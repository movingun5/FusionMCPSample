import json
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.server import mcp_server


class HTTPAuthorizationTests(unittest.TestCase):
    def setUp(self):
        mcp_server.app = None
        self.mcp, self.server, self.thread = mcp_server.start_mcp_server(
            host="127.0.0.1",
            port=0,
            bearer_token="test-token",
        )
        self.assertIsNotNone(self.server)
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        mcp_server.stop_mcp_server(self.server, self.thread)

    def _post(self, authorization=None):
        payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}).encode()
        headers = {"Content-Type": "application/json"}
        if authorization is not None:
            headers["Authorization"] = authorization
        return urlopen(Request(self.base_url + "/", data=payload, headers=headers), timeout=3)

    def test_health_is_public_and_contains_no_design_data(self):
        with urlopen(self.base_url + "/health", timeout=3) as response:
            payload = json.load(response)

        self.assertEqual(200, response.status)
        self.assertEqual({"status": "healthy", "server": "MCP"}, payload)

    def test_unauthenticated_post_is_rejected_before_dispatch(self):
        with self.assertRaises(HTTPError) as caught:
            self._post()

        try:
            self.assertEqual(401, caught.exception.code)
            payload = json.loads(caught.exception.read().decode("utf-8"))
            self.assertEqual("AUTH_FAILED", payload["error"]["data"]["code"])
        finally:
            caught.exception.close()

    def test_authenticated_initialize_succeeds(self):
        with self._post("Bearer test-token") as response:
            payload = json.load(response)

        self.assertEqual(200, response.status)
        self.assertEqual("Fusion MCP Server", payload["result"]["serverInfo"]["name"])

    def test_tools_debug_endpoint_requires_authentication(self):
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.base_url + "/tools", timeout=3)
        try:
            self.assertEqual(401, caught.exception.code)
        finally:
            caught.exception.close()


if __name__ == "__main__":
    unittest.main()
