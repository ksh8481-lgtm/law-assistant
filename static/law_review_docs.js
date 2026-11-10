/*
 * 개발사업 스마트 법규 검토 - 내역서·설명서 읽기
 * 올린 파일을 서버(/api/project_docs/start)가 읽고 AI가 "주요 사업 내용 및 목적" 글을 정리해 주면,
 * 미리 보여 주고 사용자가 [바꾸기] 또는 [아래에 추가]로 사업 내용 칸에 넣는다. 사업 내용 칸은 바로 덮어쓰지 않는다.
 */
(function () {
    'use strict';
    var $ = function (id) { return document.getElementById(id); };
    var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); };
    var MAX_FILES = 6, MAX_BYTES = 25 * 1024 * 1024;
    var busy = false;

    function box(kind, html) {
        var c = { ok: ['#166534', '#f0fdf4', '#86efac'], info: ['#1e40af', '#eff6ff', '#93c5fd'], error: ['#991b1b', '#fef2f2', '#fca5a5'], warn: ['#92400e', '#fffbeb', '#fcd34d'] }[kind] || ['#1e40af', '#eff6ff', '#93c5fd'];
        return '<div style="padding:0.65rem 0.85rem; border:1px solid ' + c[2] + '; background:' + c[1] + '; color:' + c[0] + '; border-radius:8px; font-size:0.88rem; line-height:1.55;">' + html + '</div>';
    }
    function status(kind, html) { $('docs-status').innerHTML = html ? box(kind, html) : ''; }

    function explain(msg) {
        var m = String(msg || '');
        if (/429|quota|한도/i.test(m)) return 'AI 호출 한도에 걸렸습니다. 몇 분 뒤 다시 시도해 주세요.';
        if (/존재하지 않는 작업/.test(m)) return '서버가 재시작되어 읽던 작업이 사라졌습니다(배포 직후에 생길 수 있습니다). 잠시 후 다시 올려 주세요.';
        if (/Failed to fetch|NetworkError/i.test(m)) return '서버와 연결이 끊어졌습니다. 인터넷 연결을 확인한 뒤 다시 시도해 주세요.';
        return m;
    }

    function pickFiles() {
        var list = [];
        ['bill', 'spec'].forEach(function (role) {
            var input = $('docs-' + role);
            Array.prototype.forEach.call(input.files || [], function (f) { list.push({ role: role, file: f }); });
        });
        return list;
    }

    function renderResult(res) {
        var notes = (res.notes || []).map(function (n) { return '<li>' + esc(n) + '</li>'; }).join('');
        var files = (res.files || []).map(function (f) { return esc(f.name) + '(' + (f.role === 'bill' ? '내역서' : '설명서') + ')'; }).join(', ');
        $('docs-result').innerHTML =
            '<div style="font-size:0.85rem; color:#475569; margin-bottom:0.3rem;">읽은 서류: ' + files + '</div>' +
            (notes ? box('warn', '<b>알림</b><ul style="margin:0.3rem 0 0 1.1rem;">' + notes + '</ul>') : '') +
            '<div style="font-size:0.85rem; font-weight:700; margin:0.6rem 0 0.3rem;">정리된 사업 내용 <span style="font-weight:400; color:#64748b;">(서류에 적힌 내용만 옮겼습니다. 확인하고 고친 뒤 넣으세요)</span></div>' +
            '<textarea id="docs-preview" rows="14" style="width:100%; box-sizing:border-box; font-size:0.88rem; line-height:1.55;"></textarea>' +
            '<div style="display:flex; gap:0.5rem; justify-content:flex-end; margin-top:0.5rem; flex-wrap:wrap;">' +
            '<button type="button" id="docs-close" class="secondary-btn" style="padding:0.45rem 0.9rem;">닫기</button>' +
            '<button type="button" id="docs-append" class="secondary-btn" style="padding:0.45rem 0.9rem;">기존 내용 아래에 추가</button>' +
            '<button type="button" id="docs-replace" class="secondary-btn" style="padding:0.45rem 0.9rem; background:#059669; color:white; border-color:#047857;">사업 내용에 넣기(바꾸기)</button></div>';
        $('docs-preview').value = res.text;
        var ta = $('description');
        function done(msg) {
            ta.dispatchEvent(new Event('input', { bubbles: true }));            // 빠진 정보 안내·작성 중 보관 갱신
            $('docs-result').innerHTML = '';
            status('ok', msg);
            ta.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
        $('docs-replace').addEventListener('click', function () {
            if (ta.value.trim() && !confirm('지금 적혀 있는 사업 내용이 정리된 글로 바뀝니다. 계속할까요?')) return;
            ta.value = $('docs-preview').value;
            done('사업 내용 칸에 넣었습니다. 아래에서 사업에 맞게 고치고, [더 적으면 정확해지는 정보]도 확인해 보세요.');
        });
        $('docs-append').addEventListener('click', function () {
            ta.value = (ta.value.replace(/\s+$/, '') + (ta.value.trim() ? '\n\n' : '') + $('docs-preview').value);
            done('기존 내용 아래에 추가했습니다.');
        });
        $('docs-close').addEventListener('click', function () { $('docs-result').innerHTML = ''; status('', ''); });
    }

    async function run() {
        if (busy) return;
        var picked = pickFiles();
        if (!picked.length) { status('error', '내역서나 설명서 파일을 하나 이상 선택해 주세요.'); return; }
        if (picked.length > MAX_FILES) { status('error', '파일은 한 번에 ' + MAX_FILES + '개까지 올릴 수 있습니다.'); return; }
        var big = picked.filter(function (p) { return p.file.size > MAX_BYTES; })[0];
        if (big) { status('error', '"' + big.file.name + '"은 25MB를 넘습니다. 필요한 쪽만 나눠 올려 주세요.'); return; }

        var fd = new FormData();
        picked.forEach(function (p) { fd.append(p.role, p.file, p.file.name); });
        var pt = document.querySelector('input[name="projectType"]:checked');
        fd.append('projectType', pt ? pt.value : '');
        fd.append('projectName', $('projectName').value || '');

        busy = true;
        var btn = $('docs-read-btn'); btn.disabled = true; btn.textContent = '읽는 중...';
        $('docs-result').innerHTML = '';
        var startedAt = Date.now(), stage = '파일을 서버로 보내는 중';
        var tick = function () { var s = Math.round((Date.now() - startedAt) / 1000); status('info', '<b>서류 읽는 중</b> · 경과 ' + s + '초<br>지금 단계: ' + esc(stage) + '<br><span style="font-size:0.8rem; opacity:0.85;">보통 20초~1분 걸립니다. 창을 닫지 마세요.</span>'); };
        tick();
        var timer = setInterval(tick, 1000);
        try {
            var r = await fetch('/api/project_docs/start', { method: 'POST', body: fd });
            var started = await r.json().catch(function () { return {}; });
            if (!r.ok || !started.success) throw new Error(started.message || ('서버 오류(' + r.status + ')'));
            for (var i = 0; i < 150; i++) {                                    // 2초 간격 최대 5분
                await new Promise(function (res) { setTimeout(res, 2000); });
                var sr = await fetch('/api/analyze/status/' + encodeURIComponent(started.job_id));
                var d = await sr.json();
                if (d.stage) stage = d.stage;
                if (d.status === 'completed') { status('', ''); renderResult(d.result); return; }
                if (d.status === 'error') throw new Error(d.message || '알 수 없는 오류');
            }
            throw new Error('5분이 넘어 중단했습니다. 파일을 줄여 다시 시도해 주세요.');
        } catch (e) {
            status('error', '<b>서류를 읽지 못했습니다.</b><br>' + esc(explain(e.message)));
        } finally {
            clearInterval(timer); busy = false; btn.disabled = false; btn.textContent = '📖 서류 읽고 사업 내용 작성';
        }
    }

    function init() { var b = $('docs-read-btn'); if (b) b.addEventListener('click', run); }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
