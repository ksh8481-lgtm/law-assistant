"""
pq_safe(경상남도 정밀안전점검·진단사업자 사업수행능력 평가) 검증 스크립트. `python test_pq_safe.py`로 실행한다.
기대값은 [별표 3]의 구간표를 손으로 계산한 값이다.
"""
import sys

import pq_engine as E

SPEC = 'gyeongnam_safe'
PROJECT = {
    'specialty': '교량 및 터널', 'overlap_target': '분야별 책임기술인',
    'fields': [{'name': '조사 및 시험', 'pct': 50}, {'name': '분석 및 평가', 'pct': 50}],
}

FIRM = {
    'sim_cnt': 9, 'sim_amt': 5,
    'bad_cnt': 1, 'very_bad_cnt': 1, 'firm_stop_months': 0.5, 'tech_stop_months': 2,
    'credit_type': '회사채', 'credit_rating': 'BBB0',
    'invest_amount': 2.4, 'sales_amount': 100,
    'new_hire_rate': 1.5,
    'dev_items': [{'type': '건설신기술'}, {'type': '특허', 'age_years': 7, 'applicants': 2}],
    'use_items': [{'type': '건설신기술', 'use_count': 2, 'use_amount': 10},
                  {'type': '특허', 'use_count': 1, 'age_years': 12}],
}

PERSONS = {
    # 책임기술인: 고시 예시(해당 6건 + 전문분야 외 9건 → 6 + 7.9 = 13.9건 → 90%)
    'lead': {'career': 9.5, 'cnt': 6, 'cnt_other': 9, 'amt': 6.5, 'overlap': 13, 'transfer': '3개월 미만'},
    'fl': {
        '조사 및 시험': {'grade': '특급', 'career': 6.5, 'cnt': 9, 'amt': 4.5, 'overlap': 20},
        '분석 및 평가': {'grade': '중급', 'career': 7, 'cnt': 11, 'cnt_other': 3, 'amt': 3, 'overlap': 10, 'transfer': '3개월 이상 6개월 미만'},
    },
    'fm': {
        '조사 및 시험': {'grade': '고급', 'career': 4.5, 'cnt': 7},
        '분석 및 평가': {'grade': '초급', 'career': 2, 'cnt': 1},
    },
    'team': {'excellent': True},
}

failures = []


def check(label, got, want, tol=1e-9):
    ok = abs(got - want) <= tol if isinstance(want, (int, float)) and not isinstance(want, bool) else got == want
    if not ok:
        failures.append(f'{label}: 기대 {want} / 실제 {got}')
    print(('OK  ' if ok else 'FAIL'), label, got)


def by_id(res, iid):
    return next(i for i in res['items'] if i['id'] == iid)


def bidder(**kw):
    b = {'name': 'A사', 'firm': dict(FIRM), 'persons': PERSONS}
    b.update(kw)
    return b


def test_full_bidder():
    out = E.evaluate(SPEC, PROJECT, [bidder()])
    r = out['results'][0]
    expected = {
        'lead.career': 6.48, 'lead.cnt': 4.5, 'lead.amt': 4.5,
        'fl.grade': 1.8, 'fl.career': 5.55, 'fl.cnt': 4.75, 'fl.amt': 3.75,
        'fm.grade': 1.8, 'fm.career': 2.4, 'fm.cnt': 3.0,
        'sim.cnt': 10.8, 'sim.amt': 9.1,
        'credit.result': 2.8, 'credit.stop': 2.4, 'credit.finance': 2.7,
        'tech.dev': 0.62, 'tech.use': 0.81, 'tech.invest': 6.4,
        'ovl.lead': 5.4, 'ovl.field': 3.4,
    }
    for iid, want in expected.items():
        check(f'항목 {iid}', by_id(r, iid)['score'], want)
    check('그룹 A', r['group_scores']['A'], 38.53)
    check('그룹 B', r['group_scores']['B'], 19.9)
    check('그룹 C', r['group_scores']['C'], 7.9)
    check('그룹 D', r['group_scores']['D'], 7.83)
    check('그룹 E', r['group_scores']['E'], 8.8)
    check('소계', r['base_total'], 82.96)
    check('가점(신규고용 0.1 + 우수기관 0.5)', r['bonus']['score'], 0.6)
    check('합계', r['total'], 83.56)
    check('배점 합계', out['total_max'], 100)
    check('경고 없음', len(out['warnings']), 0)


