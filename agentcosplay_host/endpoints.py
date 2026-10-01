"""Endpoint capability wire data; capabilities grant no authority.
端点能力传输数据；能力不授予权限。
"""

from pydantic import Field

from .base import Identifier, Model


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
