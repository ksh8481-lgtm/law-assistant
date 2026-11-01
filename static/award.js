/* 적격심사 종합평점 계산 화면 (지방자치단체 입찰시 낙찰자 결정기준).
 * 점수는 서버의 award_engine.py가 규정 값(award_specs/*.json)대로 계산한다. 이 파일은 입력을 모아 보내고 결과를 보여 줄 뿐이다. */
(function () {
    'use strict';

    var SPEC_ID = 'jibang_jeokgyeok_tech';
    var DRAFT_KEY = 'award_draft_v1';
    var IMPORT_KEY = 'pq_to_award';     // PQ 점수 산정 화면(pq_score.js)이 넘겨 주는 값
    var MAX_BIDDERS = 40;

    var spec = null;
    var S = { project: { est: '', plan: '', localApplied: '1', localKind: 'main', careerExcluded: false }, bidders: [] };
    var lastResult = null;

    function $(id) { return document.getElementById(id); }
    function el(tag, attrs, children) {
        var e = document.createElement(tag);
        Object.keys(attrs || {}).forEach(function (k) {
            var v = attrs[k];
            if (v === null || v === undefined || v === false) return;
            if (k === 'text') e.textContent = v;
            else if (k === 'class') e.className = v;
            else if (k.slice(0, 2) === 'on') e[k] = v;
            else e.setAttribute(k, v === true ? '' : v);
        });
        (children || []).forEach(function (c) { if (c) e.appendChild(c); });
        return e;
    }

    // 소수점 아래 불필요한 0을 뺀 점수 표시(최대 4자리: 규정의 반올림 자리와 같다)
    function fmt(n) {
        if (n === null || n === undefined || n === '') return '';
        var s = (Math.round(Number(n) * 10000) / 10000).toFixed(4);
        return s.replace(/0+$/, '').replace(/\.$/, '');
    }
    function won(n) { return Number(n).toLocaleString('ko-KR', { maximumFractionDigits: 2 }); }
    function toNum(v) {
        var x = parseFloat(String(v === undefined || v === null ? '' : v).replace(/,/g, '').trim());
        return isNaN(x) ? null : x;
    }

    function newBidder(name) {
        return { name: name || '', pq_score: '', penalty_deduction: '', bid_price: '', career_ratio: '', local_ratio: '', local_solo: false,
                 mgmt_mode: 'full', mgmt_tier: 't20', mgmt_score: '', tech_shortage: false, wage_arrears_count: '' };
    }

    // ------------------------------------------------------------ 임시 저장
    function saveDraft() {
        try { localStorage.setItem(DRAFT_KEY, JSON.stringify(S)); } catch (e) { /* 저장소를 못 쓰면 이번 방문 동안만 유지 */ }
    }
    function loadDraft() {
        try {
            var d = JSON.parse(localStorage.getItem(DRAFT_KEY) || 'null');
            if (d && d.project && Array.isArray(d.bidders)) {
                S.project = Object.assign(S.project, d.project);
                S.bidders = d.bidders.slice(0, MAX_BIDDERS).map(function (b) { return Object.assign(newBidder(), b); });
            }
        } catch (e) { /* 무시 */ }
    }

    // PQ 점수 산정 화면에서 넘어온 입찰사(이름·PQ 점수)를 반영한다. 같은 이름의 행이 있으면 PQ 점수만 갱신하고 나머지 입력은 유지한다.
    function importFromPq() {
        var raw = null;
        try { raw = JSON.parse(localStorage.getItem(IMPORT_KEY) || 'null'); localStorage.removeItem(IMPORT_KEY); } catch (e) { raw = null; }
        if (!raw || !Array.isArray(raw.bidders) || !raw.bidders.length) return;
        raw.bidders.slice(0, MAX_BIDDERS).forEach(function (pb) {
            var found = S.bidders.filter(function (b) { return b.name === pb.name; })[0];
            if (!found) {
                // 비어 있는 첫 행(이름·점수가 없는 행)이 있으면 그 자리에 넣는다
                found = S.bidders.filter(function (b) { return !b.name && b.pq_score === ''; })[0];
                if (!found) { found = newBidder(); S.bidders.push(found); }
                found.name = pb.name;
            }
            found.pq_score = String(Math.round(Number(pb.pq_score) * 10000) / 10000);
        });
        $('importBanner').appendChild(el('div', { class: 'banner', text: 'PQ 점수 산정 화면에서 ' + raw.bidders.length + '개 입찰사의 이름과 PQ 점수를 불러왔습니다' +
            (raw.from ? ' (' + raw.from + ')' : '') + '. 입찰가격 등 나머지 항목을 입력해 주세요. 실격한 입찰사는 넘어오지 않습니다.' }));
        saveDraft();
    }

    // ------------------------------------------------------------ 적용 구간 안내
    function pickBand(est) {
        var bands = spec.bands.slice().sort(function (a, b) { return b.min_estimated_price - a.min_estimated_price; });
        for (var i = 0; i < bands.length; i++) if (est >= bands[i].min_estimated_price) return bands[i];
        return bands[bands.length - 1];
    }
    function renderBand() {
        var box = $('bandBox');
        var est = toNum(S.project.est);
        if (est === null || est <= 0) { box.style.display = 'none'; return; }
        var band = pickBand(est);
        var w = band.weights;
        var localOff = S.project.localApplied === '0';
        var pqW = w.pq + (localOff ? w.local : 0);
        box.style.display = '';
        box.textContent = '';
        box.appendChild(el('div', {}, [el('b', { text: band.label }), document.createTextNode(' 구간 → 적격통과점수 '),
            el('b', { text: band.pass_score + '점 이상' }), document.createTextNode(' (' + band.ref + ')')]));
        var chips = [['PQ 환산', pqW], ['책임기술자 경력', w.career], ['지역업체 참여도', localOff ? 0 : w.local], ['경영상태', w.mgmt], ['입찰가격', w.price]];
        var wrap = el('div', { class: 'weights' });
        chips.forEach(function (c) { wrap.appendChild(el('span', { text: c[0] + ' ' + c[1] + '점' })); });
        wrap.appendChild(el('span', { text: '합계 100점 (감점: 기술인력 미달 -10, 임금체불 건당 -0.2)' }));
        box.appendChild(wrap);
        box.appendChild(el('div', { class: 'status', style: 'margin-top:0.4rem;', text: '입찰가격 평점: ' + band.price.ref }));
    }

    // ------------------------------------------------------------ 입찰사 표
    var COLS = ['입찰사', 'PQ 점수', '벌점 감점', '입찰가격 (원)', '책임기술자 경력 비율 (%)', '지역업체 참여비율 (%)', '경영상태', '기술인력 미달', '임금체불 공개 (회)', ''];

    function textInput(i, f, extra) {
        var b = S.bidders[i];
        var attrs = Object.assign({ type: 'text', 'data-i': i, 'data-f': f, value: b[f], inputmode: 'decimal', autocomplete: 'off' }, extra || {});
        return el('input', attrs);
    }
    function renderBidders() {
        var t = $('bidderTable');
        t.textContent = '';
        t.appendChild(el('thead', {}, [el('tr', {}, COLS.map(function (c) { return el('th', { text: c }); }))]));
        var tb = el('tbody');
        var localOff = S.project.localApplied === '0';
        var careerOff = !!S.project.careerExcluded;
        S.bidders.forEach(function (b, i) {
            var mg = el('td');
            var sel = el('select', { 'data-i': i, 'data-f': 'mgmt_mode' });
            [['full', '만점 (PQ에 반영됨)'], ['credit', '신용평가 구간 선택'], ['score', '점수 직접 입력']].forEach(function (o) {
                sel.appendChild(el('option', { value: o[0], text: o[1], selected: b.mgmt_mode === o[0] }));
            });
            mg.appendChild(sel);
            if (b.mgmt_mode === 'credit') {
                var tier = el('select', { 'data-i': i, 'data-f': 'mgmt_tier', class: 'sub-input' });
                (spec.mgmt.credit_tiers || []).forEach(function (c) {
                    tier.appendChild(el('option', { value: c.id, text: c.score.toFixed(1) + '점 · ' + c.label, selected: b.mgmt_tier === c.id }));
                });
                mg.appendChild(tier);
            } else if (b.mgmt_mode === 'score') {
                mg.appendChild(textInput(i, 'mgmt_score', { class: 'sub-input', placeholder: '0 ~ ' + spec.mgmt.max }));
            }
            var local = el('td', {}, [textInput(i, 'local_ratio', localOff || b.local_solo ? { disabled: true } : {})]);
            if (!localOff) {
                local.appendChild(el('label', { class: 'check', style: 'margin-top:0.3rem; font-size:0.75rem;' }, [
                    el('input', { type: 'checkbox', 'data-i': i, 'data-f': 'local_solo', checked: b.local_solo }), el('span', { text: '지역업체 단독 참여 (0점)' })]));
            }
            tb.appendChild(el('tr', {}, [
                el('td', {}, [textInput(i, 'name', { class: 'w-name', inputmode: 'text', placeholder: '입찰사 ' + (i + 1) })]),
                el('td', {}, [textInput(i, 'pq_score')]),
                el('td', {}, [textInput(i, 'penalty_deduction', { placeholder: '0' })]),
                el('td', {}, [textInput(i, 'bid_price', { class: 'w-price' })]),
                el('td', {}, [textInput(i, 'career_ratio', careerOff ? { disabled: true } : {})]),
                local, mg,
                el('td', { class: 'c' }, [el('input', { type: 'checkbox', 'data-i': i, 'data-f': 'tech_shortage', checked: b.tech_shortage })]),
                el('td', {}, [textInput(i, 'wage_arrears_count', { placeholder: '0' })]),
                el('td', { class: 'c' }, [el('button', { type: 'button', class: 'btn btn-ghost btn-sm', 'data-del': i, text: '삭제', title: '이 입찰사를 뺍니다' })])
            ]));
        });
        t.appendChild(tb);
        $('addBidderBtn').disabled = S.bidders.length >= MAX_BIDDERS;
    }

    // ------------------------------------------------------------ 계산 요청
    function payload() {
        var p = S.project;
        return {
            spec_id: SPEC_ID,
            project: { estimated_price: p.est, planned_price: p.plan, local_applied: p.localApplied !== '0', local_kind: p.localKind, career_excluded: !!p.careerExcluded },
            bidders: S.bidders.map(function (b) {
                return { name: b.name, pq_score: b.pq_score, penalty_deduction: b.penalty_deduction, bid_price: b.bid_price,
                         career_ratio: b.career_ratio, local_ratio: b.local_ratio, local_solo: !!b.local_solo, mgmt_mode: b.mgmt_mode,
                         mgmt_tier: b.mgmt_tier, mgmt_score: b.mgmt_score, tech_shortage: !!b.tech_shortage, wage_arrears_count: b.wage_arrears_count };
            })
        };
    }
    function calc() {
        var btn = $('calcBtn'), st = $('calcStatus');
        st.className = 'status'; st.textContent = '계산 중...'; btn.disabled = true;
        fetch('/api/award/evaluate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload()) })
            .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
            .then(function (x) {
                if (!x.ok || !x.d.success) { st.className = 'status err'; st.textContent = x.d.message || '계산하지 못했습니다.'; return; }
                st.textContent = '';
                lastResult = x.d.result;
                renderResult(lastResult);
            })
            .catch(function () { st.className = 'status err'; st.textContent = '서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.'; })
            .then(function () { btn.disabled = false; });
    }

    // ------------------------------------------------------------ 결과 표시
    var STATUS = {
        winner: ['winner', '🏆 낙찰자'], lottery: ['lottery', '🎲 추첨 대상'], pass: ['pass', '통과 (동가 중 PQ 점수 낮음)'],
        fail: ['fail', '미달'], after: ['after', '심사 생략'], over: ['over', '예정가격 초과 (제외)']
    };
    function statusTag(r) {
        var s = STATUS[r.status] || ['after', r.status];
        var txt = s[1];
        if (r.status === 'fail') txt = '미달 (' + fmt(r.shortfall) + '점 부족)';
        return el('span', { class: 'tag ' + s[0], text: txt });
    }

    function renderResult(res) {
        var box = $('results');
        box.textContent = '';
        var rs = res.results;
        var win = res.winner_index !== null ? rs[res.winner_index] : null;
        var cls = win ? 'winner-box' : (res.lottery_indexes.length ? 'winner-box lottery' : 'winner-box none');
        var wb = el('div', { class: cls });
        if (win) {
            wb.appendChild(el('div', {}, [el('b', { text: '🏆 낙찰자: ' + win.name }), document.createTextNode(' — 종합평점 ' + fmt(win.total) + '점 (적격통과점수 ' + fmt(res.band.pass_score) + '점 이상)')]));
            wb.appendChild(el('div', { class: 'status', text: '입찰가격 ' + won(win.bid_price) + '원 (예정가격의 ' + fmt(win.price_ratio * 100) + '%), 심사 순서 ' + win.review_order + '번째' }));
        } else if (res.lottery_indexes.length) {
            wb.appendChild(el('div', {}, [el('b', { text: '🎲 추첨으로 낙찰자를 정해야 합니다: ' + res.lottery_indexes.map(function (i) { return rs[i].name; }).join(', ') })]));
        } else {
            wb.appendChild(el('div', {}, [el('b', { text: '낙찰자가 없습니다 (적격통과점수 ' + fmt(res.band.pass_score) + '점 이상인 입찰사 없음)' })]));
        }
        box.appendChild(wb);
        if (res.notes.length) {
            var ul = el('ul', { class: 'status', style: 'margin:0 0 1rem 1.2rem; line-height:1.7;' });
            res.notes.forEach(function (n) { ul.appendChild(el('li', { text: n })); });
            box.appendChild(ul);
        }

        var order = rs.map(function (r, i) { return i; }).sort(function (a, b) {
            var ra = rs[a].review_order === null ? 1e9 : rs[a].review_order, rb = rs[b].review_order === null ? 1e9 : rs[b].review_order;
            return ra - rb || a - b;
        });
        var w = res.weights;
        var head = ['심사 순서', '입찰사', '입찰가격 (예정가격 대비)', 'PQ 환산 (' + fmt(w.pq) + ')', '경력 (' + fmt(w.career) + ')', '지역업체 (' + fmt(w.local) + ')',
                    '경영상태 (' + fmt(w.mgmt) + ')', '입찰가격 (' + fmt(w.price) + ')', '감점', '종합평점', '판정'];
        var t = el('table');
        t.appendChild(el('thead', {}, [el('tr', {}, head.map(function (h, i) { return el('th', { class: i >= 3 && i <= 9 ? 'num' : null, text: h }); }))]));
        var tb = el('tbody');
        order.forEach(function (i) {
            var r = rs[i], sc = r.scores;
            tb.appendChild(el('tr', { class: 's-' + r.status }, [
                el('td', { text: r.review_order === null ? '-' : String(r.review_order) }),
                el('td', { text: r.name }),
                el('td', { text: won(r.bid_price) + '원 (' + fmt(r.price_ratio * 100) + '%)' }),
                el('td', { class: 'num', text: fmt(sc.pq) }), el('td', { class: 'num', text: fmt(sc.career) }), el('td', { class: 'num', text: fmt(sc.local) }),
                el('td', { class: 'num', text: fmt(sc.mgmt) }), el('td', { class: 'num', text: fmt(sc.price) }), el('td', { class: 'num', text: fmt(sc.deduction) }),
                el('td', { class: 'num total' }, [el('span', { class: 'score-big', text: fmt(r.total) })]),
                el('td', {}, [statusTag(r)])
            ]));
        });
        t.appendChild(tb);
        box.appendChild(el('div', { class: 'tbl-wrap' }, [t]));

        box.appendChild(el('div', { class: 'no-print', style: 'margin:0.8rem 0; display:flex; gap:0.6rem; flex-wrap:wrap;' }, [
            el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: 'CSV로 저장', onclick: function () { downloadCsv(res); } }),
            el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: '인쇄 / PDF 저장', onclick: function () { window.print(); } })
        ]));

        order.forEach(function (i) {
            var r = rs[i];
            var det = el('details', { class: 'sub', open: rs.length === 1 ? true : null });
            det.appendChild(el('summary', { text: (r.review_order === null ? '제외' : r.review_order + '순위') + ' · ' + r.name + ' · 종합평점 ' + fmt(r.total) + '점 (계산 근거 보기)' }));
            var ul2 = el('ul', { class: 'basis', style: 'margin:0.5rem 0 0 1.1rem;' });
            r.basis.forEach(function (b) { ul2.appendChild(el('li', { text: b })); });
            ul2.appendChild(el('li', { text: '합계: ' + fmt(r.scores.pq) + ' + ' + fmt(r.scores.career) + ' + ' + fmt(r.scores.local) + ' + ' + fmt(r.scores.mgmt) + ' + ' + fmt(r.scores.price) +
                (r.scores.deduction ? ' - ' + fmt(-r.scores.deduction) : '') + ' = ' + fmt(r.total) + '점 (적격통과점수 ' + fmt(res.band.pass_score) + '점)' }));
            det.appendChild(ul2);
            box.appendChild(det);
        });

        var src = res.source || {};
        box.appendChild(el('p', { class: 'status', style: 'margin-top:1rem; line-height:1.7;', text:
            '적용 규정: ' + src.law_name + ' (' + src.issuer + ', 시행 ' + src.effective + ') - ' + res.band.ref + '. 적격통과점수 근거: ' + res.band.pass_ref + '. ' +
            '본 결과는 입력값을 규정 산식에 적용한 계산 결과이며, 입력값의 진위는 공식 자료로 확인해야 합니다. 낙찰자 결정은 입찰공고와 계약담당자의 심사에 따릅니다.' }));
        box.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    function csvCell(v) {
        var s = String(v === undefined || v === null ? '' : v);
        return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
    }
    function downloadCsv(res) {
        var rows = [['심사 순서', '입찰사', '입찰가격(원)', '예정가격 대비(%)', 'PQ 점수', 'PQ 환산', '책임기술자 경력', '지역업체 참여도', '경영상태', '입찰가격 평점', '감점', '종합평점', '적격통과점수', '판정']];
        var label = { winner: '낙찰자', lottery: '추첨 대상', pass: '통과(동가 중 PQ 점수 낮음)', fail: '미달', after: '심사 생략', over: '예정가격 초과(제외)' };
        res.results.forEach(function (r) {
            var s = r.scores;
            rows.push([r.review_order === null ? '' : r.review_order, r.name, r.bid_price, fmt(r.price_ratio * 100), r.pq_score, s.pq, s.career, s.local, s.mgmt, s.price, s.deduction,
                       r.total, res.band.pass_score, label[r.status] || r.status]);
        });
        rows.push([]);
        rows.push(['입찰사', '계산 근거']);
        res.results.forEach(function (r) { r.basis.forEach(function (b) { rows.push([r.name, b]); }); });
        var csv = '\ufeff' + rows.map(function (r) { return r.map(csvCell).join(','); }).join('\r\n');   // 앞의 BOM은 엑셀이 한글을 깨지 않고 열게 한다
        var a = document.createElement('a');
        a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
        a.download = '적격심사_종합평점_결과.csv';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    }

    // ------------------------------------------------------------ 이벤트
    function bindProject() {
        var map = { estPrice: 'est', planPrice: 'plan' };
        Object.keys(map).forEach(function (id) {
            $(id).value = S.project[map[id]];
            $(id).addEventListener('input', function () { S.project[map[id]] = this.value; renderBand(); saveDraft(); });
        });
        $('localApplied').value = S.project.localApplied;
        $('localApplied').addEventListener('change', function () { S.project.localApplied = this.value; renderBand(); renderBidders(); saveDraft(); });
        $('localKind').value = S.project.localKind;
        $('localKind').addEventListener('change', function () { S.project.localKind = this.value; saveDraft(); });
        $('careerExcluded').checked = !!S.project.careerExcluded;
        $('careerExcluded').addEventListener('change', function () { S.project.careerExcluded = this.checked; renderBidders(); saveDraft(); });
    }

    function bindTable() {
        var t = $('bidderTable');
        function onField(e) {
            var f = e.target.getAttribute && e.target.getAttribute('data-f');
            if (!f) return;
            var i = parseInt(e.target.getAttribute('data-i'), 10);
            var b = S.bidders[i];
            if (!b) return;
            b[f] = e.target.type === 'checkbox' ? e.target.checked : e.target.value;
            if (e.type === 'change' && (f === 'mgmt_mode' || f === 'local_solo')) renderBidders();   // 입력칸 구성이 바뀌는 항목만 다시 그린다
            saveDraft();
        }
        t.addEventListener('input', onField);
        t.addEventListener('change', onField);
        t.addEventListener('click', function (e) {
            var d = e.target.getAttribute && e.target.getAttribute('data-del');
            if (d === null || d === undefined) return;
            S.bidders.splice(parseInt(d, 10), 1);
            if (!S.bidders.length) S.bidders.push(newBidder());
            renderBidders(); saveDraft();
        });
        $('addBidderBtn').addEventListener('click', function () {
            if (S.bidders.length >= MAX_BIDDERS) return;
            S.bidders.push(newBidder());
            renderBidders(); saveDraft();
        });
        $('clearBtn').addEventListener('click', function () {
            if (!confirm('입력한 내용을 모두 지우고 처음 상태로 되돌릴까요?')) return;
            try { localStorage.removeItem(DRAFT_KEY); } catch (e) { /* 무시 */ }
            S = { project: { est: '', plan: '', localApplied: '1', localKind: 'main', careerExcluded: false }, bidders: [newBidder(), newBidder()] };
            ['estPrice', 'planPrice'].forEach(function (id) { $(id).value = ''; });
            $('localApplied').value = '1'; $('localKind').value = 'main'; $('careerExcluded').checked = false;
            $('results').textContent = ''; $('importBanner').textContent = '';
            renderBand(); renderBidders();
        });
        $('calcBtn').addEventListener('click', calc);
    }

    function renderSpecInfo() {
        var s = spec.source;
        var info = $('specInfo');
        info.className = '';
        info.textContent = '';
        info.appendChild(el('div', {}, [el('b', { text: spec.name })]));
        info.appendChild(el('div', { class: 'status', style: 'margin-top:0.3rem; line-height:1.6;', text:
            s.law_name + ' (' + s.issuer + ', ' + s.issued + ' 발령, ' + s.effective + ' 시행) · ' + s.where }));
        var nt = $('specNotice');
        nt.textContent = '';
        var ul = el('ul');
        spec.notice.forEach(function (n) { ul.appendChild(el('li', { text: n })); });
        nt.appendChild(el('div', { class: 'notice' }, [ul]));
    }

    document.addEventListener('DOMContentLoaded', function () {
        fetch('/api/award/spec/' + SPEC_ID).then(function (r) { return r.json(); }).then(function (d) {
            if (!d.success) throw new Error(d.message);
            spec = d.spec;
            loadDraft();
            if (!S.bidders.length) S.bidders = [newBidder(), newBidder()];
            renderSpecInfo();
            $('workspace').style.display = '';
            bindProject();
            bindTable();
            importFromPq();
            renderBand();
            renderBidders();
        }).catch(function (e) {
            $('specInfo').className = 'err';
            $('specInfo').textContent = '평가 기준을 불러오지 못했습니다: ' + (e && e.message ? e.message : e);
        });
    });
})();
