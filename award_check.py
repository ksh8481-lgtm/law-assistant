"""
적격심사 명세(award_specs/*.json)의 숫자가 「지방자치단체 입찰시 낙찰자 결정기준」 원문과 같은지 대조한다.

[왜 필요한가]
이 예규는 법제처 API가 조문을 주지 않고 첨부 파일(PDF)로만 제공하고, 486쪽 가운데 건설엔지니어링 적격심사는 일부 쪽이다.
버전 번호가 바뀌었다는 알림(pq_watch)만으로는 "다른 장(물품·공사 등)이 개정됐는지, 우리가 쓰는 숫자(92·95점, 64/44/34점,
입찰가격 산식 …)가 바뀌었는지" 알 수 없어서 매번 사람이 486쪽을 봐야 한다. 그래서 새 PDF에서 핵심 숫자를 뽑아 명세와 비교해
"92 -> 90"처럼 바뀐 값만 알려 준다.

[방식]
PDF 텍스트에서 공백을 모두 없앤 뒤(쪽·줄 바꿈이 숫자 사이를 갈라놓는 것을 막기 위해) 정해진 문장 모양을 정규식으로 찾는다.
- 찾았고 값이 같으면 ok, 다르면 diff(바뀜), 문장 모양을 못 찾으면 unparsed(문서 구성이 바뀌었을 수 있어 사람이 확인).
  못 찾은 것을 조용히 통과시키지 않는다.
- 경영상태 신용평가 점수표(2.0/1.8/1.6/1.4/1.0)는 표 모양이 PDF 텍스트에서 안정적이지 않아 자동 대조하지 않는다(개정 알림 때 사람이 확인).

사용: python award_check.py [--pdf 파일.pdf | --text 파일.txt] [--spec jibang_jeokgyeok_tech | jibang_gongsa_floor]
  인자가 없으면 법제처의 현행 첨부 PDF를 받아 대조한다. 바뀐 값이나 확인하지 못한 값이 있으면 종료 코드 1.
"""
import re
import sys

import award_engine


def _norm(t: str) -> str:
    """모든 공백(줄바꿈 포함)을 없앤다."""
    return re.sub(r'\s+', '', t or '')


def _num(s):
    x = float(s)
    return int(x) if x == int(x) else x


def _slice_byeolpyo1(norm_all: str) -> str:
    """[별표 1](사업수행능력평가를 하는 기술용역) 구간. 머리글 모양이 바뀌어 못 찾으면 빈 문자열."""
    start = norm_all.find('기술·학술연구용역적격심사세부기준[별표1]')   # '시설공사 적격심사 세부기준 [별표 1]' 등 다른 장의 별표 1과 섞이지 않게 장 이름까지 맞춘다
    if start < 0:
        return ''
    end = norm_all.find('기술·학술연구용역적격심사세부기준[별표2]', start)
    return norm_all[start:end if end > 0 else len(norm_all)]


