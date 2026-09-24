"""HTTP resource-server authentication; identity never comes from tool arguments.

HTTP 资源服务器认证；身份不能来自工具参数。
"""

import asyncio
import hashlib
import hmac
import secrets
import time
from typing import Any

import jwt
from mcp.server.auth.provider import AccessToken


class LocalTokenVerifier:
    """Authenticate a local owner or discovery-only client; this is not an OAuth server.

    认证本地 Owner 或仅发现客户端；这里不是 OAuth 服务器。
    """

    def __init__(self, token: str, owner: str, resource: str) -> None:
        if len(token) < 32 or not token.isascii():
            raise ValueError("Local HTTP token must contain at least 32 ASCII characters")
        self.token, self.owner, self.resource = token, owner, resource

    @property
    def discovery_token(self) -> str:
        """Derive a discovery-only credential; it cannot authorize any Runtime tool.

        派生仅用于工具发现的凭据，不能授权任何 Runtime 操作；与管理密钥隔离。
        """
        return hmac.new(
            self.token.encode(), b"agentcosplay:model-discovery:v1", hashlib.sha256
        ).hexdigest()

    async def verify_token(self, token: str) -> AccessToken | None:
        """Validate credentials and return bound access claims, or deny with None.

        验证凭据并返回绑定的访问声明；拒绝时返回 None。
        """

        if not token.isascii():
            return None
        discovery = hmac.compare_digest(token, self.discovery_token)
        if not discovery and not hmac.compare_digest(token, self.token):
            return None
        return AccessToken(
            token=token,
            client_id="local",
            subject=self.owner,
            scopes=["character:access", "character:discovery"]
            if discovery
            else ["character:access"],
            resource=self.resource,
        )


class TurnTokenVerifier:
    """Accept short-lived turn capabilities alongside existing owner authentication.

    在现有 Owner 认证之外接受短期单轮能力令牌；模型不能用该令牌切换身份或管理绑定。
    Keys are process-local: restart invalidates capabilities, never canonical state.
    签名密钥只存在于服务进程；重启使能力令牌失效，但不重置规范状态。
    """

    def __init__(self, base: "LocalTokenVerifier | JWTVerifier", resource: str) -> None:
        self.base, self.resource = base, resource
        self.secret = secrets.token_urlsafe(48)

    def issue(self, owner: str, turn_id: str, host: str, expires_at: int) -> str:
        """Issue only from an authenticated host bridge. / 仅由已认证宿主桥接入口签发。"""
        return jwt.encode(
            {
                "sub": owner,
                "turn": turn_id,
                "host": host,
                "aud": self.resource,
                "iss": "agentcosplay-turn",
                "iat": int(time.time()),
                "exp": expires_at,
            },
            self.secret,
            algorithm="HS256",
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        """A turn token is never treated as an owner token. / 单轮令牌绝不提升为 Owner 权限。"""
        try:
            claims = jwt.decode(
                token,
                self.secret,
                algorithms=["HS256"],
                audience=self.resource,
                issuer="agentcosplay-turn",
                options={"require": ["sub", "turn", "host", "iat", "exp"]},
            )
            if any(
                not isinstance(claims[k], str) or not claims[k] or len(claims[k]) > 200
                for k in ("sub", "turn", "host")
            ):
                return None
            return AccessToken(
                token=token,
                subject=claims["sub"],
                client_id="turn:" + claims["host"],
                scopes=["character:access", "character:turn:" + claims["turn"]],
                expires_at=int(claims["exp"]),
                resource=self.resource,
            )
        except (jwt.PyJWTError, ValueError, TypeError):
            return await self.base.verify_token(token)


class JWTVerifier:
    """Use an existing OAuth provider with HTTPS JWKS and audience-bound RS256 tokens.

    复用已有 OAuth 服务，以 HTTPS JWKS 验证限定受众的 RS256 令牌。
    """

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
        """Validate credentials and return bound access claims, or deny with None.

        验证凭据并返回绑定的访问声明；拒绝时返回 None。
        """

        return await asyncio.to_thread(self._verify, token)
