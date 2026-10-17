"""
국토교통부 고시(제2025-387호) 3개 별표 평가기준과 발주청 구간표 직접 입력 기능 검증 스크립트.
`python test_pq_mlit.py`로 실행한다.

1) 구간표 기본값은 경상남도 기준과 같으므로, 경상남도 검증 스크립트(test_pq_design/cm/safe)를
   국토부 고시 명세(mlit_design/mlit_cm/mlit_safe)로 그대로 다시 돌려 같은 결과가 나오는지 확인한다.
2) 구간표를 바꿔 입력하면 손으로 계산한 값대로 점수가 바뀌는지, 잘못된 입력은 거부되는지 확인한다.
"""
import copy
import sys

import pq_engine as E
import test_pq_cm
import test_pq_design
import test_pq_safe

failures = []


def check(label, got, want, tol=1e-9):
    ok = abs(got - want) <= tol if isinstance(want, (int, float)) and not isinstance(want, bool) else got == want
    if not ok:
        failures.append(f'{label}: 기대 {want} / 실제 {got}')
    print(('OK  ' if ok else 'FAIL'), label, got)


def rejects(label, spec_id, project, bidders, overrides, text=None):
    try:
        E.evaluate(spec_id, project, bidders, overrides)
    except E.OverrideError as e:
        ok = text is None or text in str(e)
        if not ok:
            failures.append(f'{label}: 오류 문구 불일치 - {e}')
        print(('OK  ' if ok else 'FAIL'), label, '→', e)
    else:
        failures.append(f'{label}: 거부되지 않음')
        print('FAIL', label)


def run_suite(mod, spec_id):
    """경상남도용 검증 스크립트의 모든 test_*를 국토부 고시 명세로 다시 실행."""
    mod.SPEC = spec_id
    n0 = len(mod.failures)
    tests = [v for k, v in sorted(vars(mod).items()) if k.startswith('test_') and callable(v)]
    for t in tests:
        t()
    new = mod.failures[n0:]
    if new:
        failures.extend(f'[{spec_id}] {f}' for f in new)
    print(f'--- {spec_id}: {len(tests)}개 시험 묶음 재실행, 실패 {len(new)}건')
    mod.SPEC = {'mlit_design': 'gyeongnam_design', 'mlit_cm': 'gyeongnam_cm', 'mlit_safe': 'gyeongnam_safe'}[spec_id]


def test_same_as_gyeongnam():
    run_suite(test_pq_design, 'mlit_design')
    run_suite(test_pq_cm, 'mlit_cm')
    run_suite(test_pq_safe, 'mlit_safe')


def test_spec_metadata():
    for sid in ('mlit_design', 'mlit_cm', 'mlit_safe'):
        sp = E.load_spec(sid)
        check(sid + ' 발령번호', sp['source']['issuer'], '국토교통부 고시 제2025-387호')
        check(sid + ' 법령ID', sp['source']['law_id'], '2100000261414')
        check(sid + ' 배점 합계', sum(i['max'] for i in sp['items']) - sum(i['max'] for i in sp['items'] if i.get('dynamic')) > 0, True)
        # 선언한 모든 행의 경로가 실제 값이고, 배점 조정 범위(±20%)가 고시와 같음
        check(sid + ' 배점 조정 범위', sp['adjust_pct'], 20)
        for rid, (t, r) in E.editable_rows(sp).items():
            v = sp
            for k in r['path']:
                v = v[k]
            ok = isinstance(v, (int, float)) or (isinstance(v, list) and all(isinstance(x, (int, float)) for x in v))
            if not ok:
                failures.append(f'{sid} {rid}: 숫자(목록)가 아님 {v}')
    print('OK   명세 메타데이터·편집 가능 행 경로')


