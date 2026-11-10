/*
 * 개발사업 스마트 법규 검토 - 편입 필지 지도
 * 검증이 끝난 필지(PNU)의 경계를 서버(/api/parcel_geometry)에서 받아 지도에 그린다.
 *  - 지목별 색, 마우스를 올리면 주소·지목·면적·지역지구, 확대하면 지번 표시
 *  - 표의 필지 줄을 누르면 지도에서 그 필지가 강조되고 그 위치로 이동, 지도의 필지를 누르면 표의 줄이 강조됨
 *  - 배경: 지도 / 위성, 지적도(주변 필지 경계) 켜고 끄기
 * 표(#parcel-container)를 지켜보다가 줄이 추가·삭제·검증되면 알아서 다시 그린다(script.js를 건드리지 않는다).
 */
(function () {
    'use strict';
    var $ = function (id) { return document.getElementById(id); };
    var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); };
    var KEY = atob('RDNDMEEyNTktQjQ1QS0zQ0U2LTg0MUQtNjJFRkIxMDNEM0NC');
    var MAX_PNUS = 80;

    // 지목 묶음 -> 색(테두리), 이름
    var GROUPS = [
        { id: 'farm', name: '농지(전·답·과수원)', color: '#ca8a04', jimok: ['전', '답', '과수원'] },
        { id: 'forest', name: '임야', color: '#15803d', jimok: ['임야'] },
        { id: 'site', name: '대지·공장·학교 등', color: '#ea580c', jimok: ['대', '공장용지', '학교용지', '주차장', '주유소용지', '창고용지', '종교용지', '사적지', '묘지', '광천지', '염전'] },
        { id: 'road', name: '도로·철도', color: '#475569', jimok: ['도로', '철도용지'] },
        { id: 'water', name: '하천·구거·유지', color: '#0284c7', jimok: ['하천', '구거', '유지', '양어장', '수도용지'] },
        { id: 'etc', name: '기타(잡종지·체육·공원 등)', color: '#7c3aed', jimok: ['잡종지', '체육용지', '공원', '제방', '목장용지', '유원지'] }
    ];
    var UNKNOWN = { id: 'unknown', name: '지목 확인 전', color: '#2563eb' };

    function groupOf(jimok) {
        var j = String(jimok || '').trim();
        if (!j) return UNKNOWN;
        for (var i = 0; i < GROUPS.length; i++) {
            for (var k = 0; k < GROUPS[i].jimok.length; k++) { if (j === GROUPS[i].jimok[k] || j.indexOf(GROUPS[i].jimok[k]) === 0) return GROUPS[i]; }
        }
        return UNKNOWN;
    }

    var map = null, baseLayers = {}, cadastral = null, geoLayer = null;
    var geomCache = {};              // pnu -> Feature | null(지적도에 없음)
    var errored = {};                // pnu -> 오류 문장(다시 시도할 수 있게 캐시하지 않는다)
    var layersByPnu = {};            // pnu -> L.geoJSON 레이어
    var shownKey = '';               // 지금 그려진 필지 묶음(바뀌면 전체 보기로 맞춤)
    var selectedPnu = null;
    var busy = false, pending = false;

    function rowsVerified() {
        var out = [];
        document.querySelectorAll('#parcel-container .parcel-row').forEach(function (row) {
            var pnu = row.dataset.pnu;
            if (row.dataset.verified === 'true' && pnu && /^\d{19}$/.test(pnu)) out.push(row);
        });
        return out;
    }

    /** 조회 오류가 난 필지의 지목은 기본값(추측)이라 믿지 않는다. */
    function jimokOf(row) { return row && row.dataset.zoningError !== '1' ? (row.dataset.jimok || '') : ''; }

    function rowsOf(pnu) {
        return Array.prototype.filter.call(document.querySelectorAll('#parcel-container .parcel-row'), function (r) { return r.dataset.pnu === pnu; });
    }

    // ------------------------------------------------------------ 지도 만들기
    function ensureMap() {
        if (map) return true;
        if (typeof L === 'undefined') {
            $('parcel-map').innerHTML = '<div style="padding:1rem; color:#991b1b;">지도 라이브러리를 불러오지 못했습니다. 인터넷 연결을 확인하고 새로고침해 주세요.</div>';
            return false;
        }
        map = L.map('parcel-map', { zoomControl: true, attributionControl: true, minZoom: 6, maxZoom: 19 }).setView([34.84, 127.89], 12);
        var wmts = function (layer, ext) { return L.tileLayer('https://api.vworld.kr/req/wmts/1.0.0/' + KEY + '/' + layer + '/{z}/{y}/{x}.' + ext, { maxZoom: 19, maxNativeZoom: 18, attribution: '© VWorld(국토교통부)' }); };
        baseLayers.map = wmts('Base', 'png');
        baseLayers.sat = L.layerGroup([wmts('Satellite', 'jpeg'), wmts('Hybrid', 'png')]);
        baseLayers.map.addTo(map);
        cadastral = L.tileLayer.wms('https://api.vworld.kr/req/wms', {
            layers: 'lp_pa_cbnd_bubun,lp_pa_cbnd_bonbun', styles: 'lp_pa_cbnd_bubun,lp_pa_cbnd_bonbun', format: 'image/png', transparent: true, version: '1.3.0',
            key: KEY, domain: location.hostname, maxZoom: 19, opacity: 0.9
        });
        geoLayer = L.layerGroup().addTo(map);
        var c = map.getContainer();
        var zoomClass = function () { c.classList.toggle('pm-zoomed', map.getZoom() >= 18); };
        map.on('zoomend', zoomClass); zoomClass();
        return true;
    }

    function setBase(kind) {
        if (!map) return;
        var cur = kind === 'sat' ? 'sat' : 'map', other = cur === 'sat' ? 'map' : 'sat';
        if (map.hasLayer(baseLayers[other])) map.removeLayer(baseLayers[other]);
        if (!map.hasLayer(baseLayers[cur])) { baseLayers[cur].addTo(map); }
        if (geoLayer) geoLayer.bringToFront && geoLayer.bringToFront();
        ['pm-base-map', 'pm-base-sat'].forEach(function (id) { var b = $(id); if (b) b.classList.toggle('pm-on', id === 'pm-base-' + cur); });
    }

    // ------------------------------------------------------------ 필지 그리기
    function styleOf(row, selected) {
        var g = groupOf(jimokOf(row));
        return selected
            ? { color: '#dc2626', weight: 4, fillColor: g.color, fillOpacity: 0.55, opacity: 1 }
            : { color: g.color, weight: 2, fillColor: g.color, fillOpacity: 0.32, opacity: 0.95 };
    }

    function tooltipHtml(feat, row) {
        var p = feat.properties || {};
        var area = row && row.dataset.actualArea ? Number(String(row.dataset.actualArea).replace(/,/g, '')) : NaN;
        var zon = row && row.dataset.zoning ? String(row.dataset.zoning) : '';
        if (zon.length > 70) zon = zon.slice(0, 70) + '…';
        return '<b>' + esc(p.addr || (row && row.dataset.fullAddr) || '') + '</b><br>'
            + esc(jimokOf(row) || '지목 미확인') + (isNaN(area) ? '' : ' · ' + area.toLocaleString() + '㎡')
            + (zon ? '<br><span style="color:#475569;">' + esc(zon) + '</span>' : '');
    }

    function drawFeature(pnu, feat, row) {
        if (layersByPnu[pnu]) { geoLayer.removeLayer(layersByPnu[pnu]); delete layersByPnu[pnu]; }
        var lyr = L.geoJSON(feat, { style: function () { return styleOf(row, pnu === selectedPnu); } });
        lyr.eachLayer(function (poly) {
            poly.bindTooltip(tooltipHtml(feat, row), { sticky: true, direction: 'top', className: 'pm-tip' });
            poly.on('click', function () { select(pnu, { fromMap: true }); });
        });
        // 확대하면 보이는 지번 이름표
        var jb = (feat.properties && feat.properties.jibun) || '';
        if (jb) {
            var c = lyr.getBounds().getCenter();
            L.marker(c, { interactive: false, icon: L.divIcon({ className: 'pm-label', html: '<span>' + esc(jb) + '</span>', iconSize: [0, 0] }) }).addTo(lyr);
        }
        lyr.addTo(geoLayer);
        layersByPnu[pnu] = lyr;
    }

    function restyle() {
        Object.keys(layersByPnu).forEach(function (pnu) {
            var rows = rowsOf(pnu), row = rows[0];
            layersByPnu[pnu].setStyle(function () { return styleOf(row, pnu === selectedPnu); });
            if (pnu === selectedPnu) layersByPnu[pnu].eachLayer(function (l) { if (l.bringToFront) l.bringToFront(); });
        });
        document.querySelectorAll('#parcel-container .parcel-row').forEach(function (r) { r.classList.toggle('pm-selected', !!selectedPnu && r.dataset.pnu === selectedPnu); });
    }

    function select(pnu, opt) {
        opt = opt || {};
        selectedPnu = pnu || null;
        restyle();
        if (!pnu) return;
        var lyr = layersByPnu[pnu];
        if (lyr && map) {
            if (opt.fromMap) {
                var r = rowsOf(pnu)[0];
                if (r && r.scrollIntoView) r.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            } else {
                map.fitBounds(lyr.getBounds(), { maxZoom: 19, padding: [50, 50] });
                if ($('parcel-map-panel') && $('parcel-map-panel').scrollIntoView) $('parcel-map-panel').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }
        } else if (!opt.fromMap) {
            note('이 필지는 지도에서 경계를 찾지 못해 표시할 수 없습니다.', 'warn');
        }
    }

    function fitAll() {
        var b = null;
        Object.keys(layersByPnu).forEach(function (pnu) { var bb = layersByPnu[pnu].getBounds(); if (bb && bb.isValid()) b = b ? b.extend(bb) : L.latLngBounds(bb.getSouthWest(), bb.getNorthEast()); });
        if (b && map) map.fitBounds(b, { maxZoom: 18, padding: [40, 40] });
    }

    function legend(rows) {
        var seen = {}, html = '';
        rows.forEach(function (row) {
            if (!layersByPnu[row.dataset.pnu]) return;
            var g = groupOf(jimokOf(row));
            if (seen[g.id]) return;
            seen[g.id] = 1;
            html += '<span style="display:inline-flex; align-items:center; gap:0.3rem; margin-right:0.9rem;"><i style="width:14px; height:14px; border:2px solid ' + g.color + '; background:' + g.color + '55; display:inline-block; border-radius:3px;"></i>' + esc(g.name) + '</span>';
        });
        $('pm-legend').innerHTML = html;
    }

    function note(msg, kind) {
        var el = $('pm-note');
        if (!el) return;
        var color = kind === 'error' ? '#991b1b' : (kind === 'warn' ? '#92400e' : '#475569');
        el.innerHTML = msg ? '<div style="color:' + color + '; font-size:0.82rem; line-height:1.5;">' + msg + '</div>' : '';
    }

    // ------------------------------------------------------------ 데이터 가져와 갱신
    async function fetchGeoms(pnus) {
        for (var i = 0; i < pnus.length; i += MAX_PNUS) {
            var chunk = pnus.slice(i, i + MAX_PNUS);
            var r = await fetch('/api/parcel_geometry?pnu=' + encodeURIComponent(chunk.join(',')));
            var d = await r.json().catch(function () { return {}; });
            if (!r.ok || !d.success) throw new Error(d.message || ('서버 오류(' + r.status + ')'));
            d.features.forEach(function (f) { geomCache[f.properties.pnu] = f; delete errored[f.properties.pnu]; });
            (d.missing || []).forEach(function (p) { geomCache[p] = null; });
            (d.errors || []).forEach(function (e) { errored[e.pnu] = e.message; });
        }
    }

    async function refresh() {
        if (busy) { pending = true; return; }
        busy = true;
        try {
            var rows = rowsVerified();
            var panel = $('parcel-map-panel');
            if (!rows.length) {
                panel.style.display = 'none';
                if (geoLayer) { geoLayer.clearLayers(); layersByPnu = {}; }
                shownKey = ''; selectedPnu = null;
                return;
            }
            panel.style.display = 'block';
            if (!ensureMap()) return;
            map.invalidateSize();
            var byPnu = {};
            rows.forEach(function (r) { if (!byPnu[r.dataset.pnu]) byPnu[r.dataset.pnu] = r; });
            var pnus = Object.keys(byPnu);
            var need = pnus.filter(function (p) { return !(p in geomCache); });
            if (need.length) {
                note('필지 경계를 불러오는 중입니다...', 'info');
                try { await fetchGeoms(need); }
                catch (e) { note('지도 데이터를 불러오지 못했습니다: ' + esc(e.message) + ' <a href="#" id="pm-retry">다시 시도</a>', 'error'); bindRetry(); }
            }
            // 지워진 필지 정리, 새 필지 그리기(지목·정보가 바뀌었을 수 있으니 매번 다시 그린다)
            Object.keys(layersByPnu).forEach(function (p) { if (!byPnu[p]) { geoLayer.removeLayer(layersByPnu[p]); delete layersByPnu[p]; } });
            var missing = [], errs = [];
            pnus.forEach(function (p) {
                var f = geomCache[p];
                if (f) drawFeature(p, f, byPnu[p]);
                else if (p in errored) errs.push(p);
                else if (p in geomCache) missing.push(p);
            });
            if (selectedPnu && !byPnu[selectedPnu]) selectedPnu = null;
            restyle();
            legend(rows);
            var key = pnus.slice().sort().join(',');
            if (key !== shownKey) { shownKey = key; fitAll(); }
            $('pm-count').textContent = '(' + Object.keys(layersByPnu).length + '/' + pnus.length + '개 표시)';
            var msgs = [];
            if (missing.length) msgs.push('지적도에서 경계를 찾지 못한 필지 ' + missing.length + '개: ' + esc(missing.map(function (p) { return (byPnu[p].dataset.fullAddr || p); }).slice(0, 5).join(', ')) + (missing.length > 5 ? ' 외' : '') + ' (지번이 새로 분할·합병됐거나 지적도에 아직 없는 필지일 수 있습니다)');
            if (errs.length) msgs.push('경계를 불러오지 못한 필지 ' + errs.length + '개(' + esc(errored[errs[0]]) + '). <a href="#" id="pm-retry">다시 시도</a>');
            note(msgs.join('<br>'), msgs.length ? 'warn' : '');
            bindRetry();
        } finally {
            busy = false;
            if (pending) { pending = false; setTimeout(refresh, 50); }
        }
    }

    function bindRetry() {
        var a = $('pm-retry');
        if (a) a.addEventListener('click', function (e) { e.preventDefault(); Object.keys(errored).forEach(function (p) { delete geomCache[p]; delete errored[p]; }); refresh(); });
    }

    var timer = null;
    function schedule() { clearTimeout(timer); timer = setTimeout(refresh, 350); }

    function init() {
        var container = $('parcel-container');
        if (!container || !$('parcel-map-panel')) return;
        if (window.MutationObserver) {
            new MutationObserver(schedule).observe(container, { childList: true, subtree: true, attributes: true, attributeFilter: ['data-verified', 'data-pnu', 'data-jimok', 'data-zoning-error'] });
        }
        // 표의 필지 줄을 누르거나 그 안의 칸에 커서를 두면 지도에서 그 필지를 강조한다
        var pick = function (e) {
            var row = e.target.closest && e.target.closest('.parcel-row');
            if (!row || e.target.closest('.remove-parcel-btn')) return;
            if (row.dataset.verified === 'true' && row.dataset.pnu) select(row.dataset.pnu);
        };
        container.addEventListener('click', pick);
        container.addEventListener('focusin', pick);
        $('pm-base-map').addEventListener('click', function () { setBase('map'); });
        $('pm-base-sat').addEventListener('click', function () { setBase('sat'); });
        $('pm-cadastral').addEventListener('change', function () {
            if (!map) return;
            if (this.checked) cadastral.addTo(map); else map.removeLayer(cadastral);
        });
        $('pm-fit').addEventListener('click', function () { select(null); fitAll(); });
        setBase('map');
        schedule();
    }

    window.ParcelMap = { refresh: refresh, select: select, groupOf: groupOf };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
