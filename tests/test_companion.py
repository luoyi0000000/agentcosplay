import unittest
from datetime import UTC, datetime, timedelta

from character_runtime.characters import Characters
from character_runtime.companion import Companion
from character_runtime.companion_models import CompanionUpdate
from character_runtime.models import CharacterDefinition
from character_runtime.storage import SQLiteStorage


class CompanionFixture(unittest.TestCase):
    def setUp(self):
        self.db = SQLiteStorage(":memory:")
        self.addCleanup(self.db.close)
        self.characters = Characters(self.db, "alice")
        self.character = self.characters.create(CharacterDefinition(name="角色"))
        self.time = datetime(2026, 9, 20, 12, tzinfo=UTC)
        self.c = Companion(self.db, "alice", self.characters, clock=lambda: self.time)
        self.cid = self.character.id

    def update(self, **data):
        return self.c.update(self.cid, CompanionUpdate.model_validate(data))


class CompanionTests(CompanionFixture):
    def test_mood_persists_decays_and_cannot_jump(self):
        result = self.update(mood={"label": "happy", "intensity": 1, "reason": "聊天"})
        self.assertLessEqual(result.mood.intensity, 0.25)
        self.assertEqual(self.c.get(self.cid).mood.label, "happy")
        self.time += timedelta(hours=12)
        self.assertLess(self.c.advance(self.cid).mood.intensity, result.mood.intensity)

    def test_goal_lifecycle_and_habits_need_distinct_days(self):
        goal = {"id": "book", "description": "读书", "activity": "reading"}
        self.update(goal=goal)
        self.update(goal={**goal, "status": "paused"})
        self.assertEqual(self.c.get(self.cid).goals[0].status, "paused")
        self.update(goal={**goal, "status": "completed", "progress": 1})
        for _ in range(3):
            self.update(habit={"id": "reading", "description": "午后阅读", "activity": "reading"})
        self.assertFalse(self.c.get(self.cid).habits[0].established)
        for _ in range(2):
            self.time += timedelta(days=1)
            self.update(habit={"id": "reading", "description": "午后阅读", "activity": "reading"})
        self.assertTrue(self.c.get(self.cid).habits[0].established)

    def test_simulation_is_low_risk_opt_in_and_thresholded(self):
        self.update(
            goal={"id": "book", "description": "读书", "activity": "reading", "simulate": True}
        )
        self.c.advance(self.cid)
        self.time += timedelta(days=2)
        self.assertEqual(self.c.advance(self.cid).life.activity, "idle")
        self.update(settings={"life_simulation": True})
        self.c.advance(self.cid)
        self.time += timedelta(days=3)
        result = self.c.advance(self.cid)
        self.assertIn(result.life.activity, ("reading", "resting", "working", "walking", "idle"))
        events = self.c.drain_simulated_memories(self.cid)
        self.assertTrue(events)
        self.assertTrue(all(item.source == "simulated_life" for item in events))
        self.assertEqual(self.c.drain_simulated_memories(self.cid), [])
        with self.assertRaises(ValueError):
            self.update(goal={"id": "bad", "description": "重大事故", "activity": "accident"})

    def test_owner_isolation_future_version_and_context_bounds(self):
        foreign = Companion(self.db, "other", Characters(self.db, "other"))
        with self.assertRaises(KeyError):
            foreign.get(self.cid)
        for i in range(8):
            self.update(goal={"id": str(i), "description": "目标" * 200})
        context = self.c.context(self.cid, "目标")
        self.assertLessEqual(len(context["goals"]), 3)
        self.assertLessEqual(len(context["goals"][0]["description"]), 240)
        raw = self.c.get(self.cid).model_dump(mode="json")
        raw["schema_version"] = 2
        self.db.put("alice", "companion", self.cid, raw)
        with self.assertRaises(ValueError):
            self.c.get(self.cid)
