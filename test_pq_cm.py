"""
pq_cm(경상남도 건설사업관리사업자 사업수행능력 평가) 검증 스크립트. `python test_pq_cm.py`로 실행한다.
기대값은 [별표 2]의 구간표를 손으로 계산한 값이다.
"""
import sys

import pq_engine as E

SPEC = 'gyeongnam_cm'
PROJECT = {
    'total_cost': 600, 'main_work': '토목·폐기물처리시설', 'phase': '설계 및 시공단계',
    'include_construction': True, 'interview': False,
    'no_result_score': '1.8',
    'fields': [{'name': '토목', 'pct': 60}, {'name': '건축', 'pct': 40}],
    'support_fields': [{'name': '토목', 'pct': 100}],
}

FIRM = {
    'cm_both': 20, 'cm_design': 10, 'cm_design_eng': 10, 'cm_const': 30, 'cm_super': 10, 'perf_avg': 93,
    'suspend_months': 1.2, 'tech_suspend_months': 0, 'bad_deduct_firm': 0.5, 'bad_deduct_tech': 0.3,
    'credit_type': '회사채', 'credit_rating': 'A0',
    'invest_amount': 2, 'sales_amount': 200,
    'swap_cnt': 3, 'swap_support_cnt': 7, 'deployed_cnt': 50, 'swap_resident': 1, 'swap_support': 2,
    'new_hire_rate': 2.5,
    'dev_items': [{'applicants': 2}],
    'use_items': [{'type': '건설신기술', 'use_count': 2, 'use_amount': 10},
                  {'type': '특허', 'use_count': 1, 'age_years': 7}],
}

PERSONS = {
    'lead': {'grade': '특급', 'career': 12, 'perf': 14, 'edu_training': '2주 이상', 'qualification': '기사'},
    'field': {
        '토목': {'grade': '특급', 'career': 50, 'perf': 9, 'edu_training': '1주 이상 2주 미만'},
        '건축': {'grade': '고급', 'career': 60, 'perf': 5, 'edu_training': '2주 이상'},
    },
    'support': {'토목': {'grade': '특급', 'career': 10, 'edu_training': '1주 이상 2주 미만', 'qualification': '기술사·건축사'}},
    'team': {'save_res_amt': 6, 'save_res_rate': 0.2, 'save_sup_amt': 12, 'save_sup_rate': 0.3},
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
        'lead.career': 13.5, 'lead.perf': 8.1, 'lead.edu': 0.8,
        'fm.career': 13.2, 'fm.perf': 6.84, 'fm.edu': 0.7,
        'sup.grade': 3.0, 'sup.career': 4.8, 'sup.edu': 0.8,
        'sim.perf': 7.2, 'sim.result': 1.8,
        'credit.stop': 6.6, 'credit.penalty': 4.2, 'credit.finance': 3.0,
        'tech.devuse': 1.84, 'tech.invest': 6.6,
        'swap.firm': 2.5, 'swap.tech': 1.55,
    }
    for iid, want in expected.items():
        check(f'항목 {iid}', by_id(r, iid)['score'], want)
    check('그룹 A', r['group_scores']['A'], 51.74)
    check('그룹 B', r['group_scores']['B'], 9.0)
    check('그룹 C', r['group_scores']['C'], 13.8)
    check('그룹 D', r['group_scores']['D'], 8.44)
    check('그룹 E', r['group_scores']['E'], 4.05)
    check('소계', r['base_total'], 87.03)
    check('가점(신규고용 0.2 + 절감 0.08+0.1)', r['bonus']['score'], 0.38)
    check('합계', r['total'], 87.41)
    check('배점 합계', out['total_max'], 100)
    check('순위 1', r['rank'], 1)
    check('경고 없음', len(out['warnings']), 0)


