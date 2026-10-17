"""
pq_design(경상남도 설계 등 건설엔지니어링사업자 사업수행능력 평가) 검증 스크립트. `python test_pq_design.py`로 실행한다.
기대값은 [별표 1]의 구간표를 손으로 계산한 값이다.
"""
import sys
from collections import Counter

import pq_engine as E

SPEC = 'gyeongnam_design'
PROJECT = {
    'has_prev': False, 'skip_tech': False, 'rel_mode': '등급 직접 입력', 'no_result_score': '1.8',
    'overlap_full': 200, 'overlap_step': 50, 'overlap_style': '이하·초과 방식(예: 200% 이하 만점)',
    'fields': [{'name': '도로', 'pct': 60}, {'name': '토질', 'pct': 40}],
    'staff_list': [{'name': '김실무'}, {'name': '이실무'}],
}

FIRM = {
    'sim_cnt': 7, 'sim_amt': 35, 'perf_avg': 93,
    'stop_months': 1.5, 'tech_stop_months': 0, 'bad_avg_firm': 3, 'bad_avg_tech': 1,
    'credit_type': '회사채', 'credit_rating': 'BBB-',
    'invest_amount': 2.0, 'sales_amount': 100, 'new_hire_rate': 2.2,
    'dev_items': [{'type': '건설신기술'}, {'type': '특허', 'age_years': 7, 'applicants': 2}],
    'use_items': [{'type': '건설신기술', 'use_count': 3, 'use_amount': 15},
                  {'type': '특허', 'use_count': 2, 'age_years': 12}],
}

PERSONS = {
    'lead': {'grade': '특급', 'career': 15.5, 'cnt': 8, 'cnt_field': 5, 'tech_grade': '우', 'overlap_pct': 220,
             'edu_training': '2주 이상', 'transfer': '3개월 미만'},
    'fl': {
        '도로': {'grade': '고급', 'career': 9, 'cnt': 6, 'cnt_field': 2, 'ovl_target': True, 'overlap_pct': 260, 'edu_training': '1주 이상 2주 미만'},
        '토질': {'grade': '초급', 'career': 4, 'cnt': 2.5, 'transfer': '3개월 이상 6개월 미만'},
    },
    'fm': {
        '도로': {'grade': '중급', 'career': 4.5, 'cnt': 3, 'cnt_field': 1, 'ovl_target': True, 'overlap_pct': 150, 'edu_training': '해당 없음'},
        '토질': {'grade': '초급', 'career': 2, 'cnt': 1, 'ovl_target': True, 'overlap_pct': 330, 'edu_training': '2주 이상'},
    },
    'staff': {'김실무': {'overlap_pct': 190}, '이실무': {'overlap_pct': 400}},
    'team': {'young_cnt': 2, 'young_total': 10},
}

failures = []


def check(label, got, want, tol=1e-9):
    ok = abs(got - want) <= tol if isinstance(want, (int, float)) and not isinstance(want, bool) else got == want
    if not ok:
        failures.append(f'{label}: 기대 {want} / 실제 {got}')
    print(('OK  ' if ok else 'FAIL'), label, got)


def by_id(res, iid):
    return next(i for i in res['items'] if i['id'] == iid)


def has(res, iid):
    return any(i['id'] == iid for i in res['items'])


def bidder(**kw):
    b = {'name': 'A사', 'firm': dict(FIRM), 'persons': PERSONS}
    b.update(kw)
    return b


