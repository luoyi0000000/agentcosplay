from character_runtime.growth import grow
from character_runtime.models import (
    Candidate,
    CharacterDefinition,
    CharacterState,
    Fact,
    GrowthPolicy,
    GrowthProposal,
)
from tests.test_runtime import RuntimeFixture


class GrowthTests(RuntimeFixture):
    def test_no_sudden_intimacy(self):
        self.rt.open_session("chat", character_id=self.a.id)
        evidence = self.rt.commit_turn(
            "chat", "one", [Candidate(content="相识", kind="relationship", importance=0.9)]
        )["memory_ids"]

        with self.assertRaises(ValueError):
            self.rt.commit_turn(
                "chat",
                "two",
                [],
                GrowthProposal(stage="close", evidence_ids=evidence, reason="刚见面"),
            )

        self.assertEqual(self.rt.characters.state(self.a.id).relationship.stage, "stranger")

    def test_relationship_growth_needs_three_distinct_evidence_turns(self):
        self.rt.open_session("chat", character_id=self.a.id)
        evidence_ids = []
        for turn in ("one", "two", "three"):
            result = self.rt.commit_turn(
                "chat",
                turn,
                [Candidate(content=f"关系事件 {turn}", kind="relationship", importance=0.9)],
            )
            evidence_ids.extend(result["memory_ids"])
        self.rt.commit_turn("chat", "four", [])

        result = self.rt.commit_turn(
            "chat",
            "five",
            [],
            GrowthProposal(stage="acquaintance", evidence_ids=evidence_ids, reason="三次不同互动"),
        )
        state = self.rt.characters.state(self.a.id)

        self.assertEqual(state.relationship.stage, "acquaintance")
        self.assertEqual(state.relationship_history[-1]["evidence_ids"], ",".join(evidence_ids))
        self.assertEqual(self.rt.commit_turn("chat", "five", []), result)
        self.assertEqual(self.rt.characters.state(self.a.id).turn_count, state.turn_count)

    def test_three_memories_from_one_turn_are_not_three_interactions(self):
        self.rt.open_session("chat", character_id=self.a.id)
        result = self.rt.commit_turn(
            "chat",
            "one",
            [
                Candidate(content=f"同轮事件 {number}", kind="relationship", importance=0.9)
                for number in range(3)
            ],
        )
        for turn in ("two", "three", "four"):
            self.rt.commit_turn("chat", turn, [])

        with self.assertRaises(ValueError):
            self.rt.commit_turn(
                "chat",
                "five",
                [],
                GrowthProposal(
                    stage="acquaintance",
                    evidence_ids=result["memory_ids"],
                    reason="同一轮不能冒充三轮",
                ),
            )

    def test_relationship_growth_requires_fresh_evidence_turns(self):
        self.rt.open_session("chat", character_id=self.a.id)
        first_evidence = []
        for turn in ("one", "two", "three"):
            result = self.rt.commit_turn(
                "chat",
                turn,
                [Candidate(content=f"早期事件 {turn}", kind="relationship", importance=0.9)],
            )
            first_evidence.extend(result["memory_ids"])
        self.rt.commit_turn("chat", "four", [])
        self.rt.commit_turn(
            "chat",
            "five",
            [],
            GrowthProposal(stage="acquaintance", evidence_ids=first_evidence, reason="首轮成长"),
        )

        fresh_evidence = []
        for turn in ("six", "seven", "eight"):
            result = self.rt.commit_turn(
                "chat",
                turn,
                [Candidate(content=f"新事件 {turn}", kind="relationship", importance=0.9)],
            )
            fresh_evidence.extend(result["memory_ids"])
        self.rt.commit_turn("chat", "nine", [])

        with self.assertRaises(ValueError):
            self.rt.commit_turn(
                "chat",
                "ten",
                [],
                GrowthProposal(stage="familiar", evidence_ids=first_evidence, reason="复用旧证据"),
            )
        self.rt.commit_turn(
            "chat",
            "ten",
            [],
            GrowthProposal(stage="familiar", evidence_ids=fresh_evidence, reason="新三轮互动"),
        )
        self.assertEqual(self.rt.characters.state(self.a.id).relationship.stage, "familiar")

    def test_each_growth_axis_respects_low_medium_high_intervals(self):
        intervals = {"low": 20, "medium": 5, "high": 3}
        axes = (
            ("relationship", "relationship_mutability"),
            ("personality", "personality_mutability"),
            ("world", "world_state_mutability"),
        )

        for axis, policy_field in axes:
            for level, interval in intervals.items():
                with self.subTest(axis=axis, level=level):
                    policy = GrowthPolicy.model_validate({policy_field: level})
                    definition = CharacterDefinition(name="间隔角色", growth=policy)
                    if axis == "relationship":
                        proposal = GrowthProposal(
                            stage="acquaintance",
                            evidence_ids=["one", "two", "three"],
                            reason="边界测试",
                        )
                    else:
                        proposal = GrowthProposal.model_validate(
                            {
                                axis: {"change": "新状态"},
                                "evidence_ids": ["one"],
                                "reason": "边界测试",
                            }
                        )
                    before = grow(
                        definition,
                        CharacterState(character_id=definition.id, turn_count=interval - 1),
                        proposal,
                    )
                    at_interval = grow(
                        definition,
                        CharacterState(character_id=definition.id, turn_count=interval),
                        proposal,
                    )

                    if axis == "relationship":
                        self.assertEqual(before.relationship.stage, "stranger")
                        self.assertEqual(at_interval.relationship.stage, "acquaintance")
                    else:
                        self.assertFalse(any(e.axis == axis for e in before.evolution))
                        self.assertTrue(any(e.axis == axis for e in at_interval.evolution))

    def test_rejects_nonpersistent_growth_evidence(self):
        self.rt.open_session("chat", character_id=self.a.id)
        session_memory = self.rt.memory.store(
            self.a.id,
            Candidate(content="本轮秘密", kind="session", importance=0.9),
            "chat",
            turn_id="manual-session",
        )
        short_memory = self.rt.memory.store(
            self.a.id,
            Candidate(content="短期线索", kind="short_term", importance=0.9),
            turn_id="manual-short",
        )
        source = self.rt.memory.store(
            self.a.id,
            Candidate(content="现实线索", importance=0.9),
            turn_id="manual-real",
        )
        real_memory = self.rt.memory.promote(
            self.a.id, source.id, confirmation="用户明确确认真实并保存"
        )

        for number, memory in enumerate((session_memory, short_memory, real_memory), start=1):
            with self.subTest(kind=memory.kind):
                with self.assertRaises(ValueError):
                    self.rt.commit_turn(
                        "chat",
                        f"reject-{number}",
                        [],
                        GrowthProposal(
                            personality={"mood": "变化"},
                            evidence_ids=[memory.id],
                            reason="非持久证据",
                        ),
                    )

    def test_commit_stamps_memory_with_receipt_id(self):
        self.rt.open_session("chat", character_id=self.a.id)

        result = self.rt.commit_turn(
            "chat", "one", [Candidate(content="可追踪事件", importance=0.9)]
        )
        memory = self.rt.memory.owned(self.a.id, result["memory_ids"][0])

        self.assertEqual(memory.turn_id, "4:chat:one")

    def test_automatic_evolution_cannot_shadow_any_definition_fact(self):
        character = self.rt.characters.create(
            CharacterDefinition(
                name="有设定角色",
                facts={"weather": Fact(value="晴朗", source_type="inferred")},
            )
        )
        self.rt.open_session("facts", character_id=character.id)
        evidence = self.rt.commit_turn(
            "facts", "one", [Candidate(content="天气事件", importance=0.9)]
        )["memory_ids"]

        with self.assertRaises(ValueError):
            self.rt.commit_turn(
                "facts",
                "two",
                [],
                GrowthProposal(world={"weather": "暴雨"}, evidence_ids=evidence, reason="自动覆盖"),
            )

    def test_evolution_records_portable_summary(self):
        character = self.rt.characters.create(
            CharacterDefinition(
                name="成长角色",
                growth=GrowthPolicy(personality_mutability="high"),
            )
        )
        self.rt.open_session("summary", character_id=character.id)
        evidence = self.rt.commit_turn(
            "summary", "one", [Candidate(content="完整私密事件", importance=0.9)]
        )["memory_ids"]
        self.rt.commit_turn("summary", "two", [])

        self.rt.commit_turn(
            "summary",
            "three",
            [],
            GrowthProposal(
                personality={"calm": "因完整私密事件变得平静"},
                personality_summaries={"calm": "逐渐变得平静"},
                evidence_ids=evidence,
                reason="连续互动",
            ),
        )

        evolution = self.rt.characters.state(character.id).evolution[-1]
        self.assertEqual(evolution.portable_summary, "逐渐变得平静")