def test_interview_reduces_career_points():
    proj = dict(PROJECT, interview=True, fee=25)
    p = {**PERSONS, 'team': {**PERSONS['team'], 'itv_lead_grade': '수', 'itv_fm_grade': '우'}}
    out = E.evaluate(SPEC, proj, [bidder(persons=p)])
    r = out['results'][0]
    check('면접 시 책임 경력 배점 15-3=12 × 90%', by_id(r, 'lead.career')['score'], 10.8)
    check('면접 책임(수 100% × 3점)', by_id(r, 'itv.lead')['score'], 3.0)
    check('면접 분야별(우 90% × 1.5점)', by_id(r, 'itv.fm')['score'], 1.35)
    check('면접 시 분야별 경력 배점 15-1.5=13.5 → 88% ', by_id(r, 'fm.career')['score'], 11.88)
    check('배점 합계 여전히 100', out['total_max'], 100)


def test_interview_fee_tiers():
    for fee, lead_pts in ((19.9, 2), (20, 3), (29.9, 3), (30, 4)):
        out = E.evaluate(SPEC, dict(PROJECT, interview=True, fee=fee), [bidder(persons={**PERSONS, 'team': {'itv_lead_grade': '수'}})])
        check(f'사업비 {fee}억 → 책임 면접 {lead_pts}점', by_id(out['results'][0], 'itv.lead')['score'], lead_pts)


def test_relative_interview():
    proj = dict(PROJECT, interview=True, fee=25, rel_mode='평가위원 점수 입력 후 상대평가 자동 배분')
    bs = []
    for n, raw in (('가', 90), ('나', 80), ('다', 70)):
        bs.append(bidder(name=n, persons={**PERSONS, 'team': {'itv_lead_raw': raw, 'itv_fm_raw': raw}}))
    out = E.evaluate(SPEC, proj, bs)
    pts = [by_id(r, 'itv.lead')['score'] for r in out['results']]
    check('3개사 상대평가 수·우·미 = 3.0 / 2.7 / 2.4', pts, [3.0, 2.7, 2.4])


def test_support_excluded_without_construction():
    out = E.evaluate(SPEC, dict(PROJECT, include_construction=False), [bidder()])
    r = out['results'][0]
    assert not any(i['id'].startswith(('sup.', 'swap.')) for i in r['items']), '시공단계 제외인데 항목이 남음'
    check('제외 시 배점 합계 85', out['total_max'], 85)
    assert any('제외했습니다' in w for w in out['warnings']), out['warnings']
    print('OK   기술지원·교체빈도 제외 안내')


def test_sim_phase_variants():
    f = {'cm_both': 20, 'cm_design': 10, 'cm_design_eng': 10, 'cm_const': 30, 'cm_super': 10}
    for phase, want in (('설계단계', 20 + 17), ('시공단계', 20 + 37)):
        out = E.evaluate(SPEC, dict(PROJECT, phase=phase), [bidder(firm=dict(FIRM, **f))])
        eff_txt = by_id(out['results'][0], 'sim.perf')['basis']
        assert f'= {want}억원' in eff_txt, (phase, eff_txt)
        print('OK  ', phase, '유사과업 환산', want)


def test_building_table():
    proj = dict(PROJECT, main_work='건축', total_cost=800)
    out = E.evaluate(SPEC, proj, [bidder(firm=dict(FIRM, cm_both=40, cm_design=0, cm_design_eng=0, cm_const=0, cm_super=0))])
    # 건축 500억~1,000억: [40,35,30,25] → 40 이상 100% → 8점
    check('건축 구간표(500~1000억, 40억 이상)', by_id(out['results'][0], 'sim.perf')['score'], 8.0)


def test_credit_and_zero_cases():
    out = E.evaluate(SPEC, PROJECT, [bidder(firm=dict(FIRM, credit_type='기업어음', credit_rating='B-', suspend_months=0.2, swap_resident=10))])
    r = out['results'][0]
    check('기업어음 B- → B- 이상 구간 2.8점', by_id(r, 'credit.finance')['score'], 2.8)
    check('영업정지 0.2개월 → 1개월 올림 -0.2', by_id(r, 'credit.stop')['score'], 6.8)
    check('상주 교체 10회 → 0점 하한', by_id(r, 'swap.tech')['score'], 0.0)


