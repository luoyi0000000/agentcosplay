"""Keep AffectState authoritative while preserving legacy Mood archives exactly.

验证 AffectState 唯一当前权威，以及旧 Mood 档案、备份和包往返的无损保留。
"""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from character_runtime.companion_models import CompanionUpdate
from character_runtime.knowledge_models import EventBatch, EventInput, TurnProposal
from character_runtime.lifelike_models import AffectEffect
from character_runtime.models import Candidate, CharacterDefinition
from character_runtime.packages import export_character, import_character
from character_runtime.runtime import Runtime
from character_runtime.server import safe
from character_runtime.storage import SQLiteStorage


def main():
    with TemporaryDirectory() as directory:
        path = Path(directory) / "legacy.sqlite3"
        store = SQLiteStorage(path)
        instant = datetime(2026, 9, 23, tzinfo=UTC)
        rt = Runtime(store, "owner", clock=lambda: instant)
        cid = rt.characters.create(CharacterDefinition(name="affect")).id
        rt.open_session("s", character_id=cid)
        legacy = {
            "label": "legacy-mood-sentinel",
            "intensity": 0.987,
            "reason": "archived only",
            "evidence_ids": ["old-opaque-evidence"],
            "updated_at": "2021-01-01T00:00:00+00:00",
            "influenced_at": None,
            "unknown_extension": {"nested": [1, "preserve", {"units": "unmapped"}]},
        }
        companion = rt.companion.get(cid).model_dump(mode="json")
        companion.update(mood=legacy, unknown_outer={"keep": True})
        store.put("owner", "companion", cid, companion)
        store.close()
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA user_version=4")
        original = connection.execute(
            "SELECT value FROM records WHERE collection='companion' AND key=?", (cid,)
        ).fetchone()[0]
        connection.commit()
        original_rows = connection.execute(
            "SELECT * FROM records ORDER BY owner, collection, key"
        ).fetchall()
        connection.close()
        archive = SQLiteStorage._archive_legacy_mood

        def interrupted(storage, version):
            archive(storage, version)
            raise RuntimeError("synthetic interrupted Mood archival")

        with patch.object(SQLiteStorage, "_archive_legacy_mood", interrupted):
            try:
                SQLiteStorage(path)
            except RuntimeError:
                pass
            else:
                raise AssertionError("Interrupted migration succeeded")
        with sqlite3.connect(path) as connection:
            assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
            assert (
                connection.execute(
                    "SELECT * FROM records ORDER BY owner, collection, key"
                ).fetchall()
                == original_rows
            )
        store = SQLiteStorage(path)
        try:
            rt = Runtime(store, "owner", clock=lambda: instant)
            assert store.migration_backup, "Affect semantic migration requires private backup"
            with sqlite3.connect(store.migration_backup) as backup:
                assert (
                    backup.execute(
                        "SELECT value FROM records WHERE collection='companion' AND key=?", (cid,)
                    ).fetchone()[0]
                    == original
                )
            assert rt.companion.get(cid).model_dump(mode="json")["mood"] == legacy
            for days in (0, 1, 90):
                instant += timedelta(days=days)
                rt.companion.advance(cid)
                assert store.get("owner", "companion", cid)["mood"] == legacy
                assert "legacy-mood-sentinel" not in json.dumps(rt.context("s"))
                assert "mood" not in rt.companion.context(cid)
            before = store.get("owner", "companion", cid)
            update = CompanionUpdate(mood={"label": "happy", "intensity": 1, "reason": "write"})
            blocked = safe(lambda: rt.companion.update(cid, update))()
            assert blocked["error"] == "LEGACY_MOOD_WRITE_UNSUPPORTED" and blocked["read_only"]
            assert blocked["replacement"] == "AffectEffect"
            assert store.get("owner", "companion", cid) == before
            blocked = safe(
                lambda: rt.commit_turn(
                    "s", TurnProposal(operation_id="old-mood", companion_update=update)
                )
            )()
            assert blocked["error"] == "LEGACY_MOOD_WRITE_UNSUPPORTED"
            assert rt.knowledge.lifelike.get(cid).affect.valence == 0
            event = rt.knowledge.ingest(
                EventBatch(
                    session_id="s",
                    operation_id="e",
                    events=[
                        EventInput(
                            source_id="source",
                            source_event_id="e",
                            source_kind="USER_DIRECT",
                            content="Thank you for helping",
                            timestamp=instant,
                        )
                    ],
                )
            )["event_ids"][0]
            rt.commit_turn(
                "s",
                TurnProposal(
                    operation_id="affect",
                    affect_effects=[AffectEffect(valence=0.2, evidence_refs=[event])],
                ),
            )
            assert rt.knowledge.lifelike.get(cid).affect.valence == 0.2
            assert store.get("owner", "companion", cid)["mood"] == legacy
            assert store.list("owner", "affect_effect") == [], "Effect became a second state"
            memory = rt.memory.store(
                cid,
                Candidate(
                    content="unrelated memory",
                    source="chat",
                    kind="character_long_term",
                    importance=1,
                ),
            )
            rt.memory.modify(cid, memory.id, content="corrected unrelated memory")
            assert store.get("owner", "companion", cid)["mood"] == legacy, (
                "Ordinary memory correction erased the detached legacy archive"
            )
            for version in (2, 3):
                package = export_character(rt, cid, include_memories=True, include_companion=True)
                data = package.model_dump(mode="json")
                if version == 2:
                    from character_runtime.packages import PackageV2

                    data = {
                        key: value for key, value in data.items() if key in PackageV2.model_fields
                    }
                    data["schema_version"] = 2
                imported = import_character(rt, data)
                rt.open_session("imported", character_id=imported.id)
                assert rt.knowledge.lifelike.get(imported.id).affect.valence == 0
                assert "legacy-mood-sentinel" not in json.dumps(rt.context("imported"))
                exported = export_character(
                    rt, imported.id, include_memories=True, include_companion=True
                )
                assert exported.companion.model_dump(mode="json")["mood"] == legacy
                assert exported.companion.model_dump()["unknown_outer"] == {"keep": True}
            secret_record = store.get("owner", "companion", cid)
            secret_record["mood"]["unknown_extension"]["api_key"] = "synthetic-opaque-credential"
            store.put("owner", "companion", cid, secret_record)
            try:
                export_character(rt, cid, include_memories=True, include_companion=True)
            except ValueError:
                pass
            else:
                raise AssertionError("Opaque legacy fields bypassed credential export rejection")
            rt.memory.forget(cid, memory.id)
            assert store.get("owner", "companion", cid)["mood"] == {}, (
                "Explicit privacy erasure left the opaque archive behind"
            )
        finally:
            store.close()
    print(
        "PASS Affect authority: immutable legacy Mood, compatibility code, reducer, "
        "backup/rollback, V2/V3 roundtrip"
    )


if __name__ == "__main__":
    main()