def extract(text: str) -> dict:
    """원문 텍스트에서 명세와 대조할 값들을 뽑는다. 못 찾은 항목은 None."""
    n = _norm(text)
    b1 = _slice_byeolpyo1(n)
    out = {}

    m = re.search(r'종합평점이추정가격10억원이상인용역은(\d+(?:\.\d+)?)점.{0,40}?이상,추정가격이10억원미만인용역은(\d+(?:\.\d+)?)점이상인자,학술연구용역의경우(\d+(?:\.\d+)?)점이상', n)
    out['pass_ge_10'] = _num(m.group(1)) if m else None
    out['pass_lt_10'] = _num(m.group(2)) if m else None

    w = re.findall(r'평점=평가점수×(\d+)점', b1)
    for key, v in zip(('pq_ge_10', 'pq_ge_5', 'pq_lt_5'), w[:3]):
        out[key] = _num(v)
    prices = re.findall(r'평점=(\d+)-(?:(\d+)×)?\(88-입찰가격\)×100100예정가격', b1)
    for key, v in zip(('ge_10', 'ge_5', 'lt_5'), prices[:3]):
        out['price_top_' + key] = _num(v[0])
        out['price_slope_' + key] = _num(v[1]) if v[1] else 1
    caps = re.findall(r'100분의(\d+(?:\.\d+)?)이상인경우의평점은(\d+(?:\.\d+)?)점', b1)
    for key, v in zip(('ge_10', 'ge_5', 'lt_5'), caps[:3]):
        out['cap_from_' + key] = _num(v[0])
        out['cap_score_' + key] = _num(v[1])

    def one(pattern):
        m = re.search(pattern, b1)
        return _num(m.group(1)) if m else None

    out['career_30'] = one(r'경력합산비율30%이상:(\d(?:\.\d)?)점')
    out['career_20'] = one(r'경력합산비율30%미만20%이상:(\d(?:\.\d)?)점')
    out['local_main_30'] = one(r'지역업체합산비율30%이상:(\d(?:\.\d)?)점')
    out['local_main_20'] = one(r'지역업체합산비율30%미만20%이상:(\d(?:\.\d)?)점')
    out['local_other_20'] = one(r'다른법령에따른지역업체합산비율20%이상:(\d(?:\.\d)?)점')
    out['local_other_10'] = one(r'다른법령에따른지역업체합산비율20%미만10%이상:(\d(?:\.\d)?)점')
    out['tech_shortage'] = one(r'△(\d+)※주5\)')
    m = re.search(r'공개한횟수당△(\d(?:\.\d)?)△(\d(?:\.\d)?)', b1)
    out['wage_per'] = _num(m.group(1)) if m else None
    out['wage_cap'] = _num(m.group(2)) if m else None
    return out


def expected(spec: dict) -> dict:
    """명세가 말하는 값(extract와 같은 키)."""
    bands = {b['id']: b for b in spec['bands']}
    e = {'pass_ge_10': bands['ge_10']['pass_score'], 'pass_lt_10': bands['ge_5']['pass_score']}
    for k in ('ge_10', 'ge_5', 'lt_5'):
        b = bands[k]
        e['pq_' + k] = b['weights']['pq']
        e['price_top_' + k] = b['price']['top']
        e['price_slope_' + k] = b['price']['slope']
        e['cap_from_' + k] = round(b['price']['cap_from_ratio'] * 100, 6)
        e['cap_score_' + k] = b['price']['cap_score']
    e['cap_from_ge_10'], e['cap_from_ge_5'], e['cap_from_lt_5'] = [_num(e[k]) for k in ('cap_from_ge_10', 'cap_from_ge_5', 'cap_from_lt_5')]
    c, loc = spec['career']['tiers'], spec['local']['tiers']
    e.update(career_30=c[0][1], career_20=c[1][1], local_main_30=loc['main'][0][1], local_main_20=loc['main'][1][1],
             local_other_20=loc['other'][0][1], local_other_10=loc['other'][1][1],
             tech_shortage=abs(spec['deductions']['tech_shortage']['points']),
             wage_per=abs(spec['deductions']['wage_arrears']['per_count']), wage_cap=abs(spec['deductions']['wage_arrears']['cap']))
    for k, v in list(e.items()):
        e[k] = _num(v)
    return e


