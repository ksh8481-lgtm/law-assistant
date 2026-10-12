/* 사업수행능력평가 점수 산정 화면
 * - 입력 폼은 /api/pq/spec/<id> 의 form 스키마로 그린다(평가기준이 늘어도 같은 화면 재사용).
 * - 점수는 서버(pq_engine)가 고시 공식대로 계산한다. AI 추출값은 노란색으로 표시되고, 사람이 고치면 '확인함'이 된다.
 */
(function () {
    'use strict';

    var DRAFT_KEY = 'pq_score_draft_v1';
    var MAX_BIDDERS = 40;

    var specList = { ready: [], planned: [] };
    var spec = null;
    var S = null; // 현재 입력 상태

    // ------------------------------------------------------------ 유틸
    function el(tag, attrs, kids) {
        var n = document.createElement(tag);
        if (attrs) {
            Object.keys(attrs).forEach(function (k) {
                var v = attrs[k];
                if (v === null || v === undefined || v === false) return;
                if (k === 'class') n.className = v;
                else if (k === 'text') n.textContent = v;
                else if (k === 'style') n.setAttribute('style', v);
                else if (k.indexOf('on') === 0 && typeof v === 'function') n.addEventListener(k.slice(2), v);
                else n.setAttribute(k, v === true ? '' : v);
            });
        }
        (kids || []).forEach(function (c) {
            if (c === null || c === undefined || c === false) return;
            n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
        });
        return n;
    }
    function $(id) { return document.getElementById(id); }
    function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }
    function fmt(x) {
        if (x === null || x === undefined || x === '') return '-';
        return (Math.round(Number(x) * 100) / 100).toString();
    }
    function isBlank(v) { return v === undefined || v === null || v === ''; }

    function newBidder(i) {
        return { name: '입찰사 ' + (i + 1), firm: {}, persons: { lead: {}, field_lead: {}, field_member: {} }, ai: {}, notes: [], evidence: {} };
    }
    function newState() {
        return {
            project: { values: {}, fields: [], adjust: {} },
            bidders: [newBidder(0)],
            active: 0,
            resultShown: null
        };
    }

    function saveDraft() {
        if (!spec) return;
        try {
            var slim = JSON.parse(JSON.stringify(S));
            slim.resultShown = null;
            localStorage.setItem(DRAFT_KEY + ':' + spec.id, JSON.stringify(slim));
        } catch (e) { /* 저장소를 못 쓰는 환경이면 건너뜀 */ }
    }
    function loadDraft(id) {
        try {
            var raw = localStorage.getItem(DRAFT_KEY + ':' + id);
            if (!raw) return null;
            var d = JSON.parse(raw);
            if (!d || !d.bidders || !d.bidders.length) return null;
            return d;
        } catch (e) { return null; }
    }
    var saveTimer = null;
    function touch() {
        clearTimeout(saveTimer);
        saveTimer = setTimeout(saveDraft, 400);
    }

    // ------------------------------------------------------------ 평가기준 선택
    function loadSpecs() {
        fetch('/api/pq/specs').then(function (r) { return r.json(); }).then(function (d) {
            specList = { ready: d.ready || [], planned: d.planned || [] };
            renderSpecCards();
            if (specList.ready.length === 1) selectSpec(specList.ready[0].id);
        }).catch(function () {
            $('specCards').textContent = '평가기준 목록을 불러오지 못했습니다.';
        });
    }
    function renderSpecCards() {
        var box = $('specCards');
        clear(box);
        specList.ready.forEach(function (s) {
            var c = el('div', { class: 'spec-card' + (spec && spec.id === s.id ? ' active' : ''), onclick: function () { selectSpec(s.id); } }, [
                el('b', { text: s.short || s.name }),
                el('small', { text: (s.source && s.source.issuer ? s.source.issuer + ' · ' : '') + (s.source && s.source.effective ? s.source.effective + ' 시행' : '') })
            ]);
            box.appendChild(c);
        });
        specList.planned.forEach(function (s) {
            box.appendChild(el('div', { class: 'spec-card planned', title: s.note || '' }, [
                el('b', {}, [s.short, el('span', { class: 'badge', text: '준비 중' })]),
                el('small', { text: s.note || '' })
            ]));
        });
    }
    function selectSpec(id) {
        fetch('/api/pq/spec/' + encodeURIComponent(id)).then(function (r) { return r.json(); }).then(function (d) {
            if (!d.success) { alert(d.message || '평가기준을 불러오지 못했습니다.'); return; }
            spec = d.spec;
            S = loadDraft(spec.id) || newState();
            S.resultShown = null;
            renderSpecCards();
            renderNotice();
            $('workspace').style.display = '';
            renderAll();
            $('results').textContent = '';
        });
    }
    function renderNotice() {
        var box = $('specNotice');
        clear(box);
        var src = spec.source || {};
        var kids = [];
        if (src.title) {
            kids.push(el('div', {}, [
                '근거: ',
                src.link ? el('a', { href: src.link, target: '_blank', rel: 'noopener', text: src.title }) : src.title,
                ' (' + (src.issuer || '') + (src.effective ? ', ' + src.effective + ' 시행' : '') + ')'
            ]));
        }
        var ul = el('ul');
        (spec.notice || []).forEach(function (t) { ul.appendChild(el('li', { text: t })); });
        kids.push(ul);
        box.appendChild(el('div', { class: 'notice' }, kids));
    }

    // ------------------------------------------------------------ 필드 입력 위젯
    // f: 필드 정의, store: 값을 담는 객체, aiPath: AI 근거 키(없으면 null), bidder: 해당 입찰사(AI 표시용)
    function fieldWidget(f, store, opts) {
        opts = opts || {};
        var aiInfo = opts.aiPath && opts.bidder ? opts.bidder.ai[opts.aiPath] : null;
        var wrap = el('div', { class: 'field' + (aiInfo && !aiInfo.confirmed ? ' ai' : '') });
        var lab = el('label');
        if (f.type === 'checkbox') {
            // 체크박스는 라벨을 옆에 둔다
            var cur = isBlank(store[f.key]) ? (f.default === true) : !!store[f.key];
            var cb = el('input', { type: 'checkbox' });
            cb.checked = cur;
            cb.addEventListener('change', function () {
                store[f.key] = cb.checked;
                markConfirmed(opts, wrap);
                touch();
            });
            var line = el('label', { class: 'check' }, [cb, el('span', { text: f.label })]);
            wrap.appendChild(line);
            appendAiTag(line, aiInfo);
            return wrap;
        }
        lab.appendChild(document.createTextNode(f.label));
        if (f.unit) lab.appendChild(el('span', { class: 'unit', text: ' (' + f.unit + ')' }));
        appendAiTag(lab, aiInfo);
        wrap.appendChild(lab);

        var inp;
        if (f.type === 'select') {
            inp = el('select');
            inp.appendChild(el('option', { value: '', text: '선택' }));
            (f.options || []).forEach(function (o) { inp.appendChild(el('option', { value: o, text: o })); });
            inp.value = isBlank(store[f.key]) ? '' : String(store[f.key]);
            inp.addEventListener('change', function () {
                if (inp.value === '') delete store[f.key]; else store[f.key] = inp.value;
                markConfirmed(opts, wrap); touch();
            });
        } else if (f.type === 'number') {
            inp = el('input', { type: 'number', step: 'any', inputmode: 'decimal' });
            if (f.min !== undefined) inp.setAttribute('min', f.min);
            inp.value = isBlank(store[f.key]) ? '' : store[f.key];
            inp.addEventListener('input', function () {
                if (inp.value === '') delete store[f.key]; else store[f.key] = Number(inp.value);
                markConfirmed(opts, wrap); touch();
            });
        } else if (f.type === 'date') {
            inp = el('input', { type: 'date' });
            inp.value = isBlank(store[f.key]) ? '' : store[f.key];
            inp.addEventListener('change', function () {
                if (inp.value === '') delete store[f.key]; else store[f.key] = inp.value;
                touch();
            });
        } else {
            inp = el('input', { type: 'text' });
            inp.value = isBlank(store[f.key]) ? '' : store[f.key];
            inp.addEventListener('input', function () {
                if (inp.value === '') delete store[f.key]; else store[f.key] = inp.value;
                markConfirmed(opts, wrap); touch();
            });
        }
        wrap.appendChild(inp);
        if (f.help) wrap.appendChild(el('div', { class: 'help', text: f.help }));
        return wrap;
    }
    function appendAiTag(parent, aiInfo) {
        if (!aiInfo) return;
        var tag = el('span', { class: 'ai-tag' + (aiInfo.confirmed ? ' ok' : ''), text: aiInfo.confirmed ? '확인함' : 'AI', title: aiInfo.evidence || 'AI가 서류에서 추출한 값입니다. 근거를 확인하세요.' });
        tag.setAttribute('data-ai-tag', '1');
        parent.appendChild(tag);
    }
    function markConfirmed(opts, wrap) {
        if (!opts.aiPath || !opts.bidder) return;
        var info = opts.bidder.ai[opts.aiPath];
        if (info && !info.confirmed) {
            info.confirmed = true;
            wrap.classList.remove('ai');
            var t = wrap.querySelector('[data-ai-tag]');
            if (t) { t.textContent = '확인함'; t.classList.add('ok'); }
        }
    }

    // ------------------------------------------------------------ 2. 사업 정보
    function projectFieldDefs() {
        return spec.form.project.map(function (f) {
            if (f.key === 'work_type') {
                var g = JSON.parse(JSON.stringify(f));
                g.options = ['(직접 구성)'].concat(Object.keys(spec.templates || {}));
                return g;
            }
            return f;
        });
    }
    function renderProject() {
        var box = $('projectForm');
        clear(box);
        projectFieldDefs().forEach(function (f) {
            var w = fieldWidget(f, S.project.values, {});
            if (f.key === 'work_type') {
                var sel = w.querySelector('select');
                sel.addEventListener('change', function () { applyTemplate(sel.value); });
            }
            if (f.key === 'rel_mode') {
                var sel2 = w.querySelector('select');
                sel2.addEventListener('change', function () { renderBidders(); });
            }
            box.appendChild(w);
        });
        renderFieldsTable();
    }
    function applyTemplate(name) {
        var tpl = (spec.templates || {})[name];
        if (!tpl) return;
        S.project.fields = tpl.map(function (r) { return { name: r[0], pct: r[1], kind: r[2] || '필수' }; });
        renderFieldsTable();
        renderBidders();
        touch();
    }
    function renameField(oldName, newName) {
        if (!oldName || !newName || oldName === newName) return;
        S.bidders.forEach(function (b) {
            ['field_lead', 'field_member'].forEach(function (role) {
                if (b.persons[role][oldName] !== undefined && b.persons[role][newName] === undefined) {
                    b.persons[role][newName] = b.persons[role][oldName];
                    delete b.persons[role][oldName];
                }
            });
            (b.firm.prev_items || []).forEach(function (r) { if (r.cur_role === oldName) r.cur_role = newName; });
        });
    }
    function renderFieldsTable() {
        var tb = $('fieldsTable').querySelector('tbody');
        clear(tb);
        S.project.fields.forEach(function (r, i) {
            var nameInp = el('input', { type: 'text', value: r.name || '' });
            var oldName = r.name;
            nameInp.addEventListener('change', function () {
                var nn = nameInp.value.trim();
                renameField(oldName, nn);
                r.name = nn; oldName = nn;
                renderBidders(); touch();
            });
            var pctInp = el('input', { type: 'number', step: 'any', min: '0', value: isBlank(r.pct) ? '' : r.pct });
            pctInp.addEventListener('input', function () { r.pct = pctInp.value === '' ? null : Number(pctInp.value); updateFieldsSum(); touch(); });
            var kindSel = el('select');
            ['필수', '추가'].forEach(function (k) { kindSel.appendChild(el('option', { value: k, text: k })); });
            kindSel.value = r.kind || '필수';
            kindSel.addEventListener('change', function () { r.kind = kindSel.value; touch(); });
            var del = el('button', { class: 'btn btn-danger btn-sm', type: 'button', text: '삭제', onclick: function () {
                S.project.fields.splice(i, 1); renderFieldsTable(); renderBidders(); touch();
            } });
            tb.appendChild(el('tr', {}, [el('td', {}, [nameInp]), el('td', {}, [pctInp]), el('td', {}, [kindSel]), el('td', {}, [del])]));
        });
        if (!S.project.fields.length) {
            tb.appendChild(el('tr', {}, [el('td', { colspan: '4', class: 'muted', text: '업무분야를 선택하거나 [+ 분야 추가]로 직접 구성하세요.' })]));
        }
        updateFieldsSum();
    }
    function updateFieldsSum() {
        var sum = S.project.fields.reduce(function (a, r) { return a + (Number(r.pct) || 0); }, 0);
        var n = $('fieldsSum');
        n.textContent = '업무기여도 합계 ' + fmt(sum) + '%' + (Math.abs(sum - 100) > 0.01 ? ' (100%가 아니면 비율대로 환산해 계산합니다)' : '');
        n.style.color = Math.abs(sum - 100) > 0.01 ? '#b91c1c' : '';
    }

    // ------------------------------------------------------------ 3. 배점 조정
    function renderAdjust() {
        var tb = $('adjustTable').querySelector('tbody');
        clear(tb);
        var pctAdj = spec.adjust_pct || 20;
        spec.items.forEach(function (it) {
            var lo = it.max * (1 - pctAdj / 100), hi = it.max * (1 + pctAdj / 100);
            var cur = S.project.adjust[it.id];
            var inp = el('input', { type: 'number', step: '0.1', value: isBlank(cur) ? it.max : cur });
            var rangeTd = el('td', { class: 'status', text: fmt(lo) + ' ~ ' + fmt(hi) + '점' });
            inp.addEventListener('input', function () {
                var v = inp.value === '' ? it.max : Number(inp.value);
                if (Math.abs(v - it.max) < 1e-9) delete S.project.adjust[it.id]; else S.project.adjust[it.id] = v;
                rangeTd.style.color = (v < lo - 1e-9 || v > hi + 1e-9) ? '#b91c1c' : '';
                updateAdjustSum(); touch();
            });
            tb.appendChild(el('tr', {}, [el('td', { text: it.name }), el('td', { class: 'num', text: fmt(it.max) }), el('td', {}, [inp]), rangeTd]));
        });
        updateAdjustSum();
    }
    function updateAdjustSum() {
        var sum = spec.items.reduce(function (a, it) {
            var v = S.project.adjust[it.id];
            return a + (isBlank(v) ? it.max : Number(v));
        }, 0);
        var n = $('adjustSum');
        n.textContent = '배점 합계 ' + fmt(sum) + '점' + (Math.abs(sum - 100) > 0.01 ? ' (고시 합계는 100점)' : '');
        n.style.color = Math.abs(sum - 100) > 0.01 ? '#b91c1c' : '';
    }

    // ------------------------------------------------------------ 4. 입찰사
    function relMode() {
        return String(S.project.values.rel_mode || '').indexOf('평가위원') === 0 ? 'relative' : 'direct';
    }
    function renderBidders() {
        var tabs = $('bidderTabs');
        clear(tabs);
        S.bidders.forEach(function (b, i) {
            tabs.appendChild(el('button', { type: 'button', class: 'tab' + (i === S.active ? ' active' : ''), text: b.name || ('입찰사 ' + (i + 1)), onclick: function () {
                S.active = i; renderBidders(); touch();
            } }));
        });
        tabs.appendChild(el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: '+ 입찰사 추가', onclick: function () {
            if (S.bidders.length >= MAX_BIDDERS) { alert('입찰사는 최대 ' + MAX_BIDDERS + '개까지 입력할 수 있습니다.'); return; }
            S.bidders.push(newBidder(S.bidders.length));
            S.active = S.bidders.length - 1;
            renderBidders(); touch();
        } }));
        renderBidderPanel();
    }

    function sectionCard(title, kids) {
        return el('div', { class: 'sub' }, [el('h3', { text: title })].concat(kids));
    }

    function renderBidderPanel() {
        var panel = $('bidderPanel');
        clear(panel);
        var b = S.bidders[S.active];
        if (!b) return;

        // 이름 / 삭제
        var nameInp = el('input', { type: 'text', value: b.name || '' });
        nameInp.addEventListener('input', function () { b.name = nameInp.value; touch(); });
        nameInp.addEventListener('change', function () { renderTabsOnly(); });
        var delBtn = el('button', { type: 'button', class: 'btn btn-danger btn-sm', text: '이 입찰사 삭제', onclick: function () {
            if (S.bidders.length <= 1) { alert('입찰사는 최소 1개가 필요합니다.'); return; }
            if (!confirm("'" + (b.name || '입찰사') + "' 입력 내용을 삭제할까요?")) return;
            S.bidders.splice(S.active, 1);
            S.active = Math.max(0, S.active - 1);
            renderBidders(); touch();
        } });
        panel.appendChild(el('div', { class: 'grid', style: 'margin-bottom:1rem; align-items:end;' }, [
            el('div', { class: 'field' }, [el('label', { text: '입찰사(대행자) 이름' }), nameInp]),
            el('div', {}, [delBtn])
        ]));

        panel.appendChild(buildExtractBox(b));

        // 대행자 항목
        spec.form.firm.forEach(function (sec) {
            var g = el('div', { class: 'grid' });
            sec.fields.forEach(function (f) {
                g.appendChild(fieldWidget(f, b.firm, { aiPath: 'firm.' + f.key, bidder: b }));
            });
            panel.appendChild(sectionCard(sec.title, [g]));
        });

        // 행 입력 표
        (spec.form.firm_rows || []).forEach(function (def) { panel.appendChild(buildRowsTable(def, b)); });

        // 기술인
        var fields = S.project.fields.filter(function (r) { return (r.name || '').trim(); });
        panel.appendChild(personCard('lead', b, null));
        if (!fields.length) {
            panel.appendChild(el('div', { class: 'notice', text: '위 2단계에서 분야별 책임기술인 구성을 먼저 입력하면 분야별 기술인 입력란이 나타납니다.' }));
        }
        fields.forEach(function (r) { panel.appendChild(personCard('field_lead', b, r.name.trim())); });
        fields.forEach(function (r) { panel.appendChild(personCard('field_member', b, r.name.trim())); });
    }
    function renderTabsOnly() {
        var tabs = $('bidderTabs').querySelectorAll('.tab');
        S.bidders.forEach(function (b, i) { if (tabs[i]) tabs[i].textContent = b.name || ('입찰사 ' + (i + 1)); });
    }

    function personCard(role, b, fieldName) {
        var def = spec.form.persons[role];
        var store;
        var pathBase;
        if (role === 'lead') {
            store = b.persons.lead;
            pathBase = 'persons.lead.';
        } else {
            if (!b.persons[role][fieldName]) b.persons[role][fieldName] = {};
            store = b.persons[role][fieldName];
            pathBase = 'persons.' + role + '.' + fieldName + '.';
        }
        var mode = relMode();
        var g = el('div', { class: 'grid' });
        def.fields.forEach(function (f) {
            if (role === 'lead') {
                if (mode === 'relative' && (f.key === 'tech_grade' || f.key === 'mgmt_grade')) return;
                if (mode === 'direct' && (f.key === 'tech_raw' || f.key === 'mgmt_raw')) return;
            }
            g.appendChild(fieldWidget(f, store, { aiPath: pathBase + f.key, bidder: b }));
        });
        var title = def.label + (fieldName ? ' - ' + fieldName : '');
        return el('div', { class: 'sub' }, [el('details', { open: role === 'lead' ? true : null }, [el('summary', { text: title }), el('div', { style: 'margin-top:0.8rem;' }, [g])])]);
    }

    function roleOptions() {
        var opts = [{ v: 'lead', t: '사업책임기술인' }];
        S.project.fields.forEach(function (r) { if ((r.name || '').trim()) opts.push({ v: r.name.trim(), t: '분야별책임: ' + r.name.trim() }); });
        return opts;
    }
    function buildRowsTable(def, b) {
        if (!Array.isArray(b.firm[def.key])) b.firm[def.key] = [];
        var rows = b.firm[def.key];
        var box = el('div', { class: 'sub' }, [el('h3', { text: def.title })]);
        if (def.help) box.appendChild(el('div', { class: 'status', style: 'margin-bottom:0.6rem;', text: def.help }));
        var wrap = el('div', { class: 'tbl-wrap' });
        var table = el('table');
        var thead = el('thead');
        var htr = el('tr');
        def.columns.forEach(function (c) { htr.appendChild(el('th', { text: c.label, title: c.help || '' })); });
        htr.appendChild(el('th', { style: 'width:60px;' }));
        thead.appendChild(htr);
        table.appendChild(thead);
        var tb = el('tbody');
        table.appendChild(tb);
        wrap.appendChild(table);
        box.appendChild(wrap);

        function draw() {
            clear(tb);
            if (!rows.length) {
                tb.appendChild(el('tr', {}, [el('td', { colspan: String(def.columns.length + 1), class: 'muted', text: '해당 실적이 없으면 비워 두세요.' })]));
            }
            rows.forEach(function (row, i) {
                var tr = el('tr', { style: row._ai ? 'background:var(--ai-bg);' : null });
                def.columns.forEach(function (c) {
                    var td = el('td');
                    var inp;
                    if (c.type === 'select' || c.type === 'role_select') {
                        inp = el('select');
                        inp.appendChild(el('option', { value: '', text: '선택' }));
                        var opts = c.type === 'role_select' ? roleOptions() : (c.options || []).map(function (o) { return { v: o, t: o }; });
                        opts.forEach(function (o) { inp.appendChild(el('option', { value: o.v, text: o.t })); });
                        // 서류에서 읽은 역할이 목록에 없으면 임시로 보여준다
                        if (!isBlank(row[c.key]) && !opts.some(function (o) { return o.v === String(row[c.key]); })) {
                            inp.appendChild(el('option', { value: String(row[c.key]), text: String(row[c.key]) + ' (목록에 없음)' }));
                        }
                        inp.value = isBlank(row[c.key]) ? '' : String(row[c.key]);
                        inp.addEventListener('change', function () {
                            if (inp.value === '') delete row[c.key];
                            else row[c.key] = (c.key === 'form_pct') ? Number(inp.value) : inp.value;
                            row._ai = false; tr.style.background = ''; touch();
                        });
                    } else if (c.type === 'number') {
                        inp = el('input', { type: 'number', step: 'any' });
                        if (c.min !== undefined) inp.setAttribute('min', c.min);
                        inp.value = isBlank(row[c.key]) ? '' : row[c.key];
                        inp.addEventListener('input', function () {
                            if (inp.value === '') delete row[c.key]; else row[c.key] = Number(inp.value);
                            row._ai = false; tr.style.background = ''; touch();
                        });
                    } else {
                        inp = el('input', { type: 'text', value: isBlank(row[c.key]) ? '' : row[c.key] });
                        inp.addEventListener('input', function () {
                            if (inp.value === '') delete row[c.key]; else row[c.key] = inp.value;
                            row._ai = false; tr.style.background = ''; touch();
                        });
                    }
                    td.appendChild(inp);
                    tr.appendChild(td);
                });
                tr.appendChild(el('td', {}, [el('button', { type: 'button', class: 'btn btn-danger btn-sm', text: '삭제', onclick: function () { rows.splice(i, 1); draw(); touch(); } })]));
                tb.appendChild(tr);
            });
        }
        draw();
        box.appendChild(el('div', { style: 'margin-top:0.5rem;' }, [el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: '+ 행 추가', onclick: function () { rows.push({}); draw(); touch(); } })]));
        return box;
    }

    // ------------------------------------------------------------ AI 추출
    function buildExtractBox(b) {
        var box = el('div', { class: 'extract-box no-print' });
        box.appendChild(el('b', { text: '🤖 AI로 서류에서 입력값 채우기 (선택)' }));
        box.appendChild(el('div', { class: 'status', style: 'margin-top:0.3rem;', text: '이 입찰사의 자기평가서·실적증명서·경력증명서 등을 올리면 AI가 값을 옮겨 적습니다. 서류에 없는 값은 비워 두며, 노란색 칸은 [AI] 표시에 마우스를 올려 근거를 확인한 뒤 맞으면 그대로 두고 틀리면 고치세요. 점수는 AI가 아니라 고시 공식으로 계산됩니다. 개인정보가 있는 서류는 마스킹해서 올리는 것을 권장합니다.' }));
        var file = el('input', { type: 'file', multiple: true, accept: '.pdf,.hwp,.hwpx,.docx,.doc,.xlsx,.xls,.txt,.png,.jpg,.jpeg' });
        var over = el('input', { type: 'checkbox' });
        var status = el('span', { class: 'status' });
        var btn = el('button', { type: 'button', class: 'btn btn-primary btn-sm', text: 'AI 추출 실행' });
        btn.addEventListener('click', function () {
            if (!file.files.length) { status.textContent = '파일을 먼저 선택하세요.'; return; }
            runExtract(b, file.files, over.checked, btn, status, box);
        });
        box.appendChild(el('div', { class: 'row' }, [file, el('label', { class: 'check' }, [over, el('span', { text: '이미 입력한 값도 덮어쓰기' })]), btn, status]));
        var res = el('div', { class: 'evidence', 'data-extract-result': '1' });
        box.appendChild(res);
        renderExtractNotes(b, res);
        return box;
    }
    function renderExtractNotes(b, res) {
        clear(res);
        if (b.notes && b.notes.length) {
            var ul = el('ul');
            b.notes.forEach(function (n) { ul.appendChild(el('li', { text: n })); });
            res.appendChild(el('div', { text: '안내' }));
            res.appendChild(ul);
        }
        var ev = b.evidence || {};
        var keys = Object.keys(ev);
        if (keys.length) {
            var det = el('details', {}, [el('summary', { text: 'AI가 제시한 근거 ' + keys.length + '건 보기' })]);
            var ul2 = el('ul');
            keys.forEach(function (k) { ul2.appendChild(el('li', { text: k + ' ← ' + ev[k] })); });
            det.appendChild(ul2);
            res.appendChild(det);
        }
    }
    function runExtract(b, files, overwrite, btn, status, box) {
        var fd = new FormData();
        fd.append('spec_id', spec.id);
        fd.append('bidder_name', b.name || '');
        fd.append('project', JSON.stringify({ fields: S.project.fields, announce_date: S.project.values.announce_date || '' }));
        for (var i = 0; i < files.length; i++) fd.append('files', files[i]);
        btn.disabled = true;
        status.textContent = '서류를 올리는 중...';
        fetch('/api/pq/extract', { method: 'POST', body: fd }).then(function (r) { return r.json(); }).then(function (d) {
            if (!d.success) throw new Error(d.message || '추출 요청에 실패했습니다.');
            status.textContent = 'AI가 서류를 읽는 중입니다(1~3분 걸릴 수 있어요)...';
            return pollExtract(d.jobId, status);
        }).then(function (result) {
            var cnt = applyExtract(b, result, overwrite);
            status.textContent = 'AI가 ' + cnt.filled + '개 값을 채웠습니다' + (cnt.skipped ? ' (이미 입력된 ' + cnt.skipped + '개는 그대로 둠)' : '') + '. 노란 칸을 확인하세요.';
            renderBidderPanel();
            touch();
        }).catch(function (e) {
            status.textContent = '';
            status.appendChild(el('span', { class: 'err', text: String(e.message || e) }));
        }).then(function () { btn.disabled = false; });
    }
    function pollExtract(jobId, status) {
        return new Promise(function (resolve, reject) {
            var tries = 0;
            (function tick() {
                tries++;
                if (tries > 200) { reject(new Error('시간이 너무 오래 걸려 중단했습니다. 파일을 줄여서 다시 시도해 주세요.')); return; }
                fetch('/api/pq/extract_status/' + encodeURIComponent(jobId)).then(function (r) { return r.json(); }).then(function (d) {
                    if (d.status === 'completed') resolve(d.result);
                    else if (d.status === 'error') reject(new Error(d.message || 'AI 추출 중 오류가 발생했습니다.'));
                    else { status.textContent = 'AI가 서류를 읽는 중입니다... (' + (tries * 3) + '초)'; setTimeout(tick, 3000); }
                }).catch(function (e) { reject(e); });
            })();
        });
    }
    function applyExtract(b, result, overwrite) {
        var inputs = result.inputs || {};
        var ev = result.evidence || {};
        var cnt = { filled: 0, skipped: 0 };
        function put(store, key, val, path) {
            if (val === undefined || val === null) return;
            if (!isBlank(store[key]) && !overwrite) { cnt.skipped++; return; }
            store[key] = val;
            b.ai[path] = { evidence: ev[path] || '', confirmed: false };
            cnt.filled++;
        }
        var firm = inputs.firm || {};
        Object.keys(firm).forEach(function (k) {
            if (Array.isArray(firm[k])) {
                if (!firm[k].length) return;
                var cur = Array.isArray(b.firm[k]) ? b.firm[k] : [];
                var hasInput = cur.some(function (r) { return Object.keys(r).filter(function (x) { return x !== '_ai'; }).length; });
                if (hasInput && !overwrite) { cnt.skipped += firm[k].length; return; }
                b.firm[k] = firm[k].map(function (r) { r._ai = true; return r; });
                cnt.filled += firm[k].length;
            } else {
                put(b.firm, k, firm[k], 'firm.' + k);
            }
        });
        var persons = inputs.persons || {};
        var lead = persons.lead || {};
        Object.keys(lead).forEach(function (k) { put(b.persons.lead, k, lead[k], 'persons.lead.' + k); });
        ['field_lead', 'field_member'].forEach(function (role) {
            var m = persons[role] || {};
            Object.keys(m).forEach(function (fname) {
                if (!b.persons[role][fname]) b.persons[role][fname] = {};
                Object.keys(m[fname]).forEach(function (k) {
                    put(b.persons[role][fname], k, m[fname][k], 'persons.' + role + '.' + fname + '.' + k);
                });
            });
        });
        b.notes = result.notes || [];
        b.evidence = ev;
        return cnt;
    }

    // ------------------------------------------------------------ 5. 점수 계산
    function cleanStore(obj) {
        var out = {};
        Object.keys(obj || {}).forEach(function (k) {
            var v = obj[k];
            if (k === '_ai' || isBlank(v)) return;
            out[k] = v;
        });
        return out;
    }
    function buildPayload() {
        var pv = S.project.values;
        var project = {
            title: pv.title || '',
            announce_date: pv.announce_date || '',
            work_type: pv.work_type || '',
            apply_transfer_penalty: !!pv.apply_transfer_penalty,
            rel_mode: pv.rel_mode || '',
            fields: S.project.fields.map(function (r) { return { name: (r.name || '').trim(), pct: r.pct, kind: r.kind || '필수' }; }),
            adjust: S.project.adjust
        };
        var bidders = S.bidders.map(function (b, i) {
            var firm = cleanStore(b.firm);
            (spec.form.firm_rows || []).forEach(function (def) {
                firm[def.key] = (b.firm[def.key] || []).map(cleanStore).filter(function (r) { return Object.keys(r).length; });
            });
            var persons = { lead: cleanStore(b.persons.lead), field_lead: {}, field_member: {} };
            ['field_lead', 'field_member'].forEach(function (role) {
                S.project.fields.forEach(function (r) {
                    var n = (r.name || '').trim();
                    if (n && b.persons[role][n]) persons[role][n] = cleanStore(b.persons[role][n]);
                });
            });
            return { name: b.name || ('입찰사 ' + (i + 1)), firm: firm, persons: persons };
        });
        return { spec_id: spec.id, project: project, bidders: bidders };
    }
    function calc() {
        var status = $('scoreStatus');
        var btn = $('scoreBtn');
        btn.disabled = true;
        status.textContent = '계산 중...';
        fetch('/api/pq/score', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(buildPayload()) })
            .then(function (r) { return r.json(); }).then(function (d) {
                if (!d.success) throw new Error(d.message || '계산에 실패했습니다.');
                status.textContent = '';
                S.resultShown = d.result;
                renderResults(d.result);
            }).catch(function (e) {
                status.textContent = '';
                status.appendChild(el('span', { class: 'err', text: String(e.message || e) }));
            }).then(function () { btn.disabled = false; });
    }

    function renderResults(res) {
        var box = $('results');
        clear(box);
        var pv = S.project.values;
        if (pv.title) box.appendChild(el('p', { style: 'margin-bottom:0.6rem; font-weight:700;', text: '사업명: ' + pv.title + (pv.announce_date ? ' (입찰공고일 ' + pv.announce_date + ')' : '') }));

        if (res.warnings && res.warnings.length) {
            var ul = el('ul', { class: 'warn-list' });
            res.warnings.forEach(function (w) { ul.appendChild(el('li', { text: w })); });
            box.appendChild(el('div', { style: 'font-weight:700; margin-bottom:0.3rem;', text: '확인이 필요한 사항 ' + res.warnings.length + '건' }));
            box.appendChild(ul);
        }

        // 요약표
        var groups = res.groups || [];
        var gMax = {};
        spec.items.forEach(function (it) { gMax[it.group] = (gMax[it.group] || 0) + (res.maxes[it.id] !== undefined ? res.maxes[it.id] : it.max); });
        var table = el('table');
        var htr = el('tr', {}, [el('th', { class: 'num', text: '순위' }), el('th', { text: '입찰사' })]);
        groups.forEach(function (g) { htr.appendChild(el('th', { class: 'num', text: g.name + ' (' + fmt(gMax[g.id]) + ')' })); });
        htr.appendChild(el('th', { class: 'num', text: '가점' }));
        htr.appendChild(el('th', { class: 'num', text: '합계 (' + fmt(res.total_max) + ' + 가점)' }));
        table.appendChild(el('thead', {}, [htr]));
        var tb = el('tbody');
        var order = res.results.map(function (r, i) { return i; }).sort(function (a, b) { return res.results[a].rank - res.results[b].rank || a - b; });
        order.forEach(function (i) {
            var r = res.results[i];
            var tr = el('tr', { class: r.rank === 1 ? 'rank1' : null }, [el('td', { class: 'num', text: String(r.rank) }), el('td', { text: r.name })]);
            groups.forEach(function (g) { tr.appendChild(el('td', { class: 'num', text: fmt(r.group_scores[g.id]) })); });
            tr.appendChild(el('td', { class: 'num', text: fmt(r.bonus.score) }));
            tr.appendChild(el('td', { class: 'num' }, [el('span', { class: 'score-big', text: fmt(r.total) })]));
            tb.appendChild(tr);
        });
        table.appendChild(tb);
        box.appendChild(el('div', { class: 'tbl-wrap' }, [table]));

        box.appendChild(el('div', { class: 'no-print', style: 'margin:0.8rem 0; display:flex; gap:0.6rem; flex-wrap:wrap;' }, [
            el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: 'CSV로 저장', onclick: function () { downloadCsv(res); } }),
            el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: '인쇄 / PDF 저장', onclick: function () { window.print(); } })
        ]));

        // 입찰사별 상세
        order.forEach(function (i) {
            var r = res.results[i];
            var det = el('details', { class: 'sub', open: res.results.length === 1 ? true : null });
            det.appendChild(el('summary', { text: r.rank + '위 · ' + r.name + ' · ' + fmt(r.total) + '점 (평가요소별 근거 보기)' }));
            var t = el('table', { style: 'margin-top:0.7rem;' });
            t.appendChild(el('thead', {}, [el('tr', {}, [el('th', { text: '평가요소' }), el('th', { class: 'num', style: 'width:70px;', text: '배점' }), el('th', { class: 'num', style: 'width:80px;', text: '득점률' }), el('th', { class: 'num', style: 'width:70px;', text: '득점' }), el('th', { text: '산정 근거' })])]));
            var tbody = el('tbody');
            var lastGroup = null;
            r.items.forEach(function (it) {
                if (it.group !== lastGroup) {
                    lastGroup = it.group;
                    var gname = (groups.filter(function (g) { return g.id === it.group; })[0] || {}).name || it.group;
                    tbody.appendChild(el('tr', {}, [el('td', { colspan: '5', style: 'background:#f8fafc; font-weight:700;', text: gname + ' - ' + fmt(r.group_scores[it.group]) + '점' })]));
                }
                var basis = el('td', {}, [el('div', { class: 'basis', text: it.basis || '' })]);
                if (it.note) basis.appendChild(el('div', { class: 'basis muted', text: '※ ' + it.note }));
                tbody.appendChild(el('tr', {}, [
                    el('td', { text: it.name }), el('td', { class: 'num', text: fmt(it.max) }),
                    el('td', { class: 'num', text: it.pct === null || it.pct === undefined ? '-' : fmt(it.pct) + '%' }),
                    el('td', { class: 'num', text: fmt(it.score) }), basis
                ]));
            });
            tbody.appendChild(el('tr', {}, [el('td', { text: '소계(가점 제외)', style: 'font-weight:700;' }), el('td', { class: 'num', text: fmt(res.total_max) }), el('td'), el('td', { class: 'num', text: fmt(r.base_total), style: 'font-weight:700;' }), el('td')]));
            tbody.appendChild(el('tr', {}, [el('td', { text: r.bonus.name }), el('td'), el('td'), el('td', { class: 'num', text: fmt(r.bonus.score) }), el('td', {}, [el('div', { class: 'basis', text: r.bonus.basis })])]));
            tbody.appendChild(el('tr', {}, [el('td', { text: '합계', style: 'font-weight:800;' }), el('td'), el('td'), el('td', { class: 'num' }, [el('span', { class: 'score-big', text: fmt(r.total) })]), el('td')]));
            t.appendChild(tbody);
            det.appendChild(el('div', { class: 'tbl-wrap' }, [t]));
            box.appendChild(det);
        });
        box.appendChild(el('p', { class: 'status', style: 'margin-top:1rem;', text: '본 결과는 입력된 값을 고시 [별표]의 구간표에 적용한 계산 결과이며, 입력값의 진위는 건설기술용역 실적관리시스템 등 공식 자료로 검증해야 합니다. 최종 평가 결과는 평가위원회·발주청의 판단에 따릅니다.' }));
        box.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    function csvCell(v) {
        var s = String(v === undefined || v === null ? '' : v);
        return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
    }
    function downloadCsv(res) {
        var rows = [];
        rows.push(['순위', '입찰사'].concat(res.groups.map(function (g) { return g.name; })).concat(['가점', '합계']));
        res.results.forEach(function (r) {
            rows.push([r.rank, r.name].concat(res.groups.map(function (g) { return r.group_scores[g.id]; })).concat([r.bonus.score, r.total]));
        });
        rows.push([]);
        rows.push(['입찰사', '평가요소', '배점', '득점률(%)', '득점', '산정 근거']);
        res.results.forEach(function (r) {
            r.items.forEach(function (it) { rows.push([r.name, it.name, it.max, it.pct === null ? '' : it.pct, it.score, it.basis]); });
        });
        var csv = '﻿' + rows.map(function (r) { return r.map(csvCell).join(','); }).join('\r\n');
        var a = document.createElement('a');
        a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
        a.download = '사업수행능력평가_결과.csv';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    }

    // ------------------------------------------------------------ 시작
    function renderAll() {
        renderProject();
        renderAdjust();
        renderBidders();
    }

    document.addEventListener('DOMContentLoaded', function () {
        $('addFieldBtn').addEventListener('click', function () {
            S.project.fields.push({ name: '', pct: null, kind: '필수' });
            renderFieldsTable(); touch();
        });
        $('toggleAdjustBtn').addEventListener('click', function () {
            var b = $('adjustBox');
            var open = b.style.display === 'none';
            b.style.display = open ? '' : 'none';
            this.textContent = open ? '접기' : '펼치기';
        });
        $('resetAdjustBtn').addEventListener('click', function () { S.project.adjust = {}; renderAdjust(); touch(); });
        $('clearDraftBtn').addEventListener('click', function () {
            if (!confirm('입력한 내용을 모두 지우고 처음 상태로 되돌릴까요?')) return;
            try { localStorage.removeItem(DRAFT_KEY + ':' + spec.id); } catch (e) { /* 무시 */ }
            S = newState();
            renderAll();
            $('results').textContent = '';
        });
        $('scoreBtn').addEventListener('click', calc);
        loadSpecs();
    });
})();
