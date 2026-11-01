"""
사업수행능력평가(PQ)·적격심사 평가기준 개정 감시.

PQ 명세(pq_specs/*.json)와 적격심사 명세(award_specs/*.json)의 배점·구간표는 고시·예규의 특정 시행 버전을 옮겨 둔 값이라,
기준이 개정돼도 저절로 바뀌지 않는다. 이 모듈은 명세의 source.law_name(행정규칙명)·source.law_id(행정규칙일련번호)로 법제처에서
현재 시행 중인 버전을 조회해서, 명세에 적힌 버전과 다르면 "개정됨"으로 알려 준다. 행정규칙일련번호는 개정될 때마다 새로 부여된다.
아직 시행 전인 개정본(시행 예정)도 함께 찾아 미리 알려 준다.

경상남도 기준처럼 법제처에 없는 기준(law_name 없음)은 감시하지 못한다.

적격심사 명세(「지방자치단체 입찰시 낙찰자 결정기준」)는 개정이 감지되면 새 PDF를 받아 명세의 숫자(적격통과점수 92·95점,
PQ 환산 배점, 입찰가격 산식 등)가 원문과 같은지 대조해 "바뀐 값"만 보고서에 적는다(award_check.py). 이 예규는 다른 장(물품·공사 등)의
개정이 잦아서, 숫자 대조가 없으면 관련 없는 개정에도 매번 사람이 486쪽을 확인해야 한다.

사용: python pq_watch.py [--out 보고서.md]
  개정이 감지되면 --out 파일에 마크다운 보고서를 쓴다(워크플로가 이 파일로 GitHub 이슈를 만든다).
  종료 코드는 항상 0이다(감시 때문에 일일 크롤링이 실패로 보이지 않게 한다).
"""
import datetime
import json
import os
import sys
import urllib.parse

import award_engine
import crawler  # fetch_law_xml(재시도·시간 제한), _norm(법령명 비교)
import pq_engine

API_KEY = crawler.API_KEY
SEARCH = 'https://www.law.go.kr/DRF/lawSearch.do?OC={key}&target=admrul&type=XML&query={q}&display=50'


def _items(root, law_name):
    """검색 결과에서 law_name과 이름이 같은 행정규칙들의 {serial, name, issue_no, issued, effective} 목록."""
    want = crawler._norm(law_name)
    out = []
    for a in root.findall('.//admrul'):
        name = (a.findtext('행정규칙명') or '').strip()
        if crawler._norm(name) == want:
            out.append({'serial': (a.findtext('행정규칙일련번호') or '').strip(), 'name': name,
                        'issue_no': (a.findtext('발령번호') or '').strip(),
                        'issued': (a.findtext('발령일자') or '').strip(),
                        'effective': (a.findtext('시행일자') or '').strip()})
    return out


def current_version(law_name, fetch=None):
    """법제처에서 law_name과 이름이 같은 현행 행정규칙의 {serial, name, issue_no, issued, effective}. 못 찾으면 None."""
    fetch = fetch or crawler.fetch_law_xml
    root = fetch(SEARCH.format(key=API_KEY, q=urllib.parse.quote(law_name)))
    if root is None:
        return None
    found = _items(root, law_name)
    return found[0] if found else None


def upcoming_version(law_name, have_serial, today=None, fetch=None):
    """아직 시행 전인 개정본(명세 버전과 다른 일련번호 중 시행일이 오늘보다 뒤인 것)의 {serial,...}. 없거나 조회 실패면 None."""
    fetch = fetch or crawler.fetch_law_xml
    root = fetch(SEARCH.format(key=API_KEY, q=urllib.parse.quote(law_name)) + '&nw=3')
    if root is None:
        return None
    today = today or datetime.date.today().strftime('%Y%m%d')
    for it in _items(root, law_name):
        if it['serial'] and it['serial'] != have_serial and it['effective'] > today:
            return it
    return None


def _date(s):
    s = (s or '').strip()
    return f'{s[:4]}-{s[4:6]}-{s[6:]}' if len(s) == 8 and s.isdigit() else s


def _watched_specs():
    """감시할 모든 명세: PQ 명세와 적격심사 명세. 적격심사 명세의 id에는 'award:'를 붙여 구분한다."""
    out = []
    for s in pq_engine.list_specs():
        sp = pq_engine.load_spec(s['id'])
        out.append({'id': sp['id'], 'short': sp['short'], 'source': sp.get('source', {})})
    for s in award_engine.list_specs():
        sp = award_engine.load_spec(s['id'])
        out.append({'id': 'award:' + sp['id'], 'short': sp['short'], 'source': sp.get('source', {})})
    return out


