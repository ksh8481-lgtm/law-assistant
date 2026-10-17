"""
pq_env(환경영향평가업자 사업수행능력 평가) 검증 스크립트. `python test_pq_env.py`로 실행한다.
기대값은 [별표]의 구간표를 손으로 계산한 값이다.
"""
import sys

import pq_engine as E

SPEC = 'env_assess'
PROJECT = {
    'complexity': '복잡사업', 'order_amount': 10, 'overlap_base': 2.5,
    'fl_list': [{'name': '대기'}, {'name': '수질'}],
    'fm_list': [{'name': '소음'}, {'name': '토양'}],
}

FIRM = {
    'cnt_a': 4, 'cnt_b': 2, 'cnt_c': 5, 'cnt_d': 5,
    'amt_a': 20, 'amt_b': 10, 'amt_c': 0, 'amt_d': 0,
    'company_size': '소기업', 'credit_type': '회사채', 'credit_rating': 'A0',
    'invest_amount': 3, 'sales_amount': 200, 'youth_rate': 2.7,
    'dev_items': [{'type': '신기술'}, {'type': '특허', 'age_years': 7}],
}

PERSONS = {
    'lead': {'grade': '환경영향평가사', 'career_a': 16, 'career_b': 5, 'n_a': 10, 'n_b': 5, 'n_c': 5, 'n_d': 0,
             'overlap': 3.0, 'edu_training': '2주 이상', 'prev': True},
    'fl': {
        '대기': {'grade': '특급', 'career_a': 14, 'career_b': 0, 'n_a': 12, 'overlap': 5.0, 'edu_training': '1주 이상 2주 미만',
                 'transfer': '3개월 미만'},
        '수질': {'grade': '고급', 'career_a': 10, 'career_b': 10, 'n_a': 5, 'n_c': 10, 'overlap': 2.0, 'edu_training': '해당 없음', 'prev': True},
    },
    'fm': {
        '소음': {'grade': '중급', 'career_a': 8, 'n_a': 9, 'overlap': 2.5, 'edu_training': '2주 이상', 'transfer': '6개월 이상'},
        '토양': {'grade': '초급', 'career_a': 5, 'n_a': 4, 'overlap': 5.0, 'edu_training': '1주 이상 2주 미만', 'prev': True,
                 'transfer': '3개월 미만', 'transfer_exempt': True},
    },
    'team': {'bad_suspend': 1.5, 'bad_false': 0, 'bad_poor': 1, 'bad_other': 0.5, 'jv_12': True, 'org_score': 1.5},
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
        'qual.lead': 3.0, 'qual.fl': 4.56, 'qual.fm': 4.25,
        'career.lead': 4.0, 'career.fl': 6.02, 'career.fm': 4.5,
        'perf.lead': 4.0, 'perf.fl': 5.04, 'perf.fm': 5.1,
        'free.lead': 3.2, 'free.fl': 3.5, 'free.fm': 3.0,
        'edu': 1.2, 'prev': 0.6,
        'firm.cnt': 5.6, 'firm.amt': 4.2,
        'credit.bad': 3.4, 'credit.finance': 3.0,
        'tech.dev': 1.48, 'tech.invest': 2.0, 'tech.use': 2.0,
        'jv.bonus': 0.5, 'org.eval': 1.5,
    }
    for iid, want in expected.items():
        check(f'항목 {iid}', by_id(r, iid)['score'], want)
    check('그룹 A', r['group_scores']['A'], 51.97)
    check('그룹 B', r['group_scores']['B'], 9.8)
    check('그룹 C', r['group_scores']['C'], 6.4)
    check('그룹 D', r['group_scores']['D'], 5.48)
    check('그룹 E', r['group_scores']['E'], 2.0)
    check('소계', r['base_total'], 75.65)
    check('가점(청년고용 2.7% → 절삭 2% → 0.2)', r['bonus']['score'], 0.2)
    check('합계', r['total'], 75.85)
    check('배점 합계', out['total_max'], 100)
    check('경고 없음', len(out['warnings']), 0)