LABELS = {
    'pass_ge_10': '적격통과점수(추정가격 10억원 이상)', 'pass_lt_10': '적격통과점수(추정가격 10억원 미만)',
    'pq_ge_10': 'PQ 환산 배점(10억원 이상)', 'pq_ge_5': 'PQ 환산 배점(5억원 이상 10억원 미만)', 'pq_lt_5': 'PQ 환산 배점(5억원 미만)',
    'price_top_ge_10': '입찰가격 만점(10억원 이상)', 'price_top_ge_5': '입찰가격 만점(5억~10억원)', 'price_top_lt_5': '입찰가격 만점(5억원 미만)',
    'price_slope_ge_10': '입찰가격 산식 계수(10억원 이상)', 'price_slope_ge_5': '입찰가격 산식 계수(5억~10억원)', 'price_slope_lt_5': '입찰가격 산식 계수(5억원 미만)',
    'cap_from_ge_10': '입찰가격 고정점수 시작 비율 %(10억원 이상)', 'cap_from_ge_5': '입찰가격 고정점수 시작 비율 %(5억~10억원)', 'cap_from_lt_5': '입찰가격 고정점수 시작 비율 %(5억원 미만)',
    'cap_score_ge_10': '입찰가격 고정점수(10억원 이상)', 'cap_score_ge_5': '입찰가격 고정점수(5억~10억원)', 'cap_score_lt_5': '입찰가격 고정점수(5억원 미만)',
    'career_30': '책임기술자 경력 30% 이상 점수', 'career_20': '책임기술자 경력 20% 이상 점수',
    'local_main_30': '지역업체 참여 30% 이상 점수', 'local_main_20': '지역업체 참여 20% 이상 점수',
    'local_other_20': '지역업체 참여(다른 법령) 20% 이상 점수', 'local_other_10': '지역업체 참여(다른 법령) 10% 이상 점수',
    'tech_shortage': '기술인력 미달 감점', 'wage_per': '임금체불 건당 감점', 'wage_cap': '임금체불 감점 한도',
}


def compare(spec: dict, text: str) -> list:
    """[{key, label, expected, found, status: ok|diff|unparsed}]. 명세 id에 따라 기술용역 적격심사 또는 시설공사 낙찰하한 값을 대조한다."""
    if spec.get('id') == FLOOR_SPEC_ID:
        want, got, labels = expected_floor(spec), extract_floor(text), FLOOR_LABELS
    else:
        want, got, labels = expected(spec), extract(text), LABELS
    rows = []
    for key, label in labels.items():
        f = got.get(key)
        if f is None:
            status = 'unparsed'
        elif want[key] is None:
            status = 'diff'              # 명세에는 고정점수가 없는데 원문에는 있다(또는 반대)
        else:
            status = 'ok' if abs(float(f) - float(want[key])) < 1e-9 else 'diff'
        rows.append({'key': key, 'label': label, 'expected': want[key], 'found': f, 'status': status})
    return rows


def summarize(rows: list) -> dict:
    d = [r for r in rows if r['status'] == 'diff']
    u = [r for r in rows if r['status'] == 'unparsed']
    return {'ok': len(rows) - len(d) - len(u), 'diff': d, 'unparsed': u, 'clean': not d and not u}


# ---------------------------------------------------------------- 시설공사 낙찰하한(jibang_gongsa_floor)
FLOOR_SPEC_ID = 'jibang_gongsa_floor'
_FLOOR_BANDS = ('b1', 'b2', 'b3', 'b4', 'b5', 'b6', 'b7')         # 별표 번호와 같다(b1 = [별표 1], 추정가격 100억원 이상 300억원 미만)


def _floor_sections(n: str) -> dict:
    """시설공사 적격심사 세부기준 [별표 1]~[별표 7] 본문. 다른 곳에서 별표를 언급한 문장과 섞이지 않게 '추정가격이'로 이어지는 머리글만 쓴다."""
    heads = [(m.start(), int(m.group(1))) for m in re.finditer(r'시설공사적격심사세부기준\[별표(\d)\]추정가격이', n)]
    out = {}
    for i, (pos, no) in enumerate(heads):
        end = heads[i + 1][0] if i + 1 < len(heads) else len(n)
        if 1 <= no <= 7 and no not in out:
            out[no] = n[pos:end]
    return out