def test_design_override_changes_score():
    d = test_pq_design
    base = E.evaluate('mlit_design', d.PROJECT, [d.bidder()])['results'][0]
    check('기본값 합계', base['total'], 87.08)
    # 책임기술인 경력 15.5년: 기본(15 이상=100%) → 새 기준 [16,14,12,10] → 14 이상 90%
    ov = {'grid.lead.career': [16, 14, 12, 10]}
    r = E.evaluate('mlit_design', d.PROJECT, [d.bidder()], ov)
    item = d.by_id(r['results'][0], 'lead.career')
    check('책임 경력 점수(4점×90%×이적 감점 0.9)', item['score'], 3.24)
    check('합계 = 87.08 - (3.6 - 3.24)', r['results'][0]['total'], 86.72)
    check('변경 표 기록', r['custom_tables'], ['책임기술인 경력'])
    check('근거 문장에 새 기준 반영', '16' in item['basis'], True)
    # 원본 명세는 바뀌지 않는다
    again = E.evaluate('mlit_design', d.PROJECT, [d.bidder()])['results'][0]
    check('덮어쓰기 후 원본 명세 불변', again['total'], 87.08)
    check('덮어쓰지 않으면 custom_tables 없음', 'custom_tables' in E.evaluate('mlit_design', d.PROJECT, [d.bidder()]), False)
    same = E.evaluate('mlit_design', d.PROJECT, [d.bidder()], {'grid.lead.career': [15, 14, 13, 12]})
    check('기본값과 같은 입력은 변경으로 보지 않음', 'custom_tables' in same, False)
    # 분야별 책임기술인 등급 점수와 전문분야 외 인정률
    r2 = E.evaluate('mlit_design', d.PROJECT, [d.bidder()], {'grade.fl.고급': 3})
    check('분야별 책임 고급 등급 점수 4→3 반영', d.by_id(r2['results'][0], 'fl.grade')['score'] < d.by_id(base, 'fl.grade')['score'], True)
    r3 = E.evaluate('mlit_design', d.PROJECT, [d.bidder()], {'other.fl': 0.6})
    check('전문분야 외 인정률 0.6 → 분야별 책임 경력·실적 낮아지거나 같음',
          d.by_id(r3['results'][0], 'fl.career')['score'] <= d.by_id(base, 'fl.career')['score'], True)


def test_cm_override_changes_score():
    c = test_pq_cm
    base = E.evaluate('mlit_cm', c.PROJECT, [c.bidder()])['results'][0]
    check('CM 기본값 합계', base['total'], 87.41)
    sp = E.load_spec('mlit_cm')
    # 모든 구간표를 한 단계 높은 기준으로 바꾸면 점수는 같거나 낮아진다
    ov = {}
    for rid, (t, r) in E.editable_rows(sp).items():
        if rid.endswith('.cost_min'):
            continue
        v = sp
        for k in r['path']:
            v = v[k]
        if isinstance(v, list):
            ov[rid] = [x * 2 for x in v]
    r = E.evaluate('mlit_cm', c.PROJECT, [c.bidder()], ov)['results'][0]
    check('CM 기준을 2배로 올리면 점수 하락', r['total'] < base['total'], True)
    # 기준을 모두 0으로 낮추면 경력·실적 항목은 만점
    ov0 = {}
    for rid, (t, r_) in E.editable_rows(sp).items():
        if rid.endswith('.cost_min'):
            continue
        v = sp
        for k in r_['path']:
            v = v[k]
        ov0[rid] = [0] * len(v)
    r0 = E.evaluate('mlit_cm', c.PROJECT, [c.bidder()], ov0)['results'][0]
    for iid in ('lead.career', 'lead.perf', 'fm.career', 'fm.perf'):
        it = c.by_id(r0, iid)
        check(f'기준 0 → {iid} 만점', it['score'], it['max'])
    # 공사규모 구간 하한 변경: 마지막 칸 0 고정
    rejects('CM 마지막 구간 하한은 0', 'mlit_cm', c.PROJECT, [c.bidder()], {'lead_career.cost_min': [1000, 500, 300, 100]}, '마지막 칸은 0')
    ok = E.evaluate('mlit_cm', c.PROJECT, [c.bidder()], {'lead_career.cost_min': [2000, 800, 300, 0]})
    check('CM 공사규모 하한 변경 허용', ok['custom_tables'], ['구간별 해당공사규모 하한(억원 이상)'])


