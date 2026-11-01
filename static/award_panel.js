/* 사업수행능력평가 점수 산정 화면의 6단계: 적격심사 통과 기준 계산 - "얼마에 입찰해야 통과하나?"
 *
 * 용역비(추정가격·예정가격)와 입찰사의 PQ 점수(5단계 결과가 자동으로 들어오고, 직접 입력도 가능)를 알면
 * 입찰가격을 예정가격의 몇 %(몇 원)로 써야 적격심사 종합평점이 적격통과점수 이상인지 거꾸로 계산한다.
 * (지방자치단체 입찰시 낙찰자 결정기준 제2장의2 [별표 1]). 점수는 서버(award_reverse.py·award_engine.py)가 규정 값으로 계산하고
 * 이 파일은 입력을 모아 보내고 결과를 보여 줄 뿐이다.
 * 아래쪽 접힌 "참고" 영역은 반대로 입찰가격이 정해진 뒤 종합평점·낙찰자를 확인하는 계산이다. */
(function () {
    'use strict';

    var SPEC_ID = 'jibang_jeokgyeok_tech';
    var KEY = 'award_panel_v3';
    var spec = null;
    var pqNames = [];              // 5단계 결과에서 온 입찰사 [{key,name,pq,rank}]
    var skipped = [];
    var built = false;
    var S = { project: { est: '', plan: '', localApplied: '1', localKind: 'main', careerExcluded: false }, rows: {}, manual: [], seq: 0 };
    var lastRequired = null;

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
    function fmt(n) {
        if (n === null || n === undefined || n === '') return '';
        return (Math.round(Number(n) * 10000) / 10000).toFixed(4).replace(/0+$/, '').replace(/\.$/, '');
    }
    function won(n) { return Number(n).toLocaleString('ko-KR', { maximumFractionDigits: 0 }); }
    function toNum(v) {
        var x = parseFloat(String(v === undefined || v === null ? '' : v).replace(/,/g, '').trim());
        return isNaN(x) ? null : x;
    }
    // 비율(%) 표시: 하한은 올림, 상한은 내림해서 "통과 구간 안쪽" 값으로 적는다(반올림하면 경계 밖 값이 될 수 있다).
    function pct3(v, up) {
        // 하한(올림)은 86.395처럼 정확히 떨어지는 값이 부동소수 오차로 86.396이 되지 않게 먼저 6자리로 정리한다.
        // 상한(내림)은 89.6049999(=896,049,999원)가 89.605로 반올림돼 경계 밖 값이 되지 않도록 정리하지 않고 그대로 내린다.
        if (up) { var x = Math.round(Number(v) * 1e6) / 1e6; return String(Math.ceil(x * 1000 - 1e-9) / 1000); }
        return String(Math.floor(Number(v) * 1000 + 1e-9) / 1000);
    }

    function blankRow() {
        return { penalty_deduction: '', career_ratio: '', local_ratio: '', local_solo: false, mgmt_mode: 'full', mgmt_tier: 't20', mgmt_score: '',
                 tech_shortage: false, wage_arrears_count: '', bid_price: '' };
    }
    function save() { try { localStorage.setItem(KEY, JSON.stringify(S)); } catch (e) { /* 저장소를 못 쓰면 이번 방문 동안만 유지 */ } }
    function load() {
        try {
            var d = JSON.parse(localStorage.getItem(KEY) || 'null');
            if (d && d.project && d.rows) { S.project = Object.assign(S.project, d.project); S.rows = d.rows; S.manual = d.manual || []; S.seq = d.seq || 0; }
        } catch (e) { /* 무시 */ }
    }
    function bidders() {
        var list = pqNames.slice();
        S.manual.forEach(function (m, i) { list.push({ key: 'm' + m.id, name: m.name || '직접 입력 ' + (i + 1), pq: m.pq, manual: true, id: m.id }); });
        list.forEach(function (b) { if (!S.rows[b.key]) S.rows[b.key] = blankRow(); });
        return list;
    }

    // ------------------------------------------------------------ 5단계 결과 받기
    // PQ 점수를 다시 계산하면 점수가 바뀌므로 이전 결과는 지우고, 입찰사 이름이 같으면 이미 입력한 값은 그대로 둔다.
    function onPqResult(res) {
        pqNames = [];
        skipped = [];
        var seen = {};
        (res.results || []).forEach(function (r) {
            if (r.disqualified || r.rank === null || r.rank === undefined) { skipped.push(r.name); return; }
            var n = r.name || '입찰사';
            seen[n] = (seen[n] || 0) + 1;
            if (seen[n] > 1) n = n + ' (' + seen[n] + ')';
            pqNames.push({ key: n, name: r.name, pq: r.total, rank: r.rank });
        });
        ensureBuilt().then(function () {
            if (!built) return;
            $('awResults').textContent = '';
            $('awFwdResults').textContent = '';
            $('awStatus').textContent = '';
            renderAll();
        });
    }

    // ------------------------------------------------------------ 화면 뼈대 (처음 한 번만)
    var buildPromise = null;
    function ensureBuilt() {
        if (buildPromise) return buildPromise;
        buildPromise = fetch('/api/award/spec/' + SPEC_ID).then(function (r) { return r.json(); }).then(function (d) {
            if (!d.success) throw new Error(d.message);
            spec = d.spec;
            load();
            build();
            renderAll();
        }).catch(function (e) {
            buildPromise = null;
            $('awardBody').textContent = '적격심사 기준을 불러오지 못했습니다: ' + (e && e.message ? e.message : e);
        });
        return buildPromise;
    }

    function field(label, id, help, attrs) {
        return el('div', { class: 'field' }, [el('label', { for: id, text: label }), el('input', Object.assign({ type: 'text', id: id, autocomplete: 'off' }, attrs || {})),
            help ? el('div', { class: 'help', text: help }) : null]);
    }
    function selectField(label, id, opts, help) {
        var sel = el('select', { id: id });
        opts.forEach(function (o) { sel.appendChild(el('option', { value: o[0], text: o[1] })); });
        return el('div', { class: 'field' }, [el('label', { for: id, text: label }), sel, help ? el('div', { class: 'help', text: help }) : null]);
    }

    function build() {
        var body = $('awardBody');
        body.textContent = '';
        var s = spec.source;
        body.appendChild(el('p', { class: 'status', style: 'line-height:1.7;' }, [
            document.createTextNode('용역비와 입찰사의 PQ 점수를 알면, 입찰가격을 '), el('b', { text: '얼마로 써야 적격심사(종합평점이 적격통과점수 이상)를 통과하는지' }),
            document.createTextNode(' 거꾸로 계산합니다. 근거: ' + s.law_name + ' (' + s.issuer + ', ' + s.effective + ' 시행) 제2장의2 [별표 1] 사업수행능력평가(P.Q)를 하는 기술용역.')]));

        body.appendChild(el('div', { class: 'grid', style: 'margin-top:1rem;' }, [
            field('용역비 - 추정가격 (원)', 'awEst', '부가가치세를 제외한 추정가격입니다. 10억원·5억원을 기준으로 배점과 적격통과점수(92점/95점)가 달라집니다.', { inputmode: 'numeric', placeholder: '예: 1,200,000,000' }),
            field('예정가격 (원, 모르면 비워 두세요)', 'awPlan', '비우면 입찰가격을 예정가격 대비 비율(%)로만 알려 드립니다. 입력하면 원 단위 금액도 계산합니다.', { inputmode: 'numeric', placeholder: '예: 1,150,000,000' }),
            selectField('지역업체 참여도 평가', 'awLocalApplied', [['1', '적용 (기본)'], ['0', '적용하지 않음']], '적용하지 않으면 그 배점(3점)이 PQ 환산 배점에 합산됩니다. 입찰공고에 명시된 대로 선택하세요.'),
            selectField('지역업체 참여도 구분', 'awLocalKind', [['main', '엔지니어링·건설기술 용역 (30% 이상 3점 / 20% 이상 1점)'], ['other', '다른 법령에 따른 기술용역 (20% 이상 3점 / 10% 이상 1점)']], ''),
            el('div', { class: 'field' }, [el('label', { class: 'check', style: 'margin-top:1.4rem;' }, [
                el('input', { type: 'checkbox', id: 'awCareerExcluded' }),
                el('span', { text: '책임기술자 경력 평가를 입찰공고에서 제외함 (제외하면 배점한도 1점)' })])])
        ]));
        body.appendChild(el('div', { id: 'awBand', class: 'band-box', style: 'display:none;' }));

        body.appendChild(el('h3', { style: 'margin:1.4rem 0 0.4rem; font-size:1rem; color:var(--primary-dark);', text: '입찰사와 PQ 점수' }));
        body.appendChild(el('div', { id: 'awSkipped', class: 'status' }));
        body.appendChild(el('div', { class: 'tbl-wrap' }, [el('table', { id: 'awTable', class: 'bt' })]));
        body.appendChild(el('div', { class: 'no-print', style: 'margin-top:0.6rem;' }, [
            el('button', { type: 'button', class: 'btn btn-ghost btn-sm', id: 'awAddManual', text: '+ PQ 점수 직접 입력해서 추가' }),
            el('span', { class: 'status', style: 'margin-left:0.6rem;', text: '5단계를 계산하지 않았거나 다른 곳에서 받은 PQ 점수를 쓰고 싶을 때' })]));

        var det = el('details', { class: 'sub', style: 'margin-top:1rem;' });
        det.appendChild(el('summary', { text: '입찰사별 세부 조건 (선택) — 비워 두면 경력·지역업체·경영상태는 만점, 감점은 없다고 가정합니다' }));
        det.appendChild(el('div', { class: 'tbl-wrap', style: 'margin-top:0.6rem;' }, [el('table', { id: 'awDetail', class: 'bt' })]));
        det.appendChild(el('p', { class: 'status', style: 'margin-top:0.6rem; line-height:1.6;' }, [
            document.createTextNode('• 벌점 감점: PQ 평가에서 사업자·참여기술인 벌점으로 깎인 점수가 있으면 적어 주세요(규정상 이 감점은 환산하지 않고 그대로 뺍니다).'), el('br'),
            document.createTextNode('• 경영상태: PQ 점수에 경영상태(신용평가)가 이미 반영된 경우는 만점으로 둡니다.')]));
        body.appendChild(det);

        body.appendChild(el('div', { class: 'no-print', style: 'margin:1.2rem 0;' }, [
            el('button', { type: 'button', class: 'btn btn-primary', id: 'awCalc', text: '통과 기준 계산하기' }),
            el('span', { id: 'awStatus', class: 'status', style: 'margin-left:0.8rem;' })]));
        body.appendChild(el('div', { id: 'awResults' }));

        var fwd = el('details', { class: 'sub', style: 'margin-top:1.4rem;' });
        fwd.appendChild(el('summary', { text: '(참고) 입찰가격이 정해진 뒤 — 입찰사별 종합평점과 낙찰자 확인' }));
        fwd.appendChild(el('p', { class: 'status', style: 'margin:0.6rem 0; line-height:1.6;', text: '입찰사별 입찰가격을 입력하면 종합평점을 계산하고, 예정가격 이하 최저가 입찰자부터 심사해 낙찰자를 정합니다. (위 세부 조건의 경력·지역업체 비율도 입력해야 합니다.)' }));
        fwd.appendChild(el('div', { class: 'tbl-wrap' }, [el('table', { id: 'awFwdTable', class: 'bt' })]));
        fwd.appendChild(el('div', { class: 'no-print', style: 'margin:0.8rem 0;' }, [
            el('button', { type: 'button', class: 'btn btn-ghost', id: 'awFwdCalc', text: '종합평점·낙찰자 계산하기' }),
            el('span', { id: 'awFwdStatus', class: 'status', style: 'margin-left:0.8rem;' })]));
        fwd.appendChild(el('div', { id: 'awFwdResults' }));
        body.appendChild(fwd);

        $('awEst').value = S.project.est; $('awPlan').value = S.project.plan;
        $('awLocalApplied').value = S.project.localApplied; $('awLocalKind').value = S.project.localKind;
        $('awCareerExcluded').checked = !!S.project.careerExcluded;
        bind();
        built = true;
    }

    // ------------------------------------------------------------ 적용 구간 안내
    function pickBand(est) {
        var bands = spec.bands.slice().sort(function (a, b) { return b.min_estimated_price - a.min_estimated_price; });
        for (var i = 0; i < bands.length; i++) if (est >= bands[i].min_estimated_price) return bands[i];
        return bands[bands.length - 1];
    }
    function renderBand() {
        var box = $('awBand');
        if (!box) return;
        var est = toNum(S.project.est);
        if (est === null || est <= 0) { box.style.display = 'none'; return; }
        var band = pickBand(est), w = band.weights, off = S.project.localApplied === '0';
        box.style.display = '';
        box.textContent = '';
        box.appendChild(el('div', {}, [el('b', { text: band.label }), document.createTextNode(' 구간 → 종합평점 '), el('b', { text: band.pass_score + '점 이상' }),
            document.createTextNode('이어야 통과 (' + band.ref + ')')]));
        var chips = [['PQ 환산', w.pq + (off ? w.local : 0)], ['책임기술자 경력', w.career], ['지역업체 참여도', off ? 0 : w.local], ['경영상태', w.mgmt], ['입찰가격', w.price]];
        var wrap = el('div', { class: 'weights' });
        chips.forEach(function (c) { wrap.appendChild(el('span', { text: c[0] + ' ' + c[1] + '점' })); });
        wrap.appendChild(el('span', { text: '합계 100점' }));
        box.appendChild(wrap);
        box.appendChild(el('div', { class: 'status', style: 'margin-top:0.4rem;', text: '입찰가격 평점: ' + band.price.ref }));
    }

    // ------------------------------------------------------------ 입찰사 표
    function inp(key, f, extra) {
        return el('input', Object.assign({ type: 'text', 'data-k': key, 'data-f': f, value: S.rows[key][f], inputmode: 'decimal', autocomplete: 'off' }, extra || {}));
    }
    function renderAll() { renderBand(); renderMain(); renderDetail(); renderFwd(); }

    function renderMain() {
        var t = $('awTable');
        t.textContent = '';
        var list = bidders();
        $('awSkipped').textContent = skipped.length ? 'PQ 평가에서 실격한 입찰사(' + skipped.join(', ') + ')는 적격심사 대상이 아니라 제외했습니다.' : '';
        t.appendChild(el('thead', {}, [el('tr', {}, ['입찰사', 'PQ 점수', ''].map(function (c) { return el('th', { text: c }); }))]));
        var tb = el('tbody');
        if (!list.length) {
            tb.appendChild(el('tr', {}, [el('td', { colspan: '3', class: 'muted', text: '5단계에서 "점수 계산하기"를 누르면 입찰사와 PQ 점수가 자동으로 들어옵니다. 또는 아래 "PQ 점수 직접 입력해서 추가"를 누르세요.' })]));
        }
        list.forEach(function (b) {
            if (b.manual) {
                var m = S.manual.filter(function (x) { return x.id === b.id; })[0];
                tb.appendChild(el('tr', {}, [
                    el('td', {}, [el('input', { type: 'text', 'data-m': b.id, 'data-mf': 'name', value: m.name, placeholder: '입찰사 이름' })]),
                    el('td', {}, [el('input', { type: 'text', 'data-m': b.id, 'data-mf': 'pq', value: m.pq, inputmode: 'decimal', placeholder: '예: 93.25' })]),
                    el('td', { class: 'c' }, [el('button', { type: 'button', class: 'btn btn-ghost btn-sm', 'data-delm': b.id, text: '삭제' })])]));
            } else {
                tb.appendChild(el('tr', {}, [
                    el('td', {}, [el('b', { text: b.name }), el('span', { class: 'muted', style: 'font-size:0.78rem; margin-left:0.4rem;', text: 'PQ ' + b.rank + '위' })]),
                    el('td', { class: 'num' }, [el('b', { text: fmt(b.pq) })]), el('td')]));
            }
        });
        t.appendChild(tb);
    }

    function renderDetail() {
        var t = $('awDetail');
        t.textContent = '';
        var list = bidders();
        var cols = ['입찰사', '벌점 감점', '책임기술자 경력 비율 (%)', '지역업체 참여비율 (%)', '경영상태', '기술인력 미달', '임금체불 공개 (회)'];
        t.appendChild(el('thead', {}, [el('tr', {}, cols.map(function (c) { return el('th', { text: c }); }))]));
        var off = S.project.localApplied === '0', careerOff = !!S.project.careerExcluded;
        var tb = el('tbody');
        list.forEach(function (b) {
            var r = S.rows[b.key];
            var mg = el('td');
            var sel = el('select', { 'data-k': b.key, 'data-f': 'mgmt_mode' });
            [['full', '만점 (PQ에 반영됨)'], ['credit', '신용평가 구간 선택'], ['score', '점수 직접 입력']].forEach(function (o) {
                sel.appendChild(el('option', { value: o[0], text: o[1], selected: r.mgmt_mode === o[0] }));
            });
            mg.appendChild(sel);
            if (r.mgmt_mode === 'credit') {
                var tier = el('select', { 'data-k': b.key, 'data-f': 'mgmt_tier', class: 'sub-input' });
                spec.mgmt.credit_tiers.forEach(function (c) { tier.appendChild(el('option', { value: c.id, text: c.score.toFixed(1) + '점 · ' + c.label, selected: r.mgmt_tier === c.id })); });
                mg.appendChild(tier);
            } else if (r.mgmt_mode === 'score') {
                mg.appendChild(inp(b.key, 'mgmt_score', { class: 'sub-input', placeholder: '0 ~ ' + spec.mgmt.max }));
            }
            var local = el('td', {}, [inp(b.key, 'local_ratio', off || r.local_solo ? { disabled: true, placeholder: '' } : { placeholder: '비우면 만점' })]);
            if (!off) {
                local.appendChild(el('label', { class: 'check', style: 'margin-top:0.3rem; font-size:0.75rem;' }, [
                    el('input', { type: 'checkbox', 'data-k': b.key, 'data-f': 'local_solo', checked: r.local_solo }), el('span', { text: '지역업체 단독 참여 (0점)' })]));
            }
            tb.appendChild(el('tr', {}, [
                el('td', { text: b.name }),
                el('td', {}, [inp(b.key, 'penalty_deduction', { placeholder: '0' })]),
                el('td', {}, [inp(b.key, 'career_ratio', careerOff ? { disabled: true } : { placeholder: '비우면 만점' })]),
                local, mg,
                el('td', { class: 'c' }, [el('input', { type: 'checkbox', 'data-k': b.key, 'data-f': 'tech_shortage', checked: r.tech_shortage })]),
                el('td', {}, [inp(b.key, 'wage_arrears_count', { placeholder: '0' })])
            ]));
        });
        t.appendChild(tb);
    }

    function renderFwd() {
        var t = $('awFwdTable');
        t.textContent = '';
        var list = bidders();
        t.appendChild(el('thead', {}, [el('tr', {}, ['입찰사', 'PQ 점수', '입찰가격 (원)'].map(function (c) { return el('th', { text: c }); }))]));
        var tb = el('tbody');
        list.forEach(function (b) {
            tb.appendChild(el('tr', {}, [el('td', { text: b.name }), el('td', { class: 'num', text: fmt(toNum(b.pq)) }),
                el('td', {}, [inp(b.key, 'bid_price', { class: 'w-price' })])]));
        });
        t.appendChild(tb);
    }

    // ------------------------------------------------------------ 요청 만들기
    function payload() {
        var p = S.project;
        return {
            spec_id: SPEC_ID,
            project: { estimated_price: p.est, planned_price: p.plan, local_applied: p.localApplied !== '0', local_kind: p.localKind, career_excluded: !!p.careerExcluded },
            bidders: bidders().map(function (n) {
                var r = S.rows[n.key];
                return { name: n.name, pq_score: n.pq, penalty_deduction: r.penalty_deduction, bid_price: r.bid_price, career_ratio: r.career_ratio, local_ratio: r.local_ratio,
                         local_solo: !!r.local_solo, mgmt_mode: r.mgmt_mode, mgmt_tier: r.mgmt_tier, mgmt_score: r.mgmt_score, tech_shortage: !!r.tech_shortage,
                         wage_arrears_count: r.wage_arrears_count };
            })
        };
    }
    function post(url, btn, st, done) {
        if (!bidders().length) { st.className = 'status err'; st.textContent = '입찰사가 없습니다. 5단계에서 PQ 점수를 계산하거나 "PQ 점수 직접 입력해서 추가"를 눌러 주세요.'; return; }
        st.className = 'status'; st.textContent = '계산 중...'; btn.disabled = true;
        fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload()) })
            .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
            .then(function (x) {
                if (!x.ok || !x.d.success) { st.className = 'status err'; st.textContent = x.d.message || '계산하지 못했습니다.'; return; }
                st.textContent = '';
                done(x.d.result);
            })
            .catch(function () { st.className = 'status err'; st.textContent = '서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.'; })
            .then(function () { btn.disabled = false; });
    }

    // ------------------------------------------------------------ 결과: 얼마에 입찰해야 통과하나
    function rangeText(r, res) {
        var hasWon = r.min_price !== null && r.min_price !== undefined || (r.max_price !== null && r.max_price !== undefined);
        var lo = r.min_ratio_pct === null ? null : pct3(r.min_ratio_pct, true);
        var hi = pct3(r.max_ratio_pct, false);
        var pctPart = (lo === null ? '예정가격의 ' + '(하한 없음) ~ ' + hi + '%' : '예정가격의 ' + lo + '% ~ ' + hi + '%');
        var wonPart = '';
        if (hasWon) wonPart = (r.min_price === null || r.min_price === undefined ? '' : won(r.min_price) + '원') + ' ~ ' + won(r.max_price) + '원';
        return { pct: pctPart, won: wonPart };
    }
    function renderRequired(res) {
        lastRequired = res;
        var box = $('awResults');
        box.textContent = '';
        var pass = res.band.pass_score;
        box.appendChild(el('div', { class: 'band-box', style: 'display:block; margin:0 0 1rem;' }, [
            el('b', { text: res.band.label + ' → 종합평점 ' + fmt(pass) + '점 이상이면 적격심사 통과' }),
            el('div', { class: 'status', text: '종합평점 = PQ 환산 ' + fmt(res.weights.pq) + ' + 책임기술자 경력 ' + fmt(res.weights.career) + ' + 지역업체 ' + fmt(res.weights.local) +
                ' + 경영상태 ' + fmt(res.weights.mgmt) + ' + 입찰가격 ' + fmt(res.weights.price) + ' (합계 100점) - 감점' })]));

        // 요약표
        var t = el('table');
        t.appendChild(el('thead', {}, [el('tr', {}, ['입찰사', 'PQ 점수', '통과 가능?', '통과하려면 입찰가격을', '금액'].map(function (h) { return el('th', { text: h }); }))]));
        var tb = el('tbody');
        res.results.forEach(function (r) {
            if (r.possible) {
                var rt = rangeText(r, res);
                tb.appendChild(el('tr', {}, [el('td', { text: r.name }), el('td', { class: 'num', text: fmt(r.pq_score) }),
                    el('td', {}, [el('span', { class: 'tag pass', text: '가능' })]), el('td', { text: rt.pct + ' 로 입찰' }), el('td', { text: rt.won || (res.planned_price ? '' : '예정가격을 입력하면 금액이 나옵니다') })]));
            } else {
                tb.appendChild(el('tr', {}, [el('td', { text: r.name }), el('td', { class: 'num', text: fmt(r.pq_score) }),
                    el('td', {}, [el('span', { class: 'tag fail', text: '불가' })]),
                    el('td', { colspan: '2', text: r.pq_needed === null ? 'PQ 점수가 100점이어도 통과할 수 없습니다(감점이 큽니다)' : '어떤 입찰가격으로도 통과 불가 — PQ 점수가 최소 ' + fmt(r.pq_needed) + '점은 되어야 합니다' })]));
            }
        });
        t.appendChild(tb);
        box.appendChild(el('div', { class: 'tbl-wrap' }, [t]));
        box.appendChild(el('div', { class: 'no-print', style: 'margin:0.8rem 0;' }, [
            el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: '결과 CSV로 저장', onclick: function () { downloadRequiredCsv(res); } }),
            el('button', { type: 'button', class: 'btn btn-ghost btn-sm', style: 'margin-left:0.5rem;', text: '인쇄 / PDF 저장', onclick: function () { window.print(); } })]));

        // 입찰사별 상세
        res.results.forEach(function (r) {
            var det = el('details', { class: 'sub', open: res.results.length === 1 ? true : null });
            var rt = r.possible ? rangeText(r, res) : null;
            det.appendChild(el('summary', { text: r.name + ' · PQ ' + fmt(r.pq_score) + '점 · ' + (r.possible ? rt.pct + ' 로 입찰하면 통과' : '어떤 가격으로도 통과 불가') }));
            var ul = el('ul', { class: 'basis', style: 'margin:0.6rem 0 0 1.1rem; line-height:1.8;' });
            var p = r.parts;
            ul.appendChild(el('li', { text: '입찰가격을 뺀 점수: PQ 환산 ' + fmt(p.pq) + ' + 경력 ' + fmt(p.career) + ' + 지역업체 ' + fmt(p.local) + ' + 경영상태 ' + fmt(p.mgmt) +
                (p.deduction ? ' - 감점 ' + fmt(-p.deduction) : '') + ' = ' + fmt(r.subtotal) + '점' }));
            ul.appendChild(el('li', { text: '통과하려면 입찰가격 평점이 ' + fmt(r.need_price_score) + '점 이상이어야 합니다 (' + fmt(pass) + ' - ' + fmt(r.subtotal) + ', 입찰가격 만점 ' + fmt(r.price_score_max) + '점).' }));
            if (r.possible) {
                ul.appendChild(el('li', { text: '입찰가격 평점 공식으로 풀면, 예정가격 대비 ' + (r.min_ratio_pct === null ? '아무리 낮아도' : pct3(r.min_ratio_pct, true) + '% 이상') + ', ' + pct3(r.max_ratio_pct, false) + '% 이하일 때 통과합니다.' }));
                var upperTxt = r.max_ratio_pct >= 100 ? '예정가격(100%)까지는 모두 통과하며, 예정가격을 넘으면 심사 대상에서 제외됩니다.' : '이보다 높게 쓰면 종합평점이 ' + fmt(pass) + '점에 못 미칩니다.';
                ul.appendChild(el('li', { text: '이보다 낮게 쓰면 가격 평점이 모자라 탈락합니다. ' + upperTxt + ' 최저가부터 심사하므로 통과 구간의 아래쪽 끝(' +
                    (r.min_ratio_pct === null ? '하한 없음' : pct3(r.min_ratio_pct, true) + '%') + ')이 가장 낙찰 가능성이 높은 가격입니다.' }));
            } else {
                ul.appendChild(el('li', { text: '가격을 가장 유리하게(예정가격의 88%) 써도 종합평점이 ' + fmt(pass) + '점에 못 미칩니다.' + (r.pq_needed !== null ? ' 같은 조건에서 통과하려면 PQ 점수가 최소 ' + fmt(r.pq_needed) + '점 필요합니다.' : '') }));
            }
            det.appendChild(ul);
            if (r.assumptions && r.assumptions.length) {
                var as = el('ul', { class: 'warn-list', style: 'margin:0.6rem 0 0; padding-left:1.4rem;' });
                r.assumptions.forEach(function (a) { as.appendChild(el('li', { text: '가정: ' + a })); });
                det.appendChild(as);
            }
            if (r.possible && r.ladder) {
                var lt = el('table', { style: 'margin-top:0.8rem;' });
                lt.appendChild(el('thead', {}, [el('tr', {}, ['예정가격 대비 입찰가격', '입찰가격 평점', '종합평점', '적격심사'].map(function (h, i) { return el('th', { class: i ? 'num' : null, text: h }); }))]));
                var lb = el('tbody');
                r.ladder.slice().reverse().forEach(function (x) {
                    lb.appendChild(el('tr', { class: x.pass ? 'rank1' : null }, [el('td', { text: x.ratio_pct + '%' + (res.planned_price ? ' (' + won(res.planned_price * x.ratio_pct / 100) + '원)' : '') }),
                        el('td', { class: 'num', text: fmt(x.price_score) }), el('td', { class: 'num', text: fmt(x.total) }), el('td', { class: 'num', text: x.pass ? '통과' : '미달' })]));
                });
                lt.appendChild(lb);
                var ld = el('details', { style: 'margin-top:0.6rem;' });
                ld.appendChild(el('summary', { style: 'cursor:pointer; font-weight:600;', text: '입찰가격별 종합평점 표 보기 (70% ~ 100%, 1% 단위)' }));
                ld.appendChild(el('div', { class: 'tbl-wrap' }, [lt]));
                det.appendChild(ld);
            }
            box.appendChild(det);
        });
        if (res.notes.length) {
            var nu = el('ul', { class: 'status', style: 'margin:1rem 0 0 1.2rem; line-height:1.7;' });
            res.notes.forEach(function (n) { nu.appendChild(el('li', { text: n })); });
            box.appendChild(nu);
        }
        var src = res.source || {};
        box.appendChild(el('p', { class: 'status', style: 'margin-top:1rem; line-height:1.7;', text:
            '적용 규정: ' + src.law_name + ' (' + src.issuer + ', 시행 ' + src.effective + ') - ' + res.band.ref + '. 적격통과점수 근거: ' + res.band.pass_ref +
            '. 본 결과는 입력값을 규정 산식에 적용한 계산 결과이며, 입력값의 진위는 공식 자료로 확인해야 합니다. 적격심사 통과가 낙찰을 보장하지는 않습니다.' }));
        box.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    // ------------------------------------------------------------ (참고) 입찰가격이 정해진 뒤 종합평점·낙찰자
    var STATUS = { winner: ['winner', '🏆 낙찰자'], lottery: ['lottery', '🎲 추첨 대상'], pass: ['pass', '통과 (동가 중 PQ 점수 낮음)'], fail: ['fail', '미달'],
                   after: ['after', '심사 생략'], over: ['over', '예정가격 초과 (제외)'] };
    function statusTag(r) {
        var s = STATUS[r.status] || ['after', r.status];
        return el('span', { class: 'tag ' + s[0], text: r.status === 'fail' ? '미달 (' + fmt(r.shortfall) + '점 부족)' : s[1] });
    }
    function renderForward(res) {
        var box = $('awFwdResults');
        box.textContent = '';
        var rs = res.results;
        var win = res.winner_index !== null ? rs[res.winner_index] : null;
        var wb = el('div', { class: win ? 'winner-box' : (res.lottery_indexes.length ? 'winner-box lottery' : 'winner-box none') });
        if (win) wb.appendChild(el('div', {}, [el('b', { text: '🏆 낙찰자: ' + win.name }), document.createTextNode(' — 종합평점 ' + fmt(win.total) + '점 (적격통과점수 ' + fmt(res.band.pass_score) + '점 이상)')]));
        else if (res.lottery_indexes.length) wb.appendChild(el('b', { text: '🎲 추첨으로 낙찰자를 정해야 합니다: ' + res.lottery_indexes.map(function (i) { return rs[i].name; }).join(', ') }));
        else wb.appendChild(el('b', { text: '낙찰자가 없습니다 (적격통과점수 ' + fmt(res.band.pass_score) + '점 이상인 입찰사 없음)' }));
        box.appendChild(wb);
        var order = rs.map(function (r, i) { return i; }).sort(function (a, b) {
            var ra = rs[a].review_order === null ? 1e9 : rs[a].review_order, rb = rs[b].review_order === null ? 1e9 : rs[b].review_order;
            return ra - rb || a - b;
        });
        var t = el('table');
        t.appendChild(el('thead', {}, [el('tr', {}, ['심사 순서', '입찰사', '입찰가격 (예정가격 대비)', 'PQ 환산', '경력', '지역업체', '경영상태', '입찰가격', '감점', '종합평점', '판정'].map(function (h, i) {
            return el('th', { class: i >= 3 && i <= 9 ? 'num' : null, text: h }); }))]));
        var tb = el('tbody');
        order.forEach(function (i) {
            var r = rs[i], sc = r.scores;
            tb.appendChild(el('tr', { class: 's-' + r.status }, [
                el('td', { text: r.review_order === null ? '-' : String(r.review_order) }), el('td', { text: r.name }),
                el('td', { text: won(r.bid_price) + '원 (' + fmt(r.price_ratio * 100) + '%)' }),
                el('td', { class: 'num', text: fmt(sc.pq) }), el('td', { class: 'num', text: fmt(sc.career) }), el('td', { class: 'num', text: fmt(sc.local) }),
                el('td', { class: 'num', text: fmt(sc.mgmt) }), el('td', { class: 'num', text: fmt(sc.price) }), el('td', { class: 'num', text: fmt(sc.deduction) }),
                el('td', { class: 'num total' }, [el('b', { text: fmt(r.total) })]), el('td', {}, [statusTag(r)])]));
        });
        t.appendChild(tb);
        box.appendChild(el('div', { class: 'tbl-wrap' }, [t]));
        order.forEach(function (i) {
            var r = rs[i];
            var det = el('details', { class: 'sub' });
            det.appendChild(el('summary', { text: r.name + ' · 종합평점 ' + fmt(r.total) + '점 (계산 근거 보기)' }));
            var ul = el('ul', { class: 'basis', style: 'margin:0.5rem 0 0 1.1rem;' });
            r.basis.forEach(function (b) { ul.appendChild(el('li', { text: b })); });
            det.appendChild(ul);
            box.appendChild(det);
        });
    }

    // ------------------------------------------------------------ CSV
    function csvCell(v) {
        var s = String(v === undefined || v === null ? '' : v);
        return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
    }
    function downloadRequiredCsv(res) {
        var rows = [['입찰사', 'PQ 점수', '적격심사 통과 가능', '통과 하한(예정가격 대비 %)', '통과 상한(예정가격 대비 %)', '하한 금액(원)', '상한 금액(원)', '통과에 필요한 최소 PQ 점수',
                     '입찰가격을 뺀 점수', '필요한 입찰가격 평점', '적격통과점수', '가정 사항']];
        res.results.forEach(function (r) {
            rows.push([r.name, r.pq_score, r.possible ? '가능' : '불가', r.possible && r.min_ratio_pct !== null ? pct3(r.min_ratio_pct, true) : '', r.possible ? pct3(r.max_ratio_pct, false) : '',
                       r.min_price === null || r.min_price === undefined ? '' : r.min_price, r.max_price === null || r.max_price === undefined ? '' : r.max_price,
                       r.possible ? '' : (r.pq_needed === null ? '100점 초과' : r.pq_needed), r.subtotal, r.need_price_score, res.band.pass_score, (r.assumptions || []).join(' / ')]);
        });
        var csv = '﻿' + rows.map(function (r) { return r.map(csvCell).join(','); }).join('\r\n');   // 앞의 BOM은 엑셀이 한글을 깨지 않고 열게 한다
        var a = document.createElement('a');
        a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
        a.download = '적격심사_통과기준.csv';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    }

    // ------------------------------------------------------------ 이벤트 (이 카드 안에서만)
    function bind() {
        var map = { awEst: 'est', awPlan: 'plan' };
        Object.keys(map).forEach(function (id) {
            $(id).addEventListener('input', function () { S.project[map[id]] = this.value; renderBand(); save(); });
        });
        $('awLocalApplied').addEventListener('change', function () { S.project.localApplied = this.value; renderBand(); renderDetail(); save(); });
        $('awLocalKind').addEventListener('change', function () { S.project.localKind = this.value; save(); });
        $('awCareerExcluded').addEventListener('change', function () { S.project.careerExcluded = this.checked; renderDetail(); save(); });

        function onRow(e) {
            var t = e.target;
            if (!t.getAttribute) return;
            var mid = t.getAttribute('data-m');
            if (mid !== null) {                                   // 직접 입력한 입찰사의 이름·PQ 점수
                var m = S.manual.filter(function (x) { return String(x.id) === mid; })[0];
                if (m) { m[t.getAttribute('data-mf')] = t.value; save(); if (e.type === 'change') { renderDetail(); renderFwd(); } }
                return;
            }
            var f = t.getAttribute('data-f');
            if (!f) return;
            var k = t.getAttribute('data-k');
            var r = S.rows[k];
            if (!r) return;
            r[f] = t.type === 'checkbox' ? t.checked : t.value;
            if (e.type === 'change' && (f === 'mgmt_mode' || f === 'local_solo')) renderDetail();   // 입력칸 구성이 바뀌는 항목만 다시 그린다
            save();
        }
        ['awTable', 'awDetail', 'awFwdTable'].forEach(function (id) { $(id).addEventListener('input', onRow); $(id).addEventListener('change', onRow); });
        $('awTable').addEventListener('click', function (e) {
            var d = e.target.getAttribute && e.target.getAttribute('data-delm');
            if (d === null || d === undefined) return;
            S.manual = S.manual.filter(function (x) { return String(x.id) !== d; });
            save(); renderAll();
        });
        $('awAddManual').addEventListener('click', function () {
            S.seq += 1;
            S.manual.push({ id: S.seq, name: '', pq: '' });
            save(); renderAll();
        });
        $('awCalc').addEventListener('click', function () { post('/api/award/required_price', $('awCalc'), $('awStatus'), renderRequired); });
        $('awFwdCalc').addEventListener('click', function () { post('/api/award/evaluate', $('awFwdCalc'), $('awFwdStatus'), renderForward); });
    }

    document.addEventListener('DOMContentLoaded', function () {
        $('awardToggle').addEventListener('click', function () {
            var b = $('awardBody');
            var open = b.style.display === 'none';
            b.style.display = open ? '' : 'none';
            this.textContent = open ? '접기' : '펼치기';
        });
        ensureBuilt();      // 5단계를 계산하기 전에도 화면이 보이게(PQ 점수를 직접 입력해 쓸 수 있다)
    });

    window.AwardPanel = { onPqResult: onPqResult };
})();
