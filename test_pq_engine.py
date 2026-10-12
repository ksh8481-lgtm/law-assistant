"""
pq_engine(사업수행능력평가 점수 산정 엔진) 검증 스크립트.

pytest 없이 `python test_pq_engine.py`로 실행한다(이 저장소의 다른 test_*.py처럼 수동 실행용).
기대값은 고시 [별표]의 구간표와 별첨 6 예시를 손으로 계산한 값이다.
"""
import sys

import pq_engine as E

PROJECT = {
    'fields': [
        {'name': '수자원개발', 'pct': 75, 'kind': '필수'},
        {'name': '토질·지질', 'pct': 25, 'kind': '필수'},
    ],
    'apply_transfer_penalty': False,
    'rel_mode': '등급 직접 입력',
}

BIDDER_A = {
    'name': 'A사',
    'firm': {
        'perf5_d_cnt': 3, 'perf5_s_cnt': 2, 'perf5_d_amt': 40, 'perf5_s_amt': 10,
        'suspend_months': 1.5, 'tech_suspend_months': 0, 'bad_point_deduct': 0.3,
        'credit_type': '회사채', 'credit_rating': 'BBB0',
        'invest_amount': 4, 'sales_amount': 300, 'use_amount': 15,
        'new_hire_rate': 2.5,
        'dev_items': [
            {'type': '특허', 'age_years': 3, 'applicants': 1},
            {'type': '신기술'},
            {'type': '실용신안', 'age_years': 6, 'applicants': 1},
        ],
        'use_items': [{'type': '신기술'}, {'type': '특허'}],
        'prev_items': [
            {'cur_role': 'lead', 'tech_rate': 100, 'elapsed': 2, 'form_pct': '60', 'volume_pct': 50},
            {'cur_role': '수자원개발', 'tech_rate': 100, 'elapsed': 2, 'form_pct': '60', 'volume_pct': 50},
            {'cur_role': '토질·지질', 'tech_rate': 100, 'elapsed': 4, 'form_pct': '100', 'volume_pct': 100},
        ],
    },
    'persons': {
        'lead': {'eligible': True, 'grade': '기술사', 'career': 16, 'cnt_d': 10, 'cnt_s': 5, 'amt_d': 80, 'amt_s': 25,
                 'overlap': 250, 'tech_grade': '수', 'mgmt_grade': '우'},
        'field_lead': {
            '수자원개발': {'eligible': True, 'grade': '특급', 'career': 9, 'cnt_d': 7, 'cnt_s': 0, 'overlap': 450},
            '토질·지질': {'eligible': True, 'grade': '고급', 'career': 11, 'cnt_d': 3, 'cnt_s': 5, 'overlap': 350},
        },
        'field_member': {
            '수자원개발': {'eligible': True, 'grade': '고급', 'career': 6, 'cnt_d': 5, 'cnt_s': 0},
            '토질·지질': {'eligible': True, 'grade': '중급', 'career': 3, 'cnt_d': 3, 'cnt_s': 0},
        },
    },
}

failures = []


def check(label, got, want, tol=1e-9):
    ok = abs(got - want) <= tol if isinstance(want, (int, float)) else got == want
    if not ok:
        failures.append(f'{label}: 기대 {want} / 실제 {got}')
    print(('OK  ' if ok else 'FAIL'), label, got)


def by_id(res, iid):
    return next(i for i in res['items'] if i['id'] == iid)


