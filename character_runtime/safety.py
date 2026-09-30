"""Contextual risk evidence and typed persistence policy; detector hits are not facts.
上下文风险证据与类型化持久化策略；检测命中不等于事实，也不授予写入权限。
"""

import hashlib
import re
from typing import Literal, Protocol

from pydantic import Field

from .models import Identifier, Model, Score
from .policy_models import DecisionReason, Evidence


class SensitivityAssessment(Model):
    """Independent risk axes; none claims that a detected value is genuine.
    独立风险维度；不声称检测值一定是真实凭据或真人信息。
    """

    private: Score = 0
    person_linkable: Score = 0
    authentication: Score = 0
    financial: Score = 0
    health: Score = 0
    precise_location: Score = 0
    contact: Score = 0
    confidence: Score = 0

    @property
    def sensitive(self) -> bool:
        """Risk threshold is a policy input, not a real-world identity claim.

        风险阈值用于策略，不声称识别了真实身份。
        """
        return (
            max(
                self.private,
                self.person_linkable,
                self.financial,
                self.health,
                self.precise_location,
                self.contact,
            )
            >= 0.7
        )


class SafetyContext(Model):
    """Trusted operation context, not model-granted storage permission.
    可信操作上下文，不是模型自行授予的存储权限。
    """

    operation_id: Identifier = "default"
    purpose: Literal[
        "general", "authentication", "financial", "health", "precise_location", "contact"
    ] = "general"
    provenance: str = "unknown"
    declared_sensitive: bool = False


class SensitiveSpan(Model):
    """Record offsets and evidence, never private matched text.
    只记录偏移及证据，不复制私人命中文本。
    """

    start: int = Field(ge=0)
    end: int = Field(ge=0)
    assessment: SensitivityAssessment
    evidence: tuple[Evidence, ...]


class StorageAuthorization(Model):
    """Approval is bound to exact content and operation; never a reusable blanket bool.
    批准绑定精确正文和操作，不是可重复使用的无限制布尔许可。
    """

    explicit: bool
    scope: Literal["this_span", "this_memory", "this_operation"] = "this_memory"
    operation_id: Identifier
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    span_start: int | None = Field(default=None, ge=0)
    span_end: int | None = Field(default=None, ge=0)

    @classmethod
    def for_content(
        cls, content: str, operation_id: str, *, explicit: bool
    ) -> "StorageAuthorization":
        """Bind an already-authorized user action; callers must verify OOC/authority first.
        绑定已经授权的用户操作；调用方必须先验证 OOC 与权限。
        """
        return cls(
            explicit=explicit,
            operation_id=operation_id,
            content_sha256=hashlib.sha256(content.encode()).hexdigest(),
        )

    def permits(self, content: str, context: SafetyContext) -> bool:
        """Check exact binding; span approval never authorizes its surrounding text.
        验证精确绑定；局部片段批准不能授权周围正文。
        """
        return (
            self.explicit
            and self.operation_id == context.operation_id
            and self.content_sha256 == hashlib.sha256(content.encode()).hexdigest()
            and (
                self.scope != "this_span"
                or (self.span_start == 0 and self.span_end == len(content))
            )
        )


class SafetyDecision(Model):
    """Ephemeral policy result with auditable reasons and no plaintext echo.
    可审计的临时策略结果，不回显私人正文。
    """

    action: Literal["allow", "require_confirmation", "reject"]
    assessment: SensitivityAssessment
    reasons: tuple[DecisionReason, ...]
    evidence: tuple[Evidence, ...] = ()
    authorization: StorageAuthorization | None = None


class SensitivityClassifier(Protocol):
    """Optional trusted local/Host assessor; a score cannot lower deterministic risk.
    可选可信本地或宿主评估器；评分不能降低已发现的确定性风险。
    """

    def assess(self, text: str, context: SafetyContext) -> SensitivityAssessment:
        """Assess content function without assuming country-specific formats.
        根据正文功能评估，不假定国家或固定标识符格式。
        """
        ...


