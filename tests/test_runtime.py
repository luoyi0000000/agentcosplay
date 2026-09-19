import tempfile
import unittest
from pathlib import Path

from character_runtime.models import CharacterDefinition, Fact
from character_runtime.runtime import Runtime
from character_runtime.storage import SQLiteStorage


class RuntimeFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = SQLiteStorage(Path(self.temp.name) / "角色 data" / "state.db")
        self.rt = Runtime(self.store, "user-a")
        self.a = self.rt.characters.create(
            CharacterDefinition(
                name="林舟", facts={"personality": Fact(value="安静", source_type="user_explicit")}
            )
        )
        self.b = self.rt.characters.create(CharacterDefinition(name="岚"))

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()


class RuntimeTests(RuntimeFixture):
    def test_priority_definition_state_separation_and_owner(self):
        with self.assertRaises(ValueError):
            self.rt.characters.update(self.a.id, facts={"personality": Fact(value="热闹")})
        with self.assertRaises(KeyError):
            Runtime(self.store, "user-b").characters.get(self.a.id)
        self.assertEqual(self.rt.characters.get(self.a.id).facts["personality"].value, "安静")
        self.assertEqual(self.rt.characters.state(self.a.id).relationship.stage, "stranger")

    def test_routing_ooc_task_restore_and_disable(self):
        self.rt.set_default(self.a.id)
        self.rt.bind_project("code", self.b.id)
        self.assertEqual(self.rt.open_session("s1").character_id, self.a.id)
        self.assertEqual(self.rt.open_session("s2", project="code").character_id, self.b.id)
        self.rt.session_control("s1", "enter_ooc")
        self.assertTrue(self.rt.context("s1")["ooc"])
        self.rt.session_control("s1", "exit_ooc")
        self.rt.session_control("s1", "start_task", mode="task_neutral")
        self.assertEqual(self.rt.context("s1")["effective_mode"], "task_neutral")
        self.rt.session_control("s1", "end_task")
        self.assertEqual(self.rt.context("s1")["effective_mode"], "soft_roleplay")
        self.rt.session_control("s1", "deactivate")
        self.assertIsNone(self.rt.open_session("s1").character_id)
        self.assertIsNone(self.rt.context("s1")["definition"])
        self.assertEqual(self.rt.context("s2")["definition"]["id"], self.b.id)

    def test_canon_override_remains_user_authored(self):
        a = self.rt.characters.update(self.a.id, mode="canon")
        a = self.rt.characters.update(
            a.id,
            facts={
                "world": Fact(
                    value="用户自定义世界", source_type="user_explicit", canon_status="user_defined"
                )
            },
        )
        self.assertEqual(a.facts["world"].canon_status, "user_defined")
        self.rt.characters.update(a.id, mode="au")
        self.assertEqual(self.rt.characters.get(a.id).mode, "au")
        self.rt.characters.update(a.id, mode="inspired")
        self.assertEqual(self.rt.characters.get(a.id).mode, "inspired")

    def test_stale_revision_rejected(self):
        self.rt.characters.update(self.a.id, name="新名", expected_revision=1)
        with self.assertRaises(ValueError):
            self.rt.characters.update(self.a.id, name="旧名", expected_revision=1)


if __name__ == "__main__":
    unittest.main()