def test_other_field_cap_example():
    # 고시 예시: 해당 6건 + 전문분야 외 9건 → 6 + 7.9 = 13.9건 → 12건 이상 14건 미만 → 4.5점
    r = E.evaluate(SPEC, PROJECT, [bidder()])['results'][0]
    assert '13.9건' in by_id(r, 'lead.cnt')['basis'], by_id(r, 'lead.cnt')['basis']
    print('OK   전문분야 외 60% 한도 예시(13.9건)')
    check('예시 점수 4.5', by_id(r, 'lead.cnt')['score'], 4.5)
    # 전문분야 외 7건(한도 미만)은 그대로 인정: 6 + 7 = 13 → 90%
    p = {**PERSONS, 'lead': {**PERSONS['lead'], 'cnt_other': 7}}
    r = E.evaluate(SPEC, PROJECT, [bidder(persons=p)])['results'][0]
    assert '13건' in by_id(r, 'lead.cnt')['basis']
    check('전문분야 외 7건은 전부 인정(13건 → 4.5점)', by_id(r, 'lead.cnt')['score'], 4.5)


def test_building_no_other():
    out = E.evaluate(SPEC, dict(PROJECT, specialty='건축'), [bidder()])
    r = out['results'][0]
    # 건축: 해당 6건만 → 6건 미만 8건 이상? 6건은 8건 미만 → 60% → 3.0
    check('건축분야는 전문분야 외 실적 불인정(6건 → 3.0점)', by_id(r, 'lead.cnt')['score'], 3.0)
    assert any('건축분야는 해당 전문분야 외' in w for w in out['warnings']), out['warnings']
    print('OK   건축분야 전문분야 외 불인정 경고')


def test_lead_tables():
    for yrs, want in ((10, 8.0), (9.9, 7.2), (9, 7.2), (8.9, 6.4), (7, 5.6), (6.9, 4.8)):
        p = {**PERSONS, 'lead': {**PERSONS['lead'], 'career': yrs, 'transfer': None}}
        r = E.evaluate(SPEC, PROJECT, [bidder(persons=p)])['results'][0]
        check(f'책임 경력 {yrs}년', by_id(r, 'lead.career')['score'], want)
    for cnt, want in ((14, 5.0), (12, 4.5), (10, 4.0), (8, 3.5), (7.9, 3.0)):
        p = {**PERSONS, 'lead': {**PERSONS['lead'], 'cnt': cnt, 'cnt_other': 0}}
        r = E.evaluate(SPEC, PROJECT, [bidder(persons=p)])['results'][0]
        check(f'책임 실적 {cnt}건', by_id(r, 'lead.cnt')['score'], want)
    for amt, want in ((7, 5.0), (6, 4.5), (5, 4.0), (4, 3.5), (3.9, 3.0)):
        p = {**PERSONS, 'lead': {**PERSONS['lead'], 'amt': amt}}
        r = E.evaluate(SPEC, PROJECT, [bidder(persons=p)])['results'][0]
        check(f'책임 실적 {amt}억', by_id(r, 'lead.amt')['score'], want)


def test_transfer_applies_to_career_only():
    for tr, ex, f in (('3개월 미만', False, 0.90), ('3개월 이상 6개월 미만', False, 0.95), ('6개월 이상', False, 1.0), ('3개월 미만', True, 1.0)):
        p = {**PERSONS, 'lead': {**PERSONS['lead'], 'career': 10, 'transfer': tr, 'transfer_exempt': ex}}
        r = E.evaluate(SPEC, PROJECT, [bidder(persons=p)])['results'][0]
        check(f'이적 {tr}{"(예외)" if ex else ""} → 경력 8×{f}', by_id(r, 'lead.career')['score'], round(8 * f, 2))
        check('실적은 이적계수 영향 없음', by_id(r, 'lead.cnt')['score'], 4.5)


def test_grade_tables():
    for g, want in (('특급', 2.0), ('고급', 1.8), ('중급', 1.6)):
        p = {**PERSONS, 'fl': {k: {**v, 'grade': g} for k, v in PERSONS['fl'].items()}}
        r = E.evaluate(SPEC, PROJECT, [bidder(persons=p)])['results'][0]
        check(f'분야별 책임 등급 {g}', by_id(r, 'fl.grade')['score'], want)
    p = {**PERSONS, 'fl': {k: {**v, 'grade': '초급'} for k, v in PERSONS['fl'].items()}}
    out = E.evaluate(SPEC, PROJECT, [bidder(persons=p)])
    check('분야별 책임기술인 초급은 등급표에 없음 → 0점', by_id(out['results'][0], 'fl.grade')['score'], 0.0)
    for g, want in (('특급', 2.0), ('고급', 2.0), ('중급', 1.8), ('초급', 1.6)):
        p = {**PERSONS, 'fm': {k: {**v, 'grade': g} for k, v in PERSONS['fm'].items()}}
        r = E.evaluate(SPEC, PROJECT, [bidder(persons=p)])['results'][0]
        check(f'분야별 참여 등급 {g}', by_id(r, 'fm.grade')['score'], want)