def extract_floor(text: str) -> dict:
    """원문에서 시설공사 낙찰하한을 정하는 값(입찰가격 평점 식·고정점수·적격통과점수)을 뽑는다. 못 찾은 항목은 None."""
    n = _norm(text)
    out = {}
    m = re.search(r'종합평점이?추정가격이100억원미만인공사는(\d+(?:\.\d+)?)점.{0,40}?100억원이상300억원미만인공사는(\d+(?:\.\d+)?)점이상', n)
    out['pass_lt_100'] = _num(m.group(1)) if m else None
    out['pass_ge_100'] = _num(m.group(2)) if m else None
    sections = _floor_sections(n)
    centers, rounds, mins = set(), set(), set()
    for no in range(1, 8):
        sec = sections.get(no, '')
        key = f'b{no}'
        # 평점(점)=30(90-…) / 502×(90-… / 70-4×(90-… : PDF에서 '-'가 빠지기도 해서 앞 두 자리를 만점, 나머지를 계수로 읽는다(만점은 모두 두 자리, 계수가 없으면 1)
        m = re.search(r'입찰가격평점산식평점\(점\)=(\d+)(?:-(\d+))?×?\((\d+)-\(입찰가격-A\)\)', sec)
        if m:
            digits = m.group(1) + (m.group(2) or '')
            out['top_' + key] = int(digits[:2])
            out['slope_' + key] = int(digits[2:]) if digits[2:] else 1
            centers.add(int(m.group(3)))
        else:
            out['top_' + key] = out['slope_' + key] = None
        m = re.search(r'예정가격-A\)의100분의(\d+(?:\.\d+)?)이상(?:인|일)경우의평점은(\d+(?:\.\d+)?)점', sec)
        out['cap_from_' + key] = _num(m.group(1)) if m else None
        out['cap_score_' + key] = _num(m.group(2)) if m else None
        if sec:
            rounds.add('소수점다섯째자리에서반올림' in sec)
            m = re.search(r'최저평점은(\d+(?:\.\d+)?)점', sec)
            mins.add(_num(m.group(1)) if m else None)
    out['center_pct'] = centers.pop() if len(centers) == 1 else None
    out['rounding_5th'] = 1 if rounds == {True} else None
    out['min_price_score'] = mins.pop() if len(mins) == 1 else None
    return out


def expected_floor(spec: dict) -> dict:
    """명세(jibang_gongsa_floor)가 말하는 값(extract_floor와 같은 키)."""
    bands = {b['id']: b for b in spec['bands']}
    e = {'pass_lt_100': bands['b5']['pass_score'], 'pass_ge_100': bands['b1']['pass_score'],
         'center_pct': spec['center'] * 100, 'rounding_5th': 1 if spec['rounding_digits'] == 4 else 0, 'min_price_score': spec['min_price_score']}
    for key in _FLOOR_BANDS:
        p = bands[key]['price']
        e['top_' + key], e['slope_' + key] = p['top'], p['slope']
        e['cap_from_' + key] = round(p['cap_from'] * 100, 6) if p['cap_from'] is not None else None
        e['cap_score_' + key] = p['cap_score']
    return {k: (_num(v) if v is not None else None) for k, v in e.items()}


_FLOOR_NAMES = {'b1': '[별표 1] 100억~300억원', 'b2': '[별표 2] 50억~100억원', 'b3': '[별표 3] 30억~50억원', 'b4': '[별표 4] 10억~30억원',
                'b5': '[별표 5] 4억~10억원', 'b6': '[별표 6] 2억~4억원', 'b7': '[별표 7] 2억원 미만'}
FLOOR_LABELS = {'pass_lt_100': '적격통과점수(추정가격 100억원 미만)', 'pass_ge_100': '적격통과점수(100억원 이상 300억원 미만)',
                'center_pct': '입찰가격 평점 식의 기준 비율 %', 'rounding_5th': '비율 소수점 다섯째 자리 반올림(1 = 있음)', 'min_price_score': '입찰가격 최저평점'}
for _k in _FLOOR_BANDS:
    FLOOR_LABELS.update({f'top_{_k}': f'입찰가격 만점 {_FLOOR_NAMES[_k]}', f'slope_{_k}': f'입찰가격 산식 계수 {_FLOOR_NAMES[_k]}',
                         f'cap_from_{_k}': f'입찰가격 고정점수 시작 비율 % {_FLOOR_NAMES[_k]}', f'cap_score_{_k}': f'입찰가격 고정점수 {_FLOOR_NAMES[_k]}'})


