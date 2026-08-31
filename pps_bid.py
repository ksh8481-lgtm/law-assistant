"""
조달청 나라장터 낙찰정보서비스(data.go.kr) 연동 모듈.

"낙찰가 예측" 기능의 데이터 소스. 공사 입찰 개찰결과(낙찰된 목록)를 검색조건별로
가져와서, 낙찰률(예정가격 대비 낙찰금액 비율)의 과거 분포를 통계로 뽑아낸다.

[왜 "예측"이 아니라 "통계"인가]
적격심사 방식(2억~100억대 공사에서 가장 흔히 쓰임)은 낙찰 전에 예정가격 자체가
복수예비가격 추첨으로 정해지기 때문에, 특정 공사의 낙찰가를 미리 정확히 계산하는
것은 원리상 불가능하다. 대신 "비슷한 발주기관/공종/규모의 과거 낙찰들이 실제로
어느 낙찰률(%) 근처에 몰려 있었는지"를 통계 내면, 이번 입찰에서 어느 낙찰률로
투찰해야 경쟁력 있는지 확률적으로 가늠할 수 있다. 이 모듈은 그 과거 분포를
만드는 역할만 하고, "이렇게 하면 100% 낙찰된다"는 보장을 하지 않는다.

API 사용상 제약(실측으로 확인):
- 조회 기간(inqryBgnDt~inqryEndDt)은 한 번에 최대 약 1개월까지만 허용된다.
  그 이상 주면 resultCode "07"(입력범위값 초과 에러)가 온다. 그래서 여러 달을
  조회하려면 달별로 나눠서 여러 번 호출해야 한다.
- numOfRows는 999까지 한 번에 받아본 사례로 문제없이 동작함을 확인했다(대부분의
  월별/필터 조합에서 999건을 넘는 경우는 드묾).
"""
import os
import statistics
import requests
from datetime import datetime, timedelta

PPS_BID_API_KEY = os.environ.get("PPS_BID_API_KEY", "")
BASE_URL = "https://apis.data.go.kr/1230000/as/ScsbidInfoService/getScsbidListSttusCnstwkPPSSrch"

# 조달청_나라장터 입찰공고정보서비스(별도 API, 같은 계정 서비스키 공용 확인됨) - "진행 중인 입찰공고" 조회용
OPEN_BID_LIST_URL = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoCnstwkPPSSrch"
OPEN_BID_BASE_AMOUNT_URL = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoCnstwkBsisAmount"


def _month_ranges(months: int):
    """오늘로부터 거슬러 올라가며 (연,월) 튜플을 최신순으로 만든다."""
    today = datetime.now()
    y, m = today.year, today.month
    ranges = []
    for _ in range(months):
        ranges.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return ranges


def _fetch_month(year: int, month: int, dminstt_nm=None, keyword=None, region=None,
                  presumed_price_min=None, presumed_price_max=None):
    """한 달치 낙찰 목록을 전부(페이지네이션 포함) 가져온다."""
    if month == 12:
        end = datetime(year + 1, 1, 1) - timedelta(minutes=1)
    else:
        end = datetime(year, month + 1, 1) - timedelta(minutes=1)
    begin = datetime(year, month, 1)

    params = {
        "serviceKey": PPS_BID_API_KEY,
        "pageNo": "1",
        "numOfRows": "999",
        "inqryDiv": "1",
        "inqryBgnDt": begin.strftime("%Y%m%d0000"),
        "inqryEndDt": end.strftime("%Y%m%d%H%M"),
        "type": "json",
    }
    if dminstt_nm:
        params["dminsttNm"] = dminstt_nm
    if keyword:
        params["bidNtceNm"] = keyword
    if region:
        params["prtcptLmtRgnNm"] = region
    if presumed_price_min:
        params["presmptPrceBgn"] = str(int(presumed_price_min))
    if presumed_price_max:
        params["presmptPrceEnd"] = str(int(presumed_price_max))

    try:
        res = requests.get(BASE_URL, params=params, timeout=15)
        res.encoding = "utf-8"
        data = res.json()
    except Exception as e:
        return [], f"{year}-{month:02d} 조회 실패: {e}"

    body = data.get("response", {}).get("body")
    if body is None:
        # resultCode != 00 인 에러 응답 형태(nkoneps.com.response.ResponseError 등)
        err_key = next(iter(data.keys()), "")
        msg = data.get(err_key, {}).get("header", {}).get("resultMsg", "알 수 없는 오류")
        return [], f"{year}-{month:02d}: {msg}"

    return body.get("items", []) or [], None


