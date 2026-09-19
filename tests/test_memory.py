from datetime import timedelta

from character_runtime.models import Candidate, now
from tests.test_runtime import RuntimeFixture


class MemoryTests(RuntimeFixture):
    def test_isolation_shared_scope_and_session(self):
        m = self.rt.memory.store(self.a.id, Candidate(content="喜欢海风", importance=0.9))
        self.assertEqual(self.rt.memory.recall(self.b.id), [])
        with self.assertRaises(KeyError):
            self.rt.memory.modify(self.b.id, m.id, content="窥探")
        self.rt.memory.share(self.a.id, m.id, [self.b.id])
        self.assertEqual(self.rt.memory.recall(self.b.id)[0].content, "喜欢海风")
        self.rt.memory.share(self.a.id, m.id, [])
        self.assertEqual(self.rt.memory.recall(self.b.id), [])
        s = self.rt.memory.store(self.a.id, Candidate(content="本次线索", kind="session"), "s1")
        self.assertNotIn(s.id, [x.id for x in self.rt.memory.recall(self.a.id, session_id="s2")])
        self.assertIn(s.id, [x.id for x in self.rt.memory.recall(self.a.id, session_id="s1")])

    def test_promotion_requires_consent_and_no_other_write_path(self):
        m = self.rt.memory.store(self.a.id, Candidate(content="虚构海边旅行", importance=0.9))
        with self.assertRaises(ValueError):
            self.rt.memory.promote(self.a.id, m.id, confirmation="")
        with self.assertRaises(ValueError):
            self.rt.memory.store(self.a.id, Candidate(content="假现实", kind="real_user"))
        real = self.rt.memory.promote(
            self.a.id, m.id, confirmation="用户确认：这件事是真的，也保存到真实记忆"
        )
        self.assertEqual(real.kind, "real_user")
        self.assertEqual(self.rt.memory.recall(self.a.id, real=True)[0].id, real.id)
        self.assertEqual(self.rt.memory.recall(self.b.id, real=True), [])
        self.assertTrue(all(x.kind != "real_user" for x in self.rt.memory.recall(self.a.id)))
        self.assertEqual(self.rt.memory.recall(self.a.id), [])
        self.assertEqual(
            self.rt.memory.promote(self.a.id, m.id, confirmation="重复确认").id, real.id
        )
        self.rt.memory.forget(self.a.id, real.id)
        self.assertEqual(self.rt.memory.recall(self.a.id, real=True), [])
        self.assertEqual(self.rt.memory.owned(self.a.id, real.id).kind, "real_user")
        self.assertEqual(self.rt.memory.owned(self.a.id, m.id).content, "")

    def test_shared_roleplay_category_does_not_grant_access(self):
        m = self.rt.memory.store(
            self.a.id, Candidate(content="合成共同世界", kind="shared_roleplay", importance=0.9)
        )
        self.assertEqual(m.kind, "shared_roleplay")
        self.assertEqual(self.rt.memory.recall(self.b.id), [])

    def test_expiry_and_forget_remove_body(self):
        m = self.rt.memory.store(self.a.id, Candidate(content="合成秘密", importance=0.9))
        self.rt.memory.modify(self.a.id, m.id, expires_at=now() - timedelta(seconds=1))
        self.assertEqual(self.rt.memory.recall(self.a.id), [])
        self.rt.memory.forget(self.a.id, m.id)
        raw = self.store.get("user-a", "memory", m.id)
        self.assertEqual(raw["status"], "forgotten")
        self.assertEqual(raw["content"], "")
        self.assertEqual(raw["source"], "")
        with self.assertRaises(ValueError):
            self.rt.memory.modify(self.a.id, m.id, content="不许复活")

    def test_automatic_memory_low_importance_and_restart(self):
        self.rt.open_session("chat", character_id=self.a.id)
        result = self.rt.commit_turn(
            "chat",
            "turn-1",
            [
                Candidate(content="随口一句", importance=0.1, confidence=0.3),
                Candidate(content="以后请叫我旅人", importance=0.9, confidence=0.95),
            ],
        )
        self.assertEqual(len(result["memory_ids"]), 1)
        again = self.rt.commit_turn("chat", "turn-1", [Candidate(content="重复")])
        self.assertEqual(again, result)
        self.rt.open_session("next", character_id=self.a.id)
        self.assertEqual(self.rt.context("next")["memories"][0]["content"], "以后请叫我旅人")

    def test_turn_commit_is_atomic(self):
        self.rt.open_session("chat", character_id=self.a.id)
        with self.assertRaises(ValueError):
            self.rt.commit_turn(
                "chat",
                "bad",
                [
                    Candidate(content="不能半写入", importance=0.9),
                    Candidate(content="不合法", kind="real_user"),
                ],
            )
        self.assertEqual(self.rt.memory.recall(self.a.id), [])

    def test_maximum_length_session_can_commit_memory(self):
        session_id = "s" * 200
        self.rt.open_session(session_id, character_id=self.a.id)
        result = self.rt.commit_turn(
            session_id, "t" * 100, [Candidate(content="边界", importance=0.9)]
        )
        self.assertEqual(len(result["memory_ids"]), 1)

    def test_expired_memory_can_be_explicitly_renewed_after_recall(self):
        m = self.rt.memory.store(self.a.id, Candidate(content="可续期的合成记忆", importance=0.9))
        self.rt.memory.modify(self.a.id, m.id, expires_at=now() - timedelta(seconds=1))
        self.assertEqual(self.rt.memory.recall(self.a.id), [])
        renewed = self.rt.memory.modify(self.a.id, m.id, expires_at=now() + timedelta(days=1))
        self.assertEqual(renewed.status, "active")
        self.assertEqual([x.id for x in self.rt.memory.recall(self.a.id)], [m.id])

    def test_correction_invalidates_old_derived_details_and_turn_evidence(self):
        from character_runtime.models import GrowthPolicy, GrowthProposal

        self.rt.characters.update(self.a.id, growth=GrowthPolicy(personality_mutability="high"))
        self.rt.open_session("correction", character_id=self.a.id)
        m_id = self.rt.commit_turn(
            "correction", "one", [Candidate(content="错误的合成事件", importance=0.9)]
        )["memory_ids"][0]
        self.rt.commit_turn("correction", "two", [])
        self.rt.commit_turn(
            "correction",
            "three",
            [],
            GrowthProposal(
                personality={"patience": "因错误的合成事件变得耐心"},
                personality_summaries={"patience": "耐心"},
                evidence_ids=[m_id],
                reason="测试",
            ),
        )
        self.rt.memory.modify(self.a.id, m_id, content="更正后的合成事件")
        self.assertEqual(self.rt.context("correction")["state"]["evolution"], [])
        self.assertIsNone(self.rt.memory.owned(self.a.id, m_id).turn_id)
