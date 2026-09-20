import copy
import unittest

from character_runtime.companion_models import CompanionUpdate
from character_runtime.models import CharacterDefinition
from character_runtime.packages import export_character, import_character, migrate_package
from character_runtime.runtime import Runtime
from character_runtime.storage import SQLiteStorage


class CompanionPackageTests(unittest.TestCase):
    def setUp(self):
        self.db = SQLiteStorage(":memory:")
        self.addCleanup(self.db.close)
        self.rt = Runtime(self.db, "owner")
        self.cid = self.rt.characters.create(CharacterDefinition(name="旧角色")).id
        self.rt.companion.update(
            self.cid,
            CompanionUpdate.model_validate(
                {
                    "settings": {"proactive_contact": True},
                    "topic": {"id": "private", "description": "私人谈话内容"},
                    "goal": {"id": "g", "description": "私人目标"},
                }
            ),
        )

    def test_default_v1_privacy_and_explicit_v2_roundtrip(self):
        basic = export_character(self.rt, self.cid).model_dump(mode="json")
        self.assertEqual(basic["schema_version"], 1)
        self.assertNotIn("私人", str(basic))
        with self.assertRaises(ValueError):
            export_character(self.rt, self.cid, include_companion=True)
        full = export_character(
            self.rt, self.cid, include_memories=True, include_companion=True
        ).model_dump(mode="json")
        self.assertEqual(full["schema_version"], 2)
        imported = import_character(self.rt, full)
        state = self.rt.companion.get(imported.id)
        self.assertEqual(state.goals[0].description, "私人目标")
        self.assertFalse(state.settings.proactive_contact)
        self.assertIsNone(state.pending_decision)
        self.assertFalse(state.observations)

    def test_v1_migration_preserves_source_backup_and_future_rejected(self):
        old = export_character(self.rt, self.cid).model_dump(mode="json")
        backup = copy.deepcopy(old)
        new = migrate_package(old)
        self.assertEqual(new["schema_version"], 2)
        self.assertEqual(old, backup)
        self.assertNotEqual(import_character(self.rt, old).id, self.cid)
        with self.assertRaises(ValueError):
            import_character(self.rt, {**old, "schema_version": 99})

    def test_import_failure_is_atomic_and_private_state_requires_opt_in(self):
        full = export_character(
            self.rt, self.cid, include_memories=True, include_companion=True
        ).model_dump(mode="json")
        full["companion"]["character_id"] = "foreign"
        before = len(self.rt.characters.list())
        with self.assertRaises(ValueError):
            import_character(self.rt, full)
        self.assertEqual(len(self.rt.characters.list()), before)