def test_safe_override_changes_score():
    s = test_pq_safe
    base = E.evaluate('mlit_safe', s.PROJECT, [s.bidder()])['results'][0]
    check('안전 기본값 합계', base['total'], 83.56)
    ov = {'overlap.lead': [6, 9, 12, 15]}
    r = E.evaluate('mlit_safe', s.PROJECT, [s.bidder()], ov)['results'][0]
    check('중첩 기준을 더 엄격하게 하면 점수 같거나 하락', r['total'] <= base['total'], True)
    r2 = E.evaluate('mlit_safe', s.PROJECT, [s.bidder()], {'grid.sim.cnt': [0, 0, 0, 0]})['results'][0]
    check('유사실적 건수 기준 0 → 만점', s_item(r2, 'sim.cnt')['score'], s_item(r2, 'sim.cnt')['max'])
    rejects('중첩 기준은 오름차순', 'mlit_safe', s.PROJECT, [s.bidder()], {'overlap.lead': [12, 9, 15, 18]}, '커지거나')


def s_item(res, iid):
    return next(i for i in res['items'] if i['id'] == iid)


def test_invalid_overrides():
    d = test_pq_design
    P, B = d.PROJECT, [d.bidder()]
    rejects('알 수 없는 행', 'mlit_design', P, B, {'nope': [1, 2, 3, 4]}, '수정할 수 없는')
    rejects('고시 고정 표는 수정 불가(수행성과)', 'mlit_design', P, B, {'result': [1, 2]}, '수정할 수 없는')
    rejects('개수 불일치', 'mlit_design', P, B, {'grid.lead.career': [15, 14, 13]}, '4개')
    rejects('숫자 아님', 'mlit_design', P, B, {'grid.lead.career': [15, 'a', 13, 12]}, '숫자')
    rejects('음수', 'mlit_design', P, B, {'grid.lead.career': [15, 14, 13, -1]}, '작을 수 없')
    rejects('내림차순 위반', 'mlit_design', P, B, {'grid.lead.career': [10, 14, 13, 12]}, '작아지거나')
    rejects('NaN', 'mlit_design', P, B, {'grid.lead.career': [15, float('nan'), 13, 12]}, '숫자')
    rejects('불리언', 'mlit_design', P, B, {'grid.lead.career': [True, 14, 13, 12]}, '숫자')
    rejects('스칼라 자리에 목록', 'mlit_design', P, B, {'other.fl': [0.8]}, '숫자 하나')
    rejects('목록 자리에 스칼라', 'mlit_design', P, B, {'grid.lead.career': 5}, '4개')
    rejects('등급 점수가 배점 초과', 'mlit_design', P, B, {'grade.lead.특급': 3.5}, '보다 클 수 없')
    rejects('전문분야 외 인정률 60% 미만', 'mlit_design', P, B, {'other.lead': 0.5}, '작을 수 없')
    rejects('전문분야 외 인정률 100% 초과', 'mlit_design', P, B, {'other.fm': 1.2}, '보다 클 수 없')
    rejects('형식 오류', 'mlit_design', P, B, [1, 2], '형식')
    # 경상남도 명세에는 구간표 입력이 없다
    rejects('구간표 입력 미지원 명세', 'gyeongnam_design', P, B, {'grid.lead.career': [15, 14, 13, 12]}, '수정할 수 없는')
    # 빈 입력·None은 그대로 통과
    check('None 입력 통과', E.evaluate('mlit_design', P, B, None)['results'][0]['total'], 87.08)
    check('빈 dict 입력 통과', E.evaluate('mlit_design', P, B, {})['results'][0]['total'], 87.08)


def test_override_with_jv():
    d = test_pq_design
    one = d.bidder(members=[{'name': 'A', 'share': 100, 'firm': dict(d.FIRM)}])
    one['firm'] = {}
    # 구성원별 계산에도 같은 구간표가 쓰인다(국토부 명세 단독 입력과 같은 결과)
    ov = {'grid.sim.cnt': [20, 15, 10, 5]}
    solo = E.evaluate('mlit_design', d.PROJECT, [d.bidder()], ov)['results'][0]
    jv = E.evaluate('mlit_design', d.PROJECT, [one], ov)['results'][0]
    check('공동수급체 1개사(100%) = 단독(구간표 변경 시)', jv['total'], solo['total'])


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
