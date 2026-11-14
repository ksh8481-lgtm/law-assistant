/*
 * 개발사업 스마트 법규 검토 - 입력 화면 도우미 (script.js의 window.LRForm 위에서 동작)
 *
 *  - 안내·오류 메시지와 분석 진행 표시(서버가 알려 주는 실제 단계 + 경과 시간)
 *  - 저장된 분석: 보고서 다시 열기 / 입력 불러오기 / 삭제
 *  - 작성 중이던 내용 자동 보관·복구
 *  - 주소 붙여넣기(여러 줄)로 필지 한꺼번에 입력
 *  - 필지 검증 결과 요약과 실패한 필지만 다시 검증
 *  - 사업 내용에 빠진 정보 안내(눌러서 줄 추가)
 * 보관은 이 브라우저(localStorage)에만 한다.
 */
(function () {
    'use strict';
    var $ = function (id) { return document.getElementById(id); };
    var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); };
    var DRAFT_KEY = 'lawReviewDraft';
    var Store = function () { return window.LawReviewStore; };

    function lsRead(k) { try { var r = localStorage.getItem(k); return r ? JSON.parse(r) : null; } catch (e) { return null; } }
    function lsWrite(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); return true; } catch (e) { return false; } }
    function lsDrop(k) { try { localStorage.removeItem(k); } catch (e) { /* 무시 */ } }
    function debounce(fn, ms) { var t; return function () { var a = arguments; clearTimeout(t); t = setTimeout(function () { fn.apply(null, a); }, ms); }; }
    function fmtDate(ms) { var d = new Date(ms); return (d.getMonth() + 1) + '월 ' + d.getDate() + '일 ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'); }

    // ------------------------------------------------------------ 안내·오류·진행 표시
    var COLORS = {
        ok: { fg: '#166534', bg: '#f0fdf4', bd: '#86efac' },
        info: { fg: '#1e40af', bg: '#eff6ff', bd: '#93c5fd' },
        error: { fg: '#991b1b', bg: '#fef2f2', bd: '#fca5a5' },
    };
    function box(kind, html) {
        var c = COLORS[kind] || COLORS.info;
        return '<div style="padding:0.7rem 0.9rem; border:1px solid ' + c.bd + '; background:' + c.bg + '; color:' + c.fg + '; border-radius:8px; font-size:0.9rem; line-height:1.55;">' + html + '</div>';
    }

    /** 폼 아래 메시지(alert 대신). kind: ok | info | error */
    function notify(msg, kind) {
        var el = $('form-message');
        if (!el) { alert(msg); return; }
        el.innerHTML = box(kind || 'info', esc(msg));
        el.setAttribute('role', 'alert');
        if (kind === 'error') el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    function clearMessages() { var m = $('form-message'); if (m) m.innerHTML = ''; var s = $('analysis-status'); if (s) s.innerHTML = ''; }

    function showProgress(stage, sec) {
        var el = $('analysis-status');
        if (!el) return;
        var mm = Math.floor(sec / 60), ss = String(sec % 60).padStart(2, '0');
        el.innerHTML = box('info', '<b>분석 진행 중</b> · 경과 ' + mm + ':' + ss + '<br>지금 단계: ' + esc(stage) +
            '<br><span style="font-size:0.82rem; opacity:0.85;">전체 약 3~4분 걸립니다. 이 창을 닫지 마세요. 끝나면 보고서가 새 창으로 열리고, 이 브라우저에 자동 저장됩니다.</span>');
    }

    /** 서버·네트워크 오류를 원인과 대처가 보이는 말로 바꾼다. */
    function explain(message) {
        var m = String(message || '');
        if (/파싱|JSON/i.test(m)) return 'AI 응답 형식 오류로 분석이 끝나지 못했습니다. 같은 입력으로 다시 시도하면 대부분 해결됩니다(입력은 그대로 남아 있습니다).';
        if (/존재하지 않는 작업/.test(m)) return '서버가 재시작되어 진행 중이던 분석이 사라졌습니다(배포 직후에 생길 수 있습니다). 몇 분 뒤 다시 시도해 주세요.';
        if (/429|quota|한도/i.test(m)) return 'AI 호출 한도에 걸렸습니다. 몇 분 뒤 다시 시도해 주세요.';
        if (/API 키|GEMINI/i.test(m)) return '서버에 AI 키가 설정되지 않았거나 만료되었습니다. 관리자에게 문의해 주세요.';
        if (/8분|오래 걸/.test(m)) return m;
        if (/Failed to fetch|NetworkError|연결/i.test(m)) return '서버와 연결이 끊어졌습니다. 인터넷 연결을 확인한 뒤 다시 시도해 주세요.';
        return m + ' (입력은 그대로 남아 있으니 잠시 후 다시 시도해 주세요. 계속되면 오류 문구를 관리자에게 알려 주세요.)';
    }
    function showError(message, retry) {
        var el = $('analysis-status');
        if (!el) { alert(message); return; }
        el.innerHTML = box('error', '<b>분석이 끝나지 못했습니다.</b><br>' + esc(explain(message)) +
            (retry ? '<br><button type="button" id="retry-analysis" style="margin-top:0.5rem; padding:0.4rem 0.9rem; border:1px solid #fca5a5; background:white; color:#991b1b; border-radius:6px; font-weight:600; cursor:pointer;">🔁 같은 입력으로 다시 시도</button>' : ''));
        var b = $('retry-analysis');
        if (b && retry) b.addEventListener('click', function () { retry(); });
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    function showDone(url, opened, saved) {
        var el = $('analysis-status');
        if (!el) return;
        el.innerHTML = box('ok', '<b>분석이 끝났습니다.</b> ' + (opened ? '보고서가 새 창으로 열렸습니다.' : '새 창이 차단되었을 수 있습니다.') +
            ' <a href="' + esc(url) + '" target="_blank" style="color:#166534; font-weight:700;">보고서 열기</a>' +
            (saved ? '<br><span style="font-size:0.82rem;">이 분석은 이 브라우저에 저장되었습니다(아래 [저장된 분석]에서 다시 열 수 있습니다).</span>'
                : '<br><span style="font-size:0.82rem; color:#b45309;">브라우저 저장소를 쓸 수 없어 저장되지 않았습니다. 보고서에서 엑셀로 저장해 두세요.</span>'));
    }

    // ------------------------------------------------------------ 폼 값 모으기·채우기
    function typeValue() { var r = document.querySelector('input[name="projectType"]:checked'); return r ? r.value : '복합공사'; }
    function collectForm() {
        var parcels = window.LRForm ? window.LRForm.collectParcels() : [];
        var pending = [];
        document.querySelectorAll('.parcel-row').forEach(function (row) {
            if (row.dataset.verified !== 'true' && row.dataset.excelAddress) pending.push({ address: row.dataset.excelAddress, area: (row.querySelector('.p-area') || {}).value || '' });
        });
        return {
            projectName: $('projectName').value, projectType: typeValue(), budget: $('budget').value,
            budgetNational: $('budgetNational').value, budgetProvincial: $('budgetProvincial').value, budgetMunicipal: $('budgetMunicipal').value,
            publicWaterArea: $('publicWaterArea').value, description: $('description').value, parcels: parcels, pendingParcels: pending,
            design: window.TomokCard ? window.TomokCard.collect() : null,
        };
    }
    function applyForm(d) {
        $('projectName').value = d.projectName || '';
        var r = document.querySelector('input[name="projectType"][value="' + (d.projectType || '복합공사') + '"]');
        if (r) r.checked = true;
        $('budget').value = d.budget || '';
        $('budgetNational').value = d.budgetNational || '';
        $('budgetProvincial').value = d.budgetProvincial || '';
        $('budgetMunicipal').value = d.budgetMunicipal || '';
        $('publicWaterArea').value = d.publicWaterArea || 0;
        $('description').value = d.description || '';
        if (window.TomokCard) window.TomokCard.apply(d.design || null);
        if (window.LRForm) {
            window.LRForm.resetParcels();
            (d.parcels || []).forEach(function (p) { window.LRForm.restoreParcel(p); });
            (d.pendingParcels || []).forEach(function (p) { window.LRForm.addParcelRow(p.address, p.area || ''); });
            window.LRForm.updateTotalArea();
        }
        $('description').dispatchEvent(new Event('input', { bubbles: true }));
        refreshParcelSummary();
    }

    // ------------------------------------------------------------ 작성 중 내용 자동 보관
    function hasContent(d) { return !!(d && (d.projectName || d.description || d.design || (d.parcels && d.parcels.length) || (d.pendingParcels && d.pendingParcels.length))); }
    var saveDraft = debounce(function () {
        var d = collectForm();
        if (hasContent(d)) lsWrite(DRAFT_KEY, { savedAt: Date.now(), data: d }); else lsDrop(DRAFT_KEY);
    }, 800);
    function clearDraft() { lsDrop(DRAFT_KEY); var b = $('draft-banner'); if (b) b.innerHTML = ''; }
    function showDraftBanner() {
        var b = $('draft-banner');
        var d = lsRead(DRAFT_KEY);
        if (!b || !d || !hasContent(d.data) || hasContent(collectForm())) return;
        b.innerHTML = box('info', '이전에 작성하던 내용이 있습니다(' + esc(fmtDate(d.savedAt)) + ', 사업명: ' + esc(d.data.projectName || '없음') + '). ' +
            '<button type="button" id="draft-load" style="margin-left:0.4rem; padding:0.25rem 0.7rem; border:1px solid #93c5fd; background:white; border-radius:6px; cursor:pointer; font-weight:600;">불러오기</button>' +
            '<button type="button" id="draft-drop" style="margin-left:0.3rem; padding:0.25rem 0.7rem; border:1px solid #cbd5e1; background:white; border-radius:6px; cursor:pointer;">버리기</button>');
        $('draft-load').addEventListener('click', function () { applyForm(d.data); b.innerHTML = ''; notify('작성 중이던 내용을 불러왔습니다.', 'ok'); });
        $('draft-drop').addEventListener('click', clearDraft);
    }

    // ------------------------------------------------------------ 저장된 분석
    function refreshSaved() {
        var el = $('saved-panel');
        if (!el || !Store()) return;
        var list = Store().list();
        if (!list.length) { el.innerHTML = ''; return; }
        var rows = list.map(function (r) {
            return '<tr data-id="' + esc(r.id) + '"><td style="padding:0.4rem 0.5rem;"><b>' + esc(r.name) + '</b><br><span style="color:#64748b; font-size:0.78rem;">' + esc(fmtDate(r.savedAt)) + ' · ' + esc(r.type || '') + ' · 항목 ' + (r.itemCount || 0) + '개</span></td>' +
                '<td style="padding:0.4rem 0.5rem; white-space:nowrap; text-align:right;">' +
                '<a class="sv-open" href="/report?rec=' + esc(r.id) + '" target="_blank" style="margin-right:0.4rem; font-size:0.85rem;">📄 보고서 열기</a>' +
                '<button type="button" class="sv-load" style="padding:0.25rem 0.6rem; border:1px solid #cbd5e1; background:white; border-radius:6px; cursor:pointer; font-size:0.82rem;">입력 불러오기</button>' +
                '<button type="button" class="sv-del" style="margin-left:0.3rem; padding:0.25rem 0.6rem; border:1px solid #fca5a5; background:white; color:#b91c1c; border-radius:6px; cursor:pointer; font-size:0.82rem;">삭제</button></td></tr>';
        }).join('');
        el.innerHTML = '<details open style="border:1px solid #e2e8f0; border-radius:8px; padding:0.6rem 0.8rem; background:#f8fafc;"><summary style="cursor:pointer; font-weight:700;">📁 저장된 분석 ' + list.length + '건 <span style="font-weight:400; color:#64748b; font-size:0.8rem;">(이 브라우저에만 저장, 최근 ' + Store().MAX_RECORDS + '건)</span></summary>' +
            '<table style="width:100%; border-collapse:collapse; margin-top:0.4rem;">' + rows + '</table></details>';
        el.querySelectorAll('tr[data-id]').forEach(function (tr) {
            var id = tr.dataset.id;
            tr.querySelector('.sv-load').addEventListener('click', function () {
                var rec = Store().get(id);
                if (!rec) { notify('저장된 기록을 찾을 수 없습니다.', 'error'); return; }
                if (hasContent(collectForm()) && !confirm('지금 입력한 내용이 저장된 분석의 입력으로 바뀝니다. 계속할까요?')) return;
                applyForm(rec.requestData || {});
                notify('"' + rec.name + '"의 입력을 불러왔습니다. 필요한 부분만 고쳐 다시 분석하세요.', 'ok');
                window.scrollTo({ top: 0, behavior: 'smooth' });
            });
            tr.querySelector('.sv-del').addEventListener('click', function () {
                if (confirm('이 저장된 분석(점검 체크·메모 포함)을 삭제할까요? 되돌릴 수 없습니다.')) { Store().remove(id); refreshSaved(); }
            });
        });
    }

    // ------------------------------------------------------------ 필지 검증 요약
    function parcelStates() {
        var s = { ok: 0, warn: [], fail: [], pending: [], total: 0 };
        document.querySelectorAll('.parcel-row').forEach(function (row) {
            var badge = row.querySelector('.status-badge');
            var failed = badge && /error-tag/.test(badge.className);
            s.total++;
            if (row.dataset.verified === 'true') { if (row.dataset.zoningError === '1') s.warn.push(row); else s.ok++; }
            else if (failed) s.fail.push(row);
            else s.pending.push(row);
        });
        return s;
    }
    function refreshParcelSummary(scroll) {
        var el = $('parcel-summary');
        if (!el) return;
        var s = parcelStates();
        if (!s.total) { el.innerHTML = ''; return; }
        var parts = ['필지 ' + s.total + '개'];
        if (s.ok) parts.push('<span style="color:#166534;">✅ 검증 완료 ' + s.ok + '</span>');
        if (s.warn.length) parts.push('<span style="color:#b45309;">⚠ 지역지구 조회 오류 ' + s.warn.length + '</span>');
        if (s.fail.length) parts.push('<span style="color:#b91c1c;">❌ 검증 실패 ' + s.fail.length + '</span>');
        if (s.pending.length) parts.push('<span style="color:#64748b;">⏳ 검증 전 ' + s.pending.length + '</span>');
        var need = s.warn.length + s.fail.length;
        var html = '<div style="font-size:0.88rem; display:flex; flex-wrap:wrap; gap:0.9rem; align-items:center;">' + parts.join(' · ');
        if (need) html += '<button type="button" id="ps-retry" style="padding:0.3rem 0.7rem; border:1px solid #93c5fd; background:white; border-radius:6px; cursor:pointer; font-weight:600;">🔁 실패·오류 필지만 다시 검증</button>' +
            '<button type="button" id="ps-drop" style="padding:0.3rem 0.7rem; border:1px solid #fca5a5; color:#b91c1c; background:white; border-radius:6px; cursor:pointer;">실패한 필지 삭제</button>';
        html += '</div>';
        if (need) html += '<div style="font-size:0.8rem; color:#64748b; margin-top:0.3rem;">실패 사유는 표의 빨간 글씨를 보세요. 주소가 지번까지 정확한지(예: 경남 남해군 남해읍 입현리 1), 산지는 "산 12-3"처럼 적었는지 확인하세요.</div>';
        el.innerHTML = html;
        var r = $('ps-retry'), d = $('ps-drop');
        if (r) r.addEventListener('click', async function () {
            r.disabled = true; r.textContent = '다시 검증 중...';
            var targets = s.warn.concat(s.fail);
            for (var i = 0; i < targets.length; i++) { targets[i].style.outline = ''; window.LRForm.unverifyRow(targets[i]); await window.LRForm.verifyRow(targets[i]); }
            refreshParcelSummary();
        });
        if (d) d.addEventListener('click', function () {
            if (!confirm('검증에 실패한 필지 ' + s.fail.length + '개를 목록에서 삭제할까요?')) return;
            s.fail.forEach(function (row) { row.remove(); });
            window.LRForm.checkBulkVerifyButton(); refreshParcelSummary();
        });
        if (scroll) el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    // ------------------------------------------------------------ 주소 붙여넣기
    function parsePasted(text) {
        var out = [];
        String(text || '').split(/\r?\n/).forEach(function (line) {
            line = line.replace(/^\s*(?:\d+\s*[.)]\s*|[-•·]\s*)/, '').trim();
            if (!line) return;
            var addr = line, area = '';
            var tab = line.split('\t');
            if (tab.length >= 2) { addr = tab[0].trim(); area = tab[1].replace(/[^\d.]/g, ''); }
            else {
                var m = line.match(/^(.*\S)\s*[,，]\s*([\d,]+(?:\.\d+)?)\s*(?:㎡|m2|제곱미터)?\s*$/);
                if (m) { addr = m[1].trim(); area = m[2].replace(/,/g, ''); }
            }
            if (addr.length >= 4) out.push({ address: addr.replace(/\s+/g, ' '), area: area });
        });
        return out;
    }
    function existingAddresses() {
        var set = {};
        document.querySelectorAll('.parcel-row').forEach(function (row) { var a = row.dataset.fullAddr || row.dataset.excelAddress; if (a) set[a.replace(/\s+/g, ' ').trim()] = true; });
        return set;
    }
    function initPaste() {
        var btn = $('paste-parcel-btn'), panel = $('paste-panel');
        if (!btn || !panel) return;
        btn.addEventListener('click', function () { panel.style.display = panel.style.display === 'none' ? 'block' : 'none'; if (panel.style.display === 'block') $('paste-text').focus(); });
        $('paste-cancel').addEventListener('click', function () { panel.style.display = 'none'; });
        $('paste-add').addEventListener('click', function () {
            var items = parsePasted($('paste-text').value);
            if (!items.length) { notify('붙여넣은 내용에서 주소를 찾지 못했습니다. 한 줄에 주소 하나씩 적어 주세요(예: 경남 남해군 남해읍 입현리 1).', 'error'); return; }
            var have = existingAddresses(), added = 0, dup = 0;
            // 아직 아무것도 입력하지 않은 빈 수동 행은 지운다
            document.querySelectorAll('.parcel-row').forEach(function (row) {
                if (!row.dataset.excelAddress && row.dataset.verified !== 'true' && !row.querySelector('.p-addr').value && !row.querySelector('.p-bonbeon').value) row.remove();
            });
            items.forEach(function (it) {
                if (have[it.address]) { dup++; return; }
                have[it.address] = true;
                window.LRForm.addParcelRow(it.address, it.area);
                added++;
            });
            $('paste-text').value = '';
            panel.style.display = 'none';
            notify(added + '개 주소를 추가했습니다' + (dup ? ' (이미 있는 ' + dup + '개는 건너뜀)' : '') + '. 이어서 지목·지역지구를 자동으로 조회합니다.', 'ok');
            window.LRForm.checkBulkVerifyButton();
            var bulk = $('bulk-verify-btn');
            if (added && bulk && !bulk.disabled) bulk.click();
        });
    }

    // ------------------------------------------------------------ 사업 내용에 빠진 정보 안내
    var HINTS = [
        { id: 'scale', label: '규모(연장·폭·면적)', re: /연장|폭|면적|연면적|L\s*=|B\s*=/, line: '- 규모: 연장 ○○m, 폭 ○○m (또는 면적 ○○㎡)' },
        { id: 'dig', label: '굴착·절토 깊이', re: /굴착|터파기|절토|성토/, line: '- 굴착·절토: 최대 깊이 ○m (흙막이·가설구조물 여부)' },
        { id: 'struct', label: '주요 구조물', re: /옹벽|교량|암거|가시설|배수구조물|구조물/, line: '- 주요 구조물: 옹벽(높이 ○m), 교량(연장 ○m), 암거 등' },
        { id: 'demo', label: '철거·해체', re: /철거|해체/, line: '- 철거·해체: 기존 시설물 철거 여부(석면·건설폐기물 발생 여부)' },
        { id: 'water', label: '하천·공유수면', re: /하천|공유수면|수변|바다|해상|소하천/, line: '- 하천·공유수면: 횡단·점용 여부' },
        { id: 'road', label: '도로 점용·굴착', re: /점용|도로구역|도로굴착|접도구역/, line: '- 도로 점용·굴착: 기존 도로 점용 또는 굴착 여부' },
        { id: 'utility', label: '지장물(상·하수도·전기·통신)', re: /지장물|상수도|하수|전력|전기|통신|가스/, line: '- 지장물: 기존 상·하수도·전기·통신·가스 시설 이설 여부' },
        { id: 'method', label: '시행·감독 방식', re: /도급|직영|감리|건설사업관리|감독/, line: '- 시행 방식: 도급/직영, 감리(건설사업관리) 적용 여부' },
        { id: 'env', label: '산지·농지·문화재 저촉', re: /산지|농지|문화재|매장|보호구역|임야/, line: '- 환경·문화재: 산지·농지·문화재(보호구역) 저촉 여부' },
    ];
    var PLACEHOLDERS = {
        건축공사: '예) 지하 1층 / 지상 4층 공공도서관 신축, 연면적 약 3,500㎡, 최대 굴착깊이 6m, 노후 건축물 철거 후 신축',
        토목공사: '예) 소로2류 도로 개설 연장 300m 폭 8m, 포장·배수시설, 옹벽 2개소(높이 3m), 일부 구간 절토 2m, 기존 상수도 이설',
        조경공사: '예) 근린공원 조성 약 12,000㎡, 잔디광장·산책로·식재, 절·성토 약 3,000㎥, 경사지 일부 포함',
        복합공사: '예) 공종별 주요 제원을 적어 주세요(규모, 굴착·절토 깊이, 구조물, 철거 여부, 하천·도로 점용 등)',
    };
    function refreshHints() {
        var ta = $('description'), el = $('desc-hints');
        if (!ta || !el) return;
        ta.placeholder = PLACEHOLDERS[typeValue()] || PLACEHOLDERS.복합공사;
        var text = ta.value;
        var missing = HINTS.filter(function (h) { return !h.re.test(text); });
        if (!text.trim()) { el.innerHTML = '<div style="font-size:0.82rem; color:#64748b;">사업 내용을 적을수록 결과가 정확해집니다. 아래 항목을 눌러 줄을 추가해 보세요.</div>' + chips(missing); }
        else if (!missing.length) { el.innerHTML = '<div style="font-size:0.82rem; color:#166534;">✅ 주요 제원 항목이 모두 들어 있습니다.</div>'; return; }
        else el.innerHTML = '<div style="font-size:0.82rem; color:#64748b;">더 적으면 정확해지는 정보 (눌러서 줄 추가, 해당 없으면 무시):</div>' + chips(missing);
        el.querySelectorAll('.hint-chip').forEach(function (b) {
            b.addEventListener('click', function () {
                var h = HINTS.filter(function (x) { return x.id === b.dataset.id; })[0];
                ta.value = (ta.value.replace(/\s+$/, '') + (ta.value.trim() ? '\n' : '') + h.line);
                ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length);
                ta.dispatchEvent(new Event('input', { bubbles: true }));
            });
        });
    }
    function chips(list) {
        return '<div style="display:flex; flex-wrap:wrap; gap:0.35rem; margin-top:0.35rem;">' + list.map(function (h) {
            return '<button type="button" class="hint-chip" data-id="' + h.id + '" style="padding:0.25rem 0.6rem; border:1px solid #cbd5e1; background:white; border-radius:999px; font-size:0.8rem; cursor:pointer;">＋ ' + esc(h.label) + '</button>';
        }).join('') + '</div>';
    }

    // ------------------------------------------------------------ 시작
    function init() {
        window.LRInput = { notify: notify, clearMessages: clearMessages, showProgress: showProgress, showError: showError, showDone: showDone, refreshSaved: refreshSaved, refreshParcelSummary: refreshParcelSummary, clearDraft: clearDraft, explain: explain, parsePasted: parsePasted };
        refreshSaved();
        initPaste();
        refreshHints();
        refreshParcelSummary();
        showDraftBanner();
        var form = $('project-form');
        if (form) {
            form.addEventListener('input', saveDraft);
            form.addEventListener('change', saveDraft);
            $('description').addEventListener('input', debounce(refreshHints, 300));
            form.addEventListener('change', function (e) { if (e.target && e.target.name === 'projectType') refreshHints(); });
        }
        var pc = $('parcel-container');
        if (pc && window.MutationObserver) {
            var onChange = debounce(function () { refreshParcelSummary(); saveDraft(); }, 250);
            new MutationObserver(onChange).observe(pc, { childList: true, subtree: true, attributes: true, characterData: true, attributeFilter: ['class', 'data-verified', 'data-zoning-error'] });
        }
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { setTimeout(init, 0); });
    else setTimeout(init, 0);
})();