def test_overlap_tables_and_target():
    for months, want_lead, want_f in ((11.9, 6.0, 4.0), (12, 5.4, 3.6), (15, 4.8, 3.2), (18, 4.2, 2.8), (21, 3.6, 2.4), (30, 3.6, 2.4)):
        p = {**PERSONS, 'lead': {**PERSONS['lead'], 'overlap': months},
             'fl': {k: {**v, 'overlap': months} for k, v in PERSONS['fl'].items()}}
        r = E.evaluate(SPEC, PROJECT, [bidder(persons=p)])['results'][0]
        check(f'책임 중첩 {months}월', by_id(r, 'ovl.lead')['score'], want_lead)
        check(f'분야별 책임 중첩 {months}월', by_id(r, 'ovl.field')['score'], want_f)
    # 평가 대상을 분야별 참여기술인으로 바꾸면 fm의 overlap을 쓴다(입력 없으면 0점 + 경고)
    out = E.evaluate(SPEC, dict(PROJECT, overlap_target='분야별 참여기술인'), [bidder()])
    check('참여기술인 중첩 미입력 → 0점', by_id(out['results'][0], 'ovl.field')['score'], 0.0)
    assert any('중첩 기간 미입력' in w for w in out['warnings'])
    p = {**PERSONS, 'fm': {k: {**v, 'overlap': 5} for k, v in PERSONS['fm'].items()}}
    r = E.evaluate(SPEC, dict(PROJECT, overlap_target='분야별 참여기술인'), [bidder(persons=p)])['results'][0]
    check('참여기술인 중첩 5월 → 4.0', by_id(r, 'ovl.field')['score'], 4.0)


def test_sim_tables():
    for cnt, want in ((10, 12.0), (8, 10.8), (6, 9.6), (4, 8.4), (3.9, 7.2)):
        r = E.evaluate(SPEC, PROJECT, [bidder(firm=dict(FIRM, sim_cnt=cnt))])['results'][0]
        check(f'유사과업 건수 {cnt}', by_id(r, 'sim.cnt')['score'], want)
    for amt, want in ((10, 13.0), (8, 11.7), (6, 10.4), (4, 9.1), (3.9, 7.8)):
        r = E.evaluate(SPEC, PROJECT, [bidder(firm=dict(FIRM, sim_amt=amt))])['results'][0]
        check(f'유사과업 금액 {amt}', by_id(r, 'sim.amt')['score'], want)


def test_credit():
    for ctype, rating, want in (('회사채', 'A-', 3.0), ('회사채', 'BBB+', 2.7), ('회사채', 'BB+', 2.4), ('회사채', 'CCC+ 이하', 2.1),
                                ('기업어음', 'A2-', 3.0), ('기업어음', 'A3-', 2.7), ('기업어음', 'B-', 2.4), ('기업어음', 'C 이하', 2.1),
                                ('미제출', None, 0.0)):
        f = dict(FIRM, credit_type=ctype, credit_rating=rating)
        r = E.evaluate(SPEC, PROJECT, [bidder(firm=f)])['results'][0]
        check(f'재정건실도 {ctype} {rating}', by_id(r, 'credit.finance')['score'], want)
    f = dict(FIRM, bad_cnt=10, very_bad_cnt=0)
    r = E.evaluate(SPEC, PROJECT, [bidder(firm=f)])['results'][0]
    check('점검·진단 결과 감점이 배점 초과 → 0점', by_id(r, 'credit.result')['score'], 0.0)


