"""Resolved voice wire data, never Character storage. / 已解析声音传输数据，不保存角色状态。"""

from typing import Annotated, Literal

from pydantic import Field

from .base import Model, Text


class DialogueExample(Model):
    """A curated meaning-to-expression example; assistant history is never baseline authority.

    精选的语义到人物表达示范；助手历史输出绝不自动成为基线权威。
    """

    meaning: Annotated[str, Field(min_length=1, max_length=500)]
    character: Annotated[str, Field(min_length=1, max_length=1000)]


class CatchphraseRule(Model):
    """Optional suitability and repetition limits, never mandatory text insertion.

    可选适用场景与重复限制，绝不代表必须插入某个口头禅。
    """

    phrase: Annotated[str, Field(min_length=1, max_length=80)]
    usage: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        default_factory=list, max_length=6
    )
    intensity: Literal["light", "normal", "emphatic"] = "light"
    cooldown_seconds: int = Field(default=120, ge=0, le=86400)
    avoid_contexts: list[Annotated[str, Field(min_length=1, max_length=40)]] = Field(
        default_factory=lambda: [
            "CODE",
            "JSON",
            "VERBATIM",
            "COMMAND",
            "FORMAL_QUOTE",
            "SERIOUS_SAFETY",
        ],
        max_length=12,
    )


class VoiceProfile(Model):
    """One portable voice model for conversation and professional tasks alike.

    闲聊与专业任务共用同一可迁移表达模型，不建立第二套任务人格。
    """

    preferred_vocabulary: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        default_factory=list, max_length=8
    )
    avoided_vocabulary: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        default_factory=list, max_length=8
    )
    sentence_rhythm: str = Field(default="natural varied rhythm", max_length=300)
    explanation_style: str = Field(
        default="character-appropriate, clear causal reasoning", max_length=300
    )
    analogy_style: str = Field(default="only when useful", max_length=300)
    evaluation_style: str = Field(default="direct with factual conditions intact", max_length=300)
    disagreement_style: str = Field(default="state the reason respectfully", max_length=300)
    question_style: str = Field(default="ask only useful follow-up questions", max_length=300)
    verbosity_default: Literal["brief", "balanced", "detailed"] = "balanced"
    sentence_length: Literal["short", "varied", "long"] = "varied"
    directness: Literal["gentle", "direct", "blunt"] = "direct"
    addressing_style: str = Field(default="natural", max_length=300)
    self_reference_style: str = Field(default="natural", max_length=300)
    humor_style: str = Field(default="character-appropriate", max_length=300)
    emotional_expressiveness: Literal["reserved", "balanced", "expressive"] = "balanced"
    catchphrase_rules: list[CatchphraseRule] = Field(default_factory=list, max_length=8)
    catchphrases: list[Text] = Field(default_factory=list, max_length=8)
    stage_direction_policy: Literal["none", "occasional", "expressive"] = "occasional"
    repetition_tolerance: Literal["low", "normal"] = "low"
    preferred_patterns: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        default_factory=list, max_length=8
    )
    avoided_patterns: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        default_factory=list, max_length=8
    )
    dialogue_examples: list[Text | DialogueExample] = Field(default_factory=list, max_length=10)
