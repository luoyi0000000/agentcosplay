"""Typed safety decisions and scoped storage authorization.
类型化安全决策与限定范围的存储授权。
"""

from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from character_runtime.knowledge_models import (
    EventBatch,
    EventInput,
    NarrativeProposal,
    TurnProposal,
)
from character_runtime.models import Candidate, CharacterDefinition, MemoryScope, now
from character_runtime.packages import PackageV3, import_character
from character_runtime.runtime import Runtime
from character_runtime.safety import (
    SafetyContext,
    SensitivityAssessment,
    StorageAuthorization,
    assess_content,
    check_content,
)
from character_runtime.storage import SQLiteStorage


def check_persistence():
    """Corrections preserve risk and every ingress honors the configured classifier.
    更正保留敏感性，所有持久化入口执行配置的分类器。
    """

    class Classifier:
        def assess(self, text, context):
            return SensitivityAssessment(authentication=1 if "opaque-secret-value" in text else 0)

    with TemporaryDirectory() as tmp, closing(SQLiteStorage(Path(tmp) / "runtime.sqlite3")) as db:
        rt = Runtime(db, "owner", safety_classifier=Classifier())
        cid = rt.characters.create(CharacterDefinition(name="synthetic")).id
        rt.memory.scope = MemoryScope(kind="ENDPOINT_CHARACTER", endpoint_id="group")
        memory = rt.memory.store(cid, Candidate(content="ordinary public text"))
        content = "home address: synthetic private place"
        auth = StorageAuthorization.for_content(content, "default", explicit=True)
        try:
            rt.memory.modify(cid, memory.id, content=content, authorization=auth)
        except ValueError:
            pass
        else:
            raise AssertionError("Group correction accepted sensitive content")
        assert rt.memory.owned(cid, memory.id).content == memory.content
        rt.memory.scope = MemoryScope(kind="PARTICIPANT_CHARACTER", participant_id="owner")
        private = rt.memory.store(cid, Candidate(content="ordinary private text"))
        updated = rt.memory.modify(cid, private.id, content=content, authorization=auth)
        assert updated.sensitivity == "sensitive", "Correction left sensitive content untagged"
        package = PackageV3(definition=CharacterDefinition(name="opaque-secret-value"))
        before = db.list("owner", "definition")
        try:
            import_character(rt, package.model_dump(mode="json"))
        except ValueError:
            pass
        else:
            raise AssertionError("Package bypassed the configured classifier")
        assert before == db.list("owner", "definition"), "Rejected import mutated canonical data"
        rt.open_session("chat", character_id=cid)
        refs = rt.knowledge.ingest(
            EventBatch(
                operation_id="evidence",
                session_id="chat",
                events=[
                    EventInput(
                        source_event_id="one",
                        source_id="synthetic",
                        source_kind="USER_DIRECT",
                        content="ordinary evidence",
                        timestamp=now(),
                    )
                ],
            )
        )["event_ids"]
        try:
            rt.knowledge.commit(
                "chat",
                TurnProposal(
                    operation_id="narrative",
                    narrative_proposals=[
                        NarrativeProposal(
                            content="opaque-secret-value",
                            evidence_refs=refs,
                        )
                    ],
                ),
            )
        except ValueError:
            pass
        else:
            raise AssertionError("Narrative bypassed the configured classifier")
        assert not db.list("owner", "narrative")


def main():
    check_persistence()
    content = "unrecognized value ZZ/private/location-A"
    ctx = SafetyContext(
        operation_id="write-one", purpose="precise_location", provenance="USER_DIRECT"
    )
    decision = assess_content(content, context=ctx)
    assert decision.action == "require_confirmation"
    auth = StorageAuthorization.for_content(content, "write-one", explicit=True)
    assert check_content(content, context=ctx, authorization=auth).action == "allow"
    for text, op in ((content + "changed", "write-one"), (content, "different")):
        try:
            check_content(
                text, context=ctx.model_copy(update={"operation_id": op}), authorization=auth
            )
        except ValueError:
            pass
        else:
            raise AssertionError("Storage authorization escaped its content/operation")
    secret = "password: synthetic-value"
    assert (
        assess_content(
            secret, authorization=StorageAuthorization.for_content(secret, "default", explicit=True)
        ).action
        == "reject"
    )
    # Valid checksum is evidence, not a claim that arbitrary numeric data is a payment account.
    # 校验和正确是证据，不能断言任意数字就是支付账户。
    assert assess_content("4111111111111111").action == "allow"

    class Classifier:
        def assess(self, text, context):
            return SensitivityAssessment(private=0.95, person_linkable=0.95, confidence=0.9)

    result = assess_content("new format outside catalogs", classifier=Classifier())
    assert result.action == "require_confirmation" and result.reasons
    assert "new format" not in result.model_dump_json()

    class BrokenClassifier:
        def assess(self, text, context):
            raise RuntimeError("private provider diagnostic " + text)

    try:
        check_content("do not echo this", classifier=BrokenClassifier())
    except ValueError as error:
        assert "do not echo" not in str(error) and "unavailable" in str(error)
    else:
        raise AssertionError("Classifier outage did not fail closed")
    print(
        "PASS typed safety: unknown format, provenance, structural evidence, "
        "scoped approval, credential precedence"
    )


if __name__ == "__main__":
    main()
