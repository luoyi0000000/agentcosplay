"""Check scoped hybrid ranking with a deterministic synthetic semantic backend.
使用确定性合成语义后端验证作用域与混合排序，不冒充嵌入模型质量验收。
"""

from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from character_runtime.models import Candidate, CharacterDefinition
from character_runtime.persistence_models import RecallRequest
from character_runtime.retrieval import SemanticHit, duplicate, rrf
from character_runtime.runtime import Runtime
from character_runtime.storage import SQLiteStorage


class Index:
    def __init__(self):
        self.records = {}
        self.calls = []

    def upsert(self, namespace, item_id, text):
        self.records[namespace, item_id] = text

    def remove(self, namespace, item_id):
        self.records.pop((namespace, item_id), None)

    def search(self, namespace, query, *, allowed_ids, limit):
        self.calls.append((namespace, allowed_ids))
        # Fixture semantic score: an adapter supplies semantics, Core has no synonym table.
        # 合成语义得分由后端提供；Core 无同义词字典。
        return [
            SemanticHit(item_id=i, score=1)
            for i in allowed_ids
            if (namespace, i) in self.records and "sleep" in self.records[namespace, i]
        ][:limit]


def main():
    assert not duplicate("value 17", "value 18") and not duplicate("I agree", "I do not agree")
    fused = rrf(["a", "b"], ["b", "a"])
    assert fused["a"].fusion_score == fused["b"].fusion_score == 1 / 61 + 1 / 62
    assert rrf(["a", "a"], [])["a"].fusion_score == 1 / 61
    with (
        TemporaryDirectory() as tmp,
        closing(SQLiteStorage(Path(tmp) / "runtime.sqlite3")) as store,
    ):
        index = Index()
        rt = Runtime(store, "owner", semantic_index=index)
        cid = rt.characters.create(CharacterDefinition(name="test")).id
        a = rt.memory.store(
            cid, Candidate(content="sleep at midnight", kind="character_long_term", importance=0.8)
        )
        b = rt.memory.store(
            cid,
            Candidate(content="model XR-73 costs 42", kind="character_long_term", importance=0.8),
        )
        other = Runtime(store, "other", semantic_index=index)
        oid = other.characters.create(CharacterDefinition(name="other")).id
        private = other.memory.store(
            oid,
            Candidate(
                content="private sleep information", kind="character_long_term", importance=0.8
            ),
        )
        assert not index.records
        assert rt.memory.rebuild_semantic(cid) == 2
        other.memory.rebuild_semantic(oid)
        try:
            with store.transaction():
                rt.memory.rebuild_semantic(cid)
        except ValueError:
            pass
        else:
            raise AssertionError("Uncommitted records could escape through semantic indexing")
        assert rt.memory.recall(cid, "需要休息", limit=1)[0].id == a.id
        assert all(private.id not in ids for _, ids in index.calls)
        assert rt.memory.recall(cid, "XR-73 42", limit=1)[0].id == b.id
        plain = Runtime(store, "owner")
        assert plain.memory.recall(cid, "XR-73 42", limit=1)[0].id == b.id
        assert plain.memory.recall(cid, current_topic="sleep", limit=1)[0].id == a.id
        assert plain.memory.recall(cid, active_goals=["sleep"], limit=1)[0].id == a.id
        assert (
            plain.memory.recall(
                cid, current_topic="sleep", request=RecallRequest(intent="RECENT", limit=1)
            )[0].id
            == b.id
        ), "Topic hint escaped explicit recent recall bounds"
        original_search = index.search
        index.search = lambda *args, **kwargs: [SemanticHit(item_id=private.id, score=999)]
        assert all(m.id != private.id for m in rt.memory.recall(cid, "foreign backend hit"))
        index.search = original_search
        b.status = "archived"
        rt.memory._save(b)
        assert plain.memory.recall(cid, "XR-73", include_archived=True)[0].id == a.id
        b.status = "active"
        rt.memory._save(b)
        rt.memory.forget(cid, a.id)
        assert (rt.memory.index_namespace(cid), a.id) not in index.records
        assert all(m.id != a.id for m in rt.memory.recall(cid, "需要休息"))
    print(
        "PASS hybrid retrieval: scoped semantic, lexical fallback, exact entities, "
        "RRF, erasure, conservative dedup"
    )


if __name__ == "__main__":
    main()
