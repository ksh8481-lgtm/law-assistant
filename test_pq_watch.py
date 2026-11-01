"""
pq_watch(PQ 평가기준 개정 감시) 검증 스크립트. `python test_pq_watch.py`로 실행한다. 네트워크 없이 가짜 응답으로 시험한다.
"""
import os
import sys
import tempfile
import xml.etree.ElementTree as ET

import pq_engine
import pq_watch

failures = []


def check(label, got, want):
    ok = got == want
    if not ok:
        failures.append(f'{label}: 기대 {want!r} / 실제 {got!r}')
    print(('OK  ' if ok else 'FAIL'), label, got)


def xml(*items):
    """items: (이름, 일련번호, 발령번호, 발령일자, 시행일자)"""
    body = ''.join(f'<admrul><행정규칙일련번호>{s}</행정규칙일련번호><행정규칙명><![CDATA[{n}]]></행정규칙명>'
                   f'<발령번호>{no}</발령번호><발령일자>{i}</발령일자><시행일자>{e}</시행일자></admrul>'
                   for n, s, no, i, e in items)
    return ET.fromstring(f'<AdmRulSearch>{body}</AdmRulSearch>'.encode('utf-8'))


def fake(versions, fail=()):
    """versions: {행정규칙명: 일련번호}. 검색어와 이름이 같은 것 + 이름만 비슷한 다른 고시를 함께 돌려준다."""
    def f(url):
        import urllib.parse
        q = urllib.parse.unquote(url.split('query=')[1].split('&')[0])
        if q in fail:
            return None
        items = [(n, s, '2099-1', '20990101', '20990102') for n, s in versions.items() if q in n]
        return xml(*items)
    return f


def current_serials():
    """명세에 적힌 값으로 만든 '아무 개정 없음' 상태."""
    v = {}
    for s in pq_engine.list_specs():
        src = pq_engine.load_spec(s['id'])['source']
        if src.get('law_name'):
            v[src['law_name']] = src['law_id']
    return v


def test_no_change():
    res = pq_watch.check(fake(current_serials()))
    st = {tuple(r['spec_ids']): r['status'] for r in res}
    check('감시 가능한 기준은 모두 최신', sorted(set(v for k, v in st.items() if k[0] in ('bangjae', 'env_assess', 'mof_cm', 'mlit_cm'))), ['ok'])
    check('경남 기준은 감시 불가', [r['status'] for r in res if r['spec_ids'][0].startswith('gyeongnam')], ['unwatched'] * 3)
    check('같은 고시를 쓰는 국토부 3개는 한 번에 묶임', [r['spec_ids'] for r in res if 'mlit_cm' in r['spec_ids']], [['mlit_cm', 'mlit_design', 'mlit_safe']])
    check('개정 없으면 보고서 없음', pq_watch.report_markdown(res), '')


def test_changed():
    v = current_serials()
    mlit_name = pq_engine.load_spec('mlit_cm')['source']['law_name']
    v[mlit_name] = '2100000999999'
    res = pq_watch.check(fake(v))
    ch = [r for r in res if r['status'] == 'changed']
    check('국토부 고시만 개정으로 감지', [r['spec_ids'] for r in ch], [['mlit_cm', 'mlit_design', 'mlit_safe']])
    check('새 일련번호 기록', ch[0]['new']['serial'], '2100000999999')
    md = pq_watch.report_markdown(res)
    check('보고서에 영향받는 명세 표시', 'mlit_design' in md and 'mlit_safe' in md, True)
    check('보고서에 확인 링크', 'admRulSeq=2100000999999' in md, True)
    check('보고서에 시행일 표시(2099-01-02)', '2099-01-02' in md, True)
    check('다른 기준은 보고서에 없음', 'env_assess' in md, False)


def test_similar_name_not_confused():
    """이름이 일부만 같은 다른 고시(조달청 고시 등)는 무시하고 이름이 정확히 같은 것만 비교한다."""
    v = current_serials()
    mlit_name = pq_engine.load_spec('mlit_cm')['source']['law_name']
    v['조달청 ' + mlit_name] = '2100000888888'
    res = pq_watch.check(fake(v))
    check('이름이 비슷한 다른 고시는 개정으로 오인하지 않음', [r['status'] for r in res if 'mlit_cm' in r['spec_ids']], ['ok'])


def test_lookup_failure_and_missing():
    v = current_serials()
    env_name = pq_engine.load_spec('env_assess')['source']['law_name']
    res = pq_watch.check(fake(v, fail=(env_name,)))
    check('조회 실패는 unknown(개정으로 보지 않음)', [r['status'] for r in res if r['spec_ids'] == ['env_assess']], ['unknown'])
    del v[env_name]
    res = pq_watch.check(fake(v))
    check('검색 결과에 없으면 unknown', [r['status'] for r in res if r['spec_ids'] == ['env_assess']], ['unknown'])
    check('조회 실패만으로는 보고서가 생기지 않음', pq_watch.report_markdown(res), '')