def fetch_bid_history(months=12, dminstt_nm=None, keyword=None, region=None,
                       presumed_price_min=None, presumed_price_max=None, max_workers=6):
    """최근 N개월치 공사 낙찰 이력을 모아서 반환한다.

    Returns: (items: list[dict], errors: list[str])
    """
    import concurrent.futures

    ranges = _month_ranges(months)
    items = []
    errors = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_fetch_month, y, m, dminstt_nm, keyword, region,
                             presumed_price_min, presumed_price_max): (y, m)
            for y, m in ranges
        }
        for future in concurrent.futures.as_completed(futures):
            month_items, err = future.result()
            items.extend(month_items)
            if err:
                errors.append(err)

    return items, errors


def compute_rate_stats(items):
    """낙찰 이력 목록에서 낙찰률(sucsfbidRate)만 뽑아 기술통계를 계산한다.

    비정상 값(0, 음수, 100% 초과 등 - 데이터 누락이나 물품/수의계약성 특이 건)은
    통계 왜곡을 막기 위해 제외한다. 적격심사 낙찰률은 통상 85~100% 사이에 분포한다.
    """
    rates = []
    for it in items:
        raw = it.get("sucsfbidRate")
        if raw in (None, "", "0"):
            continue
        try:
            rate = float(raw)
        except (TypeError, ValueError):
            continue
        if 50.0 < rate <= 100.0:
            rates.append(rate)

    if not rates:
        return None

    rates.sort()
    n = len(rates)

    def pct(p):
        idx = min(n - 1, max(0, int(round(p / 100 * (n - 1)))))
        return rates[idx]

    return {
        "count": n,
        "mean": round(statistics.mean(rates), 3),
        "median": round(statistics.median(rates), 3),
        "stdev": round(statistics.stdev(rates), 3) if n >= 2 else 0.0,
        "min": round(rates[0], 3),
        "max": round(rates[-1], 3),
        "p10": round(pct(10), 3),
        "p25": round(pct(25), 3),
        "p40": round(pct(40), 3),
        "p50": round(pct(50), 3),
        "p60": round(pct(60), 3),
        "p75": round(pct(75), 3),
        "p90": round(pct(90), 3),
        "raw_rates": rates,
    }


def percentile_of_value(rates_sorted, value):
    """정렬된 낙찰률 목록 안에서 특정 값(value)이 하위 몇 %에 해당하는지 계산한다.
    (= 사용자가 이 낙찰률로 투찰했다면, 과거 사례 기준 몇 %보다 낮게/타이트하게 썼는지)
    """
    if not rates_sorted:
        return None
    n = len(rates_sorted)
    below = sum(1 for r in rates_sorted if r <= value)
    return round(below / n * 100, 1)


# ----------------------------------------------------------------------------
# 발주기관명 자동완성
#
# 이 API에는 "기관명 검색" 전용 오퍼레이션이 따로 없어서, 실제 낙찰 데이터에
# 등장하는 dminsttNm 값들을 모아 우리가 직접 자동완성 후보 목록을 만든다.
# 실측 결과 최근 1개월치 중 3페이지(2,997건)만 훑어도 1,000개가 넘는 서로
# 다른 발주기관명이 나왔다 - 활동 중인 기관은 한 달에 최소 한 번은 공사
# 입찰을 내는 경우가 많아서, 이 방식으로도 실용적인 커버리지가 나온다.
# 매 키 입력마다 API를 부르면 느리고 트래픽도 낭비이므로, 서버 메모리에
# 캐시해두고 일정 시간(_AGENCY_CACHE_TTL_SECONDS)마다만 새로 받아온다.
# ----------------------------------------------------------------------------
_AGENCY_CACHE = {"names": [], "fetched_at": None}
_AGENCY_CACHE_TTL_SECONDS = 24 * 3600


