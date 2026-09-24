"""Deterministic local retrieval rules; scores explain ranking, never establish facts.

确定性本地检索规则；分数解释排名，不能建立事实。
"""

import re
import unicodedata
from datetime import datetime

from .models import Memory

WORDS = re.compile(r"[^\W_]+", re.UNICODE)
CJK = re.compile(r"[\u3400-\u9fff\U00020000-\U0002ffff]+")
# Small, auditable concept groups improve recall across ordinary phrasing/languages.
CONCEPTS = (
    ("sleep", "sleeping", "rest", "睡觉", "睡眠", "休息"),
    ("work", "working", "job", "工作", "上班"),
    ("read", "reading", "book", "读书", "阅读", "书籍"),
    ("travel", "trip", "旅行", "旅游"),
    ("happy", "happiness", "开心", "高兴"),
    ("sad", "sadness", "难过", "伤心"),
)


def normalize(text: str) -> str:
    """Normalize cosmetic text differences without asserting semantic equivalence.

    规范表面文本差异，不声称语义等价。
    """

    return " ".join(unicodedata.normalize("NFKC", text).casefold().split()).rstrip("。.!！?？")


def tokens(text: str, *, concepts: bool = True) -> set[str]:
    """Extract local ranking tokens; tokens do not carry authorization.

    提取本地排序词元；词元不携带授权。
    """

    text = normalize(text)
    # Chinese runs are segmented into overlapping bigrams without a dictionary dependency.
    result = set(WORDS.findall(CJK.sub(" ", text)))
    for run in CJK.findall(text):
        result.update(run[i : i + 2] for i in range(max(1, len(run) - 1)))
    if concepts:
        for index, group in enumerate(CONCEPTS):
            if any(word in result or (CJK.search(word) and word in text) for word in group):
                result.add(f"concept{index}")
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


def score(
    memory: Memory,
    query: str,
    clock: datetime,
    *,
    fts: float = 0,
    relationship: str = "",
    current_topic: str = "",
    unfinished_topics: tuple[str, ...] = (),
    active_goals: tuple[str, ...] = (),
) -> dict[str, float]:
    """Return additive score components; their sum is the final rank.

    返回可相加的评分分量；它们之和构成最终排名。
    """
    body = tokens(memory.content, concepts=False)
    expanded = tokens(memory.content)

    def overlap(text: str, *, semantic: bool = False) -> float:
        wanted = tokens(text, concepts=semantic)
        return len(wanted & (expanded if semantic else body)) / max(1, len(wanted))

    age = max(0, (clock - (memory.last_observed_at or memory.created_at)).total_seconds() / 86400)
    return {
        "lexical": 4 * overlap(query),
        "local_tokens": overlap(query, semantic=True),
        "fts": 0.5 * fts,
        "recency": 0.7 / (1 + age / 30),
        "importance": 1.2 * memory.importance,
        "confidence": 0.6 * memory.confidence,
        "relationship": 0.5 * overlap(relationship)
        + (0.3 if memory.kind == "relationship" and relationship else 0),
        "current_topic": 1.5 * overlap(current_topic),
        "unfinished_topic": max((overlap(v) for v in unfinished_topics), default=0),
        "active_goal": max((overlap(v) for v in active_goals), default=0),
        "kind": {"relationship": 0.3, "character_long_term": 0.2, "real_user": 0.2}.get(
            memory.kind, 0.1
        ),
        "provenance": {"user_explicit": 0.4, "user_material": 0.3, "simulated_life": -0.3}.get(
            memory.source, 0
        ),
        "archive": -0.5 if memory.status == "archived" else 0,
    }
