"""
비동기 분석 작업(JOBS) 상태 저장소.

기존에는 app.py에 `JOBS = {}` 순수 파이썬 dict로 되어 있어서, 프로세스 메모리
안에서만 상태가 유지됐다. gunicorn이 워커를 여러 개 띄우거나(멀티 프로세스),
플랫폼이 유휴 시 컨테이너를 재시작/재배포하면 "작업을 시작한 프로세스"와
"상태를 조회하는 프로세스"가 달라질 수 있어서 -> 분명히 시작한 작업인데
'/api/analyze/status/<job_id>'가 404("존재하지 않는 작업입니다")를 내는 문제가
실제 운영 환경(Cloudtype)에서 재현됨.

JobStore는 같은 컨테이너 안의 여러 프로세스/워커가 공유하는 로컬 SQLite 파일
(jobs.db)에 상태를 저장해서 이 문제를 해결한다. dict와 동일한 인터페이스
(JOBS[job_id] = {...}, job_id in JOBS, del JOBS[job_id], JOBS.get(...))를 제공하므로
app.py의 기존 호출부는 거의 그대로 사용할 수 있다.

주의: Cloudtype이 컨테이너를 여러 개(별도 디스크)로 스케일링하는 구조라면
이 파일 기반 저장소만으로는 완전히 해결되지 않는다 (그 경우 Redis 등 외부
공유 저장소가 필요). 다만 가장 흔한 단일 컨테이너 + 다중 워커/재시작 케이스는
이걸로 해결된다.
"""
import os
import json
import sqlite3
import threading

_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'jobs.db')
_lock = threading.Lock()


def _get_conn():
    conn = sqlite3.connect(_DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _init_db():
    conn = _get_conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                updated_at REAL NOT NULL DEFAULT (strftime('%s', 'now'))
            )
        """)
        conn.commit()
    finally:
        conn.close()


_init_db()


class JobStore:
    def __setitem__(self, job_id, value):
        payload = json.dumps(value, ensure_ascii=False)
        with _lock:
            conn = _get_conn()
            try:
                conn.execute(
                    "INSERT INTO jobs (job_id, data, updated_at) VALUES (?, ?, strftime('%s','now')) "
                    "ON CONFLICT(job_id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
                    (job_id, payload)
                )
                conn.commit()
            finally:
                conn.close()

    def __getitem__(self, job_id):
        with _lock:
            conn = _get_conn()
            try:
                row = conn.execute("SELECT data FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            finally:
                conn.close()
        if row is None:
            raise KeyError(job_id)
        return json.loads(row[0])

    def __contains__(self, job_id):
        with _lock:
            conn = _get_conn()
            try:
                row = conn.execute("SELECT 1 FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            finally:
                conn.close()
        return row is not None

    def __delitem__(self, job_id):
        with _lock:
            conn = _get_conn()
            try:
                conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
                conn.commit()
            finally:
                conn.close()

    def get(self, job_id, default=None):
        try:
            return self[job_id]
        except KeyError:
            return default

    def cleanup_stale(self, max_age_seconds=3600):
        """1시간 넘게 조회되지 않은 오래된 작업 기록 정리 (jobs.db가 무한정 쌓이는 것 방지)."""
        with _lock:
            conn = _get_conn()
            try:
                conn.execute(
                    "DELETE FROM jobs WHERE updated_at < strftime('%s','now') - ?",
                    (max_age_seconds,)
                )
                conn.commit()
            finally:
                conn.close()