_LEGACY_CREDENTIAL = re.compile(
    r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----|"
    r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,})|"
    r"\b(?:AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)|"
    r"(?:password|passwd|api[ _-]?key|access[ _-]?token|secret|authorization|cookie|密码|密钥|令牌)"
    r"\s*(?:[:=：]|是)\s*\S+|\bBearer\s+[A-Za-z0-9._~-]{8,}",
    re.IGNORECASE,
)
_LEGACY_PRIVATE = re.compile(
    r"(?:身份证|护照|社保号|银行卡|信用卡|家庭住址|病历|诊断|passport|social security|"
    r"home address|medical record)\s*(?:[:=：]|是)|"
    # Exclude embedded identifier fragments without requiring spaces in Chinese prose.
    # 排除标识符内部的数字片段，同时不要求中文正文在号码两侧添加空格。
    r"\b\d{3}-\d{2}-\d{4}\b|(?<![A-Za-z0-9_])\d{17}[\dXx](?![A-Za-z0-9_])",
    re.IGNORECASE,
)


def detect(content: str) -> tuple[SensitiveSpan, ...]:
    """Legacy signatures remain conservative evidence during migration, not semantic truth.
    迁移期间保留旧签名作为保守证据，不将格式识别当成语义事实。
    """
    spans = []
    for pattern, kind, risk in (
        (
            _LEGACY_CREDENTIAL,
            "CREDENTIAL_SIGNATURE",
            SensitivityAssessment(authentication=0.99, confidence=0.8),
        ),
        (
            _LEGACY_PRIVATE,
            "LEGACY_PRIVATE_PATTERN",
            SensitivityAssessment(private=0.8, person_linkable=0.7, confidence=0.5),
        ),
    ):
        for match in pattern.finditer(content):
            evidence = Evidence(
                id=f"{kind}-{match.start()}",
                source="structural_detector",
                kind=kind,
                confidence=risk.confidence,
            )
            spans.append(
                SensitiveSpan(
                    start=match.start(), end=match.end(), assessment=risk, evidence=(evidence,)
                )
            )
    # Luhn is a checksum signal only: numbers without personal context remain processable.
    # Luhn 仅是校验和信号：没有个人上下文的数字仍可处理。
    for match in re.finditer(r"(?<![0-9])(?:[0-9][ -]?){12,19}(?![0-9])", content):
        digits = [int(c) for c in match.group() if c.isdecimal()]
        total = sum(
            (n * 2 - 9 if n * 2 > 9 else n * 2) if i % 2 else n
            for i, n in enumerate(reversed(digits))
        )
        if len(digits) >= 12 and total % 10 == 0:
            evidence = Evidence(
                id=f"checksum-{match.start()}", source="luhn", kind="VALID_CHECKSUM", confidence=0.5
            )
            spans.append(
                SensitiveSpan(
                    start=match.start(),
                    end=match.end(),
                    assessment=SensitivityAssessment(financial=0.4, confidence=0.5),
                    evidence=(evidence,),
                )
            )
    return tuple(spans)


class PersistenceSafetyPolicy:
    """Decide storage from merged risk; confirmation never overrides authentication risk.
    根据合并风险决定存储；确认不能覆盖凭据风险。
    """

    @staticmethod
    def decide(
        content: str,
        context: SafetyContext,
        assessment: SensitivityAssessment,
        evidence: tuple[Evidence, ...],
        authorization: StorageAuthorization | None,
    ) -> SafetyDecision:
        """Return a machine-readable decision without disclosing private values.
        返回机器可读决策，不暴露私人值。
        """
        action: Literal["allow", "require_confirmation", "reject"]
        refs = tuple(e.id for e in evidence)
        if assessment.authentication >= 0.9:
            action, code = "reject", "HIGH_AUTHENTICATION_RISK"
        elif assessment.sensitive:
            if authorization is not None and authorization.permits(content, context):
                action, code = "allow", "SCOPED_STORAGE_AUTHORIZATION"
            else:
                action, code = "require_confirmation", "PRIVATE_STORAGE_CONFIRMATION_REQUIRED"
        else:
            action, code = "allow", "NO_HIGH_RISK_EVIDENCE"
        return SafetyDecision(
            action=action,
            assessment=assessment,
            reasons=(DecisionReason(code=code, evidence_refs=refs),),
            evidence=evidence,
            authorization=authorization
            if authorization is not None and authorization.permits(content, context)
            else None,
        )