def _fetch_agency_names_page(year: int, month: int, page: int):
    if month == 12:
        end = datetime(year + 1, 1, 1) - timedelta(minutes=1)
    else:
        end = datetime(year, month + 1, 1) - timedelta(minutes=1)
    begin = datetime(year, month, 1)

    params = {
        "serviceKey": PPS_BID_API_KEY,
        "pageNo": str(page),
        "numOfRows": "999",
        "inqryDiv": "1",
        "inqryBgnDt": begin.strftime("%Y%m%d0000"),
        "inqryEndDt": end.strftime("%Y%m%d%H%M"),
        "type": "json",
    }
    try:
        res = requests.get(BASE_URL, params=params, timeout=15)
        res.encoding = "utf-8"
        data = res.json()
        items = data.get("response", {}).get("body", {}).get("items", []) or []
        return {it.get("dminsttNm") for it in items if it.get("dminsttNm")}
    except Exception:
        return set()


def _refresh_agency_cache(months=2, pages_per_month=3):
    import concurrent.futures

    ranges = _month_ranges(months)
    names = set()
    jobs = [(y, m, p) for (y, m) in ranges for p in range(1, pages_per_month + 1)]

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(_fetch_agency_names_page, y, m, p) for (y, m, p) in jobs]
        for future in concurrent.futures.as_completed(futures):
            names |= future.result()

    _AGENCY_CACHE["names"] = sorted(names)
    _AGENCY_CACHE["fetched_at"] = datetime.now()
    return _AGENCY_CACHE["names"]


def search_agency_names(query: str, limit: int = 15):
    """발주기관명 자동완성 후보를 반환한다. 캐시가 없거나 오래됐으면 새로 받아온다."""
    query = (query or "").strip()
    if not query:
        return []

    stale = (
        _AGENCY_CACHE["fetched_at"] is None
        or (datetime.now() - _AGENCY_CACHE["fetched_at"]).total_seconds() > _AGENCY_CACHE_TTL_SECONDS
    )
    names = _refresh_agency_cache() if stale else _AGENCY_CACHE["names"]

    starts = [n for n in names if n.startswith(query)]
    contains = [n for n in names if query in n and n not in starts]
    return (starts + contains)[:limit]


# ----------------------------------------------------------------------------
# 진행 중인 입찰공고 목록 (아직 마감되지 않은 공고)
#
# 낙찰정보서비스와 달리, 이 API는 "공고게시일시"(inqryDiv=1) 기준으로만 기간
# 검색이 된다 - "아직 안 끝난 공고"를 직접 걸러주는 파라미터는 없다. 그래서
# 최근 N일간 게시된 공고를 다 받아온 뒤, bidClseDt(입찰마감일시)가 아직
# 지나지 않은 것만 우리 쪽에서 골라낸다. 적격심사 공사 입찰의 공고~마감 기간은
# 보통 2~3주 안팎이므로, 최근 30일치만 봐도 현재 진행 중인 공고는 사실상 다
# 잡힌다.
# ----------------------------------------------------------------------------
def _fetch_open_bids_page(begin, now, page, dminstt_nm=None, keyword=None, region=None):
    params = {
        "serviceKey": PPS_BID_API_KEY,
        "pageNo": str(page),
        "numOfRows": "999",
        "inqryDiv": "1",
        "inqryBgnDt": begin.strftime("%Y%m%d0000"),
        "inqryEndDt": now.strftime("%Y%m%d%H%M"),
        "type": "json",
    }
    if dminstt_nm:
        params["dminsttNm"] = dminstt_nm
    if keyword:
        params["bidNtceNm"] = keyword
    if region:
        params["prtcptLmtRgnNm"] = region

    res = requests.get(OPEN_BID_LIST_URL, params=params, timeout=15)
    res.encoding = "utf-8"
    return res.json()


