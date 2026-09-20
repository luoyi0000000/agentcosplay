import unittest
from datetime import UTC, datetime, timedelta

from character_runtime.companion_models import CompanionUpdate
from character_runtime.models import CharacterDefinition, GrowthProposal
from character_runtime.runtime import Runtime
from character_runtime.scheduler import tick
from character_runtime.storage import SQLiteStorage


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.store = SQLiteStorage(":memory:")
        self.addCleanup(self.store.close)
        self.time = datetime(2026, 9, 20, 12, tzinfo=UTC)
        self.rt = Runtime(self.store, "synthetic", clock=lambda: self.time)
        self.cid = self.rt.characters.create(CharacterDefinition(name="旅人")).id
        self.rt.open_session("chat", character_id=self.cid)

    def test_companion_commit_is_atomic_idempotent_and_growth_toggle_works(self):
        change = CompanionUpdate.model_validate(
            {"mood": {"label": "happy", "intensity": 0.5, "reason": "聊天"}}
        )
        first = self.rt.commit_turn("chat", "1", [], companion=change)
        revision = self.rt.companion.get(self.cid).revision
        self.assertEqual(self.rt.commit_turn("chat", "1", [], companion=change), first)
        self.assertEqual(self.rt.companion.get(self.cid).revision, revision)
        self.rt.companion.update(
            self.cid, CompanionUpdate.model_validate({"settings": {"relationship_growth": False}})
        )
        with self.assertRaises(ValueError):
            self.rt.commit_turn("chat", "2", [], GrowthProposal(stage="acquaintance", reason="x"))
        self.assertEqual(self.rt.characters.state(self.cid).turn_count, 1)

    def test_host_and_runtime_scheduler_share_reservation_after_restart(self):
        self.rt.companion.update(
            self.cid,
            CompanionUpdate.model_validate(
                {
                    "settings": {"proactive_contact": True},
                    "topic": {"id": "book", "description": "聊读书", "priority": 1},
                }
            ),
        )
        first = tick(self.rt, [self.cid])[0]
        self.assertTrue(first["should_contact"])
        restarted = Runtime(self.store, "synthetic", clock=lambda: self.time)
        self.assertEqual(
            restarted.companion.decide(self.cid).silence_reason, "delivery_unconfirmed"
        )
        restarted.companion.ack(self.cid, first["id"], True)
        self.assertFalse(tick(restarted, [self.cid])[0]["should_contact"])

    def test_simulation_drain_rolled_back_on_interrupt_then_once(self):
        self.rt.companion.update(
            self.cid,
            CompanionUpdate.model_validate(
                {
                    "settings": {"life_simulation": True},
                    "goal": {"id": "book", "description": "读书", "simulate": True},
                }
            ),
        )
        self.time += timedelta(days=3)
        with self.assertRaises(RuntimeError), self.store.transaction():
            self.rt.advance(self.cid)
            raise RuntimeError("interrupted before commit")
        self.assertEqual(self.store.list("synthetic", "memory"), [])
        self.rt.advance(self.cid)
        self.rt.advance(self.cid)
        self.assertEqual(len(self.store.list("synthetic", "memory")), 1)
        self.assertEqual(self.store.list("synthetic", "memory")[0]["source"], "simulated_life")

    def test_optional_views_and_self_model_use_existing_records(self):
        small = self.rt.context("chat", include_companion=False, include_self_model=False)
        self.assertNotIn("companion", small)
        self.assertNotIn("self_model", small)
        full = self.rt.context("chat")
        self.assertEqual(full["self_model"]["current_mood"], "/companion/mood")
        self.assertEqual(self.store.list("synthetic", "self_model"), [])

    def test_runtime_scheduler_cli_once_reopens_pending_intent(self):
        import json
        import os
        import subprocess
        import sys
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            store = SQLiteStorage(Path(folder) / "runtime.sqlite3")
            rt = Runtime(store, "scheduler-test")
            cid = rt.characters.create(CharacterDefinition(name="合成角色")).id
            rt.companion.update(
                cid,
                CompanionUpdate.model_validate(
                    {
                        "settings": {"proactive_contact": True, "quiet_start": 0, "quiet_end": 0},
                        "topic": {"id": "read", "description": "读书", "priority": 1},
                    }
                ),
            )
            store.close()
            results = []
            for _ in range(2):
                result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "character_runtime",
                        "scheduler",
                        "--once",
                        "--character",
                        cid,
                    ],
                    env={
                        **os.environ,
                        "CHARACTER_DATA_DIR": folder,
                        "CHARACTER_OWNER": "scheduler-test",
                    },
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=10,
                )
                results.append(json.loads(result.stdout))
            self.assertTrue(results[0]["should_contact"])
            self.assertEqual(results[1]["silence_reason"], "delivery_unconfirmed")
