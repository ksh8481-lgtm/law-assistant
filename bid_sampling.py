"""
과거 낙찰 공고의 기초금액·A값 표본 조회(낙찰가 예측용).

낙찰 목록 API는 기초금액을 주지 않아서, 공고번호로 기초금액 자료를 따로 조회해야 한다(1건 약 0.1~4초). 이 자료에는 기초금액(bssamt)과 함께
적격심사 낙찰하한을 좌우하는 A값의 구성 항목(보험료·안전관리비·품질관리비 등)이 들어 있다. 과거 공고의 자료는 바뀌지 않으므로
한 번 조회한 값은 서버 메모리와 디스크(bid_base_cache.json)에 보관해 다시 조회하지 않는다(공공데이터 API의 일일 호출 한도를 아끼기 위해, 재시작 후에도 유지).
최근 사례일수록 현재 시장 상황과 가까우므로 최근순으로 limit건만 표본으로 쓴다.

분석 결과가 일부 사례 누락 채로 나오지 않도록, 조회가 시간 안에 끝나지 못한 사례·일시 오류는 budget_s 안에서 여러 번 다시 시도한다.
호출 한도 초과(quota)가 확인되면 다시 시도해도 소용이 없으므로 멈추고 stats['quota']로 알린다.
"""
import concurrent.futures
import json
import os
import threading
import time

import bid_rules
import pps_bid

_CACHE = {}                 # (공고번호, 차수) -> {'base': 기초금액, 'a': A값} 또는 None(공고에 기초금액이 없음이 확인된 경우)
_LOCK = threading.Lock()
_MAX_CACHE = 20000
_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bid_base_cache.json')   # None이면 디스크에 저장하지 않는다(시험용)
_LOADED = False
NOT_FOUND_MSG = '해당 공고의 기초금액 정보를 찾을 수 없습니다.'   # pps_bid.fetch_bid_base_amount가 '없음'을 알릴 때의 문구(일시 오류와 구별)
QUOTA_HINTS = ('요청제한', 'LIMITED_NUMBER')                  # 공공데이터포털 일일 호출 한도 초과 응답의 문구


def _key(it):
    return (it.get('bidNtceNo'), it.get('bidNtceOrd') or '000')


def _load_disk():
    """처음 쓸 때 디스크에 보관된 값을 읽는다. 파일이 없거나 깨졌으면 조용히 빈 캐시로 시작한다."""
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    if not _CACHE_PATH or not os.path.isfile(_CACHE_PATH):
        return
    try:
        with open(_CACHE_PATH, encoding='utf-8') as f:
            rows = json.load(f)
        for no, ord_, base, a in rows:
            _CACHE.setdefault((no, ord_), {'base': float(base), 'a': float(a)} if base else None)
    except Exception as e:                                       # 캐시는 속도·호출량을 위한 것이라 못 읽어도 분석은 된다
        print('[bid_sampling] 디스크 캐시를 읽지 못했습니다:', type(e).__name__, e)


def _save_disk():
    if not _CACHE_PATH:
        return
    try:
        with _LOCK:
            rows = [[k[0], k[1], v['base'] if v else 0, v['a'] if v else 0] for k, v in _CACHE.items()]
        tmp = _CACHE_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(rows, f, ensure_ascii=False)
        os.replace(tmp, _CACHE_PATH)
    except Exception as e:
        print('[bid_sampling] 디스크 캐시를 저장하지 못했습니다:', type(e).__name__, e)


def _fetch_one(it):
    """한 건 조회. 반환 (키, 값, 상태): 상태는 ok / missing(공고에 기초금액 없음) / quota(호출 한도 초과) / failed(일시 오류)."""
    match, err = pps_bid.fetch_bid_base_amount(it['bidNtceNo'], it.get('bidNtceOrd') or '000')
    if match is not None:
        try:
            v = float(match.get('bssamt'))
        except (TypeError, ValueError):
            return _key(it), None, 'missing'
        return _key(it), ({'base': v, 'a': bid_rules.a_amount(match)} if v > 0 else None), 'ok'
    if err == NOT_FOUND_MSG:
        return _key(it), None, 'missing'
    if any(h in (err or '') for h in QUOTA_HINTS):
        return _key(it), None, 'quota'
    return _key(it), None, 'failed'


def fetch_base_info(items, limit=120, workers=8, budget_s=25, progress=None):
    """최근순으로 limit건의 기초금액·A값을 {(공고번호,차수): {'base','a'}|None}으로 돌려준다.
    못 가져온 것(일시 오류·시간 초과)은 budget_s 안에서 여러 번 다시 시도하고, 끝까지 못 가져온 것만 결과에서 빠진다.
    progress(done, total): 처리한 건수가 늘 때마다 호출(보관된 값 포함).
    stats: requested(요청), cached(이미 보관), fetched(새로 조회), missing(기초금액 없음), failed(끝까지 못 가져옴), quota(호출 한도 초과 여부), passes(시도 횟수)."""
    _load_disk()
    chosen = sorted((it for it in items if it.get('bidNtceNo')), key=lambda it: it.get('rlOpengDt') or '', reverse=True)[:limit]
    result, todo = {}, []
    stats = {'requested': len(chosen), 'cached': 0, 'fetched': 0, 'missing': 0, 'failed': 0, 'quota': False, 'passes': 0}
    with _LOCK:
        for it in chosen:
            k = _key(it)
            if k in _CACHE:
                result[k] = _CACHE[k]
                stats['cached'] += 1
            else:
                todo.append(it)
    total = len(chosen)
    done = stats['cached']
    if progress:
        progress(done, total)

    deadline = time.time() + budget_s
    pending = todo
    while pending and time.time() < deadline and not stats['quota']:
        stats['passes'] += 1
        ex = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
        retry, gained = [], 0
        try:
            futs = [(it, ex.submit(_fetch_one, it)) for it in pending]
            for it, f in futs:
                left = deadline - time.time()
                try:
                    k, v, state = f.result(timeout=max(left, 0.01))
                except Exception:                                # 이번 시간 안에 못 끝남(시간 초과): 남은 시간이 있으면 다음 차례에 다시
                    retry.append(it)
                    continue
                if state == 'quota':
                    stats['quota'] = True
                    retry.append(it)
                    continue
                if state == 'failed':
                    retry.append(it)
                    continue
                result[k] = v
                stats['fetched' if state == 'ok' else 'missing'] += 1
                gained += 1
                done += 1
                with _LOCK:
                    if len(_CACHE) < _MAX_CACHE:
                        _CACHE[k] = v
                if progress:
                    progress(done, total)
        finally:
            ex.shutdown(wait=False, cancel_futures=True)
        pending = retry
        if pending and not gained and stats['passes'] >= 3:      # 세 번 연속 한 건도 못 가져오면 계속해도 소용없다
            break
        if pending and not stats['quota'] and time.time() < deadline:
            time.sleep(min(1.5, max(0.0, deadline - time.time())))
    stats['failed'] = len(pending)
    if stats['fetched']:
        _save_disk()
    return result, stats


def clear_cache():
    """메모리 캐시를 비운다(디스크 파일은 그대로 두며, 다시 읽지도 않는다 - 시험에서 쓴다)."""
    global _LOADED
    with _LOCK:
        _CACHE.clear()
    _LOADED = True
