"""HTTP resource-server authentication; identity never comes from tool arguments."""

import asyncio
import hashlib
import hmac
from typing import Any

import jwt
from mcp.server.auth.provider import AccessToken


class LocalTokenVerifier:
    """Single-user loopback testing only; not an OAuth authorization server."""

    def __init__(self, token: str, owner: str, resource: str) -> None:
        if len(token) < 32 or not token.isascii():
            raise ValueError("Local HTTP token must contain at least 32 ASCII characters")
        self.token, self.owner, self.resource = token, owner, resource

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token.isascii() or not hmac.compare_digest(token, self.token):
            return None
        return AccessToken(
            token=token,
            client_id="local",
            subject=self.owner,
            scopes=["character:access"],
            resource=self.resource,
        )


class JWTVerifier:
    """Use an existing OAuth provider with HTTPS JWKS and audience-bound RS256 tokens."""

    def __init__(self, issuer: str, audience: str, jwks_url: str, resource: str) -> None:
        if not all(u.startswith("https://") for u in (issuer, jwks_url, resource)):
            raise ValueError("Remote issuer, JWKS and resource URLs require HTTPS")
        self.issuer, self.audience, self.resource = issuer, audience, resource
        self.keys = jwt.PyJWKClient(jwks_url, timeout=10)

    def _verify(self, token: str) -> AccessToken | None:
        try:
            key = self.keys.get_signing_key_from_jwt(token)
            claims: dict[str, Any] = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "sub", "iss", "aud"]},
            )
            sub = claims["sub"]
            if not isinstance(sub, str) or not sub or len(sub) > 1000:
                return None
            scope = claims.get("scope", "")
            if not isinstance(scope, str):
                return None
            scopes = scope.split()
            if "character:access" not in scopes:
                return None
            principal = hashlib.sha256((self.issuer + "\0" + sub).encode()).hexdigest()
            return AccessToken(
                token=token,
                client_id=str(claims.get("azp", "oauth")),
                subject=principal,
                scopes=scopes,
                expires_at=int(claims["exp"]),
                resource=self.resource,
            )
        except (jwt.PyJWTError, ValueError, TypeError, OSError):
            return None

    async def verify_token(self, token: str) -> AccessToken | None:
        return await asyncio.to_thread(self._verify, token)
