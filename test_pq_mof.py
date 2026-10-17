"""
mof_cm(해양수산부 건설사업관리 건설엔지니어링사업자 사업수행능력 평가) 검증 스크립트. `python test_pq_mof.py`로 실행한다.
기대값은 해양수산부 훈령 제793호 [별표 1]·[별표 2]의 구간표를 손으로 계산한 값이다.
"""
import sys

import pq_engine as E

SPEC = 'mof_cm'
PROJECT = {
    'total_cost': 600, 'phase': '설계 및 시공단계', 'include_construction': True, 'interview': False,
    'fields': [{'name': '토목', 'pct': 60}, {'name': '건축', 'pct': 40}],
    'support_fields': [{'name': '토목', 'pct': 100}],
}

FIRM = {
    'cm_both': 20, 'cm_design': 10, 'cm_design_eng': 10, 'cm_const': 30, 'cm_other': 40, 'perf_avg': 91,
    'suspend_months': 1.2, 'tech_suspend_months': 0, 'bad_avg_firm': 3, 'bad_avg_tech': 1.5,
    'credit_type': '회사채', 'credit_rating': 'A0',
    'invest_amount': 2, 'sales_amount': 200,
    'swap_cnt': 3, 'swap_support_cnt': 7, 'deployed_cnt': 50, 'swap_resident': 1, 'swap_support': 2,
    'new_hire_rate': 2.5,
    'dev_items': [{'type': '건설신기술', 'applicants': 2}],
    'use_items': [{'type': '해양수산신기술', 'use_count': 3, 'use_amount': 15},
                  {'type': '특허', 'use_count': 1, 'age_years': 7}],
}

PERSONS = {
    'lead': {'career': 12, 'perf_a': 14, 'perf_b': 8, 'edu_training': '2주 이상', 'qualification': '기사'},
    'field': {
        '토목': {'career': 50, 'perf_a': 9, 'perf_b': 4, 'edu_training': '1주 이상 2주 미만'},
        '건축': {'career': 40, 'perf_a': 11, 'perf_b': 6, 'edu_training': '2주 이상'},
    },
    'support': {'토목': {'grade': '고급', 'career': 10, 'edu_training': '1주 이상 2주 미만', 'qualification': '기술사·건축사'}},
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
        'lead.career': 13.5, 'lead.perf': 8.4, 'lead.edu': 0.8,
        'fm.career': 13.8, 'fm.perf': 7.86, 'fm.edu': 0.7,
        'sup.grade': 2.0, 'sup.career': 4.8, 'sup.edu': 0.8,
        'sim.perf': 8.0, 'sim.result': 1.8,
        'credit.stop': 6.6, 'credit.penalty': 4.3, 'credit.finance': 3.0,
        'tech.devuse': 2.34, 'tech.invest': 6.6,
        'swap.firm': 2.5, 'swap.tech': 1.55,
    }
    for iid, want in expected.items():
        check(f'항목 {iid}', by_id(r, iid)['score'], want)
    check('그룹 A', r['group_scores']['A'], 52.66)
    check('그룹 B', r['group_scores']['B'], 9.8)
    check('그룹 C', r['group_scores']['C'], 13.9)
    check('그룹 D', r['group_scores']['D'], 8.94)
    check('그룹 E', r['group_scores']['E'], 4.05)
    check('소계', r['base_total'], 89.35)
    check('가감점(신규고용 0.2 + 절감 0.18)', r['bonus']['score'], 0.38)
    check('합계', r['total'], 89.73)
    check('배점 합계', out['total_max'], 100)
    check('경고 없음', len(out['warnings']), 0)


def test_lead_perf_two_parts():
    # 6점 구간 14년(90%) + 3점 구간 8년(100%) = 5.4 + 3.0 = 8.4
    r = E.evaluate(SPEC, PROJECT, [bidder()])['results'][0]
    check('책임 직무분야 실적(6점+3점)', by_id(r, 'lead.perf')['score'], 8.4)
    p = {**PERSONS, 'lead': {**PERSONS['lead'], 'perf_b': None}}
    out = E.evaluate(SPEC, PROJECT, [bidder(persons=p)])
    check('3점 구간 미입력 → 직무분야 실적 0점', by_id(out['results'][0], 'lead.perf')['score'], 0.0)
    assert any('3점 구간' in w for w in out['warnings']), out['warnings']
    print('OK   3점 구간 미입력 경고')