def test_full_bidder():
    out = E.evaluate('bangjae', PROJECT, [BIDDER_A])
    r = out['results'][0]
    # 손계산(고시 구간표) 기대값
    expected = {
        'lead.grade': 6.00, 'lead.career': 6.00, 'lead.perf_cnt': 3.60, 'lead.perf_amt': 4.00,
        'lead.tech': 1.50, 'lead.mgmt': 1.35,
        'fl.grade': 5.25, 'fl.career': 5.55, 'fl.perf': 4.00,
        'fm.grade': 4.88, 'fm.career': 4.75, 'fm.perf': 2.85,
        'prev.service': 0.34,
        'firm.perf_cnt': 7.20, 'firm.perf_amt': 6.30,
        'credit.penalty': 4.30, 'credit.finance': 3.00,
        'tech.dev': 2.90, 'tech.invest': 5.40, 'tech.use': 1.75,
        'ovl.lead': 5.00, 'ovl.fl': 4.95,
    }
    for iid, want in expected.items():
        check(f'항목 {iid}', by_id(r, iid)['score'], want, 1e-9)
    check('그룹 A', r['group_scores']['A'], 50.07)
    check('그룹 B', r['group_scores']['B'], 13.50)
    check('그룹 C', r['group_scores']['C'], 7.30)
    check('그룹 D', r['group_scores']['D'], 10.05)
    check('그룹 E', r['group_scores']['E'], 9.95)
    check('가점', r['bonus']['score'], 0.20)
    check('합계', r['total'], 91.07)
    check('경고 없음', len(out['warnings']), 0)


def test_attachment6_example():
    """고시 별첨 6: 배점 0.5 x 분야별 100% x 기술인 100% x 발주형태 60% x 사업량 50% = 0.15."""
    b = {'name': 'x', 'firm': {'prev_items': [
        {'cur_role': 'lead', 'tech_rate': 100, 'elapsed': 1, 'form_pct': '60', 'volume_pct': 50}]}, 'persons': {}}
    r = E.evaluate('bangjae', PROJECT, [b])['results'][0]
    check('별첨6 사업책임 예시(0.15)', by_id(r, 'prev.service')['score'], 0.15)
    # 사업책임 갑(전차 사업책임 33%) 사례: 0.5 x 100% x 33% x 60% x 50% = 0.0495 -> 0.05
    b['firm']['prev_items'][0]['tech_rate'] = 33
    r = E.evaluate('bangjae', PROJECT, [b])['results'][0]
    check('별첨6 기술인 33% 예시(0.05)', by_id(r, 'prev.service')['score'], 0.05)


def test_elapsed_buckets():
    for el, want in ((3, 0.5), (3.01, 0.3), (5, 0.3), (5.01, 0.1), (10, 0.1), (10.01, 0.0)):
        b = {'name': 'x', 'firm': {'prev_items': [
            {'cur_role': 'lead', 'tech_rate': 100, 'elapsed': el, 'form_pct': '100', 'volume_pct': 100}]}, 'persons': {}}
        r = E.evaluate('bangjae', PROJECT, [b])['results'][0]
        check(f'전차용역 경과 {el}년', by_id(r, 'prev.service')['score'], want)


def test_tier_boundaries():
    cases = [  # (경력 년, 기대 %)
        (15, 100), (14.99, 90), (13, 90), (12.99, 80), (11, 80), (10.99, 70), (9, 70), (8.99, 60), (0, 60)]
    for yrs, pct in cases:
        b = {'name': 'x', 'firm': {}, 'persons': {'lead': {'eligible': True, 'grade': '기술사', 'career': yrs}}}
        r = E.evaluate('bangjae', PROJECT, [b])['results'][0]
        check(f'사업책임 경력 {yrs}년 -> {pct}%', by_id(r, 'lead.career')['score'], 6.0 * pct / 100)
    for ov, pct in ((299.9, 100), (300, 90), (399.9, 90), (400, 80), (599.9, 70), (600, 60)):
        b = {'name': 'x', 'firm': {}, 'persons': {'lead': {'eligible': True, 'overlap': ov}}}
        r = E.evaluate('bangjae', PROJECT, [b])['results'][0]
        check(f'업무중복도 {ov}% -> {pct}%', by_id(r, 'ovl.lead')['score'], 5.0 * pct / 100)