def test_main_writes_and_removes_report():
    v = current_serials()
    name = pq_engine.load_spec('mof_cm')['source']['law_name']
    path = os.path.join(tempfile.gettempdir(), 'pq_watch_test_report.md')
    orig = pq_watch.check
    try:
        v[name] = '2100000777777'
        pq_watch.check = lambda: orig(fake(v))
        check('main 종료 코드 0', pq_watch.main(['x', '--out', path]), 0)
        check('개정 시 보고서 파일 생성', os.path.exists(path) and 'mof_cm' in open(path, encoding='utf-8').read(), True)
        v[name] = pq_engine.load_spec('mof_cm')['source']['law_id']
        pq_watch.main(['x', '--out', path])
        check('개정 해소되면 보고서 파일 삭제', os.path.exists(path), False)
    finally:
        pq_watch.check = orig
        if os.path.exists(path):
            os.remove(path)


def _award_src():
    import award_engine
    return award_engine.load_spec('jibang_jeokgyeok_tech')['source']


def test_award_spec_is_watched():
    v = current_serials()
    src = _award_src()
    v[src['law_name']] = src['law_id']
    res = pq_watch.check(fake(v))
    check('적격심사 명세(낙찰자 결정기준)도 감시 대상', [r['status'] for r in res if r['spec_ids'] == ['award:jibang_jeokgyeok_tech']], ['ok'])


def test_award_change_report_lists_changed_numbers():
    v = current_serials()
    v[_award_src()['law_name']] = '2100000999999'
    res = pq_watch.check(fake(v))
    summary = {'ok': 25, 'diff': [{'key': 'pass_ge_10', 'label': '적격통과점수(추정가격 10억원 이상)', 'expected': 92, 'found': 90, 'status': 'diff'}],
               'unparsed': [], 'clean': False}
    calls = []
    pq_watch.attach_award_verification(res, lambda spec_id, serial: calls.append((spec_id, serial)) or summary)
    md = pq_watch.report_markdown(res)
    check('개정 시 새 일련번호로 숫자 대조 호출', calls, [('jibang_jeokgyeok_tech', '2100000999999')])
    check('보고서에 바뀐 값(92 → 90)', '명세 92 → 원문 90' in md, True)
    check('보고서에 명세 id', 'award:jibang_jeokgyeok_tech' in md, True)
    check('다른 PQ 기준은 보고서에 없음', 'mlit_cm' in md, False)


def test_award_clean_verification_says_numbers_unchanged():
    v = current_serials()
    v[_award_src()['law_name']] = '2100000999999'
    res = pq_watch.check(fake(v))
    pq_watch.attach_award_verification(res, lambda spec_id, serial: {'ok': 26, 'diff': [], 'unparsed': [], 'clean': True})
    md = pq_watch.report_markdown(res)
    check('숫자가 같으면 영향 없어 보인다고 알림', '모두 명세와 같습니다' in md, True)


def test_award_verification_failure_still_reports_amendment():
    v = current_serials()
    v[_award_src()['law_name']] = '2100000999999'
    res = pq_watch.check(fake(v))

    def boom(spec_id, serial):
        raise RuntimeError('다운로드 실패')
    pq_watch.attach_award_verification(res, boom)
    md = pq_watch.report_markdown(res)
    check('대조가 실패해도 개정 알림은 나간다', 'award:jibang_jeokgyeok_tech' in md, True)
    check('대조 실패 안내', '숫자 대조 실패' in md, True)


def test_upcoming_amendment_is_detected_and_past_versions_are_ignored():
    import urllib.parse
    name = pq_engine.load_spec('mlit_cm')['source']['law_name']
    base = fake(current_serials())

    def with_upcoming(effective):
        def f(url):
            if 'nw=3' in url and urllib.parse.unquote(url.split('query=')[1].split('&')[0]) == name:
                return xml((name, '2100000555555', '2099-5', '20990101', effective))
            return base(url)
        return f
    res = pq_watch.check(with_upcoming('20991231'), today='20261101')
    st = [r['status'] for r in res if 'mlit_cm' in r['spec_ids']]
    check('시행 예정 개정 감지', st, ['upcoming'])
    md = pq_watch.report_markdown(res)
    check('보고서에 시행 예정 표시', '시행 예정 개정' in md and '2100000555555' in md, True)
    res = pq_watch.check(with_upcoming('20200101'), today='20261101')
    check('이미 지난 다른 버전은 무시', [r['status'] for r in res if 'mlit_cm' in r['spec_ids']], ['ok'])


def test_spec_sources_have_names():
    for sid in ('bangjae', 'env_assess', 'mof_cm', 'mlit_design', 'mlit_cm', 'mlit_safe'):
        src = pq_engine.load_spec(sid)['source']
        check(sid + ' law_name·law_id 있음', bool(src.get('law_name')) and bool(src.get('law_id')), True)


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
