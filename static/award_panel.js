/* 사업수행능력평가 점수 산정 화면의 6단계: 적격심사 종합평점·낙찰자 결정 (지방자치단체 입찰시 낙찰자 결정기준).
 *
 * 5단계에서 계산한 입찰사별 PQ 점수를 그대로 받아(pq_score.js가 AwardPanel.onPqResult를 부른다) 입찰가격 등을 더해 종합평점을 계산하고,
 * 예정가격 이하 최저가 입찰자부터 순서대로 심사해 낙찰자를 정한다. 점수는 서버의 award_engine.py가 규정 값(award_specs/*.json)대로
 * 계산하고, 이 파일은 입력을 모아 보내고 결과를 보여 줄 뿐이다. */
(function () {
    'use strict';

    var SPEC_ID = 'jibang_jeokgyeok_tech';
    var KEY = 'award_panel_v2';
    var spec = null;
    var pq = null;                 // 5단계 결과(res): {results:[{name,total,rank,disqualified,...}], ...}
    var S = { project: { est: '', plan: '', localApplied: '1', localKind: 'main', careerExcluded: false }, rows: {} };   // rows: 입찰사 이름 -> 입력값
    var names = [];                // 지금 표에 나오는 입찰사(이름, 중복이면 번호가 붙음)와 PQ 점수
    var built = false;

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
    function won(n) { return Number(n).toLocaleString('ko-KR', { maximumFractionDigits: 2 }); }
    function toNum(v) {
        var x = parseFloat(String(v === undefined || v === null ? '' : v).replace(/,/g, '').trim());
        return isNaN(x) ? null : x;
    }

    function blankRow() {
        return { penalty_deduction: '', bid_price: '', career_ratio: '', local_ratio: '', local_solo: false, mgmt_mode: 'full', mgmt_tier: 't20',
                 mgmt_score: '', tech_shortage: false, wage_arrears_count: '' };
    }
    function save() { try { localStorage.setItem(KEY, JSON.stringify(S)); } catch (e) { /* 저장소를 못 쓰면 이번 방문 동안만 유지 */ } }
    function load() {
        try {
            var d = JSON.parse(localStorage.getItem(KEY) || 'null');
            if (d && d.project && d.rows) { S.project = Object.assign(S.project, d.project); S.rows = d.rows; }
        } catch (e) { /* 무시 */ }
    }

    // ------------------------------------------------------------ 5단계 결과 받기
    // PQ 점수를 다시 계산하면 점수가 바뀌므로 이전 종합평점 결과는 지우고, 입찰사 이름이 같으면 이미 입력한 값은 그대로 둔다.
    function onPqResult(res) {
        pq = res;
        names = [];
        var seen = {};
        var skipped = [];
        (res.results || []).forEach(function (r) {
            if (r.disqualified || r.rank === null || r.rank === undefined) { skipped.push(r.name); return; }
            var n = r.name || '입찰사';
            seen[n] = (seen[n] || 0) + 1;
            if (seen[n] > 1) n = n + ' (' + seen[n] + ')';
            names.push({ key: n, name: r.name, pq: r.total, rank: r.rank });
            if (!S.rows[n]) S.rows[n] = blankRow();
        });
        $('awardCard').style.display = '';
        ensureBuilt().then(function () {
            if (!built) return;
            $('awResults').textContent = '';
            $('awStatus').textContent = '';
            $('awSkipped').textContent = skipped.length ? 'PQ 평가에서 실격한 입찰사(' + skipped.join(', ') + ')는 적격심사 대상이 아니라 제외했습니다.' : '';
            renderBidders();
            renderBand();
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
        }).catch(function (e) {
            buildPromise = null;
            $('awardBody').textContent = '적격심사 기준을 불러오지 못했습니다: ' + (e && e.message ? e.message : e);
        });
        return buildPromise;
    }

    function build() {
        var body = $('awardBody');
        body.textContent = '';
        var s = spec.source;
        var notice = el('ul');
        spec.notice.forEach(function (n) { notice.appendChild(el('li', { text: n })); });
        body.appendChild(el('div', {}, [
            el('div', { class: 'status', style: 'line-height:1.6;', text: s.law_name + ' (' + s.issuer + ', ' + s.effective + ' 시행) · ' + s.where }),
            el('div', { class: 'notice' }, [notice])
        ]));

        body.appendChild(el('div', { class: 'grid', style: 'margin-top:1rem;' }, [
            field('추정가격 (원)', 'awEst', 'text', '부가가치세를 제외한 추정가격입니다. 10억원·5억원을 기준으로 배점과 적격통과점수가 달라집니다.', { inputmode: 'numeric', placeholder: '예: 1,200,000,000' }),
            field('예정가격 (원)', 'awPlan', 'text', '입찰가격은 예정가격 이하여야 하며, 입찰가격 평점은 입찰가격 ÷ 예정가격으로 계산합니다.', { inputmode: 'numeric', placeholder: '예: 1,150,000,000' }),
            selectField('지역업체 참여도 평가', 'awLocalApplied', [['1', '적용 (기본)'], ['0', '적용하지 않음']], '적용하지 않으면 그 배점(3점)이 PQ 환산 배점에 합산됩니다. 이 내용은 입찰공고에 명시해야 합니다.'),
            selectField('지역업체 참여도 구분', 'awLocalKind', [['main', '엔지니어링·건설기술 용역 (30% 이상 3점 / 20% 이상 1점)'], ['other', '다른 법령에 따른 기술용역 (20% 이상 3점 / 10% 이상 1점)']], ''),
            el('div', { class: 'field' }, [el('label', { class: 'check', style: 'margin-top:1.4rem;' }, [
                el('input', { type: 'checkbox', id: 'awCareerExcluded' }),
                el('span', { text: '책임기술자 경력 평가를 입찰공고에서 제외함 (제외하면 모든 입찰사에게 배점한도 1점)' })])])
        ]));
        body.appendChild(el('div', { id: 'awBand', class: 'band-box', style: 'display:none;' }));

        body.appendChild(el('div', { id: 'awSkipped', class: 'status', style: 'margin-top:0.8rem;' }));
        body.appendChild(el('div', { class: 'tbl-wrap', style: 'margin-top:0.8rem;' }, [el('table', { id: 'awTable', class: 'bt' })]));
        body.appendChild(el('p', { class: 'status', style: 'margin-top:0.7rem; line-height:1.6;' }, [
            document.createTextNode('• 입찰사 이름과 PQ 점수는 5단계 계산 결과가 자동으로 들어옵니다. 5단계를 다시 계산하면 PQ 점수가 새로 반영됩니다.'), el('br'),
            document.createTextNode('• 벌점 감점: PQ 평가에서 사업자·참여기술인 벌점으로 깎인 점수가 있으면 그 점수를 적어 주세요(규정상 이 감점은 환산하지 않고 그대로 뺍니다).'), el('br'),
            document.createTextNode('• 경영상태: PQ 점수에 경영상태(신용평가)가 이미 반영된 경우는 만점으로 둡니다. 그렇지 않으면 신용평가 구간을 고르거나 점수를 직접 입력하세요.')
        ]));
        body.appendChild(el('div', { class: 'no-print', style: 'margin:1rem 0;' }, [
            el('button', { type: 'button', class: 'btn btn-primary', id: 'awCalc', text: '종합평점·낙찰자 계산하기' }),
            el('span', { id: 'awStatus', class: 'status', style: 'margin-left:0.8rem;' })]));
        body.appendChild(el('div', { id: 'awResults' }));

        $('awEst').value = S.project.est; $('awPlan').value = S.project.plan;
        $('awLocalApplied').value = S.project.localApplied; $('awLocalKind').value = S.project.localKind;
        $('awCareerExcluded').checked = !!S.project.careerExcluded;
        bind();
        built = true;
    }
    function field(label, id, type, help, attrs) {
        return el('div', { class: 'field' }, [el('label', { for: id, text: label }), el('input', Object.assign({ type: type, id: id, autocomplete: 'off' }, attrs || {})),
            help ? el('div', { class: 'help', text: help }) : null]);
    }
    function selectField(label, id, opts, help) {
        var sel = el('select', { id: id });
        opts.forEach(function (o) { sel.appendChild(el('option', { value: o[0], text: o[1] })); });
        return el('div', { class: 'field' }, [el('label', { for: id, text: label }), sel, help ? el('div', { class: 'help', text: help }) : null]);
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
        box.appendChild(el('div', {}, [el('b', { text: band.label }), document.createTextNode(' 구간 → 적격통과점수 '), el('b', { text: band.pass_score + '점 이상' }),
            document.createTextNode(' (' + band.ref + ')')]));
        var chips = [['PQ 환산', w.pq + (off ? w.local : 0)], ['책임기술자 경력', w.career], ['지역업체 참여도', off ? 0 : w.local], ['경영상태', w.mgmt], ['입찰가격', w.price]];
        var wrap = el('div', { class: 'weights' });
        chips.forEach(function (c) { wrap.appendChild(el('span', { text: c[0] + ' ' + c[1] + '점' })); });
        wrap.appendChild(el('span', { text: '합계 100점 (감점: 기술인력 미달 -10, 임금체불 건당 -0.2)' }));
        box.appendChild(wrap);
        box.appendChild(el('div', { class: 'status', style: 'margin-top:0.4rem;', text: '입찰가격 평점: ' + band.price.ref }));
    }

    // ------------------------------------------------------------ 입찰사 표
    var COLS = ['입찰사', 'PQ 점수', '벌점 감점', '입찰가격 (원)', '책임기술자 경력 비율 (%)', '지역업체 참여비율 (%)', '경영상태', '기술인력 미달', '임금체불 공개 (회)'];
    function inp(key, f, extra) {
        return el('input', Object.assign({ type: 'text', 'data-k': key, 'data-f': f, value: S.rows[key][f], inputmode: 'decimal', autocomplete: 'off' }, extra || {}));
    }
    function renderBidders() {
        var t = $('awTable');
        if (!t) return;
        t.textContent = '';
        t.appendChild(el('thead', {}, [el('tr', {}, COLS.map(function (c) { return el('th', { text: c }); }))]));
        var off = S.project.localApplied === '0', careerOff = !!S.project.careerExcluded;
        var tb = el('tbody');
        names.forEach(function (n) {
            var b = S.rows[n.key];
            var mg = el('td');
            var sel = el('select', { 'data-k': n.key, 'data-f': 'mgmt_mode' });
            [['full', '만점 (PQ에 반영됨)'], ['credit', '신용평가 구간 선택'], ['score', '점수 직접 입력']].forEach(function (o) {
                sel.appendChild(el('option', { value: o[0], text: o[1], selected: b.mgmt_mode === o[0] }));
            });
            mg.appendChild(sel);
            if (b.mgmt_mode === 'credit') {
                var tier = el('select', { 'data-k': n.key, 'data-f': 'mgmt_tier', class: 'sub-input' });
                spec.mgmt.credit_tiers.forEach(function (c) { tier.appendChild(el('option', { value: c.id, text: c.score.toFixed(1) + '점 · ' + c.label, selected: b.mgmt_tier === c.id })); });
                mg.appendChild(tier);
            } else if (b.mgmt_mode === 'score') {
                mg.appendChild(inp(n.key, 'mgmt_score', { class: 'sub-input', placeholder: '0 ~ ' + spec.mgmt.max }));
            }
            var local = el('td', {}, [inp(n.key, 'local_ratio', off || b.local_solo ? { disabled: true } : {})]);
            if (!off) {
                local.appendChild(el('label', { class: 'check', style: 'margin-top:0.3rem; font-size:0.75rem;' }, [
                    el('input', { type: 'checkbox', 'data-k': n.key, 'data-f': 'local_solo', checked: b.local_solo }), el('span', { text: '지역업체 단독 참여 (0점)' })]));
            }
            tb.appendChild(el('tr', {}, [
                el('td', {}, [el('b', { text: n.name }), el('div', { class: 'muted', style: 'font-size:0.75rem;', text: 'PQ ' + n.rank + '위' })]),
                el('td', { class: 'num' }, [el('b', { text: fmt(n.pq) })]),
                el('td', {}, [inp(n.key, 'penalty_deduction', { placeholder: '0' })]),
                el('td', {}, [inp(n.key, 'bid_price', { class: 'w-price' })]),
                el('td', {}, [inp(n.key, 'career_ratio', careerOff ? { disabled: true } : {})]),
                local, mg,
                el('td', { class: 'c' }, [el('input', { type: 'checkbox', 'data-k': n.key, 'data-f': 'tech_shortage', checked: b.tech_shortage })]),
                el('td', {}, [inp(n.key, 'wage_arrears_count', { placeholder: '0' })])
            ]));
        });
        t.appendChild(tb);
    }

    // ------------------------------------------------------------ 계산 요청
    function payload() {
        var p = S.project;
        return {
            spec_id: SPEC_ID,
            project: { estimated_price: p.est, planned_price: p.plan, local_applied: p.localApplied !== '0', local_kind: p.localKind, career_excluded: !!p.careerExcluded },
            bidders: names.map(function (n) {
                var b = S.rows[n.key];
                return { name: n.key, pq_score: n.pq, penalty_deduction: b.penalty_deduction, bid_price: b.bid_price, career_ratio: b.career_ratio, local_ratio: b.local_ratio,
                         local_solo: !!b.local_solo, mgmt_mode: b.mgmt_mode, mgmt_tier: b.mgmt_tier, mgmt_score: b.mgmt_score, tech_shortage: !!b.tech_shortage,
                         wage_arrears_count: b.wage_arrears_count };
            })
        };
    }
    function calc() {
        var btn = $('awCalc'), st = $('awStatus');
        if (!names.length) { st.className = 'status err'; st.textContent = '적격심사 대상 입찰사가 없습니다. 5단계에서 PQ 점수를 먼저 계산해 주세요.'; return; }
        st.className = 'status'; st.textContent = '계산 중...'; btn.disabled = true;
        fetch('/api/award/evaluate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload()) })
            .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
            .then(function (x) {
                if (!x.ok || !x.d.success) { st.className = 'status err'; st.textContent = x.d.message || '계산하지 못했습니다.'; return; }
                st.textContent = '';
                renderResult(x.d.result);
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
        return el('span', { class: 'tag ' + s[0], text: r.status === 'fail' ? '미달 (' + fmt(r.shortfall) + '점 부족)' : s[1] });
    }
    function renderResult(res) {
        var box = $('awResults');
        box.textContent = '';
        var rs = res.results;
        var win = res.winner_index !== null ? rs[res.winner_index] : null;
        var wb = el('div', { class: win ? 'winner-box' : (res.lottery_indexes.length ? 'winner-box lottery' : 'winner-box none') });
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
                el('td', { text: r.review_order === null ? '-' : String(r.review_order) }), el('td', { text: r.name }),
                el('td', { text: won(r.bid_price) + '원 (' + fmt(r.price_ratio * 100) + '%)' }),
                el('td', { class: 'num', text: fmt(sc.pq) }), el('td', { class: 'num', text: fmt(sc.career) }), el('td', { class: 'num', text: fmt(sc.local) }),
                el('td', { class: 'num', text: fmt(sc.mgmt) }), el('td', { class: 'num', text: fmt(sc.price) }), el('td', { class: 'num', text: fmt(sc.deduction) }),
                el('td', { class: 'num total' }, [el('span', { class: 'score-big', text: fmt(r.total) })]), el('td', {}, [statusTag(r)])
            ]));
        });
        t.appendChild(tb);
        box.appendChild(el('div', { class: 'tbl-wrap' }, [t]));
        box.appendChild(el('div', { class: 'no-print', style: 'margin:0.8rem 0; display:flex; gap:0.6rem; flex-wrap:wrap;' }, [
            el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: '종합평점 CSV로 저장', onclick: function () { downloadCsv(res); } }),
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
        var csv = '﻿' + rows.map(function (r) { return r.map(csvCell).join(','); }).join('\r\n');   // 앞의 BOM은 엑셀이 한글을 깨지 않고 열게 한다
        var a = document.createElement('a');
        a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
        a.download = '적격심사_종합평점_결과.csv';
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
        $('awLocalApplied').addEventListener('change', function () { S.project.localApplied = this.value; renderBand(); renderBidders(); save(); });
        $('awLocalKind').addEventListener('change', function () { S.project.localKind = this.value; save(); });
        $('awCareerExcluded').addEventListener('change', function () { S.project.careerExcluded = this.checked; renderBidders(); save(); });
        var t = $('awTable');
        function onField(e) {
            var f = e.target.getAttribute && e.target.getAttribute('data-f');
            if (!f) return;
            var k = e.target.getAttribute('data-k');
            var b = S.rows[k];
            if (!b) return;
            b[f] = e.target.type === 'checkbox' ? e.target.checked : e.target.value;
            if (e.type === 'change' && (f === 'mgmt_mode' || f === 'local_solo')) renderBidders();   // 입력칸 구성이 바뀌는 항목만 다시 그린다
            save();
        }
        t.addEventListener('input', onField);
        t.addEventListener('change', onField);
        $('awCalc').addEventListener('click', calc);
    }

    document.addEventListener('DOMContentLoaded', function () {
        $('awardToggle').addEventListener('click', function () {
            var b = $('awardBody');
            var open = b.style.display === 'none';
            b.style.display = open ? '' : 'none';
            this.textContent = open ? '접기' : '펼치기';
        });
    });

    window.AwardPanel = { onPqResult: onPqResult };
})();