def test_extra_field_overlap_tiers():
    """추가기술인은 400/500/600/700% 구간을 쓴다."""
    proj = {'fields': [{'name': '수자원개발', 'pct': 100, 'kind': '추가'}]}
    b = {'name': 'x', 'firm': {}, 'persons': {'field_lead': {'수자원개발': {'eligible': True, 'overlap': 399}}}}
    r = E.evaluate('bangjae', proj, [b])['results'][0]
    check('추가기술인 중복도 399% -> 100%', by_id(r, 'ovl.fl')['score'], 6.0)


def test_eligibility_zero():
    b = {'name': 'x', 'firm': {}, 'persons': {'lead': {'eligible': False, 'grade': '기술사', 'career': 20, 'cnt_d': 20,
                                                       'amt_d': 200}}}
    r = E.evaluate('bangjae', PROJECT, [b])['results'][0]
    for iid in ('lead.grade', 'lead.career', 'lead.perf_cnt', 'lead.perf_amt'):
        check(f'요건 미충족 {iid}', by_id(r, iid)['score'], 0.0)


def test_blank_vs_zero():
    """빈 값은 0점 처리 + 경고, 0을 입력하면 구간 최저(60%)."""
    blank = {'name': 'x', 'firm': {}, 'persons': {'lead': {'eligible': True, 'grade': '기술사'}}}
    out = E.evaluate('bangjae', PROJECT, [blank])
    check('경력 빈 값 -> 0점', by_id(out['results'][0], 'lead.career')['score'], 0.0)
    assert any('경력 미입력' in w for w in out['warnings']), out['warnings']
    zero = {'name': 'x', 'firm': {}, 'persons': {'lead': {'eligible': True, 'grade': '기술사', 'career': 0}}}
    out = E.evaluate('bangjae', PROJECT, [zero])
    check('경력 0년 -> 60%', by_id(out['results'][0], 'lead.career')['score'], 3.6)


def test_transfer_penalty():
    proj = dict(PROJECT, apply_transfer_penalty=True)
    b = {'name': 'x', 'firm': {}, 'persons': {'lead': {'eligible': True, 'grade': '기술사', 'transfer': '3개월 미만'}}}
    r = E.evaluate('bangjae', proj, [b])['results'][0]
    check('이적 3개월 미만 x0.95', by_id(r, 'lead.grade')['score'], 6.0 * 0.95)


def test_credit_paper_mapping():
    for ctype, rating, want in (('기업어음', 'A3-', 3.0), ('기업어음', 'A3-'.replace('A3-', 'A3-'), 3.0),
                                ('기업어음', 'B+', 2.8), ('기업어음', 'C 이하', 2.1), ('회사채', 'CCC+ 이하', 2.1),
                                ('회사채', 'B-', 2.8), ('회사채', 'BBB-', 3.0), ('미제출', '', 0.0)):
        b = {'name': 'x', 'firm': {'credit_type': ctype, 'credit_rating': rating}, 'persons': {}}
        r = E.evaluate('bangjae', PROJECT, [b])['results'][0]
        check(f'신용 {ctype} {rating}', by_id(r, 'credit.finance')['score'], want)


def test_relative_distribution_and_grades():
    spec = E.load_spec('bangjae')
    for n, dist in spec['scoring']['relative_distribution'].items():
        assert sum(dist) == int(n), (n, dist)
    g = E.relative_grades({'a': 90, 'b': 80, 'c': 70, 'd': 60, 'e': 50}, spec)
    check('5개사 상대평가 등급', [g[k] for k in 'abcde'], ['수', '우', '우', '미', '양'])
    g = E.relative_grades({'a': 90, 'b': 90, 'c': 50}, spec)
    check('동점은 같은 등급', g['a'] == g['b'], True)
    g = E.relative_grades({'a': 90, 'b': None}, spec)
    check('미제출 등급', g['b'], '미제출')