# ---------------------------------------------------------------- 원문 가져오기
def pdf_to_text(data: bytes) -> str:
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    doc = fitz.open(stream=data, filetype='pdf')
    return '\n'.join(page.get_text() for page in doc)


def download_current_pdf(admrul_id: str, timeout: int = 120) -> bytes:
    """법제처 행정규칙 응답의 첨부파일 목록에서 PDF를 받는다. (법제처가 본문을 주지 않는 예규용)"""
    import urllib.parse
    import xml.etree.ElementTree as ET
    import requests
    import crawler
    r = requests.get(f"https://www.law.go.kr/DRF/lawService.do?OC={crawler.API_KEY}&target=admrul&ID={urllib.parse.quote(str(admrul_id))}&type=XML", timeout=30)
    root = ET.fromstring(r.text)
    names = [(e.text or '').strip() for e in root.iter('첨부파일명')]
    links = [(e.text or '').strip() for e in root.iter('첨부파일링크')]
    for name, link in zip(names, links):
        if name.lower().endswith('.pdf') and link:
            link = link.replace('http://', 'https://')
            res = requests.get(link, timeout=timeout, allow_redirects=True)
            res.raise_for_status()
            if not res.content.startswith(b'%PDF'):
                raise ValueError('첨부파일이 PDF가 아닙니다')
            return res.content
    raise ValueError('현행 첨부파일 목록에서 PDF를 찾지 못했습니다')


_TEXT_CACHE = {}


def verify_online(spec_id: str = 'jibang_jeokgyeok_tech', admrul_id: str = None) -> dict:
    """현행(또는 admrul_id) 예규 PDF를 받아 명세와 대조한다. summarize() 결과에 rows를 덧붙여 돌려준다."""
    spec = award_engine.load_spec(spec_id)
    law_id = str(admrul_id or spec['source']['law_id'])
    if law_id not in _TEXT_CACHE:                                   # 같은 예규를 쓰는 명세가 여럿이라(기술용역·시설공사) 486쪽 PDF를 한 번만 받는다
        _TEXT_CACHE[law_id] = pdf_to_text(download_current_pdf(law_id))
    rows = compare(spec, _TEXT_CACHE[law_id])
    out = summarize(rows)
    out['rows'] = rows
    return out


def report_lines(summary: dict) -> list:
    """사람이 읽을 요약(마크다운 목록)."""
    if summary['clean']:
        return [f"- 숫자 대조: 확인한 {summary['ok']}개 값이 모두 명세와 같습니다. 이번 개정은 적격심사 숫자에는 영향이 없어 보입니다(다른 장 개정일 수 있음)."]
    lines = []
    for r in summary['diff']:
        lines.append(f"- **바뀐 값**: {r['label']} — 명세 {r['expected']} → 원문 {r['found']}")
    for r in summary['unparsed']:
        lines.append(f"- 확인 못 함: {r['label']} (원문 문장 모양이 바뀌었을 수 있어 사람이 확인해야 합니다)")
    lines.append(f"- 같은 값 {summary['ok']}개")
    return lines


def main(argv):
    spec_id = argv[argv.index('--spec') + 1] if '--spec' in argv else 'jibang_jeokgyeok_tech'
    spec = award_engine.load_spec(spec_id)
    if '--text' in argv:
        with open(argv[argv.index('--text') + 1], encoding='utf-8') as f:
            text = f.read()
    elif '--pdf' in argv:
        with open(argv[argv.index('--pdf') + 1], 'rb') as f:
            text = pdf_to_text(f.read())
    else:
        text = pdf_to_text(download_current_pdf(spec['source']['law_id']))
    rows = compare(spec, text)
    for r in rows:
        mark = {'ok': 'OK  ', 'diff': 'DIFF', 'unparsed': '??  '}[r['status']]
        print(f"{mark} {r['label']}: 명세 {r['expected']} / 원문 {r['found']}")
    s = summarize(rows)
    print(f"\n일치 {s['ok']}개 / 바뀜 {len(s['diff'])}개 / 확인 못 함 {len(s['unparsed'])}개")
    return 0 if s['clean'] else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