def test_full_bidder():
    out = E.evaluate(SPEC, PROJECT, [bidder()])
    r = out['results'][0]
    expected = {
        'lead.grade': 2.7, 'lead.career': 3.6, 'lead.cnt': 4.5, 'lead.tech': 3.6,
        'fl.grade': 3.16, 'fl.career': 5.64, 'fl.cnt': 6.62,
        'fm.grade': 3.6, 'fm.career': 4.1, 'fm.cnt': 3.9,
        'edu': 1.0,
        'sim.cnt': 5.4, 'sim.amt': 4.8, 'result': 1.8,
        'credit.stop': 5.9, 'credit.finance': 3.0,
        'tech.dev': 2.0, 'tech.invest': 10.0, 'tech.use': 2.9,
        'ovl.lead': 2.7, 'ovl.fl': 3.2, 'ovl.fm': 1.76, 'ovl.staff': 0.8,
    }
    for iid, want in expected.items():
        check(f'항목 {iid}', by_id(r, iid)['score'], want)
    assert not has(r, 'prev.person') and not has(r, 'prev.firm'), '전차 없음인데 전차 항목이 있음'
    print('OK   전차 없음 → 전차 항목 제외')
    check('그룹 A', r['group_scores']['A'], 42.42)
    check('그룹 B', r['group_scores']['B'], 12.0)
    check('그룹 C', r['group_scores']['C'], 8.9)
    check('그룹 D', r['group_scores']['D'], 14.9)
    check('그룹 E', r['group_scores']['E'], 8.46)
    check('소계', r['base_total'], 86.68)
    check('가점(신규고용 0.2 + 젊은기술인 0.2)', r['bonus']['score'], 0.4)
    check('합계', r['total'], 87.08)
    check('배점 합계', out['total_max'], 100)
    check('경고 없음', len(out['warnings']), 0)
    check('실격 아님', r['disqualified'], False)


def test_dynamic_maxes():
    cases = ((False, False, {'lead.tech': 4, 'lead.cnt': 5, 'edu': 2, 'prev.person': None, 'prev.firm': None}),
             (True, False, {'lead.tech': 3, 'lead.cnt': 5, 'edu': 1, 'prev.person': 1, 'prev.firm': 1}),
             (True, True, {'lead.tech': None, 'lead.cnt': 8, 'edu': 1, 'prev.person': 1, 'prev.firm': 1}),
             (False, True, {'lead.tech': None, 'lead.cnt': 9, 'edu': 2, 'prev.person': None, 'prev.firm': None}))
    for hp, st, want in cases:
        out = E.evaluate(SPEC, dict(PROJECT, has_prev=hp, skip_tech=st), [bidder()])
        r = out['results'][0]
        check(f'배점 합계 100 (전차 {hp}, 기술능력 생략 {st})', out['total_max'], 100)
        for iid, mx in want.items():
            if mx is None:
                assert not has(r, iid), (iid, hp, st)
            else:
                check(f'  배점 {iid} (전차 {hp}, 생략 {st})', by_id(r, iid)['max'], mx)


def test_grid_boundaries():
    for yrs, want in ((15, 4.0), (14.9, 3.6), (14, 3.6), (13, 3.2), (12, 2.8), (11.9, 2.4)):
        p = {**PERSONS, 'lead': {**PERSONS['lead'], 'career': yrs, 'transfer': None}}
        r = E.evaluate(SPEC, PROJECT, [bidder(persons=p)])['results'][0]
        check(f'책임 경력 {yrs}년', by_id(r, 'lead.career')['score'], want)
    for cnt, want in ((10, 5.0), (9, 4.5), (8, 4.0), (7, 3.5), (6.9, 3.0)):
        p = {**PERSONS, 'lead': {**PERSONS['lead'], 'cnt': cnt, 'cnt_field': 0, 'transfer': None}}
        r = E.evaluate(SPEC, PROJECT, [bidder(persons=p)])['results'][0]
        check(f'책임 실적 {cnt}건', by_id(r, 'lead.cnt')['score'], want)
    for g, want in (('특급', 3.0), ('고급', 2.0), ('중급', 1.0)):
        p = {**PERSONS, 'lead': {**PERSONS['lead'], 'grade': g, 'transfer': None}}
        r = E.evaluate(SPEC, PROJECT, [bidder(persons=p)])['results'][0]
        check(f'책임 등급 {g}', by_id(r, 'lead.grade')['score'], want)
    for cnt, want in ((8, 6.0), (6, 5.4), (4, 4.8), (2, 4.2), (1.9, 3.6)):
        r = E.evaluate(SPEC, PROJECT, [bidder(firm=dict(FIRM, sim_cnt=cnt))])['results'][0]
        check(f'유사실적 건수 {cnt}', by_id(r, 'sim.cnt')['score'], want)
    for amt, want in ((50, 6.0), (40, 5.4), (30, 4.8), (20, 4.2), (19.9, 3.6)):
        r = E.evaluate(SPEC, PROJECT, [bidder(firm=dict(FIRM, sim_amt=amt))])['results'][0]
        check(f'유사실적 금액 {amt}', by_id(r, 'sim.amt')['score'], want)
    for inv, want in ((1.5, 10), (1.25, 9), (1.0, 8), (0.75, 7), (0.5, 6), (0.49, 0)):
        r = E.evaluate(SPEC, PROJECT, [bidder(firm=dict(FIRM, invest_amount=inv, sales_amount=100))])['results'][0]
        check(f'투자 {inv}%', by_id(r, 'tech.invest')['score'], want)


