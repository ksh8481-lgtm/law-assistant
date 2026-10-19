"""
crawler.crawl_laws의 멈춤 방지 검증 스크립트. `python test_crawler.py`로 실행한다. 네트워크 없이 가짜 process_law로 시험한다.
"""
import contextlib
import io
import sys
import time

import crawler

failures = []


def check(label, got, want):
    ok = got == want
    if not ok:
        failures.append(f'{label}: 기대 {want!r} / 실제 {got!r}')
    print(('OK  ' if ok else 'FAIL'), label, got)


def run(fake, laws, law_timeout=1, budget=1000):
    """crawl_laws를 가짜 process_law로 실행하고 (종료코드, 출력, 걸린 시간)을 돌려준다."""
    saved = (crawler.process_law, crawler.TARGET_LAWS, crawler.LAW_TIMEOUT, crawler.TOTAL_BUDGET)
    crawler.process_law, crawler.TARGET_LAWS, crawler.LAW_TIMEOUT, crawler.TOTAL_BUDGET = fake, laws, law_timeout, budget
    buf = io.StringIO()
    code = 0
    t0 = time.time()
    try:
        with contextlib.redirect_stdout(buf):
            crawler.crawl_laws()
    except SystemExit as e:
        code = e.code
    finally:
        crawler.process_law, crawler.TARGET_LAWS, crawler.LAW_TIMEOUT, crawler.TOTAL_BUDGET = saved
    return code, buf.getvalue(), time.time() - t0


def stuck_download():
    time.sleep(30)  # 응답이 멈춘 요청을 흉내 낸다


def test_hang_is_skipped_and_located():
    def fake(name):
        if name == '멈춤법':
            stuck_download()
        if name == '예외법':
            raise RuntimeError('boom')
        return name != '없는법'
    code, out, took = run(fake, ['가법', '멈춤법', '예외법', '없는법', '나법'])
    check('멈춘 법령 때문에 전체가 매달리지 않음(1초 제한 → 5초 안에 끝)', took < 5, True)
    check('나머지 법령은 계속 처리 - 종료 코드 0', code, 0)
    check('성공 2건·실패 3건 집계', '성공 2건 / 실패 3건 / 미룸 0건' in out, True)
    check('멈춘 위치(함수명)가 로그에 남음', 'stuck_download' in out, True)
    check('경고 주석 형식', '::warning::멈춤법' in out, True)
    check('실패 목록에 멈춘 법령 포함', '멈춤법' in out.split('실패한 법령')[1], True)


def test_budget_defers_rest():
    def fake(name):
        time.sleep(0.6)
        return True
    code, out, took = run(fake, ['가', '나', '다', '라', '마'], budget=1)
    check('예산 초과 시 정상 종료(0)', code, 0)
    check('앞쪽은 처리하고 남은 법령은 미룸', '미룸 3건' in out and '성공 2건' in out, True)
    check('미룸 경고 출력', '다음 실행으로 미룹니다' in out, True)


def test_all_fail_exit_code():
    code, out, _ = run(lambda n: False, ['가', '나'])
    check('전부 실패하면 종료 코드 1', code, 1)
    code, out, _ = run(lambda n: True, ['가', '나'])
    check('전부 성공하면 종료 코드 0', code, 0)


def test_hang_only_one_law_not_all_fail():
    def fake(name):
        if name == '가':
            time.sleep(30)
        return True
    code, out, _ = run(fake, ['가', '나'])
    check('하나만 멈추고 나머지 성공이면 종료 코드 0', code, 0)


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