def test_dev_use_invest():
    f = dict(FIRM, dev_items=[{'type': '특허', 'age_years': 1}] * 3)
    r = E.evaluate(SPEC, PROJECT, [bidder(firm=f)])['results'][0]
    check('특허 개발실적 합계 0.5점 한도(0.3×3=0.9)', by_id(r, 'tech.dev')['score'], 0.5)
    f = dict(FIRM, dev_items=[{'type': '건설신기술', 'dup_group': 'x'}, {'type': '특허', 'age_years': 1, 'dup_group': 'x'}])
    r = E.evaluate(SPEC, PROJECT, [bidder(firm=f)])['results'][0]
    check('동일 내용 신기술·특허 → 점수 높은 1건(신기술 0.5)', by_id(r, 'tech.dev')['score'], 0.5)
    f = dict(FIRM, dev_items=[{'type': '건설신기술'}] * 3)
    r = E.evaluate(SPEC, PROJECT, [bidder(firm=f)])['results'][0]
    check('개발실적 상한 1점', by_id(r, 'tech.dev')['score'], 1.0)
    for cnt, amt, w in ((5, 0, 1.0), (4, 0, 0.9), (2, 0, 0.7), (1, 0, 0.6), (0.9, 0, 0.0), (0.5, 12, 0.6)):
        f = dict(FIRM, use_items=[{'type': '건설신기술', 'use_count': cnt, 'use_amount': amt}])
        r = E.evaluate(SPEC, PROJECT, [bidder(firm=f)])['results'][0]
        want = min(E.rnd(0.5 * w * cnt, 2), 1.0) if w else 0.0
        check(f'신기술 활용 {cnt}건/{amt}억 → 가중치 {w}', by_id(r, 'tech.use')['score'], want)
    for inv, want in ((3.0, 8.0), (2.5, 7.2), (2.0, 6.4), (1.5, 5.6), (1.4, 4.8), (0.0, 4.8)):
        r = E.evaluate(SPEC, PROJECT, [bidder(firm=dict(FIRM, invest_amount=inv, sales_amount=100))])['results'][0]
        check(f'투자 {inv}%', by_id(r, 'tech.invest')['score'], want)


def test_dq_and_bonus():
    p = {**PERSONS, 'team': {'dq_lead_qual': True}}
    out = E.evaluate(SPEC, PROJECT, [bidder(name='실격사', persons=p), bidder(name='정상사')])
    check('책임기술인 부적격 → 실격', out['results'][0]['disqualified'], True)
    check('실격은 순위 없음', out['results'][0]['rank'], None)
    check('정상사 1위', out['results'][1]['rank'], 1)
    # 가점 상계 3점 한도: 신규고용 0.3 + 우수 0.5 = 0.8 (한도 미만)
    r = E.evaluate(SPEC, PROJECT, [bidder(firm=dict(FIRM, new_hire_rate=5))])['results'][0]
    check('가점 0.3 + 0.5', r['bonus']['score'], 0.8)
    r = E.evaluate(SPEC, PROJECT, [bidder(firm=dict(FIRM, new_hire_rate=5, reg_over_6m=False))])['results'][0]
    check('등록 6개월 미경과 → 신규고용 가점 없음(우수기관 0.5만)', r['bonus']['score'], 0.5)


def test_jv():
    m1 = {'name': '주관사', 'share': 60, 'firm': dict(FIRM)}
    m2 = {'name': '참여사', 'share': 40, 'firm': {}}
    b = {'name': 'JV', 'firm': {}, 'persons': PERSONS, 'members': [m1, m2]}
    r = E.evaluate(SPEC, PROJECT, [b])['results'][0]
    check('JV 유사과업 건수(10.8×0.6)', by_id(r, 'sim.cnt')['score'], 6.48)
    check('JV 투자실적(6.4×0.6)', by_id(r, 'tech.invest')['score'], 3.84)
    check('JV 참여기술인은 팀 단위(그룹 A 불변)', r['group_scores']['A'], 38.53)
    check('JV 업무중첩도는 팀 단위(그룹 E 불변)', r['group_scores']['E'], 8.8)
    check('JV 가점(신규고용 0.1×0.6 + 우수기관 0.5)', r['bonus']['score'], 0.56)
    one = {'name': 'JV1', 'firm': {}, 'persons': PERSONS, 'members': [{'name': '단독', 'share': 100, 'firm': dict(FIRM)}]}
    check('JV 1개사(100%) = 단독 합계', E.evaluate(SPEC, PROJECT, [one])['results'][0]['total'], 83.56)


def test_missing_info():
    for key in ('specialty', 'overlap_target'):
        try:
            E.evaluate(SPEC, dict(PROJECT, **{key: None}), [bidder()])
        except ValueError:
            print('OK   ', key, '없으면 오류')
        else:
            failures.append(f'{key} 없음이 오류가 되지 않음')


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_') and callable(v)]
    for t in tests:
        print('---', t.__name__)
        t()
    print()
    if failures:
        print('실패', len(failures), '건')
        for f in failures:
            print(' -', f)
        sys.exit(1)
    print('모든 검증 통과')