def test_patent_cap_and_dup_group():
    f = dict(FIRM, dev_items=[], use_items=[
        {'type': '특허', 'use_count': 5, 'age_years': 1, 'dup_group': 'x'},
        {'type': '건설신기술', 'use_count': 1, 'use_amount': 0, 'dup_group': 'x'},
        {'type': '특허', 'use_count': 5, 'age_years': 1},
        {'type': '특허', 'use_count': 5, 'age_years': 1},
    ])
    r = E.evaluate(SPEC, PROJECT, [bidder(firm=f)])['results'][0]
    # 특허 1.5점(0.3×1.0×5)이 동일묶음에서 신기술(0.5×0.6=0.3)보다 크므로 특허만 남음 → 특허 3건 = 4.5 → 상한 1.0
    check('특허 활용 합계 최대 1점 + 동일내용 1건만', by_id(r, 'tech.devuse')['score'], 1.0)


def test_corruption_and_dq():
    p = {**PERSONS, 'team': {**PERSONS['team'], 'corrupt': True, 'corrupt_rate': 2, 'corrupt_amt': 1}}
    out = E.evaluate(SPEC, PROJECT, [bidder(persons=p)])
    r = out['results'][0]
    check('부패행위(피해 2% → 3점 감점) 후 가감 순점수', r['bonus']['score'], -2.62)
    dq = {**PERSONS, 'team': {**PERSONS['team'], 'dq_overlap': True}}
    out = E.evaluate(SPEC, PROJECT, [bidder(name='실격사', persons=dq), bidder(name='정상사')])
    check('실격 표시', out['results'][0]['disqualified'], True)
    check('실격은 순위 없음', out['results'][0]['rank'], None)
    check('정상사 1위', out['results'][1]['rank'], 1)


def test_jv():
    m1 = {'name': '주관사', 'share': 60, 'firm': dict(FIRM)}
    m2 = {'name': '참여사', 'share': 40, 'firm': {}}
    b = {'name': 'JV', 'firm': {}, 'persons': PERSONS, 'members': [m1, m2]}
    out = E.evaluate(SPEC, PROJECT, [b])
    r = out['results'][0]
    # 유사과업: 57.8×0.6 = 34.68억 → 500~1000억 토목 [60,50,40,30] → 30억 이상 70% → 5.6
    check('JV 유사과업(실적 지분 합산 34.68억 → 70%)', by_id(r, 'sim.perf')['score'], 5.6)
    check('JV 영업정지(6.6×0.6 + 7×0.4)', by_id(r, 'credit.stop')['score'], 6.76)
    check('JV 재정건실도(3.0×0.6 + 0)', by_id(r, 'credit.finance')['score'], 1.8)
    check('JV 참여기술인은 팀 단위(그룹 A 불변)', r['group_scores']['A'], 51.74)
    check('JV 신규고용 가점 지분 반영(0.2×0.6)+절감 0.18', r['bonus']['score'], 0.3)
    check('JV 구성원 수', len(r['members']), 2)
    # 구성원 1개사(지분 100%) = 단독 결과
    one = {'name': 'JV1', 'firm': {}, 'persons': PERSONS, 'members': [{'name': '단독', 'share': 100, 'firm': dict(FIRM)}]}
    r1 = E.evaluate(SPEC, PROJECT, [one])['results'][0]
    check('JV 1개사(100%) = 단독 합계', r1['total'], 87.41)


def test_missing_project_info():
    try:
        E.evaluate(SPEC, dict(PROJECT, total_cost=None), [bidder()])
    except ValueError:
        print('OK   총공사비 없으면 오류')
    else:
        failures.append('총공사비 없음이 오류가 되지 않음')


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
