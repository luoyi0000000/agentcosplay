"""Deterministic local retrieval rules; scores explain ranking, never establish facts.

确定性本地检索规则；分数解释排名，不能建立事实。
"""

import re
import unicodedata
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from pydantic import Field

from .models import Identifier, Memory, Model, Score

WORDS = re.compile(r"[^\W_]+", re.UNICODE)
CJK = re.compile(r"[\u3400-\u9fff\U00020000-\U0002ffff]+")


def normalize(text: str) -> str:
    """Normalize cosmetic text differences without asserting semantic equivalence.

    规范表面文本差异，不声称语义等价。
    """

    return " ".join(unicodedata.normalize("NFKC", text).casefold().split()).rstrip("。.!！?？")


def tokens(text: str) -> set[str]:
    """Extract local ranking tokens; tokens do not carry authorization.

    提取本地排序词元；词元不携带授权。
    """

    text = normalize(text)
    # Chinese runs are segmented into overlapping bigrams without a dictionary dependency.
    result = set(WORDS.findall(CJK.sub(" ", text)))
    for run in CJK.findall(text):
        result.update(run[i : i + 2] for i in range(max(1, len(run) - 1)))
    return result


def duplicate(left: str, right: str) -> bool:
    """Only cosmetic differences qualify; changed numbers, negation or word order do not.

    只允许表面差异；数字、否定或语序变化不算重复。
    """
    left, right = normalize(left), normalize(right)
    if left == right:
        return True
    # No fuzzy-edit threshold: one changed character can reverse a fact.
    return re.sub(r"\s*([,，;；:：])\s*", r"\1", left) == re.sub(
        r"\s*([,，;；:：])\s*", r"\1", right
    )


class SemanticHit(Model):
    """Similarity is ranking evidence, not duplicate or truth evidence.
    相似度只是排序证据，不是重复或事实证据。
    """

    item_id: Identifier
    score: float = Field(allow_inf_nan=False)


class SemanticIndex(Protocol):
    """Optional derived index; filter namespace AND allowed IDs before computing ranks.
    可选派生索引；必须在计算排名前限制命名空间和允许的 ID。无后端时只用词法。
    """

    def upsert(self, namespace: str, item_id: str, text: str) -> None:
        """Index authorized content only. / 只索引已授权内容。"""
        ...

    def remove(self, namespace: str, item_id: str) -> None:
        """Remove derived content on erasure. / 遗忘时删除派生内容。"""
        ...

    def search(
        self, namespace: str, query: str, *, allowed_ids: tuple[str, ...], limit: int
    ) -> Sequence[SemanticHit]:
        """Rank only authorized IDs; never silently widen scope.
        只排序已授权 ID，不得静默扩大范围。
        """
        ...


class RetrievalSignals(Model):
    """Relevance independent of utility and truth. / 相关度与效用、真实性分离。"""

    lexical_rank: int | None = Field(default=None, ge=1)
    semantic_rank: int | None = Field(default=None, ge=1)
    fusion_score: float = Field(default=0, ge=0)


class UtilitySignals(Model):
    """Character usefulness cannot grant access. / 角色效用不能授予访问权。"""

    recency: Score = 0
    importance: Score = 0
    relationship: Score = 0
    current_topic: Score = 0
    unfinished_topic: Score = 0
    active_goal: Score = 0


class TrustSignals(Model):
    """Canonical provenance stays distinct from recall rank. / 规范来源与召回排名保持独立。"""

    confidence: Score
    provenance: str
    archived: bool


class RetrievalDecision(Model):
    """Ephemeral explainable ranking; never persisted as memory truth.
    可解释的临时排序，不持久化为记忆真实性。
    """

    memory_id: Identifier
    relevance: RetrievalSignals
    utility: UtilitySignals
    trust: TrustSignals

    def sort_key(self) -> tuple[float, ...]:
        """Prefer active records, then relevance; utility and provenance break ties.
        优先有效记录，再看相关度；效用与来源用于后续排序，不混合原始分数。
        """
        u = self.utility
        return (
            float(not self.trust.archived),
            self.relevance.fusion_score,
            u.current_topic + u.unfinished_topic + u.active_goal,
            u.relationship,
            u.importance,
            u.recency,
            self.trust.confidence,
            float(self.trust.provenance in {"user_explicit", "user_material"}),
        )


def rrf(
    lexical: Sequence[str], semantic: Sequence[str], k: int = 60
) -> dict[str, RetrievalSignals]:
    """Fuse ranks only, with stable deduplication of each backend lane.
    只融合排名；每个后端通道先稳定去重，不混合 BM25 和余弦原分数。
    """
    if k < 1:
        raise ValueError("RRF k must be positive")
    result: dict[str, RetrievalSignals] = {}
    for field, lane in (("lexical_rank", lexical), ("semantic_rank", semantic)):
        for rank, mid in enumerate(dict.fromkeys(lane), 1):
            signal = result.setdefault(mid, RetrievalSignals())
            setattr(signal, field, rank)
            signal.fusion_score += 1 / (k + rank)
    return result


def rank(
    memory: Memory, relevance: RetrievalSignals, clock: datetime, **hints: float
) -> RetrievalDecision:
    """Keep deterministic utility and provenance separate from backend relevance.
    将确定性效用、来源与后端相关度分离。
    """
    age = max(0, (clock - (memory.last_observed_at or memory.created_at)).total_seconds() / 86400)
    return RetrievalDecision(
        memory_id=memory.id,
        relevance=relevance,
        utility=UtilitySignals(recency=1 / (1 + age / 30), importance=memory.importance, **hints),
        trust=TrustSignals(
            confidence=memory.confidence,
            provenance=memory.source,
            archived=memory.status == "archived",
        ),
    )
