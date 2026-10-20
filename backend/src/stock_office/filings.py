"""Which filings are worth the CEO's attention (owner's request, 2026-10-20: check often, report
only what matters). Deterministic name/item rules, no AI cost; routine filings (insider holding
reports, IR notices, corrections, periodic report filings) are checked but not reported.
"""

from __future__ import annotations

# DART report names (spaces removed) → topic. Earnings, capital changes, big contracts and deals,
# control, legal and listing events.
KR_IMPORTANT: tuple[tuple[str, str], ...] = (
    ("영업(잠정)실적", "실적"),
    ("매출액또는손익구조", "실적 변동"),
    ("유상증자결정", "유상증자"),
    ("무상증자결정", "무상증자"),
    ("감자결정", "감자"),
    ("전환사채권발행결정", "전환사채"),
    ("신주인수권부사채권발행결정", "신주인수권부사채"),
    ("교환사채권발행결정", "교환사채"),
    ("자기주식취득", "자사주 취득"),
    ("자기주식처분", "자사주 처분"),
    ("주식소각결정", "주식 소각"),
    ("회사합병결정", "합병"),
    ("회사분할", "분할"),
    ("영업양수", "영업 양수"),
    ("영업양도", "영업 양도"),
    ("타법인주식및출자증권취득결정", "타법인 지분 취득"),
    ("타법인주식및출자증권처분결정", "타법인 지분 처분"),
    ("단일판매ㆍ공급계약", "대규모 공급계약"),
    ("최대주주변경", "최대주주 변경"),
    ("소송등의", "소송"),
    ("매매거래정지", "거래 정지"),
    ("관리종목", "관리종목"),
    ("상장폐지", "상장폐지"),
    ("현금ㆍ현물배당결정", "배당"),
    ("투자판단관련주요경영사항", "주요 경영사항"),
    ("풍문또는보도에대한해명", "보도 해명"),
)


def kr_topic(report_nm: str) -> str | None:
    """The topic of an important DART filing, or None (routine or a correction)."""
    name = report_nm.replace(" ", "")
    if "정정" in name.split("]")[0] and name.startswith("["):
        return None
    return next((topic for key, topic in KR_IMPORTANT if key in name), None)
