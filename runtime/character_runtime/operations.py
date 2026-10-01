"""Scoped transactional receipts, mutation grants, durable jobs and ingestion positions.

作用域事务回执、修改授权、持久任务及摄入位置。
"""

import json
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any

from .models import new_id, now
from .storage import Storage


def fingerprint(value: Any) -> str:
    """Stable JSON digest; rejects non-JSON values and non-finite numbers.

    稳定 JSON 摘要；拒绝非 JSON 值及非有限数值。
    """
    return sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _identifier(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError("A nonempty identifier of at most 200 characters is required")
    return value


def _identifiers(values: Iterable[str]) -> list[str]:
    result = sorted({_identifier(value) for value in values})
    if len(result) > 100:
        raise ValueError("At most 100 identifiers are allowed")
    return result


class Operations:
    """One owner + character namespace. Callbacks must perform local DB work only.

    每个实例限定 Owner 与 Character；回调只能执行本地数据库操作。
    """

    def __init__(
        self, storage: Storage, owner: str, character_id: str, clock: Callable[[], datetime] = now
    ) -> None:
        self.storage, self.owner = storage, _identifier(owner)
        self.character_id, self.clock = _identifier(character_id), clock
        if storage.get(owner, "definition", character_id) is None:
            raise KeyError("Character not found")

    def _key(self, identifier: str) -> str:
        return f"{len(self.character_id)}:{self.character_id}:{_identifier(identifier)}"

    def _get(self, collection: str, identifier: str) -> dict[str, Any] | None:
        record = self.storage.get(self.owner, collection, self._key(identifier))
        if record is not None and record.get("character_id") != self.character_id:
            raise ValueError("Record character does not match")
        return record

    def _put(self, collection: str, identifier: str, record: dict[str, Any]) -> None:
        self.storage.put(
            self.owner,
            collection,
            self._key(identifier),
            {**record, "character_id": self.character_id},
        )

    def execute(
        self,
        operation_id: str,
        payload: dict[str, Any],
        apply: Callable[[], dict[str, Any]],
        *,
        domain: str,
        operation: str,
        target_ids: Iterable[str] = (),
        before: Any = None,
        reason: str = "",
        evidence_refs: Iterable[str] = (),
        authority: str = "HOST_OBSERVED",
        proposal_source: str = "host",
    ) -> dict[str, Any]:
        """Commit callback, receipt and digest-only audit atomically, or return the old result.

        The caller validates proposals/authority and supplies only safe audit reasons. Never
        put an external send in this callback: SQLite cannot roll back a network effect.

                将回调、回执及只含摘要的审计原子提交；重复操作返回原结果。
        """
        targets, evidence = _identifiers(target_ids), _identifiers(evidence_refs)
        if len(reason) > 500:
            raise ValueError("Audit reason must be at most 500 characters")
        request = dict(
            payload=payload,
            domain=_identifier(domain),
            operation=_identifier(operation),
            target_ids=targets,
            reason=reason,
            evidence_refs=evidence,
            authority=_identifier(authority),
            proposal_source=_identifier(proposal_source),
        )
        digest = fingerprint(request)
        with self.storage.transaction():
            prior = self._get("operation", operation_id)
            if prior:
                if prior["fingerprint"] != digest:
                    raise ValueError("Operation ID was already used for a different request")
                return dict(prior["result"])
            collections = {
                "character": ("definition", "state", "relationship"),
                "knowledge": (
                    "memory",
                    "fact",
                    "narrative",
                    "project_memory",
                    "state",
                    "relationship",
                    "growth_head",
                    "lifelike",
                    "companion",
                ),
                "ingestion": ("raw_event",),
                "growth": ("growth_candidate", "growth_version", "growth_head"),
                "perception": ("perception", "visual_prototype"),
                "observation": ("companion",),
            }.get(domain, (domain,))

            actor = getattr(self.storage, "actor", None)
            if actor and not actor.private_context_allowed:
                # Audit hashes must not read private state on behalf of a group operation.
                # 群聊操作的审计摘要也不能越过私人数据边界。
                collections = tuple(
                    c
                    for c in collections
                    if c not in {"state", "relationship", "lifelike", "participant_adaptation"}
                )

            def snapshot(ids: Iterable[str]) -> dict[str, Any]:
                return {
                    collection: {
                        key: self.storage.get(self.owner, collection, key)
                        for key in sorted(set(ids))
                    }
                    for collection in collections
                }

            before_digest = fingerprint(
                before if before is not None else snapshot([self.character_id, *targets])
            )
            result = apply()
            if not isinstance(result, dict):
                raise ValueError("Operation callback must return a JSON object")
            result_ids = [
                value
                for key, values in result.items()
                if key.endswith("_ids") and isinstance(values, list)
                for value in values
                if isinstance(value, str)
            ]
            after_digest = fingerprint(snapshot([self.character_id, *targets, *result_ids]))
            timestamp = self.clock().isoformat()
            self._put(
                "mutation",
                operation_id,
                dict(
                    operation_id=operation_id,
                    domain=domain,
                    operation=operation,
                    target_ids=targets,
                    before_digest=before_digest,
                    result_digest=fingerprint(result),
                    after_digest=after_digest,
                    reason=reason,
                    evidence_refs=evidence,
                    authority=authority,
                    proposal_source=proposal_source,
                    timestamp=timestamp,
                ),
            )
            self._put(
                "operation",
                operation_id,
                dict(
                    operation_id=operation_id,
                    fingerprint=digest,
                    result=result,
                    status="committed",
                    timestamp=timestamp,
                ),
            )
            return result

    def _targets(self, collection: str, targets: list[str]) -> dict[str, str]:
        snapshots = {}
        for target in targets:
            record = self.storage.get(self.owner, collection, target)
            character_field = "id" if collection == "definition" else "character_id"
            if record is None or record.get(character_field) != self.character_id:
                raise ValueError("Mutation target is not an owned character record")
            snapshots[target] = fingerprint(record)
        return snapshots

    def issue_allowlist(
        self,
        collection: str,
        target_ids: Iterable[str],
        operations: Iterable[str],
        *,
        session_id: str | None = None,
        ttl_seconds: int = 300,
    ) -> dict[str, Any]:
        """Issue a short-lived immutable grant from actual canonical targets, never guessed IDs.

        根据真实规范记录签发短期不可变授权，不能猜测目标 ID。
        """
        targets, allowed = _identifiers(target_ids), _identifiers(operations)
        if not targets or not allowed or not 1 <= ttl_seconds <= 3600:
            raise ValueError("A grant requires targets, operations and a 1..3600 second lifetime")
        if set(allowed) - {
            "UPDATE",
            "MERGE",
            "FORGET",
            "SUPERSEDE",
            "ARCHIVE",
            "CORRECT",
            "ROLLBACK",
        }:
            raise ValueError("Unknown mutation operation")
        _identifier(collection)
        if session_id is not None:
            _identifier(session_id)
        with self.storage.transaction():
            grant: dict[str, Any] = dict(
                id=new_id(),
                collection=collection,
                target_ids=targets,
                operations=allowed,
                session_id=session_id,
                targets=self._targets(collection, targets),
                consumed=False,
                expires_at=(self.clock() + timedelta(seconds=ttl_seconds)).isoformat(),
            )
            self._put("mutation_grant", grant["id"], grant)
            return {key: value for key, value in grant.items() if key != "targets"}

    def consume_allowlist(
        self,
        grant_id: str,
        operation: str,
        target_ids: Iterable[str],
        *,
        collection: str,
        session_id: str | None = None,
    ) -> None:
        """Consume inside execute() so failed canonical mutations roll the grant back too.

        必须在 execute 事务中消费；规范写入失败时授权消费也回滚。
        """
        targets = _identifiers(target_ids)
        with self.storage.transaction():
            grant = self._get("mutation_grant", grant_id)
            if (
                not grant
                or grant["consumed"]
                or grant["collection"] != collection
                or grant["session_id"] != session_id
                or datetime.fromisoformat(grant["expires_at"]) <= self.clock()
                or operation not in grant["operations"]
                or not targets
                or not set(targets) <= set(grant["target_ids"])
            ):
                raise ValueError("Mutation grant is absent, expired, consumed or out of scope")
            actual = self._targets(grant["collection"], targets)
            if any(actual[key] != grant["targets"][key] for key in targets):
                raise ValueError("Mutation target changed; request a fresh grant")
            grant["consumed"] = True
            self._put("mutation_grant", grant_id, grant)

    def enqueue(
        self,
        operation_id: str,
        kind: str,
        payload: dict[str, Any],
        *,
        retry_safe: bool = False,
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        """retry_safe is only for deterministic DB maintenance, never an external effect.

        仅确定性的数据库维护可标记可重试，外部副作用不能标记。
        """
        if not 1 <= max_attempts <= 10:
            raise ValueError("Job attempts must be between 1 and 10")
        digest = fingerprint(
            dict(
                kind=_identifier(kind),
                payload=payload,
                retry_safe=retry_safe,
                max_attempts=max_attempts,
            )
        )
        with self.storage.transaction():
            prior = self._get("job", operation_id)
            if prior:
                if prior["fingerprint"] != digest:
                    raise ValueError("Job operation ID was reused for a different request")
                return {key: value for key, value in prior.items() if key != "claim_id"}
            job = dict(
                operation_id=operation_id,
                kind=kind,
                payload=payload,
                fingerprint=digest,
                retry_safe=retry_safe,
                max_attempts=max_attempts,
                attempts=0,
                status="pending",
                claim_id=None,
                lease_until=None,
                created_at=self.clock().isoformat(),
            )
            self._put("job", operation_id, job)
            return job

    def claim(self, operation_id: str, *, lease_seconds: int = 300) -> dict[str, Any] | None:
        """One worker wins. Expired unsafe work is quarantined with an unknown outcome.

        只有一个工作者领取；租约过期且不可安全重试的任务以未知结果隔离。
        """
        if not 1 <= lease_seconds <= 3600:
            raise ValueError("Lease must be between 1 and 3600 seconds")
        with self.storage.transaction():
            job = self._get("job", operation_id)
            if not job:
                raise KeyError("Job not found")
            instant = self.clock()
            if job["status"] == "running" and datetime.fromisoformat(job["lease_until"]) <= instant:
                job["status"] = "retry" if job["retry_safe"] else "quarantined"
                job["error_code"] = "lease_expired" if job["retry_safe"] else "outcome_unknown"
                job["claim_id"] = None
                self._put("job", operation_id, job)
            if job["status"] not in ("pending", "retry"):
                return None
            if job["attempts"] >= job["max_attempts"]:
                job["status"] = "failed"
                self._put("job", operation_id, job)
                return None
            job.update(
                status="running",
                claim_id=new_id(),
                attempts=job["attempts"] + 1,
                lease_until=(instant + timedelta(seconds=lease_seconds)).isoformat(),
            )
            self._put("job", operation_id, job)
            return job

    def _claimed(self, operation_id: str, claim_id: str) -> dict[str, Any]:
        job = self._get("job", operation_id)
        if (
            not job
            or job["status"] != "running"
            or job["claim_id"] != claim_id
            or datetime.fromisoformat(job["lease_until"]) <= self.clock()
        ):
            raise ValueError("Job claim is absent, expired or no longer owned")
        return job

    def finish(self, operation_id: str, claim_id: str, result: dict[str, Any]) -> None:
        """Call in the same outer transaction as the job's canonical DB mutations.

        与任务的规范数据库修改在同一外层事务调用。
        """
        with self.storage.transaction():
            job = self._claimed(operation_id, claim_id)
            job.update(
                status="committed",
                result_digest=fingerprint(result),
                claim_id=None,
                completed_at=self.clock().isoformat(),
            )
            self._put("job", operation_id, job)

    def fail(
        self,
        operation_id: str,
        claim_id: str,
        *,
        retryable: bool = False,
        error_code: str = "failed",
    ) -> None:
        """Never store exception text or retry ambiguous external effects.

        不保存异常正文，不重试结果不明的外部副作用。
        """
        if not error_code.replace("_", "").isalnum() or len(error_code) > 80:
            raise ValueError("Use a short error code, not an exception body")
        with self.storage.transaction():
            job = self._claimed(operation_id, claim_id)
            job["status"] = (
                "retry"
                if retryable and job["retry_safe"] and job["attempts"] < job["max_attempts"]
                else "failed"
            )
            job.update(error_code=error_code, claim_id=None)
            self._put("job", operation_id, job)

    def checkpoint(
        self,
        source_id: str,
        last_event_id: str,
        last_timestamp: datetime,
        *,
        expected_revision: int = 0,
    ) -> dict[str, Any]:
        """A position, NOT dedup: call in the same transaction as source-event ingestion.

        仅记录位置，不提供去重；与源事件摄入在同一事务调用。
        """
        _identifier(last_event_id)
        if last_timestamp.tzinfo is None or last_timestamp.utcoffset() is None:
            raise ValueError("Checkpoint timestamp requires a timezone")
        with self.storage.transaction():
            prior = self._get("source_checkpoint", source_id)
            revision = prior["revision"] if prior else 0
            if expected_revision != revision:
                raise ValueError("Checkpoint revision changed")
            record = dict(
                source_id=source_id,
                last_event_id=last_event_id,
                last_timestamp=last_timestamp.isoformat(),
                revision=revision + 1,
            )
            self._put("source_checkpoint", source_id, record)
            return record