def test_min_career():
    p = {**PERSONS, 'lead': {**PERSONS['lead'], 'career': 4.9}, 'field': {**PERSONS['field'], '토목': {**PERSONS['field']['토목'], 'career': 11}}}
    out = E.evaluate(SPEC, PROJECT, [bidder(persons=p)])
    r = out['results'][0]
    check('책임 최소 경력 5년 미달 → 경력 0점', by_id(r, 'lead.career')['score'], 0.0)
    # 분야별 경력: 토목 11개월(<12) → 0%, 건축 40개월(80%) → 0.6×0 + 0.4×80 = 32% → 15×0.32 = 4.8
    check('분야별 최소 12개월 미달 분야는 0%', by_id(r, 'fm.career')['score'], 4.8)


def test_interview_and_fee():
    proj = dict(PROJECT, interview=True, fee=25)
    p = {**PERSONS, 'team': {**PERSONS['team'], 'itv_lead_grade': '수', 'itv_fm_grade': '우'}}
    r = E.evaluate(SPEC, proj, [bidder(persons=p)])['results'][0]
    check('면접 시 책임 경력 배점 15-3=12 × 90%', by_id(r, 'lead.career')['score'], 10.8)
    check('면접 책임(수 × 3점)', by_id(r, 'itv.lead')['score'], 3.0)
    check('면접 분야별(우 90% × 1.5점)', by_id(r, 'itv.fm')['score'], 1.35)


def test_sim_lower_bound_and_blank_perf():
    for eff, want in ((10, 0.0), (15, 4.8), (29.9, 4.8), (30, 5.6)):
        f = dict(FIRM, cm_both=eff, cm_design=0, cm_design_eng=0, cm_const=0, cm_other=0)
        r = E.evaluate(SPEC, PROJECT, [bidder(firm=f)])['results'][0]
        check(f'유사실적 {eff}억(500~1000억 구간): 하한 15억 미만은 0점', by_id(r, 'sim.perf')['score'], want)
    # 1000억 미만 100억 미만 구간(cost 50): 20 이상 8점, 5 미만 0점
    for eff, want in ((20, 8.0), (5, 5.6), (4.9, 0.0)):
        f = dict(FIRM, cm_both=eff, cm_design=0, cm_design_eng=0, cm_const=0, cm_other=0)
        r = E.evaluate(SPEC, dict(PROJECT, total_cost=50), [bidder(firm=f)])['results'][0]
        check(f'유사실적 {eff}억(100억 미만 구간)', by_id(r, 'sim.perf')['score'], want)
    f = dict(FIRM)
    del f['perf_avg']
    r = E.evaluate(SPEC, PROJECT, [bidder(firm=f)])['results'][0]
    check('수행성과 평가실적 없음 → 중간점수 87.5 → 1.6점', by_id(r, 'sim.result')['score'], 1.6)


def test_other_job_cap():
    # 해양수산부 별표 2 Ⅱ.4.사 예시: 40억 + min(30억×0.6=18, 하한 15) = 55억 (500~1000억 구간)
    f = dict(FIRM, cm_both=0, cm_design=0, cm_design_eng=0, cm_const=40, cm_other=30)
    proj = dict(PROJECT, phase='시공단계')
    r = E.evaluate(SPEC, proj, [bidder(firm=f)])['results'][0]
    assert '= 55억원' in by_id(r, 'sim.perf')['basis'], by_id(r, 'sim.perf')['basis']
    print('OK   유사 이외 직무분야 60% 반영 상한(예시 55억원)')
    check('55억 → 500~1000억 구간 50 이상 → 90% → 7.2점', by_id(r, 'sim.perf')['score'], 7.2)


def test_penalty_table():
    for avg, ded in ((0.9, 0), (1, 0.2), (2, 0.5), (5, 1), (10, 2), (15, 3), (20, 5), (30, 5)):
        f = dict(FIRM, bad_avg_firm=avg, bad_avg_tech=0)
        r = E.evaluate(SPEC, PROJECT, [bidder(firm=f)])['results'][0]
        check(f'평균벌점 {avg} → {ded}점 감점', by_id(r, 'credit.penalty')['score'], round(5 - ded, 2))


