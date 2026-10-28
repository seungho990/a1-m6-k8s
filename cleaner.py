"""A1-M5: 원문 보존을 우선하는 최소 텍스트 전처리.

원본 rules.csv는 절대 수정하지 않는다. 정제 함수는 새 문자열만 반환한다.
WCAG 2.4.4, aria-label, COMP-LINK-001 같은 업무 식별자를 삭제하지 않는다.
"""
from __future__ import annotations
import re
import unicodedata

PREPROCESS_VERSION = "nfc-ws-v1"


def clean_text(value: str) -> str:
    """NFC 정규화, 연속 공백 정리, 양 끝 공백 제거."""
    if not isinstance(value, str):
        raise TypeError("전처리 대상은 문자열이어야 합니다.")
    normalized = unicodedata.normalize("NFC", value)
    return re.sub(r"\s+", " ", normalized).strip()


def char_ngrams(value: str, n: int = 2) -> list[str]:
    """형태소 분석을 하지 않는 최소 문자열 n-gram 시연."""
    if n < 1:
        raise ValueError("n은 1 이상이어야 합니다.")
    value = clean_text(value)
    return [value[i:i+n] for i in range(max(0, len(value)-n+1))]


def whitespace_tokens(value: str) -> list[str]:
    return clean_text(value).split()
