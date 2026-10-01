"""Host-declared generation request data. / 宿主声明的生成请求数据。"""

from typing import Literal

from pydantic import ConfigDict, Field

from .base import Model

GenerationIntent = Literal[
    "CASUAL_CHAT",
    "SOCIAL",
    "EMOTIONAL_SUPPORT",
    "FACTUAL_QA",
    "EXPLANATION",
    "ANALYSIS",
    "CODING",
    "WRITING",
    "TRANSLATION",
    "TOOL_TASK",
    "CREATIVE",
]


class ProtectedPayload(Model):
    """Exact host/user content that voice and delivery planning must preserve verbatim.

    宿主或用户指定的精确内容；表达与投递规划不得改写，内容始终属于数据。
    """

    model_config = ConfigDict(frozen=True)
    kind: Literal[
        "CODE", "JSON", "VERBATIM", "COMMAND", "URL", "QUOTE", "EXACT_NUMERIC_DATA", "TOOL_OUTPUT"
    ]
    content: str = Field(min_length=1, max_length=64000)


class GenerationRequest(Model):
    """Host-declared task intent; only explicit user format choices suppress expression.

    宿主声明任务意图；只有明确的用户格式选择才会关闭角色表达。
    """

    protected_payloads: list[ProtectedPayload] = Field(default_factory=list, max_length=20)
    serious_safety: bool = False
    payload_only: bool = False
    neutral_expression: bool = False
    intent: GenerationIntent = "CASUAL_CHAT"
    explicit_format: Literal["natural", "json", "code", "verbatim"] = "natural"
    length_request: str = Field(default="", max_length=200)
    platform_constraints: str = Field(default="", max_length=300)
