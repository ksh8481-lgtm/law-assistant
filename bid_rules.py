"""
지방자치단체 시설공사 적격심사(추정가격 300억원 미만)의 낙찰하한을 규정에서 계산한다.

「지방자치단체 입찰시 낙찰자 결정기준」 제2장의1 [별표 1]~[별표 7]은 추정가격 구간마다
  - 입찰가격 평점 = 만점 - 계수 × |90/100 - (입찰가격 - A)/(예정가격 - A)| × 100  (비율은 소수점 다섯째 자리 반올림, 최저 2점, 일정 비율 이상은 고정점수)
  - 종합평점 = 가격 외 점수(수행능력 등) + 입찰가격 평점 이 적격통과점수(100억원 미만 95점, 100억원 이상 300억원 미만 92점) 이상
을 정해 두었다. 그러므로 "낙찰하한율"은 과거 낙찰 분포에서 추정할 숫자가 아니라 이 식에서 정확히 나온다.
가격 외 점수가 만점이면 하한이 가장 낮고(법정 낙찰하한: 2억원 미만~10억원 89.745%, 10억~50억원 88.745%, 50억~100억원 87.495%, 100억~300억원 81.995%),
점수가 모자랄수록 하한이 올라간다. 비율은 (입찰가격 - A)/(예정가격 - A) 기준이라 예정가격 대비 %로 바꾸려면 A가 필요하다.
실제 낙찰 123건에서 낙찰자의 이 비율은 하위 5%가 89.745%로, 규정에서 계산한 하한과 일치했다(award_check 참고).
"""
import json
import os
from decimal import Decimal, ROUND_HALF_UP

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'award_specs', 'jibang_gongsa_floor.json')
_SPEC = None


def spec():
    global _SPEC
    if _SPEC is None:
        with open(_PATH, encoding='utf-8') as f:
            _SPEC = json.load(f)
    return _SPEC


def band_for(estimated_price):
    """추정가격(원)이 속한 구간. 300억원 이상은 이 규정의 범위 밖이므로 None."""
    est = Decimal(str(estimated_price))
    if est >= 30_000_000_000:
        return None
    for b in sorted(spec()['bands'], key=lambda x: -x['min_estimated_price']):
        if est >= b['min_estimated_price']:
            return b
    return spec()['bands'][0]


def estimated_from_base(base_amount):
    """기초금액(부가세 포함)에서 추정가격을 근사한다(추정가격 = 부가세 제외). 사용자가 추정가격을 입력하지 않았을 때만 쓴다."""
    return float(Decimal(str(base_amount)) / Decimal('1.1'))


def price_score(band, ratio):
    """입찰가격 평점. ratio = (입찰가격-A)/(예정가격-A)(반올림 전, Decimal). 예정가격 이하이면서 cap_from 이상이면 고정점수."""
    ratio = Decimal(str(ratio))
    p = band['price']
    if p['cap_from'] is not None and Decimal(str(p['cap_from'])) <= ratio <= 1:
        return Decimal(str(p['cap_score']))
    r = ratio.quantize(Decimal(1).scaleb(-spec()['rounding_digits']), rounding=ROUND_HALF_UP)
    s = Decimal(str(p['top'])) - Decimal(str(p['slope'])) * abs(Decimal(str(spec()['center'])) - r) * 100
    return max(s, Decimal(str(spec()['min_price_score'])))


def default_others(band):
    return band['others_max']


def min_ratio(band, others=None):
    """종합평점이 적격통과점수 이상이 되는 가장 낮은 (입찰가격-A)/(예정가격-A) 비율(Decimal, 소수 다섯째 자리). 가격 외 점수가 모자라 어떤 가격으로도 못 미치면 None.
    others: 내 가격 외 점수 합계(기본 = 구간의 만점)."""
    others = Decimal(str(default_others(band) if others is None else others))
    pass_score = Decimal(str(band['pass_score']))

    def ok(r):
        return others + price_score(band, r) >= pass_score

    if not ok(Decimal(1)) and not ok(Decimal(str(spec()['center']))):
        return None
    lo, hi = Decimal('0.5'), Decimal(str(spec()['center']))        # lo: 미달, hi: 통과 (평점은 90% 아래에서 비율이 오를수록 올라간다)
    if ok(lo):
        return lo
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if ok(mid) else (mid, hi)
    step = Decimal('0.00001')
    r5 = (hi * 100000).to_integral_value(rounding='ROUND_CEILING') / 100000
    while r5 > step and ok(r5 - step):                              # 이분 탐색이 경계를 조금 지나쳤으면 한 칸씩 되돌린다
        r5 -= step
    while not ok(r5):
        r5 += step
    return r5


def floor_rate_vs_plan(r_min, a_over_plan):
    """(입찰가격-A)/(예정가격-A) 하한 r_min을 예정가격 대비 낙찰하한율(%)로 바꾼다. a_over_plan = A/예정가격."""
    r, a = Decimal(str(r_min)), Decimal(str(a_over_plan))
    return float((a + r * (1 - a)) * 100)


def a_amount(record):
    """공고 기초금액 자료(조달청 응답 한 건)에서 A값(원)을 합산한다. 값이 없는 항목은 0."""
    total = 0.0
    for k in spec()['a_fields']:
        try:
            total += float(record.get(k) or 0)
        except (TypeError, ValueError):
            pass
    return total
