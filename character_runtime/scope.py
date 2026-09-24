"""Trusted ingress routing and endpoint delivery authority for one Runtime.

同一 Runtime 的可信入口路由与 Endpoint 投递权限。会话拥有角色，每轮拥有说话人。
Only authenticated host code may call administrative binding methods. Conversation
text and model tool arguments must never be treated as verified identity evidence.
只有已认证的宿主代码可以调用管理绑定；对话文字或模型参数不能充当身份验证。
"""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import AwareDatetime, ConfigDict

from .identity import resolve
from .models import Identifier, Model, new_id, now
from .operations import fingerprint
from .storage import Storage

Scope = Literal["CHARACTER_INSTANCE", "PARTICIPANT_CHARACTER", "ENDPOINT_CHARACTER", "SESSION_TURN"]


class TurnActorContext(Model):
    """An immutable actor snapshot; resolve again before any state access or send.

    不可变的本轮 Actor 快照；读取状态或发送前仍需重新验证绑定。
    """

    model_config = ConfigDict(frozen=True)
    id: Identifier
    owner_id: Identifier
    participant_id: Identifier
    identity_binding: Identifier
    platform_binding: Identifier
    character_id: Identifier
    session_id: Identifier
    host: Identifier
    endpoint_revision: int
    session_revision: int
    activity_revision: int = 0
    private_context_allowed: bool
    expires_at: AwareDatetime


