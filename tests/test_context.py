import json
import unittest

from character_runtime.models import Candidate, CharacterDefinition, Fact
from character_runtime.runtime import Runtime
from character_runtime.storage import SQLiteStorage


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.store = SQLiteStorage(":memory:")
        self.addCleanup(self.store.close)
        self.rt = Runtime(self.store, "synthetic")

    def test_connected_first_use_then_persistence(self):
        self.rt.open_session("first")
        context = self.rt.context("first")
        self.assertEqual(context["onboarding"]["status"], "choose_character")
        self.assertIn("扮演谁", context["onboarding"]["prompt"])
        character = self.rt.characters.create(CharacterDefinition(name="旅人"))
        self.rt.session_control("first", "activate", character_id=character.id)
        self.rt.commit_turn("first", "1", [Candidate(content="喜欢星空", importance=0.9)])
        other = Runtime(self.store, "synthetic")
        self.assertEqual(other.context("first")["memories"][0]["content"], "喜欢星空")

    def test_context_bounded_and_query_selective(self):
        facts = {f"fact-{i}": Fact(value="常规设定" * 600) for i in range(90)}
        facts["specific"] = Fact(value="寻找白鹿")
        facts["identity"] = Fact(value="森林守望者")
        character = self.rt.characters.create(CharacterDefinition(name="旅人", facts=facts))
        self.rt.open_session("chat", character_id=character.id)
        for i in range(30):
            self.rt.memory.store(character.id, Candidate(content=f"{i}旧事" * 500, importance=0.9))
        context = self.rt.context("chat", "白鹿")
        self.assertLess(len(json.dumps(context, ensure_ascii=False)), 35000)
        self.assertIn("specific", context["definition"]["facts"])
        self.assertIn("identity", context["definition"]["facts"])
        self.assertIn("self_model", context)
        self.assertEqual(
            self.rt.characters.get(character.id).facts["fact-0"].value, "常规设定" * 600
        )

    def test_simulated_life_cannot_become_real_or_shared_experience(self):
        character = self.rt.characters.create(CharacterDefinition(name="旅人"))
        memory = self.rt.memory.store(
            character.id,
            Candidate(content="模拟：持续阅读", source="simulated_life", importance=0.9),
        )
        with self.assertRaises(ValueError):
            self.rt.memory.promote(character.id, memory.id, confirmation="我确认并同意保存")
        with self.assertRaises(ValueError):
            self.rt.memory.store(
                character.id,
                Candidate(content="我们一起旅行", source="simulated_life", kind="shared_roleplay"),
            )

    def test_forget_erases_companion_derived_evidence(self):
        from character_runtime.companion_models import CompanionUpdate

        character = self.rt.characters.create(CharacterDefinition(name="旅人"))
        memory = self.rt.memory.store(character.id, Candidate(content="私人事件", importance=0.9))
        self.rt.companion.update(
            character.id,
            CompanionUpdate.model_validate(
                {
                    "mood": {
                        "label": "sad",
                        "intensity": 0.2,
                        "reason": "私人事件",
                        "evidence_ids": [memory.id],
                    },
                    "goal": {"id": "goal", "description": "私人事件", "evidence_ids": [memory.id]},
                }
            ),
        )
        self.rt.memory.forget(character.id, memory.id)
        state = self.rt.companion.get(character.id)
        self.assertEqual(state.mood.reason, "")
        self.assertEqual(state.goals, [])

    def test_forget_redacts_reserved_message_without_releasing_uncertain_delivery(self):
        from datetime import timedelta

        from character_runtime.companion_models import CompanionUpdate
        from character_runtime.models import now

        character = self.rt.characters.create(CharacterDefinition(name="旅人"))
        memory = self.rt.memory.store(
            character.id, Candidate(content="PRIVATE-MARKER", importance=0.9)
        )
        self.rt.companion.update(
            character.id,
            CompanionUpdate.model_validate(
                {
                    "settings": {"proactive_contact": True, "quiet_start": 0, "quiet_end": 0},
                    "goal": {
                        "id": "g",
                        "description": "PRIVATE-MARKER",
                        "importance": 1,
                        "deadline": now() + timedelta(hours=1),
                        "evidence_ids": [memory.id],
                    },
                }
            ),
        )
        decision = self.rt.companion.decide(character.id)
        self.assertTrue(decision.should_contact)
        self.rt.memory.forget(character.id, memory.id)
        state = self.rt.companion.get(character.id)
        self.assertNotIn("PRIVATE-MARKER", state.model_dump_json())
        self.assertEqual(state.pending_decision.id, decision.id)
        self.assertFalse(self.rt.companion.decide(character.id).should_contact)
