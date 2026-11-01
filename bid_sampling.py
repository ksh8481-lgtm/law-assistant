"""
과거 낙찰 공고의 기초금액·A값 표본 조회(낙찰가 예측용).

낙찰 목록 API는 기초금액을 주지 않아서, 공고번호로 기초금액 자료를 따로 조회해야 한다(1건 약 0.1~0.4초). 이 자료에는 기초금액(bssamt)과 함께
적격심사 낙찰하한을 좌우하는 A값의 구성 항목(보험료·안전관리비·품질관리비 등)이 들어 있다. 과거 공고의 자료는 바뀌지 않으므로
한 번 조회한 값은 서버 메모리에 보관해 다시 조회하지 않는다(공공데이터 API의 일일 호출 한도를 아끼기 위해).
최근 사례일수록 현재 시장 상황과 가까우므로 최근순으로 limit건만 표본으로 쓴다.
"""
import concurrent.futures
import threading
import time

import bid_rules
import pps_bid

_CACHE = {}                 # (공고번호, 차수) -> {'base': 기초금액, 'a': A값} 또는 None(공고에 기초금액이 없음이 확인된 경우)
_LOCK = threading.Lock()
_MAX_CACHE = 20000
NOT_FOUND_MSG = '해당 공고의 기초금액 정보를 찾을 수 없습니다.'   # pps_bid.fetch_bid_base_amount가 '없음'을 알릴 때의 문구(일시 오류와 구별)


def _key(it):
    return (it.get('bidNtceNo'), it.get('bidNtceOrd') or '000')


def fetch_base_info(items, limit=120, workers=8, budget_s=25):
    """최근순으로 limit건의 기초금액·A값을 {(공고번호,차수): {'base','a'}|None}으로 돌려준다. 못 가져온 것(일시 오류·시간 초과)은 결과에 넣지 않는다.
    stats: requested(요청), cached(이미 보관), fetched(새로 조회), missing(기초금액 없음), failed(오류·시간 초과)."""
    chosen = sorted((it for it in items if it.get('bidNtceNo')), key=lambda it: it.get('rlOpengDt') or '', reverse=True)[:limit]
    result, todo = {}, []
    stats = {'requested': len(chosen), 'cached': 0, 'fetched': 0, 'missing': 0, 'failed': 0}
    with _LOCK:
        for it in chosen:
            k = _key(it)
            if k in _CACHE:
                result[k] = _CACHE[k]
                stats['cached'] += 1
            else:
                todo.append(it)

    def work(it):
        match, err = pps_bid.fetch_bid_base_amount(it['bidNtceNo'], it.get('bidNtceOrd') or '000')
        if match is not None:
            try:
                v = float(match.get('bssamt'))
            except (TypeError, ValueError):
                return _key(it), None, 'missing'
            return _key(it), ({'base': v, 'a': bid_rules.a_amount(match)} if v > 0 else None), 'ok'
        return _key(it), None, ('missing' if err == NOT_FOUND_MSG else 'failed')

    if todo:
        deadline = time.time() + budget_s
        ex = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
        try:
            futs = [ex.submit(work, it) for it in todo]
            for f in futs:
                left = deadline - time.time()
                try:
                    k, v, state = f.result(timeout=max(left, 0.01))
                except Exception:
                    stats['failed'] += 1
                    continue
                if state == 'failed':
                    stats['failed'] += 1
                    continue
                result[k] = v
                stats['fetched' if state == 'ok' else 'missing'] += 1
                with _LOCK:
                    if len(_CACHE) < _MAX_CACHE:
                        _CACHE[k] = v
        finally:
            ex.shutdown(wait=False, cancel_futures=True)
    return result, stats


def clear_cache():
    with _LOCK:
        _CACHE.clear()
