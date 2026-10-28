"""A1-M2 CSV 기반 규칙 검사기. YAML·Git·LLM 없이 실행한다.

python checker.py --html sample.html --rules rules.csv
"""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path
from typing import Literal

from bs4 import BeautifulSoup, Tag
from pydantic import BaseModel, ConfigDict, Field, model_validator

BASE = Path(__file__).resolve().parent
SELECTORS = {'img', 'a[href]', 'input'}
OPS = {'has_attribute', 'link_name_candidate', 'link_purpose_review',
       'field_name_candidate', 'clear_link_text', 'visible_label'}
STATUS = {'applied', 'proposed', 'retired'}
OUTCOMES = {'passed', 'failed', 'cantTell', 'inapplicable'}
EXCLUDED_INPUT_TYPES = {'hidden', 'submit', 'reset', 'button', 'image'}


class Rule(BaseModel):
    """CSV 한 행의 자료형·허용 조건을 검사한다."""
    model_config = ConfigDict(extra='forbid')
    rule_id: str = Field(pattern=r'^[A-Z]+(?:-[A-Z]+)*-\d{3}$')
    rule_version: str
    status: Literal['applied', 'proposed', 'retired']
    scope: Literal['standard', 'company']
    policy_id: str
    title: str
    selector: Literal['img', 'a[href]', 'input']
    operator: Literal['has_attribute', 'link_name_candidate', 'link_purpose_review',
                      'field_name_candidate', 'clear_link_text', 'visible_label']
    attribute: str
    values: str
    description: str
    reason: str
    limitation: str
    wcag_ref: str
    kwcag_ref: str
    reference_url: str
    effective_from: str

    @model_validator(mode='after')
    def validate_contract(self):
        allowed = {
            ('img', 'has_attribute'),
            ('a[href]', 'link_name_candidate'),
            ('a[href]', 'link_purpose_review'),
            ('a[href]', 'clear_link_text'),
            ('input', 'field_name_candidate'),
            ('input', 'visible_label'),
        }
        if (self.selector, self.operator) not in allowed:
            raise ValueError('선택자와 검사 함수의 조합을 지원하지 않습니다.')
        if self.operator == 'has_attribute' and not self.attribute:
            raise ValueError('has_attribute에는 attribute가 필요합니다.')
        if self.operator in {'link_purpose_review', 'clear_link_text'} and not self.values:
            raise ValueError('링크 검사에는 values 목록이 필요합니다.')
        if self.scope == 'company' and not self.policy_id:
            raise ValueError('사내 규칙에는 policy_id가 필요합니다.')
        if self.scope == 'standard' and not self.wcag_ref:
            raise ValueError('표준 관련 검사는 wcag_ref가 필요합니다.')
        return self

    @property
    def terms(self):
        return [v.strip() for v in self.values.split('|') if v.strip()]


def load_rules(csv_path: Path, active_only: bool = True) -> list[Rule]:
    """현재 적용된 규칙만 기본 선택한다. 모든 행은 먼저 유효성 검사한다."""
    with csv_path.open('r', encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    seen, parsed = set(), []
    for row in rows:
        rule = Rule.model_validate(row)
        if rule.rule_id in seen:
            raise ValueError(f'중복 규칙 ID: {rule.rule_id}')
        seen.add(rule.rule_id)
        parsed.append(rule)
    return [r for r in parsed if r.status == 'applied'] if active_only else parsed


def visible_label(tag: Tag, soup: BeautifulSoup) -> bool:
    parent = tag.find_parent('label')
    if parent and parent.get_text(' ', strip=True):
        return True
    ident = tag.get('id')
    return bool(ident and any(
        t.get_text(' ', strip=True) for t in soup.find_all('label', attrs={'for': ident})
    ))


def inspect_one(tag: Tag, soup: BeautifulSoup, rule: Rule) -> str:
    if rule.operator == 'has_attribute':
        return 'passed' if tag.has_attr(rule.attribute) else 'failed'
    if rule.operator == 'link_name_candidate':
        if tag.get_text(' ', strip=True) or str(tag.get('aria-label', '')).strip():
            return 'passed'
        if any(str(img.get('alt', '')).strip() for img in tag.select('img')):
            return 'passed'
        return 'cantTell' if tag.has_attr('aria-labelledby') else 'failed'
    if rule.operator == 'link_purpose_review':
        name = tag.get_text(' ', strip=True)
        if not name:
            return 'inapplicable'
        return 'cantTell' if name in rule.terms else 'passed'
    if rule.operator == 'field_name_candidate':
        if visible_label(tag, soup) or str(tag.get('aria-label', '')).strip():
            return 'passed'
        return 'cantTell' if tag.has_attr('aria-labelledby') else 'failed'
    if rule.operator == 'clear_link_text':
        name = tag.get_text(' ', strip=True)
        if not name:
            return 'inapplicable'
        return 'failed' if name in rule.terms else 'passed'
    if rule.operator == 'visible_label':
        if visible_label(tag, soup):
            return 'passed'
        return 'cantTell' if tag.has_attr('aria-labelledby') else 'failed'
    raise ValueError('허용되지 않은 operator')


def scan(html: str, rules: list[Rule]) -> list[dict]:
    soup = BeautifulSoup(html, 'html.parser')
    findings = []
    for rule in rules:
        targets = soup.select(rule.selector)
        if rule.selector == 'input':
            targets = [t for t in targets
                       if str(t.get('type', 'text')).lower() not in EXCLUDED_INPUT_TYPES]
        if not targets:
            targets = [None]  # 해당 규칙의 적용 대상 없음
        for i, tag in enumerate(targets, start=1):
            outcome = inspect_one(tag, soup, rule) if tag else 'inapplicable'
            target = (str(tag.get('data-case') or tag.get('id') or f'{tag.name}[{i}]')
                      if tag else '(대상 없음)')
            findings.append({
                'target': target, 'rule_id': rule.rule_id, 'rule_version': rule.rule_version,
                'scope': rule.scope, 'policy_id': rule.policy_id,
                'outcome': outcome, 'message': rule.description,
                'reason': rule.reason, 'reference_url': rule.reference_url,
                'limitation': rule.limitation, 'source_file': 'rules.csv',
            })
    return findings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', default='sample.html')
    ap.add_argument('--rules', default='rules.csv')
    args = ap.parse_args()
    rules = load_rules(BASE / 'data' / args.rules)
    findings = scan((BASE / 'data' / args.html).read_text(encoding='utf-8'), rules)
    (BASE / 'results.json').write_text(
        json.dumps(findings, ensure_ascii=False, indent=2), encoding='utf-8')
    for r in findings:
        print(f"{r['target']:>14} | {r['rule_id']:16} | {r['outcome']:12} | {r['scope']}")
    print(f'활성 규칙 {len(rules)}건 · 결과 {len(findings)}건 → results.json')


if __name__ == '__main__':
    main()
