"""Platform-neutral semantic response and transport behavior contracts.

平台中立的语义回复与发送行为契约；不属于 VoiceProfile，不授予发送权限。
"""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .models import Identifier, Model

ResponseText = Annotated[str, Field(min_length=1, max_length=64000)]


class EndpointCapabilities(Model):
    """Trusted adapter capabilities, independent of identity and delivery authority.

    可信适配器能力；能力不等于身份，也不等于发送授权。
    """

    multiple_messages: bool = False
    typing: bool = False
    reactions: bool = False
    stickers: list[Identifier] = Field(default_factory=list, max_length=100)
    replies: bool = False
    max_text_chars: int = Field(default=64000, ge=1, le=64000)


class SemanticResponse(Model):
    """Host-model semantic units, never fragments obtained by splitting punctuation.

    宿主当前模型提供完整语义单元，绝不通过切句号获取气泡。
    """

    action: Literal["TEXT", "REPLY", "REACTION", "STICKER", "SILENCE"] = "TEXT"
    parts: list[ResponseText] = Field(default_factory=list, max_length=20)
    content: str = Field(default="", max_length=200)
    fallback_text: str = Field(default="", max_length=4000)
    reply_target: Identifier | None = None
    follow_up: ResponseText | None = None

    @model_validator(mode="after")
    def complete(self) -> Self:
        """Reject incomplete actions and oversized content without truncating it.

        拒绝不完整动作与超长回复，不截断内容以伪装成功。
        """
        if self.action in {"TEXT", "REPLY"} and not self.parts:
            raise ValueError("Text responses require semantic parts")
        if self.action in {"REACTION", "STICKER"} and (not self.content or not self.fallback_text):
            raise ValueError("Non-text responses require a content reference and text fallback")
        if len("\n\n".join(self.parts)) > 64000:
            raise ValueError("Semantic response exceeds 64000 characters")
        return self


class InteractionAction(Model):
    """One behavior step; only visible segments require durable delivery ACK.

    单个行为步骤；只有可见片段需要持久投递确认。
    """

    kind: Literal[
        "WAIT", "TYPING", "SEND_TEXT", "REPLY", "REACTION", "STICKER", "FOLLOW_UP", "SILENCE"
    ]
    content: str = Field(default="", max_length=64000)
    delay_ms: int = Field(default=0, ge=0, le=60000)
    segment_index: int | None = Field(default=None, ge=0, le=20)
    reply_target: Identifier | None = None


class InteractionPlan(Model):
    """A plan is not an event, nor proof of generation or delivery.

    计划不是事件，也不是生成或发送成功的证明。
    """

    actions: list[InteractionAction] = Field(max_length=64)