class ScopeResolver:
    """Keep identity (who), endpoint (where), route and delivery authority separate.

    分离身份、交互地点、角色路由与发送权限。SQLite 事务统一仲裁多个 Host。
    """

    def __init__(self, storage: Storage, owner: str, clock: Callable[[], datetime] = now) -> None:
        self._ids(owner)
        self.storage, self.owner, self.clock = storage, owner, clock

    @staticmethod
    def _ids(*values: str) -> None:
        if any(not isinstance(v, str) or not v.strip() or len(v) > 200 for v in values):
            raise ValueError("Nonempty stable identifiers up to 200 characters are required")

    def _record(self, collection: str, key: str) -> dict[str, Any]:
        value = self.storage.get(self.owner, collection, key)
        if not value or value.get("owner_id") != self.owner or not value.get("active", True):
            raise ValueError("Binding is absent, inactive or outside the owner namespace")
        return value

    def _configure(
        self,
        collection: str,
        key: str,
        data: dict[str, Any],
        operation_id: str,
        confirmation: str,
        expected_revision: int | None,
    ) -> dict[str, Any]:
        self._ids(key, operation_id)
        if not confirmation.strip():
            raise ValueError("Explicit verified owner approval is required")
        digest = fingerprint([collection, key, data, expected_revision])
        receipt = self.storage.get(self.owner, "binding_receipt", operation_id)
        if receipt:
            if receipt["fingerprint"] != digest:
                raise ValueError("Binding operation ID conflict")
            return dict(receipt["result"])
        old = self.storage.get(self.owner, collection, key)
        if (old["revision"] if old else None) != expected_revision:
            raise ValueError("Binding revision changed; reload before updating")
        result = {
            **(old or {}),
            **data,
            "id": key,
            "owner_id": self.owner,
            "active": True,
            "revision": (old["revision"] if old else 0) + 1,
        }
        self.storage.put(self.owner, collection, key, result)
        self.storage.put(
            self.owner, "binding_receipt", operation_id, {"fingerprint": digest, "result": result}
        )
        return result

    def bind_endpoint(
        self,
        platform: str,
        endpoint: str,
        kind: Literal["dm", "group"],
        default_character_id: str,
        *,
        operation_id: str,
        confirmation: str,
        participant_id: str | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        """Configure a stable endpoint; a DM additionally belongs to one participant.

        显式配置稳定 Endpoint；私聊必须绑定唯一 Participant，群聊无私人读权限。
        Platform must include provider/account namespace when external IDs are app-scoped.
        平台 ID 若只在应用内唯一，platform 必须包含对应的提供方/账号命名空间。
        """
        self._ids(platform, endpoint, default_character_id)
        if kind not in ("dm", "group") or (kind == "dm") != (participant_id is not None):
            raise ValueError("DM requires one participant; group must not pin a participant")
        with self.storage.transaction():
            if not self.storage.get(self.owner, "definition", default_character_id):
                raise ValueError("Endpoint default character is not owned")
            if participant_id:
                self._record("participant", participant_id)
            key = fingerprint([platform, endpoint])
            return self._configure(
                "platform_binding",
                key,
                dict(
                    platform=platform,
                    endpoint=endpoint,
                    kind=kind,
                    participant_id=participant_id,
                    default_character_id=default_character_id,
                ),
                operation_id,
                confirmation,
                expected_revision,
            )

    def begin_turn(
        self,
        *,
        host: str,
        platform: str,
        actor_id: str,
        endpoint_id: str,
        session_id: str,
        request_id: str | None = None,
    ) -> TurnActorContext:
        """Resolve verified ingress to a turn without pinning the conversation's actor.

        解析可信入口，每轮独立确认说话人；同一群会话不绑定固定真人。
        """
        self._ids(host, platform, actor_id, endpoint_id, session_id)
        with self.storage.transaction():
            # Retry identifies one ingress, never a fresh actor or renewed authorization.
            # 重试指向同一入口，不得借重试更换说话人或延长过期权限。
            receipt_key = None
            digest = fingerprint([platform, actor_id, endpoint_id, session_id])
            if request_id is not None:
                self._ids(request_id)
                receipt_key = fingerprint([host, request_id])
                receipt = self.storage.get(self.owner, "turn_receipt", receipt_key)
                if receipt:
                    if receipt["fingerprint"] != digest:
                        raise ValueError("Ingress ID reused with different routing")
                    return self.load_turn(receipt["turn_id"])
            identity_id = resolve(self.storage, self.owner, host, platform, actor_id)
            if identity_id is None:
                raise ValueError("Unknown actor; explicit verified identity binding required")
            identity = self._record("identity_binding", identity_id)
            participant = identity.get("participant_id", self.owner)
            # Legacy owner bindings are not promoted to a different participant.
            # 旧绑定仅代表 Owner，不自动猜测或提升为其他 Participant。
            if participant != self.owner or self.storage.get(
                self.owner, "participant", participant
            ):
                self._record("participant", participant)
            endpoint = self._record("platform_binding", endpoint_id)
            if endpoint["platform"] != platform or (
                endpoint["kind"] == "dm" and endpoint["participant_id"] != participant
            ):
                raise ValueError("Actor is not authorized for this endpoint")
            key = fingerprint([host, endpoint_id, session_id])
            session = self.storage.get(self.owner, "conversation_session", key)
            if session is None:
                session = {
                    "id": key,
                    "owner_id": self.owner,
                    "platform_binding": endpoint_id,
                    "character_id": endpoint["default_character_id"],
                    "revision": 1,
                }
                self.storage.put(self.owner, "conversation_session", key, session)
            self._authorize_route(endpoint, participant, session["character_id"])
            activity = self.storage.get(self.owner, "endpoint_activity", endpoint_id) or {
                "revision": 0
            }
            delivery = self.storage.get(self.owner, "delivery_binding", endpoint_id)
            advances_activity = not delivery or (
                delivery.get("active", True) and delivery["host"] == host
            )
            turn = TurnActorContext(
                id=new_id(),
                owner_id=self.owner,
                participant_id=participant,
                identity_binding=identity_id,
                platform_binding=endpoint_id,
                character_id=session["character_id"],
                session_id=key,
                host=host,
                endpoint_revision=endpoint["revision"],
                session_revision=session["revision"],
                activity_revision=activity["revision"] + 1 if advances_activity else 0,
                private_context_allowed=endpoint["kind"] == "dm",
                expires_at=self.clock() + timedelta(hours=1),
            )
            self.storage.put(self.owner, "turn_actor", turn.id, turn.model_dump(mode="json"))
            # An observing host cannot interrupt the active sender's generation.
            # 旁观 Host 不得中断当前发送 Host 的生成。
            if advances_activity:
                self.storage.put(
                    self.owner,
                    "endpoint_activity",
                    endpoint_id,
                    {"revision": turn.activity_revision},
                )
            if receipt_key:
                self.storage.put(
                    self.owner,
                    "turn_receipt",
                    receipt_key,
                    {
                        "turn_id": turn.id,
                        "fingerprint": digest,
                    },
                )
            return turn

    def load_turn(self, turn_id: str) -> TurnActorContext:
        """Recheck revocation and route revisions; a cached turn is never authority.

        重新检查撤销状态和路由版本；缓存的 Actor 快照不等于持续授权。
        """
        with self.storage.transaction():
            value = self.storage.get(self.owner, "turn_actor", turn_id)
            if value is None:
                raise ValueError("Unknown turn")
            turn = TurnActorContext.model_validate(value)
            identity = self._record("identity_binding", turn.identity_binding)
            endpoint = self._record("platform_binding", turn.platform_binding)
            session = self._record("conversation_session", turn.session_id)
            participant = self.storage.get(self.owner, "participant", turn.participant_id)
            if (
                turn.owner_id != self.owner
                or turn.expires_at <= self.clock()
                or identity.get("participant_id", self.owner) != turn.participant_id
                or identity["host"] != turn.host
                or identity["platform"] != endpoint["platform"]
                or turn.private_context_allowed != (endpoint["kind"] == "dm")
                or endpoint["revision"] != turn.endpoint_revision
                or session["revision"] != turn.session_revision
                or session["character_id"] != turn.character_id
                or session["platform_binding"] != turn.platform_binding
                or (participant is not None and not participant.get("active"))
                or (participant is None and turn.participant_id != self.owner)
            ):
                raise ValueError("Turn authorization expired or changed")
            self._authorize_route(endpoint, turn.participant_id, turn.character_id)
            return turn

    def switch_character(self, turn_id: str, character_id: str) -> None:
        """Switch only this session; endpoint defaults require explicit configuration.

        只切换当前 Session；不修改 Endpoint 的持久默认角色。
        """
        with self.storage.transaction():
            turn = self.load_turn(turn_id)
            endpoint = self._record("platform_binding", turn.platform_binding)
            self._authorize_route(endpoint, turn.participant_id, character_id)
            session = self._record("conversation_session", turn.session_id)
            session.update(character_id=character_id, revision=session["revision"] + 1)
            self.storage.put(self.owner, "conversation_session", turn.session_id, session)
            self.storage.delete(self.owner, "conversation_mode", turn.session_id)

    def _authorize_route(self, endpoint: dict[str, Any], participant: str, character: str) -> None:
        if endpoint["kind"] == "dm" and endpoint["participant_id"] != participant:
            raise ValueError("DM belongs to another participant")
        route = self.storage.get(
            self.owner,
            "character_route",
            fingerprint([endpoint["id"], endpoint["participant_id"], character]),
        )
        if character != endpoint["default_character_id"] and not (
            route and route.get("active") and route.get("owner_id") == self.owner
        ):
            raise ValueError("Character route requires explicit owner authorization")
        if not self.storage.get(self.owner, "definition", character):
            raise ValueError("Character does not belong to this Runtime")

    def bind_route(
        self,
        endpoint_id: str,
        participant_id: str | None,
        character_id: str,
        *,
        operation_id: str,
        confirmation: str,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        """Grant an explicit character route; existing profiles are never public by default.

        显式授权角色路由；Owner 持有的其他角色不能因此自动成为公共可切换角色。
        """
        self._ids(endpoint_id, character_id)
        with self.storage.transaction():
            endpoint = self._record("platform_binding", endpoint_id)
            if participant_id != endpoint["participant_id"]:
                raise ValueError(
                    "A group route must be public; a DM route must match its recipient"
                )
            if participant_id:
                self._record("participant", participant_id)
            if not self.storage.get(self.owner, "definition", character_id):
                raise ValueError("Unknown character")
            return self._configure(
                "character_route",
                fingerprint([endpoint_id, participant_id, character_id]),
                dict(
                    endpoint_id=endpoint_id,
                    participant_id=participant_id,
                    character_id=character_id,
                ),
                operation_id,
                confirmation,
                expected_revision,
            )

    def bind_delivery(
        self,
        endpoint_id: str,
        host: str,
        adapter: str,
        *,
        operation_id: str,
        confirmation: str,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        """Assign one sender, preserving unknown outcomes across host changes.

        为 Endpoint 指定唯一发送者；未知投递结果禁止通过切换 Host 绕过。
        """
        self._ids(endpoint_id, host, adapter)
        with self.storage.transaction():
            self._record("platform_binding", endpoint_id)
            if self.storage.get(self.owner, "binding_receipt", operation_id):
                return self._configure(
                    "delivery_binding",
                    endpoint_id,
                    dict(host=host, adapter=adapter),
                    operation_id,
                    confirmation,
                    expected_revision,
                )
            # A send in flight or of unknown outcome must be reconciled first.
            # 发送中或结果未知的记录必须先人工核对，不能借换 Host 重发。
            if any(
                r.get("endpoint_id") == endpoint_id and r["status"] in ("pending", "unknown")
                for r in self.storage.list(self.owner, "endpoint_delivery")
            ):
                raise ValueError("Endpoint has an unresolved delivery; authority switch denied")
            return self._configure(
                "delivery_binding",
                endpoint_id,
                dict(host=host, adapter=adapter),
                operation_id,
                confirmation,
                expected_revision,
            )

    def claim_delivery(
        self, endpoint_id: str, decision_id: str, host: str, revision: int
    ) -> dict[str, Any] | None:
        """Atomically reserve one external send; interruption is not retry permission.

        原子保留一次实际发送权；进程中断或租约过期均不代表可以重发。
        """
        self._ids(endpoint_id, decision_id, host)
        with self.storage.transaction():
            self._record("platform_binding", endpoint_id)
            binding = self._record("delivery_binding", endpoint_id)
            if binding["host"] != host or binding["revision"] != revision:
                raise ValueError("Host does not hold current delivery authority")
            key = fingerprint([endpoint_id, decision_id])
            if self.storage.get(self.owner, "endpoint_delivery", key):
                return None
            result = dict(
                endpoint_id=endpoint_id,
                decision_id=decision_id,
                host=host,
                binding_revision=revision,
                claim_id=new_id(),
                status="pending",
                lease_until=(self.clock() + timedelta(minutes=5)).isoformat(),
            )
            self.storage.put(self.owner, "endpoint_delivery", key, result)
            return result

    def ack_delivery(
        self, endpoint_id: str, decision_id: str, host: str, claim_id: str, delivered: bool | None
    ) -> dict[str, Any]:
        """Acknowledge transport success, failure or ambiguity, never model generation.

        只确认平台发送成功、失败或未知；模型生成完成不是发送成功。
        """
        self._ids(endpoint_id, decision_id, host, claim_id)
        if delivered is not None and type(delivered) is not bool:
            raise ValueError("Delivery result must be true, false or unknown")
        with self.storage.transaction():
            key = fingerprint([endpoint_id, decision_id])
            record = self.storage.get(self.owner, "endpoint_delivery", key)
            if not record or record["host"] != host or record["claim_id"] != claim_id:
                raise ValueError("Delivery claim does not belong to this Host")
            status = "unknown" if delivered is None else "delivered" if delivered else "failed"
            if record["status"] != "pending":
                if record["status"] != status:
                    raise ValueError("Conflicting delivery acknowledgement")
                return {"status": status}
            record["status"] = status
            self.storage.put(self.owner, "endpoint_delivery", key, record)
            return {"status": status}
