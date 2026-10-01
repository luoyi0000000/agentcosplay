"""Small shared evidence vocabulary, not a universal decision engine.
共享的小型证据词汇，不建立通用决策引擎；证据不是事实。
"""

from agentcosplay_host.expression import (
    DecisionReason as DecisionReason,
)
from pydantic import Field, JsonValue

from .models import Identifier, Model, Score


class Evidence(Model):
    """A detector observation, never an authorization. / 检测观察不授予权限。"""

    id: Identifier
    source: str
    kind: str
    confidence: Score
    details: dict[str, JsonValue] = Field(default_factory=dict)
