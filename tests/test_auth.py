import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from character_runtime.auth import JWTVerifier, LocalTokenVerifier


class AuthTests(unittest.IsolatedAsyncioTestCase):
    async def test_jwt_requires_signature_issuer_audience_expiry_subject_and_scope(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        verifier = JWTVerifier(
            "https://id.example/",
            "character",
            "https://id.example/jwks",
            "https://runtime.example/mcp",
        )
        claims = {
            "iss": "https://id.example/",
            "aud": "character",
            "sub": "synthetic",
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
            "scope": "character:access",
        }
        with patch.object(
            verifier.keys,
            "get_signing_key_from_jwt",
            return_value=SimpleNamespace(key=key.public_key()),
        ):
            good = await verifier.verify_token(jwt.encode(claims, key, algorithm="RS256"))
            self.assertIsNotNone(good)
            self.assertEqual(len(good.subject), 64)
            for bad in (
                {"iss": "https://evil.example/"},
                {"aud": "other"},
                {"exp": int(time.time()) - 100},
                {"scope": ""},
                {"sub": ""},
            ):
                with self.subTest(bad=bad):
                    result = await verifier.verify_token(
                        jwt.encode(claims | bad, key, algorithm="RS256")
                    )
                    self.assertIsNone(result)
            self.assertIsNone(
                await verifier.verify_token(jwt.encode(claims, "w" * 32, algorithm="HS256"))
            )
            other = await verifier.verify_token(
                jwt.encode(claims | {"sub": "other"}, key, algorithm="RS256")
            )
            self.assertNotEqual(good.subject, other.subject)

    async def test_non_ascii_bearer_is_rejected_without_exception(self):
        verifier = LocalTokenVerifier("a" * 40, "u", "http://127.0.0.1/mcp")
        self.assertIsNone(await verifier.verify_token("无效令牌"))
        with self.assertRaises(ValueError):
            LocalTokenVerifier("密" * 40, "u", "http://127.0.0.1/mcp")

    async def test_local_token_and_https_validation(self):
        with self.assertRaises(ValueError):
            LocalTokenVerifier("short", "u", "http://127.0.0.1/mcp")
        with self.assertRaises(ValueError):
            JWTVerifier(
                "http://id.example", "x", "https://id.example/jwks", "https://x.example/mcp"
            )
