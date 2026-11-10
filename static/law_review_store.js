/*
 * 개발사업 스마트 법규 검토: 분석 결과·입력·점검 체크를 이 브라우저에 보관한다(서버에는 올리지 않는다).
 *
 * - 분석이 끝나면 입력(requestData)과 결과(result)를 기록으로 저장해, 나중에 보고서를 다시 열거나 같은 사업 입력을 불러올 수 있다.
 * - 보고서의 점검 체크(☑)와 항목별 메모는 기록 id별로 저장돼 다시 열어도 유지된다.
 * - 저장은 브라우저(localStorage)에만 있고, 다른 컴퓨터·브라우저·시크릿 창에서는 보이지 않는다. 저장이 막혀 있어도(시크릿 모드, 용량 초과) 화면은 그대로 동작한다.
 */
(function () {
    'use strict';
    var INDEX_KEY = 'lawReviewIndex';
    var REC_PREFIX = 'lawReviewRec:';
    var CHK_PREFIX = 'lawReviewChecks:';
    var MAX_RECORDS = 10;

    function read(key, fallback) {
        try {
            var raw = localStorage.getItem(key);
            return raw ? JSON.parse(raw) : fallback;
        } catch (e) { return fallback; }
    }
    function write(key, value) {
        try { localStorage.setItem(key, JSON.stringify(value)); return true; } catch (e) { return false; }
    }
    function drop(key) { try { localStorage.removeItem(key); } catch (e) { /* 무시 */ } }

    function newId() { return 'r' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6); }

    var Store = {
        MAX_RECORDS: MAX_RECORDS,

        /** 저장된 기록 목록(최근순): [{id, name, savedAt, type, budget, itemCount}] */
        list: function () {
            var idx = read(INDEX_KEY, []);
            return Array.isArray(idx) ? idx.slice().sort(function (a, b) { return b.savedAt - a.savedAt; }) : [];
        },

        get: function (id) { return read(REC_PREFIX + id, null); },

        /** 분석 입력과 결과를 기록으로 저장하고 id를 돌려준다. 저장하지 못하면 null. 오래된 기록은 MAX_RECORDS를 넘으면 지운다. */
        save: function (requestData, result) {
            var id = newId();
            var count = 0;
            if (result && result.permits) count += result.permits.length;
            if (result && result.phases) Object.keys(result.phases).forEach(function (k) { count += (result.phases[k] || []).length; });
            var rec = { id: id, name: (requestData && requestData.projectName) || '이름 없음', savedAt: Date.now(), requestData: requestData, result: result };
            if (!write(REC_PREFIX + id, rec)) {
                // 용량이 모자라면 가장 오래된 기록부터 지우고 한 번 더 시도한다
                var old = Store.list().reverse();
                for (var i = 0; i < old.length && !write(REC_PREFIX + id, rec); i++) Store.remove(old[i].id);
                if (!read(REC_PREFIX + id, null)) return null;
            }
            var idx = Store.list();
            idx.unshift({ id: id, name: rec.name, savedAt: rec.savedAt, type: (requestData && requestData.projectType) || '', budget: (requestData && requestData.budget) || 0, itemCount: count });
            while (idx.length > MAX_RECORDS) Store.remove(idx.pop().id, true);
            write(INDEX_KEY, idx);
            return id;
        },

        remove: function (id, skipIndex) {
            drop(REC_PREFIX + id);
            drop(CHK_PREFIX + id);
            if (!skipIndex) write(INDEX_KEY, Store.list().filter(function (r) { return r.id !== id; }));
        },

        /** 기록에 덧붙여 보관할 값(예: 처음 본 실무 점검 목록). 기록이 없으면 false. */
        setSnapshot: function (id, key, value) {
            var rec = Store.get(id);
            if (!rec) return false;
            rec[key] = value;
            return write(REC_PREFIX + id, rec);
        },

        /** 점검 체크·메모: { 항목키: {c: true|false, m: '메모'} } */
        checks: function (id) { return id ? read(CHK_PREFIX + id, {}) : {}; },

        setCheck: function (id, key, patch) {
            if (!id) return;
            var all = Store.checks(id);
            var cur = all[key] || { c: false, m: '' };
            if (patch.c !== undefined) cur.c = !!patch.c;
            if (patch.m !== undefined) cur.m = String(patch.m).slice(0, 500);
            if (!cur.c && !cur.m) delete all[key]; else all[key] = cur;
            write(CHK_PREFIX + id, all);
        },
    };
    window.LawReviewStore = Store;
})();
