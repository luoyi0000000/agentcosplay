"""Persistent native-to-canonical conversations over the authoritative Runtime store.

在唯一 Runtime 存储中持久化原生到规范会话的映射；映射本身不授予单轮权限。
"""

from typing import Any, Literal, Self

from pydantic import model_validator

from .models import Identifier, Model, new_id
from .operations import fingerprint
from .storage import Storage


class HostSessionIdentity(Model):
    """A group conversation owns a character, while each turn resolves its own actor.

    群会话拥有角色，每轮独立解析 Actor；私聊受众由已验证 Endpoint 固定。
    """

    host: Identifier
    platform: Identifier
    endpoint_id: Identifier
    native_session_id: Identifier
    audience: Literal["dm", "group"]
    participant_id: Identifier | None = None

    @model_validator(mode="after")
    def audience_consistent(self) -> Self:
        """Never infer a private audience from a group actor. / 不从群 Actor 推断私人受众。"""
        if (self.audience == "dm") != bool(self.participant_id):
            raise ValueError("Session audience requires the endpoint's participant semantics")
        return self

    def key(self) -> str:
        """Keep initial legacy session IDs; the canonical endpoint namespaces platform/audience.

        保持旧初始 Session ID；规范 Endpoint 隔离平台与受众，读取时再次核对完整身份。
        """
        return fingerprint([self.host, self.endpoint_id, self.native_session_id])


class SessionRegistry:
    """Register/recover conversations after trusted identity and endpoint authorization.

    在可信身份和 Endpoint 授权后注册/恢复会话；不拥有角色、记忆或 Scope 策略。
    """

    def __init__(self, storage: Storage, owner: str) -> None:
        self.storage, self.owner = storage, owner

    def lookup(self, identity: HostSessionIdentity) -> dict[str, Any] | None:
        """Validate mapping provenance and active target; missing is distinct from revoked.

        核对映射来源与活动目标；不存在不等于已撤销，撤销后禁止隐式复活。
        """
        with self.storage.transaction():
            mapping = self.storage.get(self.owner, "host_session", identity.key())
            if mapping is None:
                return None
            if (
                mapping.get("owner_id") != self.owner
                or mapping.get("identity") != identity.model_dump()
            ):
                raise ValueError("Session mapping identity changed")
            session = self.storage.get(self.owner, "conversation_session", mapping["session_id"])
            if (
                not session
                or not session.get("active", True)
                or session.get("owner_id") != self.owner
                or session.get("platform_binding") != identity.endpoint_id
                or session.get("mapping_id") != identity.key()
                or session.get("host_identity") != identity.model_dump()
            ):
                raise ValueError(
                    "Session mapping is inactive or invalid; trusted rotation required"
                )
            return session

    def resolve(self, identity: HostSessionIdentity, default_character: str) -> dict[str, Any]:
        """Reuse a valid mapping, or transactionally register a new/legacy conversation.

        复用有效映射，或在事务中注册新会话/旧会话；保留原路由、模式和未知字段。
        """
        with self.storage.transaction():
            existing = self.lookup(identity)
            if existing is not None:
                return existing
            key = identity.key()
            session = self.storage.get(self.owner, "conversation_session", key)
            if session is None:
                session = dict(
                    id=key,
                    owner_id=self.owner,
                    platform_binding=identity.endpoint_id,
                    character_id=default_character,
                    revision=1,
                    active=True,
                )
            if (
                session.get("id") != key
                or session.get("owner_id") != self.owner
                or session.get("platform_binding") != identity.endpoint_id
                or not session.get("active", True)
                or session.get("host_identity", identity.model_dump()) != identity.model_dump()
            ):
                raise ValueError("Legacy session cannot be safely registered")
            session.update(mapping_id=key, host_identity=identity.model_dump())
            self.storage.put(self.owner, "conversation_session", key, session)
            self.storage.put(
                self.owner,
                "host_session",
                key,
                dict(
                    owner_id=self.owner,
                    identity=identity.model_dump(),
                    session_id=key,
                ),
            )
            return session

    def transition(
        self, session_id: str, action: Literal["invalidate", "rotate"], operation_id: str
    ) -> dict[str, Any]:
        """Apply a trusted conversation boundary once, preserving historical rows and memory.

        一次性应用可信会话结束/轮换；保留历史记录和记忆，不把每轮结束当作会话结束。
        """
        if (
            action not in {"invalidate", "rotate"}
            or not operation_id.strip()
            or len(operation_id) > 200
        ):
            raise ValueError("Valid session action and operation ID required")
        with self.storage.transaction():
            digest = fingerprint([session_id, action])
            receipt = self.storage.get(self.owner, "host_session_operation", operation_id)
            if receipt:
                if receipt["fingerprint"] != digest:
                    raise ValueError("Session operation ID reused")
                return dict(receipt["result"])
            old = self.storage.get(self.owner, "conversation_session", session_id)
            if not old or old.get("owner_id") != self.owner or not old.get("host_identity"):
                raise ValueError("Registered canonical session required")
            identity = HostSessionIdentity.model_validate(old["host_identity"])
            mapping = self.storage.get(self.owner, "host_session", identity.key())
            if (
                not mapping
                or mapping.get("owner_id") != self.owner
                or mapping.get("session_id") != session_id
            ):
                raise ValueError("Only the current mapped session may be rotated")
            old.update(active=False, revision=old["revision"] + 1)
            self.storage.put(self.owner, "conversation_session", session_id, old)
            result = {"session_id": session_id, "active": False}
            if action == "rotate":
                endpoint = self.storage.get(self.owner, "platform_binding", identity.endpoint_id)
                if (
                    not endpoint
                    or not endpoint.get("active", True)
                    or endpoint.get("owner_id") != self.owner
                ):
                    raise ValueError("Active endpoint required for session rotation")
                replacement = dict(
                    id=new_id(),
                    owner_id=self.owner,
                    platform_binding=identity.endpoint_id,
                    character_id=endpoint["default_character_id"],
                    revision=1,
                    active=True,
                    mapping_id=identity.key(),
                    host_identity=identity.model_dump(),
                )
                self.storage.put(self.owner, "conversation_session", replacement["id"], replacement)
                mapping["session_id"] = replacement["id"]
                self.storage.put(self.owner, "host_session", identity.key(), mapping)
                result = {"session_id": replacement["id"], "active": True}
            self.storage.put(
                self.owner,
                "host_session_operation",
                operation_id,
                {"fingerprint": digest, "result": result},
            )
            return result
