"""
사업수행능력평가(PQ) 평가기준 개정 감시.

PQ 명세(pq_specs/*.json)의 배점·구간표는 고시의 특정 시행 버전을 옮겨 둔 값이라, 고시가 개정돼도 저절로 바뀌지 않는다.
이 모듈은 명세의 source.law_name(행정규칙명)·source.law_id(행정규칙일련번호)로 법제처에서 현재 시행 중인 버전을 조회해서,
명세에 적힌 버전과 다르면 "개정됨"으로 알려 준다. 행정규칙일련번호는 개정될 때마다 새로 부여된다.

경상남도 기준처럼 법제처에 없는 기준(law_name 없음)은 감시하지 못한다.

사용: python pq_watch.py [--out 보고서.md]
  개정이 감지되면 --out 파일에 마크다운 보고서를 쓴다(워크플로가 이 파일로 GitHub 이슈를 만든다).
  종료 코드는 항상 0이다(감시 때문에 일일 크롤링이 실패로 보이지 않게 한다).
"""
import json
import os
import sys
import urllib.parse

import crawler  # fetch_law_xml(재시도·시간 제한), _norm(법령명 비교)
import pq_engine

API_KEY = crawler.API_KEY
SEARCH = 'https://www.law.go.kr/DRF/lawSearch.do?OC={key}&target=admrul&type=XML&query={q}&display=50'


def current_version(law_name, fetch=None):
    """법제처에서 law_name과 이름이 같은 현행 행정규칙의 {serial, name, issue_no, issued, effective}. 못 찾으면 None."""
    fetch = fetch or crawler.fetch_law_xml
    root = fetch(SEARCH.format(key=API_KEY, q=urllib.parse.quote(law_name)))
    if root is None:
        return None
    want = crawler._norm(law_name)
    for a in root.findall('.//admrul'):
        name = (a.findtext('행정규칙명') or '').strip()
        if crawler._norm(name) == want:
            return {'serial': (a.findtext('행정규칙일련번호') or '').strip(), 'name': name,
                    'issue_no': (a.findtext('발령번호') or '').strip(),
                    'issued': (a.findtext('발령일자') or '').strip(),
                    'effective': (a.findtext('시행일자') or '').strip()}
    return None


def _date(s):
    s = (s or '').strip()
    return f'{s[:4]}-{s[4:6]}-{s[6:]}' if len(s) == 8 and s.isdigit() else s


def check(fetch=None):
    """감시 대상 기준마다 {status: ok|changed|unknown|unwatched, ...}. 같은 고시를 쓰는 명세는 한 번만 조회한다."""
    groups = {}
    out = []
    for s in pq_engine.list_specs():
        sp = pq_engine.load_spec(s['id'])
        src = sp.get('source', {})
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
        else:
            item.update(status='changed', new=cur)
        out.append(item)
    return out


def report_markdown(results):
    """개정이 감지된 기준별 안내문(마크다운). 없으면 빈 문자열."""
    lines = []
    for r in results:
        if r['status'] != 'changed':
            continue
        n = r['new']
        lines += [
            f"### {r['name']}",
            f"- 영향받는 평가기준: {', '.join(r['spec_ids'])}",
            f"- 명세에 반영된 버전: {r['issuer']} (시행 {r['have_effective']}, 행정규칙일련번호 {r['have_serial']})",
            f"- 법제처 현행 버전: 발령번호 {n['issue_no'] or '-'} (발령 {_date(n['issued'])}, 시행 {_date(n['effective'])}, 행정규칙일련번호 {n['serial']})",
            f"- 확인: https://www.law.go.kr/LSW/admRulInfoP.do?admRulSeq={n['serial']}",
            '',
        ]
    if not lines:
        return ''
    head = ['고시가 개정돼 PQ 점수 산정 명세의 배점·구간표가 최신 기준과 다를 수 있습니다.',
            '개정 내용을 확인해 `pq_specs/*.json`과 테스트를 고친 뒤, 명세의 source(law_id·effective·issuer)를 새 버전으로 바꾸면 이 알림이 멈춥니다.', '']
    return '\n'.join(head + lines)


def main(argv):
    out_path = argv[argv.index('--out') + 1] if '--out' in argv else None
    results = check()
    changed = [r for r in results if r['status'] == 'changed']
    for r in results:
        label = {'ok': '최신', 'changed': '개정됨', 'unknown': '조회 실패', 'unwatched': '감시 불가(법제처 외 기준)'}[r['status']]
        print(f"[PQ 기준 감시] {label}: {r['name']} ({', '.join(r['spec_ids'])})", flush=True)
        if r['status'] == 'changed':
            n = r['new']
            print(f"::warning::PQ 평가기준 개정 감지: {r['name']} - 현행 발령번호 {n['issue_no']} (시행 {_date(n['effective'])}). "
                  f"명세 반영 버전은 {r['issuer']}(시행 {r['have_effective']})입니다.", flush=True)
        elif r['status'] == 'unknown':
            print(f"::warning::PQ 평가기준 '{r['name']}'의 현행 버전을 조회하지 못했습니다(다음 실행에서 다시 확인).", flush=True)
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