def test_other_field_factor():
    # 책임·분야별 책임은 전문분야 같고 사업분야 다른 실적 80%, 분야별 참여기술인은 100%
    p = {**PERSONS, 'lead': {**PERSONS['lead'], 'cnt': 0, 'cnt_field': 12.5, 'transfer': None}}
    r = E.evaluate(SPEC, PROJECT, [bidder(persons=p)])['results'][0]
    assert '12.5건×0.8=10건' in by_id(r, 'lead.cnt')['basis'], by_id(r, 'lead.cnt')['basis']
    check('책임: 12.5건×0.8 = 10건 → 5.0', by_id(r, 'lead.cnt')['score'], 5.0)
    p = {**PERSONS, 'fm': {'도로': {**PERSONS['fm']['도로'], 'cnt': 2, 'cnt_field': 3}, '토질': PERSONS['fm']['토질']}}
    r = E.evaluate(SPEC, PROJECT, [bidder(persons=p)])['results'][0]
    assert '3건×1.0' in by_id(r, 'fm.cnt')['basis']
    print('OK   분야별 참여기술인은 전문분야 같은 실적 100% 반영')


def test_transfer_factor():
    for tr, ex, f in (('3개월 미만', False, 0.90), ('3개월 이상 6개월 미만', False, 0.95), ('6개월 이상', False, 1.0), ('3개월 미만', True, 1.0)):
        p = {**PERSONS, 'lead': {**PERSONS['lead'], 'transfer': tr, 'transfer_exempt': ex}}
        r = E.evaluate(SPEC, PROJECT, [bidder(persons=p)])['results'][0]
        check(f'이적 {tr}{"(예외)" if ex else ""}: 등급 3×{f}', by_id(r, 'lead.grade')['score'], round(3 * f, 2))
        check(f'  경력 4×{f}', by_id(r, 'lead.career')['score'], round(4 * f, 2))


def test_overlap_styles():
    le = PROJECT
    lt = dict(PROJECT, overlap_full=250, overlap_step=100, overlap_style='미만·이상 방식(예: 250% 미만 만점)')
    for v, want in ((200, 3.0), (200.1, 2.7), (250, 2.7), (250.1, 2.4), (300, 2.4), (350, 2.1), (350.1, 1.8)):
        p = {**PERSONS, 'lead': {**PERSONS['lead'], 'overlap_pct': v}}
        r = E.evaluate(SPEC, le, [bidder(persons=p)])['results'][0]
        check(f'책임 중첩 {v}% (200% 이하 방식, 차등폭 50)', by_id(r, 'ovl.lead')['score'], want)
    for v, want in ((249.9, 3.0), (250, 2.7), (349.9, 2.7), (350, 2.4), (449.9, 2.4), (450, 2.1), (550, 1.8)):
        p = {**PERSONS, 'lead': {**PERSONS['lead'], 'overlap_pct': v}}
        r = E.evaluate(SPEC, lt, [bidder(persons=p)])['results'][0]
        check(f'책임 중첩 {v}% (250% 미만 방식, 차등폭 100)', by_id(r, 'ovl.lead')['score'], want)


