"""Deterministic persistence gate. Host proposals cannot opt out of credential rejection."""

import re

SECRETS = re.compile(
    r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----|"
    r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,})|"
    r"\b(?:AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)|"
    r"(?:password|passwd|api[ _-]?key|access[ _-]?token|secret|authorization|cookie|密码|密钥|令牌)"
    r"\s*(?:[:=：]|是)\s*\S+|\bBearer\s+[A-Za-z0-9._~-]{8,}",
    re.IGNORECASE,
)
SENSITIVE = re.compile(
    r"(?:身份证|护照|社保号|银行卡|信用卡|家庭住址|病历|诊断|passport|social security|"
    r"home address|medical record)\s*(?:[:=：]|是)|"
    r"\b\d{3}-\d{2}-\d{4}\b|(?<!\d)\d{17}[\dXx](?!\d)",
    re.IGNORECASE,
)


def check_content(content: str, *, sensitive: bool = False, confirmed: bool = False) -> None:
    if SECRETS.search(content):
        raise ValueError("Credential-like content is not eligible for Runtime persistence")
    if (sensitive or SENSITIVE.search(content)) and not confirmed:
        raise ValueError("Sensitive personal content requires explicit storage authorization")
