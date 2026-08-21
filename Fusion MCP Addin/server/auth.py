"""Bearer-token verification for the localhost MCP boundary."""

import hmac


def verify_authorization(header, expected_token):
    """Return True only for an exact, non-empty ``Bearer <token>`` value."""

    if not expected_token or not header or not header.startswith("Bearer "):
        return False
    supplied_token = header[len("Bearer ") :]
    if not supplied_token or supplied_token != supplied_token.strip():
        return False
    return hmac.compare_digest(supplied_token, expected_token)
