from pydantic import ValidationError

from character_runtime.models import Candidate, Evolution
from character_runtime.packages import export_character, import_character
from tests.test_runtime import RuntimeFixture


class PackageTests(RuntimeFixture):
    def test_export_opt_in_and_import_remaps(self):
        m = self.rt.memory.store(self.a.id, Candidate(content="共同看过流星", importance=0.9))
        default = export_character(self.rt, self.a.id)
        self.assertEqual(default.memories, [])
        self.assertNotIn("共同看过流星", default.model_dump_json())
        full = export_character(self.rt, self.a.id, include_memories=True)
        self.assertEqual(len(full.memories), 1)
        new = import_character(self.rt, full.model_dump(mode="json"))
        self.assertNotEqual(new.id, self.a.id)
        found = self.rt.memory.recall(new.id)
        self.assertEqual(found[0].content, "共同看过流星")
        self.assertNotEqual(found[0].id, m.id)
        self.assertEqual(found[0].shared_with, [])

    def test_real_memory_never_in_character_package(self):
        m = self.rt.memory.store(self.a.id, Candidate(content="真实也需选择", importance=0.9))
        self.rt.memory.promote(self.a.id, m.id, confirmation="用户明确确认真实并保存")
        p = export_character(self.rt, self.a.id, include_memories=True)
        self.assertTrue(all(x.kind != "real_user" for x in p.memories))
        self.assertNotIn("真实也需选择", p.model_dump_json())

    def test_export_preserves_portable_growth_summary_without_private_event(self):
        m = self.rt.memory.store(self.a.id, Candidate(content="私密事件正文", importance=0.9))
        state = self.rt.characters.state(self.a.id)
        state.evolution = [
            Evolution(
                axis="personality",
                key="patience",
                value="私密事件正文促成的变化",
                portable_summary="更有耐心",
                evidence_ids=[m.id],
                at_turn=20,
            )
        ]
        self.rt.characters.save_state(state)
        package = export_character(self.rt, self.a.id)
        self.assertEqual(package.state.evolution[0].value, "更有耐心")
        self.assertEqual(package.state.evolution[0].evidence_ids, [])
        self.assertNotIn("私密事件正文", package.model_dump_json())
        clone = import_character(self.rt, package.model_dump(mode="json"))
        self.assertEqual(self.rt.characters.state(clone.id).evolution[0].value, "更有耐心")

    def test_invalid_memory_import_is_atomic(self):
        self.rt.memory.store(self.a.id, Candidate(content="合成", importance=0.9))
        data = export_character(self.rt, self.a.id, include_memories=True).model_dump(mode="json")
        data["memories"][0]["kind"] = "real_user"
        before = len(self.rt.characters.list())
        with self.assertRaises(ValueError):
            import_character(self.rt, data)
        self.assertEqual(len(self.rt.characters.list()), before)

    def test_bad_version_and_invalid_memory_leave_no_partial_character(self):
        p = export_character(self.rt, self.a.id).model_dump(mode="json")
        before = len(self.rt.characters.list())
        p["schema_version"] = 99
        with self.assertRaises((ValueError, ValidationError)):
            import_character(self.rt, p)
        self.assertEqual(len(self.rt.characters.list()), before)

    def test_import_rejects_short_term_memory_without_bounded_expiration(self):
        from datetime import timedelta

        from character_runtime.models import now

        self.rt.memory.store(self.a.id, Candidate(content="临时合成内容", kind="short_term"))
        package = export_character(self.rt, self.a.id, include_memories=True).model_dump(
            mode="json"
        )
        for expiry in (None, (now() + timedelta(days=365)).isoformat()):
            with self.subTest(expiry=expiry):
                package["memories"][0]["expires_at"] = expiry
                before = len(self.rt.characters.list())
                with self.assertRaises(ValueError):
                    import_character(self.rt, package)
                self.assertEqual(len(self.rt.characters.list()), before)