def test_simple_vs_complex_tables():
    # 총괄 경력 15년(≥15 → j=1): 단순 [100,100,..] → 100%, 복잡 [100,90,..] → 90%
    p = {**PERSONS, 'lead': {**PERSONS['lead'], 'career_a': 15, 'career_b': 0}}
    for cx, want in (('단순사업', 4.0), ('복잡사업', 3.6)):
        r = E.evaluate(SPEC, dict(PROJECT, complexity=cx), [bidder(persons=p)])['results'][0]
        check(f'총괄 경력 15년 {cx}', by_id(r, 'career.lead')['score'], want)


def test_career_buckets():
    for yrs, want in ((17, 100), (16.9, 90), (15, 90), (14.9, 80), (13, 80), (12.9, 70), (10, 70), (9.99, 60), (9, 60), (8.9, 50), (7, 50), (6.9, 40)):
        p = {**PERSONS, 'lead': {**PERSONS['lead'], 'career_a': yrs, 'career_b': 0}}
        r = E.evaluate(SPEC, PROJECT, [bidder(persons=p)])['results'][0]
        check(f'총괄 경력 {yrs}년(복잡) → {want}%', by_id(r, 'career.lead')['score'], round(4 * want / 100, 2))


def test_career_other_factor():
    # 기타 환경분야 경력은 60%: 10 + 10×0.6 = 16 → 복잡 총괄 15 이상 → 90% → 3.6
    p = {**PERSONS, 'lead': {**PERSONS['lead'], 'career_a': 10, 'career_b': 10}}
    r = E.evaluate(SPEC, PROJECT, [bidder(persons=p)])['results'][0]
    check('기타 환경분야 경력 60% 환산', by_id(r, 'career.lead')['score'], 3.6)


def test_perf_coefficients():
    # 실적 계수 1.0·0.6·0.6·0.36: 5 + 5×0.6 + 5×0.6 + 5×0.36 = 12.8 → 복잡 총괄 11건 이상 13건 미만 → 80%
    p = {**PERSONS, 'lead': {**PERSONS['lead'], 'n_a': 5, 'n_b': 5, 'n_c': 5, 'n_d': 5}}
    r = E.evaluate(SPEC, PROJECT, [bidder(persons=p)])['results'][0]
    check('실적 계수 적용 12.8건 → 80%', by_id(r, 'perf.lead')['score'], 3.2)


def test_free_overlap():
    for x, want_ratio in ((2.5, 1.0), (3.0, 0.8), (3.75, 0.5), (5.0, 0.0), (7.0, 0.0), (0, 1.0)):
        p = {**PERSONS, 'lead': {**PERSONS['lead'], 'overlap': x}}
        r = E.evaluate(SPEC, PROJECT, [bidder(persons=p)])['results'][0]
        check(f'1인당 중복금액 {x}억(기준 2.5억)', by_id(r, 'free.lead')['score'], round(4 * want_ratio, 2))
    p = {**PERSONS, 'lead': {**PERSONS['lead'], 'overlap': 0, 'overlap_error': True}}
    r = E.evaluate(SPEC, PROJECT, [bidder(persons=p)])['results'][0]
    check('평가자료 오류 확인 → 0점', by_id(r, 'free.lead')['score'], 0.0)


def test_qual_not_recognized():
    p = {**PERSONS, 'lead': {**PERSONS['lead'], 'grade': '특급'}}
    out = E.evaluate(SPEC, PROJECT, [bidder(persons=p)])
    check('총괄은 환경영향평가사만 인정 → 0점', by_id(out['results'][0], 'qual.lead')['score'], 0.0)
    assert any('인정되지 않아' in w for w in out['warnings']), out['warnings']
    print('OK   인정되지 않는 자격 경고')