def test_overlap_targets_and_staff():
    p = {**PERSONS, 'fl': {'도로': {**PERSONS['fl']['도로'], 'ovl_target': False}, '토질': PERSONS['fl']['토질']}}
    out = E.evaluate(SPEC, PROJECT, [bidder(persons=p)])
    check('평가 대상 체크가 없으면 0점', by_id(out['results'][0], 'ovl.fl')['score'], 0.0)
    assert any('평가 대상' in w for w in out['warnings']), out['warnings']
    print('OK   업무중첩도 평가 대상 미체크 경고')
    out = E.evaluate(SPEC, dict(PROJECT, staff_list=[]), [bidder()])
    check('실무기술인 구성 없음 → 0점', by_id(out['results'][0], 'ovl.staff')['score'], 0.0)


def test_prev_scores():
    proj = dict(PROJECT, has_prev=True)
    p = {**PERSONS,
         'lead': {**PERSONS['lead'], 'prev_elapsed': 2, 'prev_rate': 80},
         'fl': {'도로': {**PERSONS['fl']['도로'], 'prev_elapsed': 4}, '토질': {**PERSONS['fl']['토질'], 'prev_elapsed': 7, 'prev_rate': 50}},
         'team': {**PERSONS['team'], 'prev_fl_fields': 2}}
    f = dict(FIRM, prev_firm_elapsed=4, prev_firm_rate=50)
    out = E.evaluate(SPEC, proj, [bidder(persons=p, firm=f)])
    r = out['results'][0]
    # 책임: 0.5×0.8 = 0.4, 분야별 책임: (0.4×1.0 + 0.3×0.5) ÷ 2 = 0.275 → 0.675점
    check('참여기술인 전차 실적', by_id(r, 'prev.person')['score'], 0.68)
    check('사업체 전차 실적(4년 0.8 × 인정률 50%)', by_id(r, 'prev.firm')['score'], 0.4)
    check('전차 있음 → 교육훈련 1점 배점', by_id(r, 'edu')['max'], 1.0)
    for e, want in ((2.9, 1.0), (3, 0.8), (4.9, 0.8), (5, 0.6), (9.9, 0.6), (10, 0.0)):
        r = E.evaluate(SPEC, proj, [bidder(firm=dict(FIRM, prev_firm_elapsed=e))])['results'][0]
        check(f'사업체 전차 경과 {e}년', by_id(r, 'prev.firm')['score'], want)


def test_tech_relative():
    proj = dict(PROJECT, rel_mode='평가위원 점수 입력 후 상대평가 자동 배분')
    bs = []
    for n, raw in (('가', 90), ('나', 80), ('다', 70)):
        p = {**PERSONS, 'lead': {**PERSONS['lead'], 'tech_raw': raw, 'tech_grade': None}}
        bs.append(bidder(name=n, persons=p))
    out = E.evaluate(SPEC, proj, bs)
    check('3개사 기술능력 상대평가(수·우·미) 4점 배점', [by_id(r, 'lead.tech')['score'] for r in out['results']], [4.0, 3.6, 3.2])
    p = {**PERSONS, 'lead': {**PERSONS['lead'], 'tech_grade': '미제출'}}
    out = E.evaluate(SPEC, PROJECT, [bidder(persons=p)])
    check('평가서 미제출 → 0점', by_id(out['results'][0], 'lead.tech')['score'], 0.0)


def test_lead_dq():
    p = {**PERSONS, 'lead': {**PERSONS['lead'], 'career': 2.9}}
    out = E.evaluate(SPEC, PROJECT, [bidder(name='실격사', persons=p), bidder(name='정상사')])
    check('책임기술인 경력 3년 미만 → 실격', out['results'][0]['disqualified'], True)
    check('실격은 순위 없음', out['results'][0]['rank'], None)
    check('정상사 1위', out['results'][1]['rank'], 1)
    p = {**PERSONS, 'lead': {**PERSONS['lead'], 'cnt': 2.9, 'cnt_field': 20}}
    out = E.evaluate(SPEC, PROJECT, [bidder(persons=p)])
    check('같은 사업분야 실적 3건 미만 → 실격(전문분야만 같은 실적은 최소 요건에 불산입)', out['results'][0]['disqualified'], True)
    p = {**PERSONS, 'team': {**PERSONS['team'], 'dq_other': True}}
    check('기타 실격 체크', E.evaluate(SPEC, PROJECT, [bidder(persons=p)])['results'][0]['disqualified'], True)


