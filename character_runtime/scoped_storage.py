"""Authorize one immutable turn while reusing the existing storage and engines.

为不可变的单轮上下文提供权限视图；所有命名空间仍位于同一 authoritative SQLite。
The internal namespace is a tuple encoding, not another Runtime owner or database.
内部命名空间仅编码 Owner/Participant/Endpoint 组合，不是第二套 Owner 或数据库。
"""

import builtins
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from .models import CharacterState, MemoryScope
from .operations import fingerprint
from .scope import ScopeResolver, TurnActorContext
from .storage import Storage

_GLOBAL = {"definition", "growth_head", "growth_version", "compiled_context", "compiled_lkg"}
_PERSONAL = {"state", "relationship", "lifelike", "participant_adaptation"}
_AUDIENCE = {
    "turn_lifecycle",
    "memory",
    "raw_event",
    "event_digest",
    "fact",
    "narrative",
    "project_memory",
    "perception",
    "companion",
    "operation",
    "mutation",
    "mutation_grant",
    "job",
    "source_checkpoint",
    "activity_receipt",
    "reflection_receipt",
}


class ScopedStorage:
    """A fail-closed view: unknown collections and cross-character keys are denied.

    默认拒绝的存储视图：未知数据域、跨角色记录和公共状态写入均不能隐式放行。
    """

    def __init__(
        self,
        storage: Storage,
        resolver: ScopeResolver,
        actor: TurnActorContext,
        *,
        public_state: bool = False,
    ) -> None:
        self.base, self.resolver, self.actor = storage, resolver, actor
        self.owner = actor.owner_id
        self.public_state = public_state
        self.memory_scope = (
            MemoryScope(kind="PARTICIPANT_CHARACTER", participant_id=actor.participant_id)
            if actor.private_context_allowed
            else MemoryScope(kind="ENDPOINT_CHARACTER", endpoint_id=actor.platform_binding)
        )
        self.participant_namespace = self.namespace("participant", actor.participant_id)
        self.audience_namespace = (
            self.participant_namespace
            if actor.private_context_allowed
            else self.namespace("endpoint", actor.platform_binding)
        )

    def namespace(self, kind: str, identifier: str) -> str:
        """Preserve old Owner-private keys; reserve NUL-prefixed internal tuple keys.

        旧 Owner 私有键保持不变；新组合键使用外部 Owner 不允许的 NUL 前缀。
        """
        if kind == "participant" and identifier == self.owner:
            return self.owner
        return "\0agentcosplay:" + fingerprint([self.owner, kind, identifier])

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Hold scope checks and mutations in the same SQLite transaction.

        权限复查与读写位于同一 SQLite 事务，避免撤销与写入之间出现时间窗口。
        """
        with self.base.transaction():
            if self.resolver.load_turn(self.actor.id) != self.actor:
                raise ValueError("Turn context changed")
            yield

    def _target(self, owner: str, collection: str, *, write: bool = False) -> tuple[str, str]:
        if owner != self.owner:
            raise ValueError("Runtime owner mismatch")
        if collection in _GLOBAL:
            if write and collection not in {"compiled_context", "compiled_lkg"}:
                raise ValueError("Global state requires explicit owner administration")
            return owner, collection
        if collection in {"identity_binding", "participant"} and not write:
            return owner, collection
        if self.public_state:
            if collection not in {"companion", "lifelike"}:
                raise ValueError("Private state is not available to the public life engine")
            return owner, "character_" + collection
        if collection in _PERSONAL:
            # Actor attribution never grants a group access to personal state.
            # 知道群聊说话人身份不代表可以读取或更新其私人持久状态。
            if not self.actor.private_context_allowed:
                raise ValueError("Participant-private state is unavailable in a group")
            return self.participant_namespace, collection
        if collection in _AUDIENCE:
            return self.audience_namespace, collection
        raise ValueError("Collection is not authorized for this turn")

    def _visible(self, collection: str, key: str, value: dict[str, Any]) -> bool:
        if collection == "identity_binding":
            return key == self.actor.identity_binding
        if collection == "participant":
            return key == self.actor.participant_id
        return (
            value.get("id" if collection == "definition" else "character_id")
            == self.actor.character_id
        )

    def _decode(self, value: dict[str, Any] | None, namespace: str) -> dict[str, Any] | None:
        if value is None:
            return None
        result = dict(value)
        for field in ("owner", "owner_id"):
            if field in result:
                if result[field] != namespace:
                    raise ValueError("Stored record namespace mismatch")
                result[field] = self.owner
        return result

    def get(self, owner: str, collection: str, key: str) -> dict[str, Any] | None:
        """Read only this turn's audience and character. / 仅读取本轮受众和角色记录。"""
        with self.transaction():
            if collection == "session":
                if owner != self.owner or key != self.actor.id or self.public_state:
                    return None
                # Session modes survive new turns; actor identity never comes from that row.
                # 会话模式跨轮次保留；Actor 身份始终来自当前已验证 Turn。
                modes = self.base.get(owner, "conversation_mode", self.actor.session_id) or {}
                return {
                    "id": key,
                    "character_id": self.actor.character_id,
                    "identity_verified": True,
                    "identity_binding": self.actor.identity_binding,
                    **{k: modes[k] for k in ("ooc", "mode_override", "task_mode") if k in modes},
                }
            namespace, bucket = self._target(owner, collection)
            value = self.base.get(namespace, bucket, key)
            if value is None and collection == "state":
                return (
                    CharacterState(character_id=self.actor.character_id).model_dump(mode="json")
                    if key == self.actor.character_id
                    else None
                )
            if value is None or not self._visible(collection, key, value):
                return None
            return self._decode(value, namespace)

    def put(self, owner: str, collection: str, key: str, value: dict[str, Any]) -> None:
        """Write only the already-authorized namespace; never publish private state.

        只写入已授权命名空间；不能借修改字段把私人内容升级成公共状态。
        """
        with self.transaction():
            if collection == "session":
                if (
                    owner != self.owner
                    or key != self.actor.id
                    or value.get("character_id") != self.actor.character_id
                    or value.get("identity_binding") != self.actor.identity_binding
                    or not value.get("identity_verified")
                    or self.public_state
                ):
                    raise ValueError("Use explicit conversation routing to switch characters")
                self.base.put(
                    owner,
                    "conversation_mode",
                    self.actor.session_id,
                    {k: value[k] for k in ("ooc", "mode_override", "task_mode") if k in value},
                )
                return
            namespace, bucket = self._target(owner, collection, write=True)
            if not self._visible(collection, key, value):
                raise ValueError("Mutation is outside the active character")
            existing = self.base.get(namespace, bucket, key)
            if existing and not self._visible(collection, key, existing):
                raise ValueError("Record ID belongs to another character")
            record = dict(value)
            for field in ("owner", "owner_id"):
                if field in record:
                    if record[field] != owner:
                        raise ValueError("Record owner mismatch")
                    record[field] = namespace
            self.base.put(namespace, bucket, key, record)

    def list(self, owner: str, collection: str) -> builtins.list[dict[str, Any]]:
        """Filter canonical records before consumers reason over them.

        消费方推理前先过滤规范记录，不能把其他受众的记录交给后续模型。
        """
        with self.transaction():
            namespace, bucket = self._target(owner, collection)
            return [
                self._decode(r, namespace) or {}
                for r in self.base.list(namespace, bucket)
                if self._visible(collection, str(r.get("id", "")), r)
            ]

    def delete(self, owner: str, collection: str, key: str) -> None:
        """Delete only a visible private record. / 只删除当前可见的私有记录。"""
        with self.transaction():
            namespace, bucket = self._target(owner, collection, write=True)
            if collection in _GLOBAL:
                raise ValueError("Shared compiler records cannot be deleted by a turn")
            value = self.base.get(namespace, bucket, key)
            if value is not None and not self._visible(collection, key, value):
                raise ValueError("Deletion is outside the active character")
            self.base.delete(namespace, bucket, key)

    def _memory(self, owner: str, cid: str, scope: MemoryScope | None) -> str:
        if cid != self.actor.character_id or (scope is not None and scope != self.memory_scope):
            raise ValueError("Memory audience cannot be changed by the caller")
        return self._target(owner, "memory")[0]

    def memory_candidates(
        self,
        owner: str,
        character_id: str,
        query: str,
        *,
        session_id: str | None,
        real: bool,
        at: datetime,
        include_archived: bool = False,
        limit: int = 256,
        scope: MemoryScope | None = None,
    ) -> builtins.list[tuple[dict[str, Any], float]]:
        """Delegate indexed retrieval only after namespace authorization.

        先确定命名空间权限，再复用现有索引检索，不复制检索引擎。
        """
        with self.transaction():
            ns = self._memory(owner, character_id, scope)
            return [
                (self._decode(r, ns) or {}, rank)
                for r, rank in self.base.memory_candidates(
                    ns,
                    character_id,
                    query,
                    session_id=session_id,
                    real=real,
                    at=at,
                    include_archived=include_archived,
                    limit=limit,
                    scope=self.memory_scope,
                )
            ]

    def memory_window(
        self,
        owner: str,
        character_id: str,
        *,
        start: datetime | None,
        end: datetime | None,
        session_id: str | None,
        real: bool,
        include_archived: bool,
        semantic_key: str | None,
        kind: str | None,
        limit: int,
        scope: MemoryScope | None = None,
    ) -> builtins.list[dict[str, Any]]:
        """Authorize temporal retrieval too. / 时间窗口检索使用相同权限边界。"""
        with self.transaction():
            ns = self._memory(owner, character_id, scope)
            return [
                self._decode(r, ns) or {}
                for r in self.base.memory_window(
                    ns,
                    character_id,
                    start=start,
                    end=end,
                    session_id=session_id,
                    real=real,
                    include_archived=include_archived,
                    semantic_key=semantic_key,
                    kind=kind,
                    limit=limit,
                    scope=self.memory_scope,
                )
            ]

    def memory_duplicates(
        self,
        owner: str,
        character_id: str,
        content: str,
        kind: str,
        source: str,
        session_id: str | None,
        since: datetime,
        *,
        scope: MemoryScope | None = None,
    ) -> builtins.list[dict[str, Any]]:
        """Dedup only within the same audience. / 只在相同受众中去重。"""
        with self.transaction():
            ns = self._memory(owner, character_id, scope)
            return [
                self._decode(r, ns) or {}
                for r in self.base.memory_duplicates(
                    ns,
                    character_id,
                    content,
                    kind,
                    source,
                    session_id,
                    since,
                    scope=self.memory_scope,
                )
            ]

    def memory_related(
        self, owner: str, character_id: str, memory_id: str, *, scope: MemoryScope | None = None
    ) -> builtins.list[dict[str, Any]]:
        """Keep correction and erasure in scope. / 更正和遗忘不得跨受众传播。"""
        with self.transaction():
            ns = self._memory(owner, character_id, scope)
            return [
                self._decode(r, ns) or {}
                for r in self.base.memory_related(
                    ns, character_id, memory_id, scope=self.memory_scope
                )
            ]

    def memory_stale(
        self, owner: str, character_id: str, before: datetime, *, scope: MemoryScope | None = None
    ) -> builtins.list[dict[str, Any]]:
        """Maintenance is not an authorization bypass. / 维护任务也不能绕过权限。"""
        with self.transaction():
            ns = self._memory(owner, character_id, scope)
            return [
                self._decode(r, ns) or {}
                for r in self.base.memory_stale(ns, character_id, before, scope=self.memory_scope)
            ]

    def close(self) -> None:
        """The view does not own the shared connection. / 视图不负责关闭共享连接。"""