def test_transfer_factor():
    for tr, ex, f in (('3개월 미만', False, 0.8), ('3개월 이상 6개월 미만', False, 0.9), ('6개월 이상', False, 1.0), ('3개월 미만', True, 1.0)):
        p = {**PERSONS, 'lead': {**PERSONS['lead'], 'transfer': tr, 'transfer_exempt': ex}}
        r = E.evaluate(SPEC, PROJECT, [bidder(persons=p)])['results'][0]
        check(f'이적계수 {tr}{"(예외)" if ex else ""} × {f}', by_id(r, 'qual.lead')['score'], round(3 * f, 2))


def test_firm_tables():
    for cx, cnt, want in (('단순사업', 10, 7.0), ('단순사업', 9.9, 6.3), ('단순사업', 3.9, 4.2), ('복잡사업', 15, 7.0), ('복잡사업', 5.9, 4.2)):
        f = dict(FIRM, cnt_a=cnt, cnt_b=0, cnt_c=0, cnt_d=0)
        r = E.evaluate(SPEC, dict(PROJECT, complexity=cx), [bidder(firm=f)])['results'][0]
        check(f'수행건수 {cnt} {cx}', by_id(r, 'firm.cnt')['score'], want)
    for cx, ratio_amt, want in (('단순사업', 25, 7.0), ('단순사업', 20, 6.3), ('단순사업', 4.9, 4.2), ('복잡사업', 50, 7.0), ('복잡사업', 29.9, 4.2)):
        f = dict(FIRM, amt_a=ratio_amt, amt_b=0, amt_c=0, amt_d=0)
        r = E.evaluate(SPEC, dict(PROJECT, complexity=cx, order_amount=10), [bidder(firm=f)])['results'][0]
        check(f'수행금액 {ratio_amt}억/10억 {cx}', by_id(r, 'firm.amt')['score'], want)


def test_finance_by_size():
    for size, rating, want in (('대기업·중기업', 'BBB-', 3.0), ('대기업·중기업', 'BB+', 2.4), ('대기업·중기업', 'CCC+ 이하', 2.1),
                               ('소기업', 'BB+', 2.7), ('소기업', 'CCC+ 이하', 2.4), ('소기업', 'B-', 2.7)):
        f = dict(FIRM, company_size=size, credit_rating=rating)
        r = E.evaluate(SPEC, PROJECT, [bidder(firm=f)])['results'][0]
        check(f'재정건실도 {size}/{rating}', by_id(r, 'credit.finance')['score'], want)
    f = dict(FIRM, credit_type='기업어음', credit_rating='A3-', company_size='대기업·중기업')
    r = E.evaluate(SPEC, PROJECT, [bidder(firm=f)])['results'][0]
    check('기업어음 A3- → BBB- 이상 구간', by_id(r, 'credit.finance')['score'], 3.0)


def test_dev_and_invest():
    rows = [{'type': '신기술'}, {'type': '특허', 'age_years': 12}, {'type': '실용신안', 'age_years': 7}, {'type': '연구보고서', 'age_years': 12}]
    f = dict(FIRM, dev_items=rows)
    r = E.evaluate(SPEC, PROJECT, [bidder(firm=f)])['results'][0]
    # 1.0 + 0.6×0.6 + 0.3×0.8 + 0.1×0(10년 이상 인정 안 됨) = 1.0 + 0.36 + 0.24 = 1.6
    check('개발실적(신기술·특허12년·실용신안7년·연구보고서12년)', by_id(r, 'tech.dev')['score'], 1.6)
    f = dict(FIRM, dev_items=[{'type': '신기술'}] * 3)
    r = E.evaluate(SPEC, PROJECT, [bidder(firm=f)])['results'][0]
    check('개발실적 상한 2점', by_id(r, 'tech.dev')['score'], 2.0)
    for inv, want in ((3.0, 2.0), (2.4, 1.8), (2.0, 1.6), (1.5, 1.4), (1.0, 1.2), (0.9, 0.0)):
        f = dict(FIRM, invest_amount=inv, sales_amount=200)
        r = E.evaluate(SPEC, PROJECT, [bidder(firm=f)])['results'][0]
        check(f'투자 {inv}/200억 = {inv / 2}%', by_id(r, 'tech.invest')['score'], want)


