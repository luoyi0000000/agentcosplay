"""Validate resolved expression wire data; Runtime alone resolves policy.
验证已解析的表达传输数据；只有 Runtime 解析策略。
"""

from typing import Literal, Self

from pydantic import Field, model_validator

from .base import Identifier, Model


class DecisionReason(Model):
    """Explain a decision without embedding private bodies. / 解释决策，不附带私人正文。"""

    code: Identifier
    evidence_refs: tuple[str, ...] = ()


class OwnershipPolicy(Model):
    """Exact payloads are local exceptions to generated prose ownership.
    精确载荷只是自拟自然语言归属的局部例外。
    """

    generated_natural_language: Literal["character", "neutral"] = "character"
    protected_payload: Literal["explicit_only"] = "explicit_only"


class DiscoursePlan(Model):
    """Defaults do not impose a report or forbid useful structure.
    默认不强加报告结构，也不禁止有用结构。
    """

    report_template_default: Literal[False] = False
    forced_intro: Literal[False] = False
    forced_conclusion: Literal[False] = False
    exhaustive_default: Literal[False] = False
    headings: Literal["only_if_useful"] = "only_if_useful"
    lists: Literal["only_if_useful"] = "only_if_useful"


class ExpressionPolicy(Model):
    """Validate resolved policy without deciding Runtime expression authority.
    校验已解析的策略，不在宿主决定 Runtime 表达权限。
    """

    enabled: bool
    ownership: OwnershipPolicy
    discourse: DiscoursePlan = Field(default_factory=DiscoursePlan)
    reasons: tuple[DecisionReason, ...]

    @model_validator(mode="after")
    def ownership_consistent(self) -> Self:
        """Suppressed expression cannot retain character ownership.
        被抑制的表达不能仍声明角色归属。
        """
        if self.enabled != (self.ownership.generated_natural_language == "character"):
            raise ValueError("Expression ownership differs from enabled policy")
        return self
