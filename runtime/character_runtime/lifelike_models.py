"""Portable affect, attention, perception and platform-neutral interaction contracts.

可迁移情绪、注意、感知及平台无关互动契约。
"""

from typing import Literal

from pydantic import AwareDatetime, Field

from .models import Identifier, Model, Score, Text, new_id, now


class AffectEffect(Model):
    """Evidence-gated mutation input, never a second persisted emotional state.

    经证据门验证的变化输入，不是第二份持久情绪状态。
    """

    valence: float = Field(default=0, ge=-0.25, le=0.25)
    arousal: float = Field(default=0, ge=-0.25, le=0.25)
    vulnerability: float = Field(default=0, ge=-0.25, le=0.25)
    confidence: float = Field(default=0, ge=-0.25, le=0.25)
    tags: list[Text] = Field(default_factory=list, max_length=5)
    evidence_refs: list[Identifier] = Field(min_length=1, max_length=10)


class AffectState(Model):
    """The only current emotional authority within its authorized scope.

    已授权作用域内唯一的当前情绪权威；旧 Mood 不能覆盖它。
    """

    valence: float = Field(default=0, ge=-1, le=1)
    arousal: Score = 0.3
    vulnerability: Score = 0.2
    confidence: Score = 0.5
    tags: list[Text] = Field(default_factory=list, max_length=5)
    updated_at: AwareDatetime = Field(default_factory=now)
    influenced_at: AwareDatetime | None = None
    evidence_refs: list[Identifier] = Field(default_factory=list, max_length=100)


class LifelikeState(Model):
    """Keep canonical AffectState and optional simulated bodily axes for one scoped character.

    保存当前作用域角色的规范 AffectState 与可选模拟身体维度。
    """

    character_id: Identifier
    affect: AffectState = Field(default_factory=AffectState)
    fatigue: Score = 0
    hunger: Score = 0
    discomfort: Score = 0
    social_capacity: Score = 1
    custom_axes: dict[str, Score] = Field(default_factory=dict, max_length=10)
    updated_at: AwareDatetime = Field(default_factory=now)


class VisualPrototype(Model):
    """Represent a sourced visual description, not identity or lived-event evidence.

    表示有来源的视觉描述，不作为身份或亲历事件证据。
    """

    id: Identifier = Field(default_factory=new_id)
    character_id: Identifier
    source_ref: str = Field(min_length=1, max_length=1000)
    view_tags: list[Text] = Field(default_factory=list, max_length=8)
    style_tags: list[Text] = Field(default_factory=list, max_length=8)
    canonical_traits: list[Text] = Field(default_factory=list, max_length=20)
    confidence: Score = 0.5
    evidence_refs: list[Identifier] = Field(min_length=1, max_length=10)
    authority: Literal["USER_EXPLICIT", "HOST_OBSERVED"] = "HOST_OBSERVED"
    status: Literal["candidate", "trusted", "rejected"] = "candidate"
    created_at: AwareDatetime = Field(default_factory=now)


class PerceptionObservation(Model):
    """Keep bounded media perception with source evidence and expiration.

    保存带来源证据及有效期的有界媒体感知。
    """

    id: Identifier = Field(default_factory=new_id)
    character_id: Identifier
    source: Literal["MEDIA"] = "MEDIA"
    description: Text
    evidence_refs: list[Identifier] = Field(min_length=1, max_length=10)
    recognized: Literal["SELF", "OTHER", "UNKNOWN"] = "UNKNOWN"
    prototype_id: Identifier | None = None
    entity_label: str = Field(default="", max_length=200)
    confidence: Score = 0.5
    observed_at: AwareDatetime = Field(default_factory=now)
    expires_at: AwareDatetime


Interaction = Literal[
    "TEXT",
    "REPLY",
    "REACTION",
    "STICKER",
    "IMAGE_OR_MEME",
    "POKE_OR_LIGHT_PING",
    "TYPING",
    "READ_RECEIPT",
    "SILENCE",
]
Purpose = Literal[
    "AFFECTION", "TEASE", "ACKNOWLEDGE", "COMFORT", "CELEBRATE", "CURIOSITY", "SURPRISE", "REMINDER"
]


class InteractionRequest(Model):
    """Describe preferred behavior and capabilities without granting delivery authority.

    描述偏好行为及能力，不授予投递权限。
    """

    preferred: Interaction = "TEXT"
    purpose: Purpose = "ACKNOWLEDGE"
    capabilities: list[Interaction] = Field(default=["TEXT"], max_length=9)