def test_bad_credit():
    t = {'bad_suspend': 0.2, 'bad_false': 1, 'bad_poor': 0, 'bad_other': 0}
    p = {**PERSONS, 'team': {**PERSONS['team'], **t}}
    r = E.evaluate(SPEC, PROJECT, [bidder(persons=p)])['results'][0]
    check('업무정지 0.2개월→1개월(0.2) + 거짓작성 1건(4) = 6 - 4.2', by_id(r, 'credit.bad')['score'], 1.8)
    t = {'bad_suspend': 0, 'bad_false': 2, 'bad_poor': 0, 'bad_other': 0}
    p = {**PERSONS, 'team': {**PERSONS['team'], **t}}
    r = E.evaluate(SPEC, PROJECT, [bidder(persons=p)])['results'][0]
    check('감점 합이 배점 초과 → 0점', by_id(r, 'credit.bad')['score'], 0.0)


def test_youth_and_etc():
    for rate, want in ((0.9, 0.0), (1.0, 0.1), (2.99, 0.2), (3, 0.3), (10, 0.3)):
        f = dict(FIRM, youth_rate=rate)
        r = E.evaluate(SPEC, PROJECT, [bidder(firm=f)])['results'][0]
        check(f'청년고용 {rate}%', r['bonus']['score'], want)
    p = {**PERSONS, 'team': {**PERSONS['team'], 'etc_points': -1.5}}
    r = E.evaluate(SPEC, PROJECT, [bidder(persons=p)])['results'][0]
    check('발주청 기타 감점 -1.5 반영', r['total'], round(75.85 - 1.5, 2))


def test_jv():
    m1 = {'name': '주관사', 'share': 60, 'firm': dict(FIRM)}
    m2 = {'name': '참여사', 'share': 40, 'firm': {}}
    b = {'name': 'JV', 'firm': {}, 'persons': PERSONS, 'members': [m1, m2]}
    out = E.evaluate(SPEC, PROJECT, [b])
    r = out['results'][0]
    check('JV 수행건수(5.6×0.6)', by_id(r, 'firm.cnt')['score'], 3.36)
    check('JV 재정건실도(3.0×0.6)', by_id(r, 'credit.finance')['score'], 1.8)
    check('JV 투자실적(2.0×0.6)', by_id(r, 'tech.invest')['score'], 1.2)
    check('JV 참여평가자는 팀 단위(그룹 A 불변)', r['group_scores']['A'], 51.97)
    check('JV 청년고용 가점(0.2×0.6)', r['bonus']['score'], 0.12)
    check('JV 부실평가(사업체 전체 기준)', by_id(r, 'credit.bad')['score'], 3.4)
    one = {'name': 'JV1', 'firm': {}, 'persons': PERSONS, 'members': [{'name': '단독', 'share': 100, 'firm': dict(FIRM)}]}
    check('JV 1개사(100%) = 단독 합계', E.evaluate(SPEC, PROJECT, [one])['results'][0]['total'], 75.85)


def test_missing_info():
    try:
        E.evaluate(SPEC, dict(PROJECT, complexity=None), [bidder()])
    except ValueError:
        print('OK   사업 구분 없으면 오류')
    else:
        failures.append('사업 구분 없음이 오류가 되지 않음')
    out = E.evaluate(SPEC, dict(PROJECT, overlap_base=None), [bidder()])
    assert any('2.5억원' in w for w in out['warnings']), out['warnings']
    print('OK   기준금액 미입력 시 2.5억원 기본 + 경고')


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