def test_use_weights():
    # 건수 가중치 하한 0.1건 → 0.6, 금액 12억 → 0.6 (경남과 다른 표)
    for cnt, amt, w in ((5, 0, 1.0), (4, 0, 0.9), (2, 0, 0.7), (0.1, 0, 0.6), (0.05, 0, 0.0), (0.05, 12, 0.6), (0.05, 11.9, 0.0)):
        f = dict(FIRM, dev_items=[], use_items=[{'type': '건설신기술', 'use_count': cnt, 'use_amount': amt}])
        r = E.evaluate(SPEC, PROJECT, [bidder(firm=f)])['results'][0]
        want = E.rnd(0.5 * w * cnt, 2) if w else 0.0
        check(f'신기술 활용 {cnt}건/{amt}억 → 가중치 {w}', by_id(r, 'tech.devuse')['score'], want)


def test_relative_distribution_mof():
    proj = dict(PROJECT, interview=True, fee=25, rel_mode='평가위원 점수 입력 후 상대평가 자동 배분')

    def run(raws):
        bs = [bidder(name=f'{i}', persons={**PERSONS, 'team': {'itv_lead_raw': raw, 'itv_fm_raw': raw}}) for i, raw in enumerate(raws)]
        out = E.evaluate(SPEC, proj, bs)
        return [by_id(r, 'itv.lead')['score'] for r in out['results']]
    # 5개사: 수1 우1 미2 양1 (경남·방재 기준표는 수1 우2 미1 양1이라 다르다) -> 3.0, 2.7, 2.4, 2.4, 2.1
    check('5개사 상대평가(해수부 표)', run([90, 80, 70, 60, 50]), [3.0, 2.7, 2.4, 2.4, 2.1])
    # 4개사: 수1 우1 미1 양1 -> 3.0, 2.7, 2.4, 2.1
    check('4개사 상대평가(해수부 표)', run([90, 80, 70, 60]), [3.0, 2.7, 2.4, 2.1])
    # 20개사(표 없음 → 10:20:40:20:10) : 수2 우4 미8 양4 가2
    pts = run(list(range(100, 80, -1)))
    from collections import Counter
    c = Counter(pts)
    check('20개사 기본 비율 배분 수2·우4·미8·양4·가2', [c[3.0], c[2.7], c[2.4], c[2.1], c[1.8]], [2, 4, 8, 4, 2])


def test_support_grade_table():
    for cost, grade, want in ((600, '특급', 3.0), (600, '고급', 2.0), (600, '중급', 0.0), (200, '고급', 3.0), (200, '중급', 2.0), (200, '특급', 3.0), (200, '초급', 0.0)):
        p = {**PERSONS, 'support': {'토목': {**PERSONS['support']['토목'], 'grade': grade}}}
        r = E.evaluate(SPEC, dict(PROJECT, total_cost=cost), [bidder(persons=p)])['results'][0]
        check(f'기술지원 등급 {cost}억/{grade}', by_id(r, 'sup.grade')['score'], want)


def test_jv_mof():
    m1 = {'name': '주관사', 'share': 60, 'firm': dict(FIRM)}
    m2 = {'name': '참여사', 'share': 40, 'firm': {}}
    b = {'name': 'JV', 'firm': {}, 'persons': PERSONS, 'members': [m1, m2]}
    out = E.evaluate(SPEC, PROJECT, [b])
    r = out['results'][0]
    # 유사실적: 주관사 67.9억 × 0.6 = 40.74억 → 500~1000억 구간 40 이상 → 80% → 6.4
    check('JV 유사실적(실적 지분 합산 40.74억 → 80%)', by_id(r, 'sim.perf')['score'], 6.4)
    # 수행성과: 91×0.6 + 87.5(실적 없는 구성원 중간점수)×0.4 = 89.6 → 85 이상 90 미만 → 80% → 1.6
    check('JV 수행성과(평균점수 지분 합산 89.6점 → 80%)', by_id(r, 'sim.result')['score'], 1.6)
    check('JV 영업정지(6.6×0.6 + 7×0.4)', by_id(r, 'credit.stop')['score'], 6.76)
    check('JV 참여기술인은 팀 단위', r['group_scores']['A'], 52.66)
    one = {'name': 'JV1', 'firm': {}, 'persons': PERSONS, 'members': [{'name': '단독', 'share': 100, 'firm': dict(FIRM)}]}
    check('JV 1개사(100%) = 단독 합계', E.evaluate(SPEC, PROJECT, [one])['results'][0]['total'], 89.73)


def test_not_regressed_other_specs():
    # 같은 엔진을 쓰는 경남 기준이 영향받지 않았는지(경남 전용 테스트는 test_pq_cm.py)
    s = E.load_spec('gyeongnam_cm')
    assert 'sim_civil' in s['scoring'] and 'penalty_table' not in s['scoring']
    print('OK   경남 명세 유지')


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