def fetch_open_bids(days=30, dminstt_nm=None, keyword=None, region=None):
    """최근 게시된 공고 중 아직 입찰마감이 지나지 않은 것만 골라 반환한다.

    dminstt_nm/keyword/region 중 최소 하나는 있어야 한다(없으면 30일치 전체
    공고 - 수천 건 - 를 다 훑어야 해서 비효율적이고 API 일일 호출 한도도
    금방 소진된다).

    Returns: (items: list[dict], error: str|None)
    """
    if not (dminstt_nm or keyword or region):
        return [], "발주기관명, 키워드, 지역 중 하나 이상을 입력해주세요."

    now = datetime.now()
    begin = now - timedelta(days=days)

    try:
        data = _fetch_open_bids_page(begin, now, 1, dminstt_nm, keyword, region)
    except Exception as e:
        return [], f"조회 실패: {e}"

    body = data.get("response", {}).get("body")
    if body is None:
        err_key = next(iter(data.keys()), "")
        msg = data.get(err_key, {}).get("header", {}).get("resultMsg", "알 수 없는 오류")
        return [], msg

    total_count = body.get("totalCount", 0) or 0
    items = list(body.get("items", []) or [])

    # 999건을 넘는 경우에만 추가 페이지를 더 가져온다(과도한 호출 방지 위해 최대 5페이지=4995건까지).
    if total_count > 999:
        import concurrent.futures
        import math

        extra_pages = min(math.ceil(total_count / 999) - 1, 4)
        with concurrent.futures.ThreadPoolExecutor(max_workers=extra_pages) as executor:
            futures = [
                executor.submit(_fetch_open_bids_page, begin, now, p, dminstt_nm, keyword, region)
                for p in range(2, extra_pages + 2)
            ]
            for future in concurrent.futures.as_completed(futures):
                try:
                    page_data = future.result()
                    page_body = page_data.get("response", {}).get("body", {})
                    items.extend(page_body.get("items", []) or [])
                except Exception:
                    pass

    open_items = []
    for it in items:
        clse_raw = it.get("bidClseDt")
        if not clse_raw:
            continue
        try:
            clse_dt = datetime.strptime(clse_raw, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if clse_dt > now:
            open_items.append(it)

    open_items.sort(key=lambda it: it.get("bidClseDt") or "")
    return open_items, None


def fetch_bid_base_amount(bid_ntce_no: str, bid_ntce_ord: str = "000"):
    """특정 공고의 기초금액(bssamt)을 조회한다. 없으면 None."""
    if not bid_ntce_no:
        return None, "공고번호가 없습니다."

    params = {
        "serviceKey": PPS_BID_API_KEY,
        "pageNo": "1",
        "numOfRows": "5",
        "inqryDiv": "2",
        "bidNtceNo": bid_ntce_no,
        "type": "json",
    }

    try:
        res = requests.get(OPEN_BID_BASE_AMOUNT_URL, params=params, timeout=15)
        res.encoding = "utf-8"
        data = res.json()
    except Exception as e:
        return None, f"조회 실패: {e}"

    body = data.get("response", {}).get("body")
    if body is None:
        err_key = next(iter(data.keys()), "")
        msg = data.get(err_key, {}).get("header", {}).get("resultMsg", "알 수 없는 오류")
        return None, msg

    items = body.get("items", []) or []
    if not items:
        return None, "해당 공고의 기초금액 정보를 찾을 수 없습니다."

    # bidNtceOrd(차수)가 일치하는 항목을 우선하고, 없으면 첫 항목 사용
    match = next((it for it in items if it.get("bidNtceOrd") == bid_ntce_ord), items[0])
    return match, None