def test_adjust_range_warning():
    proj = dict(PROJECT, adjust={'lead.grade': 8.0})   # 6.0의 +33% -> 허용 범위(+20%) 초과
    out = E.evaluate('bangjae', proj, [BIDDER_A])
    assert any('고시 허용 범위' in w for w in out['warnings']), out['warnings']
    assert any('배점 합계' in w for w in out['warnings']), out['warnings']
    print('OK   배점 조정 허용범위/합계 경고')


def test_ranking():
    b2 = {'name': 'B사', 'firm': {}, 'persons': {}}
    out = E.evaluate('bangjae', PROJECT, [b2, BIDDER_A])
    check('A사 1위', out['results'][1]['rank'], 1)
    check('B사 2위', out['results'][0]['rank'], 2)


def _jv_bidder(members):
    firm_a = {k: v for k, v in BIDDER_A['firm'].items() if k != 'prev_items'}
    team_firm = {'prev_items': BIDDER_A['firm']['prev_items']}
    mem = []
    for name, share, kind in members:
        mem.append({'name': name, 'share': share, 'firm': firm_a if kind == 'A' else {}})
    return {'name': 'JV', 'firm': team_firm, 'persons': BIDDER_A['persons'], 'members': mem}


def test_jv_single_member_equals_single():
    """구성원 1개사(지분 100%)는 단독 입찰과 같은 결과여야 한다."""
    out = E.evaluate('bangjae', PROJECT, [_jv_bidder([('가', 100, 'A')])])
    r = out['results'][0]
    check('JV 1개사 합계 = 단독 합계', r['total'], 91.07)
    for iid in ('firm.perf_cnt', 'credit.penalty', 'tech.invest', 'lead.grade', 'prev.service', 'ovl.fl'):
        check(f'JV 1개사 항목 {iid}', by_id(r, iid)['score'], by_id(E.evaluate('bangjae', PROJECT, [BIDDER_A])['results'][0], iid)['score'])


def test_jv_share_weighted():
    """A사 실적(지분 60%) + 빈 서류 구성원(지분 40%): 대행자 항목만 지분율 가중, 기술인 항목은 팀 단위 그대로."""
    out = E.evaluate('bangjae', PROJECT, [_jv_bidder([('가', 60, 'A'), ('나', 40, 'B')])])
    r = out['results'][0]
    check('JV 나. 대행자 수행실적', r['group_scores']['B'], 8.10)
    check('JV 다. 신용도(구성원별 점수×지분: 4.30×0.6+5×0.4 + 3×0.6)', r['group_scores']['C'], 6.38)
    check('JV 라. 기술개발', r['group_scores']['D'], 6.03)
    check('JV 가. 참여기술인(팀 단위, 지분 무관)', r['group_scores']['A'], 50.07)
    check('JV 마. 업무중복도(팀 단위)', r['group_scores']['E'], 9.95)
    check('JV 가점(0.2×0.6)', r['bonus']['score'], 0.12)
    check('JV 합계', r['total'], 80.65)
    check('JV 구성원 수', len(r['members']), 2)
    assert any('[구성원 나]' in w for w in out['warnings']), out['warnings']
    print('OK   JV 구성원 서류 미입력 경고에 구성원 이름 표시')


def test_jv_share_validation():
    out = E.evaluate('bangjae', PROJECT, [_jv_bidder([('가', 50, 'A'), ('나', 30, 'A')])])
    assert any('지분율 합계가 80' in w for w in out['warnings']), out['warnings']
    check('JV 지분 합 80% → 비율 환산(둘 다 A이므로 단독과 동일)', out['results'][0]['total'], 91.07)
    try:
        E.evaluate('bangjae', PROJECT, [_jv_bidder([('가', None, 'A')])])
    except ValueError:
        print('OK   JV 지분율 없으면 오류')
    else:
        failures.append('JV 지분율 없음이 오류가 되지 않음')


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