def test_credit_and_bonus():
    for avg, ded in ((0.9, 0), (1, 0.2), (2, 0.5), (5, 1), (10, 2), (15, 3), (20, 5)):
        f = dict(FIRM, stop_months=0, tech_stop_months=0, bad_avg_firm=avg, bad_avg_tech=0)
        r = E.evaluate(SPEC, PROJECT, [bidder(firm=f)])['results'][0]
        check(f'평균벌점 {avg} → -{ded}', by_id(r, 'credit.stop')['score'], round(7 - ded, 2))
    for yc, want in ((0.5, 0.0), (1, 0.1), (3, 0.15), (5, 0.2)):
        p = {**PERSONS, 'team': {**PERSONS['team'], 'young_cnt': yc, 'young_total': 100}}
        r = E.evaluate(SPEC, PROJECT, [bidder(persons=p)])['results'][0]
        check(f'젊은기술인 {yc}% → 가점 {want}', round(r['bonus']['score'] - 0.2, 2), want)


def test_jv():
    m1 = {'name': '주관사', 'share': 60, 'firm': dict(FIRM)}
    m2 = {'name': '참여사', 'share': 40, 'firm': {}}
    b = {'name': 'JV', 'firm': {}, 'persons': PERSONS, 'members': [m1, m2]}
    r = E.evaluate(SPEC, PROJECT, [b])['results'][0]
    check('JV 유사실적 건수(7×0.6=4.2건 → 80%)', by_id(r, 'sim.cnt')['score'], 4.8)
    check('JV 유사실적 금액(35×0.6=21억 → 70%)', by_id(r, 'sim.amt')['score'], 4.2)
    check('JV 수행성과(1.8×0.6 + 기본 1.8×0.4)', by_id(r, 'result')['score'], 1.8)
    check('JV 투자실적(2.0%×0.6=1.2% → 8점)', by_id(r, 'tech.invest')['score'], 8.0)
    check('JV 개발실적(2.4×0.6=1.44)', by_id(r, 'tech.dev')['score'], 1.44)
    check('JV 활용실적(2.904×0.6=1.74)', by_id(r, 'tech.use')['score'], 1.74)
    check('JV 업무정지·벌점(5.9×0.6 + 7×0.4)', by_id(r, 'credit.stop')['score'], 6.34)
    check('JV 재정건실도(3.0×0.6)', by_id(r, 'credit.finance')['score'], 1.8)
    check('JV 참여기술인은 팀 단위(그룹 A 불변)', r['group_scores']['A'], 42.42)
    check('JV 업무중첩도는 팀 단위(그룹 E 불변)', r['group_scores']['E'], 8.46)
    check('JV 가점(신규고용 0.2×0.6 + 젊은기술인 0.2)', r['bonus']['score'], 0.32)
    one = {'name': 'JV1', 'firm': {}, 'persons': PERSONS, 'members': [{'name': '단독', 'share': 100, 'firm': dict(FIRM)}]}
    check('JV 1개사(100%) = 단독 합계', E.evaluate(SPEC, PROJECT, [one])['results'][0]['total'], 87.08)


def test_missing_info():
    for key in ('overlap_full', 'overlap_step', 'overlap_style'):
        try:
            E.evaluate(SPEC, dict(PROJECT, **{key: None}), [bidder()])
        except ValueError:
            print('OK   ', key, '없으면 오류')
        else:
            failures.append(f'{key} 없음이 오류가 되지 않음')
    out = E.evaluate(SPEC, dict(PROJECT, overlap_full=350), [bidder()])
    assert any('고시 범위(200~300%)' in w for w in out['warnings']), out['warnings']
    print('OK   만점기준 범위 밖 경고')


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
