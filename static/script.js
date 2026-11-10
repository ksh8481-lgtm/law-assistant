document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('project-form');
    const analyzeBtn = document.getElementById('analyze-btn');
    const btnText = document.getElementById('btn-text');
    const spinner = document.getElementById('spinner');

    
    // Parcel dynamic fields
    const addParcelBtn = document.getElementById('add-parcel-btn');
    const parcelContainer = document.getElementById('parcel-container');
    const totalAreaSpan = document.getElementById('total-area');
    
    // Excel bulk upload
    const excelUploadInput = document.getElementById('excel-upload');
    const uploadExcelBtn = document.getElementById('upload-excel-btn');
    const drawingUploadInput = document.getElementById('drawing-upload');
    const uploadDrawingBtn = document.getElementById('upload-drawing-btn');
    const bulkVerifyBtn = document.getElementById('bulk-verify-btn');
    
    let totalVerifiedArea = 0;

    const downloadTemplateBtn = document.getElementById('download-template-btn');
    if (downloadTemplateBtn) {
        downloadTemplateBtn.addEventListener('click', () => {
            const ws_data = [
                ['주소', '면적(㎡)'],
                ['경남 남해군 상주면 양아리 799-2', ''],
                ['서울시 강남구 역삼동 123-4', '500']
            ];
            const ws = XLSX.utils.aoa_to_sheet(ws_data);
            ws['!cols'] = [{ wpx: 300 }, { wpx: 100 }];
            const wb = XLSX.utils.book_new();
            XLSX.utils.book_append_sheet(wb, ws, "편입필지");
            XLSX.writeFile(wb, "편입필지_입력양식.xlsx");
        });
    }

    if (addParcelBtn) {
        addParcelBtn.addEventListener('click', () => addParcelRow());
    }

    const clearParcelsBtn = document.getElementById('clear-parcels-btn');
    if (clearParcelsBtn) {
        clearParcelsBtn.addEventListener('click', () => {
            if (confirm('모든 편입 필지 목록을 삭제하시겠습니까?')) {
                document.getElementById('parcel-container').innerHTML = '';
                totalVerifiedArea = 0;
                updateTotalArea();
                bulkVerifyBtn.style.display = 'none';
            }
        });
    }

    if (uploadExcelBtn) {
        uploadExcelBtn.addEventListener('click', () => {
            excelUploadInput.click();
        });
    }

    if (excelUploadInput) {
        excelUploadInput.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (!file) return;

            const reader = new FileReader();
            reader.onload = function(evt) {
                const data = new Uint8Array(evt.target.result);
                const workbook = XLSX.read(data, {type: 'array'});
                const firstSheet = workbook.Sheets[workbook.SheetNames[0]];
                const jsonData = XLSX.utils.sheet_to_json(firstSheet);
                
                let addedCount = 0;
                jsonData.forEach(row => {
                    const address = row['주소'];
                    const area = row['면적(㎡)'] || row['면적'] || '';
                    if (address) {
                        addParcelRow(address, area);
                        addedCount++;
                    }
                });
                
                if (addedCount > 0) {
                    say(`총 ${addedCount}개의 주소를 불러왔습니다. [일괄 검증]을 눌러 지목·지역지구를 조회하세요.`, 'ok');
                    bulkVerifyBtn.style.display = 'block'; // 일괄 검증 버튼 표시
                } else {
                    say('엑셀에서 "주소" 열을 찾을 수 없거나 데이터가 없습니다. 첫 줄에 "주소"라고 적혀 있어야 합니다. [엑셀 양식]을 내려받아 쓰시면 됩니다.', 'error');
                }
            };
            reader.readAsArrayBuffer(file);
            excelUploadInput.value = ''; // Reset
        });
    }

    if (uploadDrawingBtn) {
        uploadDrawingBtn.addEventListener('click', () => {
            drawingUploadInput.click();
        });
    }

    if (drawingUploadInput) {
        drawingUploadInput.addEventListener('change', async (e) => {
            const file = e.target.files[0];
            if (!file) return;
            
            const originalText = uploadDrawingBtn.textContent;
            uploadDrawingBtn.textContent = '🔄 도면 AI 분석 중... (약 5~10초 소요)';
            uploadDrawingBtn.disabled = true;
            
            const formData = new FormData();
            formData.append('file', file);
            
            try {
                const response = await fetch('/api/extract_parcel_from_drawing', {
                    method: 'POST',
                    body: formData
                });
                
                if (!response.ok) {
                    const err = await response.text();
                    throw new Error(err);
                }
                
                const data = await response.json();
                if (!data.success) {
                    throw new Error(data.message || '추출 실패');
                }
                
                const extractedList = data.data;
                let addedCount = 0;
                
                extractedList.forEach(item => {
                    if (item.address) {
                        addParcelRow(item.address, item.area || '');
                        addedCount++;
                    }
                });
                
                if (addedCount > 0) {
                    say(`AI가 도면에서 편입 지번 ${addedCount}개를 추출했습니다. 도면 글자를 잘못 읽었을 수 있으니 주소를 확인한 뒤 [일괄 검증]을 눌러 주세요.`, 'ok');
                    bulkVerifyBtn.style.display = 'block';
                } else {
                    say('도면에서 식별 가능한 주소·지번을 찾지 못했습니다. 해상도가 더 높은 파일을 쓰거나 [주소 붙여넣기]로 직접 입력해 주세요.', 'error');
                }
                
            } catch (error) {
                console.error(error);
                say('도면 AI 분석 중 오류가 발생했습니다: ' + error.message + ' (잠시 후 다시 시도하거나 [주소 붙여넣기]로 직접 입력해 주세요.)', 'error');
            } finally {
                uploadDrawingBtn.textContent = originalText;
                uploadDrawingBtn.disabled = false;
                drawingUploadInput.value = ''; // Reset
            }
        });
    }

    // 화면 아래 메시지·진행 표시는 law_review_input.js(LRInput)가 맡는다. 없으면 alert로 대신한다.
    const ui = () => window.LRInput || null;
    const say = (msg, kind) => { const u = ui(); if (u) u.notify(msg, kind); else alert(msg); };

    /** 검증이 끝난 필지(분석에 넘길 값)를 모은다. */
    function collectParcels() {
        const parcels = [];
        document.querySelectorAll('.parcel-row').forEach(row => {
            if (row.dataset.verified !== 'true') return;
            const isExcel = !!row.dataset.excelAddress;
            let address = row.dataset.fullAddr;
            if (!isExcel) {
                const sanStr = row.querySelector('.p-san').value === '2' ? '산 ' : '';
                const bonbeon = row.querySelector('.p-bonbeon').value;
                const bubeon = row.querySelector('.p-bubeon').value || '0';
                const jibun = bubeon === '0' ? bonbeon : `${bonbeon}-${bubeon}`;
                address = `${address} ${sanStr}${jibun}`;
            }
            parcels.push({ pnu: row.dataset.pnu, area: row.dataset.actualArea, zoning: row.dataset.zoning, jimok: row.dataset.jimok || '', address: address });
        });
        return parcels;
    }

    /** 검증된 필지를 다시 검증할 수 있게 되돌린다(면적 합계에서 뺀다). */
    function unverifyRow(row) {
        if (row.dataset.verified === 'true') {
            const area = parseFloat(String(row.dataset.actualArea || '0').replace(/,/g, '')) || 0;
            totalVerifiedArea -= area;
            updateTotalArea();
        }
        row.dataset.verified = '';
        row.dataset.zoningError = '';
        const badge = row.querySelector('.status-badge');
        if (badge) { badge.textContent = '대기중'; badge.className = 'status-badge'; badge.style.color = '#94a3b8'; }
    }

    function resetParcels() {
        parcelContainer.innerHTML = '';
        totalVerifiedArea = 0;
        updateTotalArea();
        checkBulkVerifyButton();
    }

    /** 저장된 필지(주소·면적·지목·지역지구)를 조회 없이 검증 완료 상태로 복원한다. */
    function restoreParcel(p) {
        addParcelRow(p.address, p.area || '');
        const row = parcelContainer.lastElementChild;
        row.dataset.verified = 'true';
        row.dataset.actualArea = p.area || '';
        row.dataset.pnu = p.pnu || '';
        row.dataset.zoning = p.zoning || '';
        row.dataset.jimok = p.jimok || '';
        row.dataset.zoningError = '';
        row.dataset.fullAddr = p.address;
        const badge = row.querySelector('.status-badge');
        if (badge) { badge.textContent = '검증 완료'; badge.className = 'status-badge verified-tag'; badge.style.color = ''; }
        const cell = row.querySelector('.zoning-result');
        if (cell) cell.innerHTML = `<strong>지목:</strong> ${p.jimok || '-'}<br><strong>지역지구:</strong> ${p.zoning || '-'} <span style="color:#64748b;">(저장된 값)</span>`;
        totalVerifiedArea += parseFloat(String(p.area || '0').replace(/,/g, '')) || 0;
        updateTotalArea();
        return row;
    }

    function addParcelRow(initAddr = null, initArea = '') {
        const row = document.createElement('tr');
        row.className = 'parcel-row';
        row.dataset.bcode = ''; 
        if (initAddr) row.dataset.excelAddress = initAddr;
        const isExcel = !!initAddr;
        
        row.innerHTML = `
            <td style="text-align: center;">
                <span class="status-badge" style="color: #94a3b8; font-size: 0.85rem; display: inline-block;">대기중</span>
            </td>
            <td>
                <div style="display: flex; gap: 0.25rem;">
                    ${isExcel ? '' : '<button type="button" class="search-addr-btn verify-btn" style="width: auto; padding: 0.4rem; white-space: nowrap;">🔍</button>'}
                    <input type="text" class="p-addr parcel-input-sm" placeholder="예: 상주면 양아리" value="${initAddr || ''}" readonly>
                </div>
            </td>
            <td>
                ${isExcel ? '<span style="color: #94a3b8; font-size: 0.8rem;">엑셀에서 자동 추출됨</span>' : `
                <div style="display: flex; gap: 0.25rem;">
                    <select class="p-san parcel-input-sm" style="width: 60px; padding: 0.4rem;"><option value="1">일반</option><option value="2">산</option></select>
                    <input type="text" class="p-bonbeon parcel-input-sm" placeholder="본번" style="width: 50px;">
                    <span style="color: #94a3b8;">-</span>
                    <input type="text" class="p-bubeon parcel-input-sm" placeholder="부번" style="width: 50px;">
                </div>
                `}
            </td>
            <td>
                <input type="number" class="p-area parcel-input-sm" placeholder="자동" value="${initArea || ''}" ${isExcel && !initArea ? 'readonly' : ''}>
            </td>
            <td class="zoning-result" style="font-size: 0.8rem; color: #64748b; word-break: keep-all;">
                -
            </td>
            <td style="text-align: center;">
                <button type="button" class="remove-parcel-btn">❌</button>
            </td>
        `;

        row.querySelector('.remove-parcel-btn').addEventListener('click', function() {
            if (row.dataset.verified === 'true') {
                const areaStr = String(row.dataset.actualArea || '0').replace(/,/g, '');
                const area = parseFloat(areaStr || 0);
                totalVerifiedArea -= area;
                updateTotalArea();
            }
            row.remove();
            checkBulkVerifyButton();
        });

        if (!isExcel) {
            const searchBtn = row.querySelector('.search-addr-btn');
            const addrInput = row.querySelector('.p-addr');

            searchBtn.addEventListener('click', () => {
                new daum.Postcode({
                    oncomplete: function(data) {
                        const cleanAddr = `${data.sido} ${data.sigungu} ${data.bname}`.trim();
                        addrInput.value = cleanAddr;
                        if (data.bcode) {
                            row.dataset.bcode = data.bcode;
                        }
                    }
                }).open();
            });
        }

        parcelContainer.appendChild(row);
        checkBulkVerifyButton();
    }

    function checkBulkVerifyButton() {
        const rows = document.querySelectorAll('.parcel-row');
        if (rows.length > 0) {
            bulkVerifyBtn.style.display = 'block';
        } else {
            bulkVerifyBtn.style.display = 'none';
        }
    }

    if (bulkVerifyBtn) {
        bulkVerifyBtn.addEventListener('click', async () => {
            const rows = document.querySelectorAll('.parcel-row');
            let pendingRows = [];
            rows.forEach(row => {
                if (row.dataset.verified !== 'true') {
                    pendingRows.push(row);
                }
            });

            if (pendingRows.length === 0) {
                say('모든 필지가 이미 검증되었습니다.', 'info');
                return;
            }

            bulkVerifyBtn.disabled = true;
            const originalText = bulkVerifyBtn.textContent;
            bulkVerifyBtn.textContent = '일괄 검증 진행 중... (창을 닫지 마세요)';

            for (let i = 0; i < pendingRows.length; i++) {
                await verifyRow(pendingRows[i]);
            }

            bulkVerifyBtn.textContent = originalText;
            bulkVerifyBtn.disabled = false;
            if (ui()) ui().refreshParcelSummary(true); else alert('일괄 검증이 완료되었습니다!');
        });
    }

        function fetchJSONP(url) {
        return new Promise((resolve, reject) => {
            const callbackName = 'vworld_cb_' + Math.round(1000000 * Math.random());
            window[callbackName] = function(data) {
                delete window[callbackName];
                document.body.removeChild(script);
                resolve(data);
            };
            const script = document.createElement('script');
            script.src = url + (url.includes('?') ? '&' : '?') + 'format=json&callback=' + callbackName;
            script.onerror = () => {
                delete window[callbackName];
                document.body.removeChild(script);
                reject(new Error("JSONP request failed (Network error)"));
            };
            document.body.appendChild(script);
        });
    }

    async function verifyRow(row) {
        const statusBadge = row.querySelector('.status-badge');
        if (statusBadge) {
            statusBadge.textContent = '검증 중...';
            statusBadge.style.color = '#3b82f6';
        }

        const isExcel = !!row.dataset.excelAddress;
        let reqData = {};

        if (isExcel) {
            reqData = {
                address: row.dataset.excelAddress,
                area: row.querySelector('.p-area').value || ''
            };
        } else {
            const bcode = row.dataset.bcode;
            if (!bcode || bcode.length !== 10) {
                if (statusBadge) {
                    statusBadge.textContent = '검증 실패';
                    statusBadge.className = 'status-badge error-tag';
                    statusBadge.style.color = '';
                }
                const zoningCell = row.querySelector('.zoning-result');
                if (zoningCell) zoningCell.innerHTML = `<span style="color: #ef4444;">주소 검색을 먼저 완료해 주세요.</span>`;
                return;
            }
            if (!row.querySelector('.p-bonbeon').value) {
                if (statusBadge) {
                    statusBadge.textContent = '검증 실패';
                    statusBadge.className = 'status-badge error-tag';
                    statusBadge.style.color = '';
                }
                const zoningCell = row.querySelector('.zoning-result');
                if (zoningCell) zoningCell.innerHTML = `<span style="color: #ef4444;">본번을 입력해 주세요.</span>`;
                return;
            }
            reqData = {
                bcode: bcode,
                san: row.querySelector('.p-san').value,
                bonbeon: row.querySelector('.p-bonbeon').value,
                bubeon: row.querySelector('.p-bubeon').value || '0',
                area: row.querySelector('.p-area').value
            };
        }

        try {
            const VWORLD_KEY = atob("RDNDMEEyNTktQjQ1QS0zQ0U2LTg0MUQtNjJFRkIxMDNEM0NC");
            let pnu = '';
            
            if (isExcel) {
                const full_address = reqData.address.trim();
                const url_search = `https://api.vworld.kr/req/search?service=search&request=search&version=2.0&size=10&page=1&query=${encodeURIComponent(full_address)}&type=address&category=parcel&key=${VWORLD_KEY}&domain=http://127.0.0.1`;
                const res_search = await fetchJSONP(url_search);
                const items = res_search?.response?.result?.items || [];
                
                if (items.length === 0) {
                    throw new Error("주소에서 고유번호(PNU)를 찾을 수 없습니다.");
                }
                
                const input_parts = full_address.split(/\s+/);
                for (const item of items) {
                    const api_addr = item.address?.parcel || '';
                    if (!api_addr) continue;
                    
                    const api_parts = api_addr.split(/\s+/);
                    if (input_parts[input_parts.length - 1] !== api_parts[api_parts.length - 1]) continue;
                    
                    let is_match = true;
                    for (let i = 0; i < input_parts.length - 1; i++) {
                        let p = input_parts[i];
                        if (!api_addr.includes(p)) {
                            if (p === '경북' && api_addr.includes('경상북도')) continue;
                            if (p === '경남' && api_addr.includes('경상남도')) continue;
                            if (p === '전북' && api_addr.includes('전라북도')) continue;
                            if (p === '전남' && api_addr.includes('전라남도')) continue;
                            if (p === '충북' && api_addr.includes('충청북도')) continue;
                            if (p === '충남' && api_addr.includes('충청남도')) continue;
                            is_match = false;
                            break;
                        }
                    }
                    if (is_match) {
                        pnu = item.id;
                        break;
                    }
                }
                
                if (!pnu) {
                    throw new Error("주소에서 고유번호(PNU)를 찾을 수 없습니다.");
                }
            } else {
                pnu = reqData.bcode + (reqData.san === '1' ? '2' : '1') + reqData.bonbeon.padStart(4, '0') + reqData.bubeon.padStart(4, '0');
            }
            
            let apiArea = '';
            let jimok = reqData.san === '1' ? '대' : '임야';
            let apiDomainError = false;
            try {
                const url_char = `https://api.vworld.kr/ned/data/getLandCharacteristics?key=${VWORLD_KEY}&domain=http://127.0.0.1&pnu=${pnu}&numOfRows=50&pageNo=1`;
                const res_char = await fetchJSONP(url_char);
                const fields = res_char?.landCharacteristicss?.field || [];
                if (fields.length > 0) {
                    apiArea = fields[0].lndpclAr || '';
                    const jimok_code = fields[0].lndcgrCodeNm || '';
                    if (jimok_code) jimok = jimok_code;
                }
            } catch (e) { 
                console.error("토지특성정보 오류", e);
                apiDomainError = true;
            }
            
            // 면적 결정: 사용자가 입력/엑셀로 불러온 값이 있으면 그 값을 최우선으로 사용, 없으면 토지대장 면적 사용
            let actualArea = '';
            if (reqData.area && reqData.area.trim() !== '') {
                actualArea = reqData.area;
            } else {
                actualArea = apiArea;
            }
            
            let zoning_list = [];
            try {
                const url_zoning = `https://api.vworld.kr/ned/data/getLandUseAttr?key=${VWORLD_KEY}&domain=http://127.0.0.1&pnu=${pnu}&numOfRows=50&pageNo=1`;
                const res_zoning = await fetchJSONP(url_zoning);
                const fields = res_zoning?.landUses?.field || [];
                for (const field of fields) {
                    if (field.prposAreaDstrcCodeNm) {
                        zoning_list.push(field.prposAreaDstrcCodeNm);
                    }
                }
            } catch (e) { 
                apiDomainError = true;
                zoning_list.push("VWorld API 도메인 인증 오류 (국토부 사이트에 클라우드타입 주소를 추가해야 합니다)"); 
            }
            
            row.dataset.verified = 'true';
            row.dataset.actualArea = actualArea;
            row.dataset.pnu = pnu;
            row.dataset.zoning = zoning_list.join(', ');
            row.dataset.jimok = jimok;                              // 농지·산지 판단은 글자 포함 검사가 아니라 지목으로 한다
            row.dataset.zoningError = apiDomainError ? '1' : '';     // 지역지구 조회가 실패한 필지는 분석에 넘기지 않는다
            row.dataset.fullAddr = isExcel ? reqData.address : row.querySelector('.p-addr').value;
            
            if (statusBadge) {
                statusBadge.textContent = '검증 완료';
                statusBadge.className = 'status-badge verified-tag';
                statusBadge.style.color = '';
            }

            const areaInput = row.querySelector('.p-area');
            if (actualArea && areaInput) {
                areaInput.value = actualArea;
            }
            
            const zoningCell = row.querySelector('.zoning-result');
            if (zoningCell) {
                let zoningText = zoning_list.join(', ');
                if (apiDomainError) {
                    zoningText = `<span style="color: #ef4444; font-weight: bold;">[API 오류]</span> ${zoningText}`;
                }
                zoningCell.innerHTML = `<strong>지목:</strong> ${jimok}<br><strong>지역지구:</strong> ${zoningText}`;
            }

            const cleanArea = String(actualArea || '0').replace(/,/g, '');
            totalVerifiedArea += parseFloat(cleanArea || 0);
            updateTotalArea();
            
        } catch (error) {
            console.error("verify_parcel 오류:", error);
            if (statusBadge) {
                statusBadge.textContent = '검증 실패';
                statusBadge.className = 'status-badge error-tag';
                statusBadge.style.color = '';
            }
            const zoningCell = row.querySelector('.zoning-result');
            if (zoningCell) {
                zoningCell.innerHTML = `<span style="color: #ef4444;">${error.message || '알 수 없는 오류'}</span>`;
            }
        }
    }

    addParcelRow();

    const publicWaterInput = document.getElementById('publicWaterArea');
    if (publicWaterInput) {
        publicWaterInput.addEventListener('input', updateTotalArea);
    }

    function updateTotalArea() {
        const pubArea = parseFloat(publicWaterInput ? publicWaterInput.value : 0) || 0;
        const finalArea = totalVerifiedArea + pubArea;
        if (totalAreaSpan) {
            totalAreaSpan.textContent = finalArea.toLocaleString();
        }
    }

    /** 분석을 시작하고 끝날 때까지 실제 서버 진행 단계를 보여 준다. 실패하면 입력은 그대로 두고 원인과 대처를 알린다. */
    async function runAnalysis(requestData) {
        const u = ui();
        analyzeBtn.disabled = true;
        spinner.classList.remove('hidden');
        btnText.textContent = '법규 분석 및 법령 원문 대조 중... (약 3~4분)';
        const startedAt = Date.now();
        let stage = '분석 요청을 보내는 중';
        const tick = () => { if (u) u.showProgress(stage, Math.round((Date.now() - startedAt) / 1000)); };
        tick();
        const timer = setInterval(tick, 1000);
        try {
            const startResponse = await fetch('/api/analyze/start', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(requestData)
            });
            if (!startResponse.ok) {
                const errorText = await startResponse.text();
                let msg = errorText;
                try { msg = JSON.parse(errorText).error || JSON.parse(errorText).message || errorText; } catch (e) {}
                throw new Error(msg);
            }
            const jobId = (await startResponse.json()).job_id;

            // 3초 간격으로 확인(최대 8분 = 160회)
            const MAX_POLL_ATTEMPTS = 160;
            for (let attempt = 1; ; attempt++) {
                await new Promise(r => setTimeout(r, 3000));
                if (attempt > MAX_POLL_ATTEMPTS) throw new Error('응답 시간이 너무 오래 걸립니다(8분 초과). 서버가 지연 중일 수 있으니 잠시 후 다시 시도해 주세요.');
                const statusResponse = await fetch(`/api/analyze/status/${jobId}`);
                if (!statusResponse.ok) throw new Error(await statusResponse.text());
                const statusData = await statusResponse.json();
                if (statusData.stage) stage = statusData.stage;
                if (statusData.status === 'completed') {
                    const store = window.LawReviewStore;
                    const id = store ? store.save(requestData, statusData.result) : null;
                    sessionStorage.setItem('aiResult', JSON.stringify(statusData.result));
                    sessionStorage.setItem('projectData', JSON.stringify(requestData));
                    if (id) sessionStorage.setItem('reportId', id); else sessionStorage.removeItem('reportId');
                    const reportUrl = id ? '/report?rec=' + id : '/report';
                    const w = window.open(reportUrl, '_blank');
                    if (u) { u.showDone(reportUrl, !!w, !!id); u.refreshSaved(); u.clearDraft(); }
                    break;
                } else if (statusData.status === 'error') {
                    throw new Error(statusData.message || '알 수 없는 서버 오류');
                }
            }
        } catch (error) {
            console.error(error);
            if (u) u.showError(error.message, () => runAnalysis(requestData)); else alert('오류 발생: ' + error.message);
        } finally {
            clearInterval(timer);
            btnText.textContent = 'AI 기반 법규 및 지역지구 분석 시작';
            spinner.classList.add('hidden');
            analyzeBtn.disabled = false;
        }
    }

    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();

            // 지역지구 조회에 실패한 필지는 오류 문구가 지역지구로 분석에 들어가 결과가 틀어지므로 막는다
            const failedRows = Array.from(document.querySelectorAll('.parcel-row')).filter(row => row.dataset.verified === 'true' && row.dataset.zoningError === '1');
            if (failedRows.length > 0) {
                failedRows.forEach(r => { r.style.outline = '2px solid #ef4444'; });
                say(`지역지구 조회에 실패한 필지가 ${failedRows.length}개 있습니다(표에서 빨간 테두리). 오류 문구가 지역지구로 분석에 들어가 결과가 틀어지므로, 필지 아래 [실패·오류 필지만 다시 검증]을 누른 뒤 분석해 주세요.`, 'error');
                failedRows[0].scrollIntoView({ behavior: 'smooth', block: 'center' });
                return;
            }

            const parcels = collectParcels();
            const pubArea = parseFloat(publicWaterInput ? publicWaterInput.value : 0) || 0;
            if (parcels.length === 0 && pubArea <= 0) {
                const pending = document.querySelectorAll('.parcel-row').length;
                say(pending > 0
                    ? '입력한 필지가 아직 검증되지 않았습니다. 필지 아래 [일괄 검증]을 먼저 눌러 주세요.'
                    : '편입 필지 또는 공유수면 면적이 하나 이상 있어야 합니다. [주소 붙여넣기]나 [엑셀 불러오기]로 필지를 넣거나, 해상·하천 사업이면 공유수면 면적을 입력해 주세요.', 'error');
                return;
            }
            const budget = parseFloat(document.getElementById('budget').value);
            if (!(budget > 0)) { say('사업 재원(억 원)을 입력해 주세요.', 'error'); document.getElementById('budget').focus(); return; }
            if (!document.getElementById('description').value.trim()) {
                say('주요 사업 내용이 비어 있습니다. 규모·구조물·굴착 같은 제원을 적을수록 결과가 정확해집니다. 아래 [더 적으면 정확해지는 정보]를 눌러 줄을 추가할 수 있습니다.', 'error');
                document.getElementById('description').focus();
                return;
            }

            const projectTypeElement = document.querySelector('input[name="projectType"]:checked');
            const requestData = {
                projectName: document.getElementById('projectName').value,
                projectType: projectTypeElement ? projectTypeElement.value : '복합공사',
                budget: budget,
                budgetNational: parseFloat(document.getElementById('budgetNational').value) || 0,
                budgetProvincial: parseFloat(document.getElementById('budgetProvincial').value) || 0,
                budgetMunicipal: parseFloat(document.getElementById('budgetMunicipal').value) || 0,
                totalArea: totalVerifiedArea + pubArea,
                publicWaterArea: pubArea,
                description: document.getElementById('description').value,
                parcels: parcels
            };
            if (ui()) ui().clearMessages();
            await runAnalysis(requestData);
        });
    }

    // law_review_input.js가 쓰는 필지·합계 함수
    window.LRForm = { addParcelRow, verifyRow, unverifyRow, restoreParcel, resetParcels, collectParcels, checkBulkVerifyButton, updateTotalArea };
});
