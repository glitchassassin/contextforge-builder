"""Exercise scope challenges and signed-token validation in the built image.

Persistence and provider discovery are mocked; RSA verification remains real.
No real accounts, access tokens, or network connections are used.
"""

from contextlib import asynccontextmanager
import json
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from cryptography.hazmat.primitives.asymmetric import rsa
import httpx
import jwt
from sqlalchemy.exc import OperationalError

from mcpgateway.transports import streamablehttp_transport as tr
from mcpgateway.utils import verify_credentials as vc

ISSUER = "https://issuer.example.com/"
SERVER_ID = "0123456789abcdef0123456789abcdef"
RESOURCE = f"https://gateway.example.com/servers/{SERVER_ID}/mcp"
SCOPES = ["openid", "email"]


def make_scope(method="POST"):
    """Return a minimal ASGI scope for the test resource."""
    return {
        "type": "http",
        "method": method,
        "path": f"/servers/{SERVER_ID}/mcp",
        "scheme": "https",
        "server": ("gateway.example.com", 443),
        "headers": [],
        "client": ("127.0.0.1", 0),
    }


class ScopeChallengeTests(unittest.IsolatedAsyncioTestCase):
    """Verify challenge guidance without relaxing any authentication gates."""

    async def asyncSetUp(self):
        """Install disposable provider keys and persistence fixtures."""
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        jwk.update(kid="test-key", use="sig", alg="RS256")
        self.server = SimpleNamespace(
            oauth_enabled=True,
            oauth_config={
                "authorization_servers": [ISSUER],
                "resource": RESOURCE,
                "scopes_supported": list(SCOPES),
            },
        )
        self.db = MagicMock()
        self.db.execute.return_value.scalar_one_or_none.side_effect = (
            lambda: self.server
        )

        @asynccontextmanager
        async def get_db():
            yield self.db

        self.user = SimpleNamespace(is_active=True, is_admin=False)
        self.lookup = MagicMock(side_effect=lambda email: self.user)
        patches = [
            patch.object(tr, "get_db", get_db),
            patch.object(tr, "_persist_learned_server_audience"),
            patch.object(
                vc,
                "_discover_oidc_metadata",
                AsyncMock(return_value={"jwks_uri": f"{ISSUER}.well-known/jwks.json"}),
            ),
            patch.object(
                vc._NoRedirectPyJWKClient, "fetch_data", return_value={"keys": [jwk]}
            ),
            patch("mcpgateway.auth._get_user_by_email_sync", self.lookup),
            patch(
                "mcpgateway.auth._resolve_teams_from_db",
                AsyncMock(return_value=["local-team"]),
            ),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        vc._oauth_jwks_client_cache.clear()
        self.checked_token = tr._oauth_checked_var.set(False)
        self.user_token = tr.user_context_var.set({})
        self.addCleanup(tr._oauth_checked_var.reset, self.checked_token)
        self.addCleanup(tr.user_context_var.reset, self.user_token)

    def mint(self, **overrides):
        """Sign a short-lived access token with a fresh local RSA key."""
        claims = {
            "iss": ISSUER,
            "aud": RESOURCE,
            "sub": "auth0|test-user",
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
            "email": "user@example.com",
            "email_verified": True,
        }
        claims.update(overrides)
        return jwt.encode(
            claims, self.key, algorithm="RS256", headers={"kid": "test-key"}
        )

    async def authenticate(self, token):
        """Call the release's OAuth handler and collect its ASGI response."""
        send = AsyncMock()
        handler = tr._StreamableHttpAuthHandler(
            scope=make_scope(), receive=AsyncMock(), send=send
        )
        result = await handler._try_oauth_access_token(token)
        messages = [call.args[0] for call in send.call_args_list]
        return result, messages

    def assert_challenge(self, messages):
        """Check the protocol response contains the configured scope guidance."""
        self.assertEqual(messages[0]["status"], 401)
        value = dict(messages[0]["headers"])[b"www-authenticate"].decode()
        self.assertIn(
            f'resource_metadata="https://gateway.example.com/.well-known/oauth-protected-resource/servers/{SERVER_ID}/mcp"',
            value,
        )
        self.assertIn('scope="openid email"', value)

    async def test_initial_challenge_in_both_auth_modes_and_methods(self):
        """GET and POST must advertise scopes even when global auth is strict."""
        for strict in (False, True):
            for method in ("GET", "POST"):
                with (
                    self.subTest(strict=strict, method=method),
                    patch.object(tr.settings, "mcp_require_auth", strict),
                ):
                    tr._oauth_checked_var.set(False)
                    send = AsyncMock()
                    allowed = await tr.streamable_http_auth(
                        make_scope(method), None, send
                    )
                    self.assertFalse(allowed)
                    self.assert_challenge(
                        [call.args[0] for call in send.call_args_list]
                    )

    async def test_missing_email_can_reauthorize_with_guided_scopes(self):
        """Missing email is denied; a signed token containing email authenticates."""
        result, messages = await self.authenticate(self.mint(email=None))
        self.assertIs(result, tr.OAuthAuthResult.FAILED)
        self.assert_challenge(messages)
        self.lookup.assert_not_called()
        self.assertFalse(tr.user_context_var.get().get("is_authenticated", False))
        result, messages = await self.authenticate(self.mint())
        self.assertIs(result, tr.OAuthAuthResult.SUCCESS)
        self.assertEqual(messages, [])
        context = tr.user_context_var.get()
        self.assertEqual(context["email"], "user@example.com")
        self.assertEqual(context["teams"], ["local-team"])
        self.assertFalse(context["is_admin"])

    async def test_signed_claims_cannot_override_local_roles(self):
        """Teams and admin privileges remain authoritative in the local database."""
        result, _ = await self.authenticate(
            self.mint(is_admin=True, teams=["attacker-team"])
        )
        self.assertIs(result, tr.OAuthAuthResult.SUCCESS)
        self.assertEqual(tr.user_context_var.get()["teams"], ["local-team"])
        self.assertFalse(tr.user_context_var.get()["is_admin"])

    async def test_invalid_tokens_remain_denied(self):
        """Wrong audiences, expired tokens, and invalid signatures cannot authenticate."""
        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        forged = jwt.encode(
            jwt.decode(self.mint(), options={"verify_signature": False}),
            other_key,
            algorithm="RS256",
            headers={"kid": "test-key"},
        )
        for token in (
            self.mint(aud="https://another-resource.example.com"),
            self.mint(exp=int(time.time()) - 30),
            self.mint(nonce="id-token"),
            forged,
        ):
            with self.subTest(
                token_type=jwt.decode(token, options={"verify_signature": False}).get(
                    "aud"
                )
            ):
                result, messages = await self.authenticate(token)
                self.assertIs(result, tr.OAuthAuthResult.FAILED)
                self.assert_challenge(messages)
        self.lookup.assert_not_called()

    async def test_untrusted_issuer_not_accepted(self):
        """The OAuth handler cannot authenticate a token from another issuer."""
        result, _ = await self.authenticate(
            self.mint(iss="https://untrusted.example.com/")
        )
        self.assertIs(result, tr.OAuthAuthResult.NOT_APPLICABLE)
        self.lookup.assert_not_called()

    async def test_unregistered_and_disabled_users_denied(self):
        """A valid provider signature never creates or reactivates a local account."""
        for user in (None, SimpleNamespace(is_active=False, is_admin=True)):
            with self.subTest(user=user):
                self.user = user
                result, messages = await self.authenticate(self.mint())
                self.assertIs(result, tr.OAuthAuthResult.FAILED)
                self.assertEqual(messages[0]["status"], 401)

    async def test_database_failure_stays_closed(self):
        """Failure to load server authentication policy returns 503."""
        self.db.execute.side_effect = OperationalError(
            "SELECT", {}, Exception("offline")
        )
        send = AsyncMock()
        allowed = await tr.streamable_http_auth(make_scope(), None, send)
        self.assertFalse(allowed)
        self.assertEqual(send.call_args_list[0].args[0]["status"], 503)

    async def test_non_oauth_servers_preserve_existing_behavior(self):
        """The patch does not force OAuth onto other virtual servers."""
        self.server.oauth_enabled = False
        for strict in (False, True):
            with patch.object(tr.settings, "mcp_require_auth", strict):
                tr._oauth_checked_var.set(False)
                send = AsyncMock()
                allowed = await tr.streamable_http_auth(make_scope(), None, send)
                self.assertEqual(allowed, not strict)
                if strict:
                    self.assertEqual(
                        dict(send.call_args_list[0].args[0]["headers"])[
                            b"www-authenticate"
                        ],
                        b"Bearer",
                    )

    def test_scope_header_safety_and_optional_configuration(self):
        """Invalid scope tokens cannot inject response headers or new parameters."""
        base = tr._build_oauth_challenge(make_scope(), SERVER_ID)
        for scopes in (
            None,
            [],
            "openid email",
            ["email\r\nInjected: yes"],
            ['email", evil="yes'],
            ["email\\evil"],
            ["email scope"],
            ["é"],
            [12],
            [""],
            ["offline_access"],
        ):
            with self.subTest(scopes=scopes):
                self.assertEqual(
                    tr._build_oauth_challenge(make_scope(), SERVER_ID, scopes), base
                )
        self.assertEqual(
            tr._build_oauth_challenge(
                make_scope(), SERVER_ID, ["openid", "email", "email", "offline_access"]
            ),
            base + ', scope="openid email"',
        )

    async def test_legacy_scopes_configuration(self):
        """The challenge uses the same legacy fallback as resource metadata."""
        self.server.oauth_config["scopes"] = self.server.oauth_config.pop(
            "scopes_supported"
        )
        send = AsyncMock()
        self.assertFalse(await tr.streamable_http_auth(make_scope(), None, send))
        self.assert_challenge([call.args[0] for call in send.call_args_list])


def test_live_challenge():
    """Check challenge behavior over HTTP against the disposable smoke container."""
    from mcpgateway.db import Server, SessionLocal

    with SessionLocal() as db:
        db.add(
            Server(
                id=SERVER_ID,
                name="OAuth scope regression",
                visibility="public",
                oauth_enabled=True,
                oauth_config={
                    "authorization_servers": [ISSUER],
                    "scopes_supported": SCOPES,
                },
            )
        )
        db.commit()
    try:
        for method in ("GET", "POST"):
            response = httpx.request(
                method, f"http://127.0.0.1:4444/servers/{SERVER_ID}/mcp", timeout=10
            )
            assert response.status_code == 401, response.text
            assert 'scope="openid email"' in response.headers.get(
                "www-authenticate", ""
            ), response.headers
            assert "resource_metadata=" in response.headers["www-authenticate"]
        print("Live HTTP OAuth scope challenges passed (GET and POST)")
    finally:
        with SessionLocal() as db:
            db.query(Server).filter(Server.id == SERVER_ID).delete()
            db.commit()


if __name__ == "__main__":
    if sys.argv[1:] == ["--live"]:
        test_live_challenge()
    else:
        unittest.main(verbosity=2)
