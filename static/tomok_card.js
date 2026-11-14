/*
 * 개발사업 스마트 법규 검토 - 공사 카드(설계 수치)와 3D 보기
 *
 *  - [설계 수치] 칸(연장·폭·두께·줄눈 간격·수로관 규격·1본 길이·집수정 간격)을 모아 공사 카드로 만든다.
 *  - [3D 보기]를 펼치면 /tomok_3d?embed=1 을 아래에 띄우고, 사업명·설계 수치를 바꿀 때마다 postMessage로 넘긴다.
 *  - [새 창으로 열기]는 /tomok_3d#card=<JSON> 으로 연다(그 화면에서 직접 고칠 수 있음).
 *  - [사업 내용에 넣기]는 설계 수치를 한 줄로 정리해 [주요 사업 내용 및 목적]에 덧붙인다.
 *  law_review_input.js(작성 중 보관·저장된 분석)와 script.js(분석 요청)가 window.TomokCard.collect/apply를 쓴다.
 */
(function () {
    'use strict';
    var $ = function (id) { return document.getElementById(id); };
    var FIELDS = { L: 'd3-L', B: 'd3-B', T: 'd3-T', joint: 'd3-joint', flume: 'd3-flume', unit: 'd3-unit', pit: 'd3-pit' };
    var DEFAULTS = { joint: 8, flume: 400, unit: 2, pit: 40 };
    var frame = null, ready = false;

    function num(id) { var el = $(id); if (!el || el.value === '') return null; var v = parseFloat(el.value); return isFinite(v) ? v : null; }

    /** 입력한 설계 수치만 담는다. 하나도 없으면 null. */
    function collect() {
        var d = {}, any = false;
        Object.keys(FIELDS).forEach(function (k) {
            var v = num(FIELDS[k]);
            if (v !== null) { d[k] = v; if (k === 'L' || k === 'B' || k === 'T') any = true; }
        });
        return any ? d : null;
    }
    function apply(d) {
        Object.keys(FIELDS).forEach(function (k) {
            var el = $(FIELDS[k]);
            if (!el) return;
            if (el.tagName === 'SELECT') el.value = String((d && d[k]) || DEFAULTS.flume);
            else el.value = d && d[k] != null ? d[k] : '';
        });
        push(false);
    }

    /** 3D 화면에 넘길 공사 카드. 연장·폭·두께가 모두 있어야 그린다. */
    function card() {
        var d = collect() || {};
        if (!(d.L > 0 && d.B > 0 && d.T > 0)) return null;
        return {
            name: ($('projectName') && $('projectName').value) || '',
            L: d.L, B: d.B, T: d.T,
            joint: d.joint || DEFAULTS.joint, flume: d.flume || DEFAULTS.flume,
            unit: d.unit || DEFAULTS.unit, pit: d.pit || DEFAULTS.pit,
        };
    }

    function setNote(msg) { var el = $('d3-note'); if (el) el.textContent = msg || ''; }

    function push(keepView) {
        if (!frame || !ready) return;
        var c = card();
        if (!c) { setNote('연장·폭·두께를 넣으면 3D 모형이 그려집니다.'); return; }
        setNote('');
        frame.contentWindow.postMessage({ type: 'tomok-card', card: c, keepView: keepView }, location.origin);
    }

    function toggle() {
        var wrap = $('d3-frame-wrap'), btn = $('d3-toggle');
        if (!wrap) return;
        var open = wrap.style.display === 'none';
        wrap.style.display = open ? 'block' : 'none';
        btn.textContent = open ? '🧊 3D 보기 닫기' : '🧊 3D 보기';
        if (open && !frame) {
            frame = document.createElement('iframe');
            frame.src = '/tomok_3d?embed=1';
            frame.title = '공사 카드 3D 보기';
            frame.style.cssText = 'width:100%; height:560px; border:0; display:block; background:#0f1115;';
            wrap.appendChild(frame);
        } else if (open) {
            push(false);
        }
        if (open) wrap.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    function openWindow() {
        var c = card();
        if (!c) { setNote('연장·폭·두께를 먼저 넣어 주세요.'); return; }
        window.open('/tomok_3d#card=' + encodeURIComponent(JSON.stringify(c)), '_blank');
    }

    function toDescription() {
        var c = card();
        if (!c) { setNote('연장·폭·두께를 먼저 넣어 주세요.'); return; }
        var line = '- [설계 수치] 콘크리트 포장 연장 ' + c.L + 'm, 폭 ' + c.B + 'm, 두께 ' + c.T + 'm(면적 ' + (c.L * c.B).toFixed(1) + '㎡), 줄눈 간격 ' + c.joint + 'm' +
            ' / U형 수로관 ' + c.flume + 'C 연장 ' + c.L + 'm(1본 ' + c.unit + 'm, ' + Math.ceil(c.L / c.unit) + '본)' +
            ' / 집수정 ' + c.pit + 'm 간격 ' + (Math.floor(c.L / c.pit) + 1) + '개소';
        var ta = $('description');
        var cur = ta.value.replace(/\n?- \[설계 수치\][^\n]*/g, '');   // 이전에 넣은 줄은 바꾼다
        ta.value = (cur.trim() ? cur.replace(/\s+$/, '') + '\n' : '') + line;
        ta.dispatchEvent(new Event('input', { bubbles: true }));
        setNote('사업 내용에 설계 수치를 넣었습니다.');
    }

    function debounce(fn, ms) { var t; return function () { clearTimeout(t); t = setTimeout(fn, ms); }; }

    document.addEventListener('DOMContentLoaded', function () {
        if (!$('d3-toggle')) return;
        $('d3-toggle').addEventListener('click', toggle);
        $('d3-open').addEventListener('click', openWindow);
        $('d3-desc').addEventListener('click', toDescription);
        var onChange = debounce(function () { push(true); }, 200);
        Object.keys(FIELDS).forEach(function (k) { var el = $(FIELDS[k]); if (el) el.addEventListener('input', onChange); });
        if ($('projectName')) $('projectName').addEventListener('input', onChange);
        window.addEventListener('message', function (e) {
            if (e.origin !== location.origin || !frame || e.source !== frame.contentWindow) return;
            if (e.data && e.data.type === 'tomok-3d-ready') { ready = true; push(false); }
        });
    });

    window.TomokCard = { collect: collect, apply: apply, card: card };
})();