def assess_content(
    content: str,
    *,
    context: SafetyContext | None = None,
    authorization: StorageAuthorization | None = None,
    classifier: SensitivityClassifier | None = None,
) -> SafetyDecision:
    """Merge trusted context, optional semantic assessment and structural evidence.
    合并可信上下文、可选语义评估与结构证据；分类器不授予权限或降低已有风险。
    """
    context = context or SafetyContext()
    scores = {key: 0.0 for key in SensitivityAssessment.model_fields}
    evidence = []
    if context.declared_sensitive:
        scores.update(private=1, person_linkable=1, confidence=1)
        evidence.append(
            Evidence(
                id="declared-sensitive",
                source=context.provenance,
                kind="DECLARED_SENSITIVITY",
                confidence=1,
            )
        )
    if context.purpose != "general":
        scores[context.purpose] = 1
        scores["confidence"] = 1
        evidence.append(
            Evidence(
                id="context-purpose",
                source=context.provenance,
                kind="TRUSTED_CONTENT_FUNCTION",
                confidence=1,
            )
        )
    if classifier is not None:
        try:
            assessed = SensitivityAssessment.model_validate(
                classifier.assess(content, context).model_dump()
            )
        except Exception:
            # Fail closed without echoing provider diagnostics or private input.
            # 失败时拒绝写入，不回显分类器诊断或私人正文。
            raise ValueError("Sensitivity classifier unavailable; persistence denied") from None
        scores = {k: max(v, getattr(assessed, k)) for k, v in scores.items()}
        evidence.append(
            Evidence(
                id="semantic-risk",
                source="trusted_classifier",
                kind="SEMANTIC_ASSESSMENT",
                confidence=assessed.confidence,
            )
        )
    if (
        context.provenance == "USER_DIRECT"
        and max(
            scores[axis]
            for axis in ("private", "financial", "health", "precise_location", "contact")
        )
        >= 0.7
    ):
        scores["person_linkable"] = max(scores["person_linkable"], 0.9)
        evidence.append(
            Evidence(
                id="direct-personal-context",
                source="USER_DIRECT",
                kind="PERSON_LINKABLE_CONTEXT",
                confidence=0.9,
            )
        )
    for span in detect(content):
        scores = {k: max(v, getattr(span.assessment, k)) for k, v in scores.items()}
        evidence.extend(span.evidence)
    return PersistenceSafetyPolicy.decide(
        content, context, SensitivityAssessment(**scores), tuple(evidence), authorization
    )


def check_content(
    content: str,
    *,
    sensitive: bool = False,
    context: SafetyContext | None = None,
    authorization: StorageAuthorization | None = None,
    classifier: SensitivityClassifier | None = None,
) -> SafetyDecision:
    """Enforce a typed decision; credentials remain rejected even with approval.
    执行类型化决策；即使已批准，凭据风险仍然拒绝。
    """
    context = context or SafetyContext()
    if sensitive:
        context = context.model_copy(update={"declared_sensitive": True})
    decision = assess_content(
        content, context=context, authorization=authorization, classifier=classifier
    )
    if decision.action == "reject":
        raise ValueError("Credential-like content is not eligible for Runtime persistence")
    if decision.action == "require_confirmation":
        raise ValueError("Sensitive personal content requires explicit storage authorization")
    return decision
