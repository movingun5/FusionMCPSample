import unittest

from fusion_mcp_addin.server.auth import verify_authorization


class AuthorizationTests(unittest.TestCase):
    def test_requires_exact_bearer_scheme_and_token(self):
        self.assertTrue(verify_authorization("Bearer abc", "abc"))
        self.assertFalse(verify_authorization("bearer abc", "abc"))
        self.assertFalse(verify_authorization("Basic abc", "abc"))
        self.assertFalse(verify_authorization(None, "abc"))

    def test_no_configured_token_rejects_requests(self):
        self.assertFalse(verify_authorization("Bearer anything", ""))
        self.assertFalse(verify_authorization("Bearer anything", None))

    def test_extra_whitespace_is_not_accepted(self):
        self.assertFalse(verify_authorization("Bearer  abc", "abc"))
        self.assertFalse(verify_authorization("Bearer abc ", "abc"))


if __name__ == "__main__":
    unittest.main()