def check(fetch=None, today=None):
    """감시 대상 기준마다 {status: ok|changed|upcoming|unknown|unwatched, ...}. 같은 고시를 쓰는 명세는 한 번만 조회한다."""
    groups = {}
    out = []
    for sp in _watched_specs():
        src = sp['source']
        if not src.get('law_name') or not src.get('law_id'):
            out.append({'status': 'unwatched', 'spec_ids': [sp['id']], 'name': sp['short'], 'issuer': src.get('issuer', '')})
            continue
        groups.setdefault((src['law_name'], src['law_id']), []).append(sp)
    for (law_name, law_id), specs in groups.items():
        src = specs[0]['source']
        item = {'spec_ids': [sp['id'] for sp in specs], 'name': law_name, 'issuer': src.get('issuer', ''),
                'have_serial': law_id, 'have_effective': src.get('effective', '')}
        cur = current_version(law_name, fetch)
        if cur is None:
            item['status'] = 'unknown'
        elif cur['serial'] == law_id:
            item['status'] = 'ok'
            up = upcoming_version(law_name, law_id, today, fetch)
            if up:
                item.update(status='upcoming', new=up)
        else:
            item.update(status='changed', new=cur)
        out.append(item)
    return out


def report_markdown(results):
    """개정(현행 변경 또는 시행 예정)이 감지된 기준별 안내문(마크다운). 없으면 빈 문자열."""
    lines = []
    for r in results:
        if r['status'] not in ('changed', 'upcoming'):
            continue
        n = r['new']
        upcoming = r['status'] == 'upcoming'
        lines += [
            f"### {r['name']}" + (' (시행 예정 개정)' if upcoming else ''),
            f"- 영향받는 평가기준: {', '.join(r['spec_ids'])}",
            f"- 명세에 반영된 버전: {r['issuer']} (시행 {r['have_effective']}, 행정규칙일련번호 {r['have_serial']})",
            (f"- 법제처의 {'시행 예정' if upcoming else '현행'} 버전: 발령번호 {n['issue_no'] or '-'} "
             f"(발령 {_date(n['issued'])}, 시행 {_date(n['effective'])}, 행정규칙일련번호 {n['serial']})"),
            f"- 확인: https://www.law.go.kr/LSW/admRulInfoP.do?admRulSeq={n['serial']}",
        ]
        lines += r.get('verify_lines', [])
        lines.append('')
    if not lines:
        return ''
    head = ['고시·예규가 개정(또는 개정 예정)돼 점수 산정 명세의 배점·구간표가 최신 기준과 다를 수 있습니다.',
            '개정 내용을 확인해 `pq_specs/*.json`(PQ) 또는 `award_specs/*.json`(적격심사)과 테스트를 고친 뒤, 명세의 source(law_id·effective·issuer)를 '
            '새 버전으로 바꾸면 이 알림이 멈춥니다. 시행 예정 개정은 시행일 전에 미리 반영해 두세요.', '']
    return '\n'.join(head + lines)


def attach_award_verification(results, verify=None):
    """개정된 적격심사 명세마다 새 예규 PDF의 숫자를 명세와 대조한 결과를 r['verify_lines']에 붙인다. 실패해도 알림은 막지 않는다.
    verify(spec_id, 행정규칙일련번호) -> award_check.summarize() 결과. 시험에서는 가짜를 넣는다."""
    import award_check
    verify = verify or award_check.verify_online
    for r in results:
        if r['status'] not in ('changed', 'upcoming'):
            continue
        award_ids = [i.split(':', 1)[1] for i in r['spec_ids'] if i.startswith('award:')]
        for spec_id in award_ids:
            try:
                r.setdefault('verify_lines', []).extend(award_check.report_lines(verify(spec_id, r['new']['serial'])))
            except Exception as e:
                r.setdefault('verify_lines', []).append(
                    f"- 숫자 대조 실패: 새 예규 PDF를 받거나 읽지 못했습니다({type(e).__name__}: {e}). 위 링크의 개정 내용을 직접 확인해 주세요.")


def main(argv):
    out_path = argv[argv.index('--out') + 1] if '--out' in argv else None
    results = check()
    attach_award_verification(results)
    changed = [r for r in results if r['status'] in ('changed', 'upcoming')]
    for r in results:
        label = {'ok': '최신', 'changed': '개정됨', 'upcoming': '시행 예정 개정 있음', 'unknown': '조회 실패',
                 'unwatched': '감시 불가(법제처 외 기준)'}[r['status']]
        print(f"[PQ 기준 감시] {label}: {r['name']} ({', '.join(r['spec_ids'])})", flush=True)
        if r['status'] in ('changed', 'upcoming'):
            n = r['new']
            kind = '시행 예정 개정' if r['status'] == 'upcoming' else '개정'
            print(f"::warning::평가기준 {kind} 감지: {r['name']} - 발령번호 {n['issue_no']} (시행 {_date(n['effective'])}). "
                  f"명세 반영 버전은 {r['issuer']}(시행 {r['have_effective']})입니다.", flush=True)
            for line in r.get('verify_lines', []):
                print(f"[PQ 기준 감시]   {line}", flush=True)
        elif r['status'] == 'unknown':
            print(f"::warning::평가기준 '{r['name']}'의 현행 버전을 조회하지 못했습니다(다음 실행에서 다시 확인).", flush=True)
    md = report_markdown(results)
    if out_path:
        if md:
            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(md)
        elif os.path.exists(out_path):
            os.remove(out_path)
    print(f"[PQ 기준 감시] 개정 감지 {len(changed)}건", flush=True)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv))
    except Exception as e:  # 감시 실패가 크롤링 결과를 망치지 않게
        print(f"::warning::PQ 기준 감시 중 예외: {e!r}", flush=True)
        sys.exit(0)
