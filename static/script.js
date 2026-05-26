document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('project-form');
    const analyzeBtn = document.getElementById('analyze-btn');
    const btnText = document.getElementById('btn-text');
    const spinner = document.getElementById('spinner');
    const resultSection = document.getElementById('result-section');
    
    // Parcel dynamic fields
    const addParcelBtn = document.getElementById('add-parcel-btn');
    const parcelContainer = document.getElementById('parcel-container');
    const totalAreaSpan = document.getElementById('total-area');
    
    // Excel bulk upload
    const excelUploadInput = document.getElementById('excel-upload');
    const uploadExcelBtn = document.getElementById('upload-excel-btn');
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

    addParcelBtn.addEventListener('click', () => addParcelRow());

    const clearParcelsBtn = document.getElementById('clear-parcels-btn');
    if (clearParcelsBtn) {
        clearParcelsBtn.addEventListener('click', () => {
            if (confirm('모든 편입 필지 목록을 삭제하시겠습니까?')) {
                document.getElementById('parcel-container').innerHTML = '';
                updateTotalArea();
            }
        });
    }

    uploadExcelBtn.addEventListener('click', () => {
        excelUploadInput.click();
    });

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
                alert(`총 ${addedCount}개의 주소를 성공적으로 불러왔습니다.`);
                bulkVerifyBtn.style.display = 'block'; // 일괄 검증 버튼 표시
            } else {
                alert('엑셀에서 "주소" 열을 찾을 수 없거나 데이터가 없습니다. (첫 줄에 "주소"라고 적혀 있어야 합니다)');
            }
        };
        reader.readAsArrayBuffer(file);
        excelUploadInput.value = ''; // Reset
    });

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
                <input type="number" class="p-area parcel-input-sm" placeholder="자동" value="${initArea || ''}" ${initArea ? 'readonly' : ''}>
            </td>
            <td class="zoning-result" style="font-size: 0.8rem; color: #64748b; word-break: keep-all;">
                -
            </td>
            <td style="text-align: center;">
                <button type="button" class="remove-parcel-btn">❌</button>
            </td>
        `;

        row.querySelector('.remove-parcel-btn').addEventListener('click', () => {
            row.remove();
            updateTotalArea();
        });

        if (!isExcel) {
            const searchBtn = row.querySelector('.search-addr-btn');
            searchBtn.addEventListener('click', () => {
                new daum.Postcode({
                    oncomplete: function(data) {
                        row.querySelector('.p-addr').value = data.address;
                        row.querySelector('.p-bonbeon').value = data.bunji || '';
                        row.querySelector('.p-bubeon').value = data.ho || '';
                        row.dataset.bcode = data.bcode || '';
                    }
                }).open();
            });
        }

        document.getElementById('parcel-container').appendChild(row);
        updateTotalArea();
    }ontentLoaded', () => {
    const form = document.getElementById('project-form');
    const analyzeBtn = document.getElementById('analyze-btn');
    const btnText = document.getElementById('btn-text');
    const spinner = document.getElementById('spinner');
    const resultSection = document.getElementById('result-section');
    
    // Parcel dynamic fields
    const addParcelBtn = document.getElementById('add-parcel-btn');
    const parcelContainer = document.getElementById('parcel-container');
    const totalAreaSpan = document.getElementById('total-area');
    
    // Excel bulk upload
    const excelUploadInput = document.getElementById('excel-upload');
    const uploadExcelBtn = document.getElementById('upload-excel-btn');
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

    addParcelBtn.addEventListener('click', () => addParcelRow());

    uploadExcelBtn.addEventListener('click', () => {
        excelUploadInput.click();
    });

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
                alert(`총 ${addedCount}개의 주소를 성공적으로 불러왔습니다.`);
                bulkVerifyBtn.style.display = 'block'; // 일괄 검증 버튼 표시
            } else {
                alert('엑셀에서 "주소" 열을 찾을 수 없거나 데이터가 없습니다. (첫 줄에 "주소"라고 적혀 있어야 합니다)');
            }
        };
        reader.readAsArrayBuffer(file);
        excelUploadInput.value = ''; // Reset
    });

    function addParcelRow(initAddr = null, initArea = '') {
        const row = document.createElement('div');
        row.className = 'parcel-row';
        row.dataset.bcode = ''; 
        
        if (initAddr) {
            row.dataset.excelAddress = initAddr;
        }

        // 엑셀로 불러온 경우 입력창을 막고 단순하게 표시
        const isExcel = !!initAddr;
        
        row.innerHTML = `
            <div class="parcel-part" style="flex: 2;">
                <label>주소</label>
                <div style="display: flex; gap: 0.5rem;">
                    ${isExcel ? '' : '<button type="button" class="search-addr-btn" style="white-space: nowrap;">🔍 검색</button>'}
                    <input type="text" class="p-addr" placeholder="예: 상주면 양아리" value="${initAddr || ''}" readonly>
                </div>
            </div>
            ${isExcel ? '' : `
            <div class="parcel-part">
                <label>산</label>
                <select class="p-san"><option value="1">일반</option><option value="2">산</option></select>
            </div>
            <div class="parcel-part">
                <label>본번</label>
                <input type="text" class="p-bonbeon">
            </div>
            <div class="parcel-part">
                <label>부번</label>
                <input type="text" class="p-bubeon">
            </div>
            `}
            <div class="parcel-part" style="flex: 0.5;">
                <label>면적(㎡)</label>
                <input type="number" class="p-area" placeholder="${isExcel ? '자동조회' : '예: 500'}" value="${initArea}" ${isExcel && !initArea ? 'readonly' : ''}>
            </div>
            
            <div class="parcel-actions">
                <span class="verified-tag">✓ 검증완료</span>
                <button type="button" class="verify-btn" style="${isExcel ? 'display: none;' : ''}">개별 검증</button>
                <button type="button" class="remove-parcel-btn">삭제</button>
            </div>
            <div class="parcel-result" style="width: 100%; margin-top: 0.5rem;"></div>
        `;

        row.querySelector('.remove-parcel-btn').addEventListener('click', function() {
            if (row.dataset.verified === 'true') {
                const area = parseFloat(row.dataset.actualArea || 0);
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

            const verifyBtn = row.querySelector('.verify-btn');
            verifyBtn.addEventListener('click', () => verifyRow(row));
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

    bulkVerifyBtn.addEventListener('click', async () => {
        const rows = document.querySelectorAll('.parcel-row');
        let pendingRows = [];
        rows.forEach(row => {
            if (row.dataset.verified !== 'true') {
                pendingRows.push(row);
            }
        });

        if (pendingRows.length === 0) {
            alert("모든 필지가 이미 검증되었습니다.");
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
        alert("일괄 검증이 완료되었습니다!");
    });

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
        const resultDiv = row.querySelector('.parcel-result');
        const verifyBtn = row.querySelector('.verify-btn');
        if (verifyBtn) {
            verifyBtn.textContent = '조회 중...';
            verifyBtn.disabled = true;
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
                resultDiv.innerHTML = `<strong style="color: #dc2626;">[검증 실패]</strong> 주소 검색을 먼저 완료해 주세요.`;
                resultDiv.classList.add('show');
                if (verifyBtn) { verifyBtn.textContent = '개별 검증'; verifyBtn.disabled = false; }
                return;
            }
            if (!row.querySelector('.p-bonbeon').value) {
                resultDiv.innerHTML = `<strong style="color: #dc2626;">[검증 실패]</strong> 본번을 입력해 주세요.`;
                resultDiv.classList.add('show');
                if (verifyBtn) { verifyBtn.textContent = '개별 검증'; verifyBtn.disabled = false; }
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

        resultDiv.innerHTML = `<span style="color: #2563eb;">로딩 중...</span>`;
        resultDiv.classList.add('show');

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
            
            // 토지특성정보 조회
            let actualArea = '';
            let jimok = reqData.san === '1' ? '대' : '임야';
            let apiDomainError = false;
            try {
                const url_char = `https://api.vworld.kr/ned/data/getLandCharacteristics?key=${VWORLD_KEY}&domain=http://127.0.0.1&pnu=${pnu}&numOfRows=50&pageNo=1`;
                const res_char = await fetchJSONP(url_char);
                const fields = res_char?.landCharacteristicss?.field || [];
                if (fields.length > 0) {
                    actualArea = fields[0].lndpclAr || '';
                    const jimok_code = fields[0].lndcgrCodeNm || '';
                    if (jimok_code) jimok = jimok_code;
                }
            } catch (e) { 
                console.error("토지특성정보 오류", e);
                apiDomainError = true;
            }
            
            if (!actualArea && reqData.area) {
                actualArea = reqData.area;
            }
            
            // 토지이용계획 조회
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
            row.dataset.pnu = pnu;
            row.dataset.actualArea = actualArea;
            row.dataset.zoning = zoning_list.join(', ');
            row.dataset.fullAddr = isExcel ? full_address : (row.querySelector('.p-addr').value || '');
            
            // UI 업데이트
            const statusBadge = row.querySelector('.status-badge');
            statusBadge.textContent = '검증 완료';
            statusBadge.className = 'status-badge verified-tag';
            
            const areaInput = row.querySelector('.p-area');
            if (actualArea) areaInput.value = actualArea;
            
            const zoningCell = row.querySelector('.zoning-result');
            let zoningText = zoning_list.join(', ');
            if (apiDomainError) {
                zoningText = `<span style="color: #ef4444; font-weight: bold;">[API 오류]</span> ${zoningText}`;
            }
            zoningCell.innerHTML = `<strong>지목:</strong> ${jimok}<br><strong>지역지구:</strong> ${zoningText}`;
            
        } catch (err) {
            const statusBadge = row.querySelector('.status-badge');
            statusBadge.textContent = '검증 실패';
            statusBadge.className = 'status-badge error-tag';
            
            const zoningCell = row.querySelector('.zoning-result');
            zoningCell.innerHTML = `<span style="color: #ef4444;">${err.message}</span>`;
        }
        updateTotalArea();
    }er('DOMContentLoaded', () => {
    const form = document.getElementById('project-form');
    const analyzeBtn = document.getElementById('analyze-btn');
    const btnText = document.getElementById('btn-text');
    const spinner = document.getElementById('spinner');
    const resultSection = document.getElementById('result-section');
    
    // Parcel dynamic fields
    const addParcelBtn = document.getElementById('add-parcel-btn');
    const parcelContainer = document.getElementById('parcel-container');
    const totalAreaSpan = document.getElementById('total-area');
    
    // Excel bulk upload
    const excelUploadInput = document.getElementById('excel-upload');
    const uploadExcelBtn = document.getElementById('upload-excel-btn');
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

    addParcelBtn.addEventListener('click', () => addParcelRow());

    uploadExcelBtn.addEventListener('click', () => {
        excelUploadInput.click();
    });

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
                alert(`총 ${addedCount}개의 주소를 성공적으로 불러왔습니다.`);
                bulkVerifyBtn.style.display = 'block'; // 일괄 검증 버튼 표시
            } else {
                alert('엑셀에서 "주소" 열을 찾을 수 없거나 데이터가 없습니다. (첫 줄에 "주소"라고 적혀 있어야 합니다)');
            }
        };
        reader.readAsArrayBuffer(file);
        excelUploadInput.value = ''; // Reset
    });

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
                <input type="number" class="p-area parcel-input-sm" placeholder="자동" value="${initArea || ''}" ${initArea ? 'readonly' : ''}>
            </td>
            <td class="zoning-result" style="font-size: 0.8rem; color: #64748b; word-break: keep-all;">
                -
            </td>
            <td style="text-align: center;">
                <button type="button" class="remove-parcel-btn">❌</button>
            </td>
        `;

        row.querySelector('.remove-parcel-btn').addEventListener('click', () => {
            row.remove();
            updateTotalArea();
        });

        if (!isExcel) {
            const searchBtn = row.querySelector('.search-addr-btn');
            searchBtn.addEventListener('click', () => {
                new daum.Postcode({
                    oncomplete: function(data) {
                        row.querySelector('.p-addr').value = data.address;
                        row.querySelector('.p-bonbeon').value = data.bunji || '';
                        row.querySelector('.p-bubeon').value = data.ho || '';
                        row.dataset.bcode = data.bcode || '';
                    }
                }).open();
            });
        }

        document.getElementById('parcel-container').appendChild(row);
        updateTotalArea();
    }ontentLoaded', () => {
    const form = document.getElementById('project-form');
    const analyzeBtn = document.getElementById('analyze-btn');
    const btnText = document.getElementById('btn-text');
    const spinner = document.getElementById('spinner');
    const resultSection = document.getElementById('result-section');
    
    // Parcel dynamic fields
    const addParcelBtn = document.getElementById('add-parcel-btn');
    const parcelContainer = document.getElementById('parcel-container');
    const totalAreaSpan = document.getElementById('total-area');
    
    // Excel bulk upload
    const excelUploadInput = document.getElementById('excel-upload');
    const uploadExcelBtn = document.getElementById('upload-excel-btn');
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

    addParcelBtn.addEventListener('click', () => addParcelRow());

    uploadExcelBtn.addEventListener('click', () => {
        excelUploadInput.click();
    });

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
                alert(`총 ${addedCount}개의 주소를 성공적으로 불러왔습니다.`);
                bulkVerifyBtn.style.display = 'block'; // 일괄 검증 버튼 표시
            } else {
                alert('엑셀에서 "주소" 열을 찾을 수 없거나 데이터가 없습니다. (첫 줄에 "주소"라고 적혀 있어야 합니다)');
            }
        };
        reader.readAsArrayBuffer(file);
        excelUploadInput.value = ''; // Reset
    });

    function addParcelRow(initAddr = null, initArea = '') {
        const row = document.createElement('div');
        row.className = 'parcel-row';
        row.dataset.bcode = ''; 
        
        if (initAddr) {
            row.dataset.excelAddress = initAddr;
        }

        // 엑셀로 불러온 경우 입력창을 막고 단순하게 표시
        const isExcel = !!initAddr;
        
        row.innerHTML = `
            <div class="parcel-part" style="flex: 2;">
                <label>주소</label>
                <div style="display: flex; gap: 0.5rem;">
                    ${isExcel ? '' : '<button type="button" class="search-addr-btn" style="white-space: nowrap;">🔍 검색</button>'}
                    <input type="text" class="p-addr" placeholder="예: 상주면 양아리" value="${initAddr || ''}" readonly>
                </div>
            </div>
            ${isExcel ? '' : `
            <div class="parcel-part">
                <label>산</label>
                <select class="p-san"><option value="1">일반</option><option value="2">산</option></select>
            </div>
            <div class="parcel-part">
                <label>본번</label>
                <input type="text" class="p-bonbeon">
            </div>
            <div class="parcel-part">
                <label>부번</label>
                <input type="text" class="p-bubeon">
            </div>
            `}
            <div class="parcel-part" style="flex: 0.5;">
                <label>면적(㎡)</label>
                <input type="number" class="p-area" placeholder="${isExcel ? '자동조회' : '예: 500'}" value="${initArea}" ${isExcel && !initArea ? 'readonly' : ''}>
            </div>
            
            <div class="parcel-actions">
                <span class="verified-tag">✓ 검증완료</span>
                <button type="button" class="verify-btn" style="${isExcel ? 'display: none;' : ''}">개별 검증</button>
                <button type="button" class="remove-parcel-btn">삭제</button>
            </div>
            <div class="parcel-result" style="width: 100%; margin-top: 0.5rem;"></div>
        `;

        row.querySelector('.remove-parcel-btn').addEventListener('click', function() {
            if (row.dataset.verified === 'true') {
                const area = parseFloat(row.dataset.actualArea || 0);
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

            const verifyBtn = row.querySelector('.verify-btn');
            verifyBtn.addEventListener('click', () => verifyRow(row));
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

    bulkVerifyBtn.addEventListener('click', async () => {
        const rows = document.querySelectorAll('.parcel-row');
        let pendingRows = [];
        rows.forEach(row => {
            if (row.dataset.verified !== 'true') {
                pendingRows.push(row);
            }
        });

        if (pendingRows.length === 0) {
            alert("모든 필지가 이미 검증되었습니다.");
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
        alert("일괄 검증이 완료되었습니다!");
    });

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
        const resultDiv = row.querySelector('.parcel-result');
        const verifyBtn = row.querySelector('.verify-btn');
        if (verifyBtn) {
            verifyBtn.textContent = '조회 중...';
            verifyBtn.disabled = true;
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
                resultDiv.innerHTML = `<strong style="color: #dc2626;">[검증 실패]</strong> 주소 검색을 먼저 완료해 주세요.`;
                resultDiv.classList.add('show');
                if (verifyBtn) { verifyBtn.textContent = '개별 검증'; verifyBtn.disabled = false; }
                return;
            }
            if (!row.querySelector('.p-bonbeon').value) {
                resultDiv.innerHTML = `<strong style="color: #dc2626;">[검증 실패]</strong> 본번을 입력해 주세요.`;
                resultDiv.classList.add('show');
                if (verifyBtn) { verifyBtn.textContent = '개별 검증'; verifyBtn.disabled = false; }
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

        resultDiv.innerHTML = `<span style="color: #2563eb;">로딩 중...</span>`;
        resultDiv.classList.add('show');

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
            
            // 토지특성정보 조회
            let actualArea = '';
            let jimok = reqData.san === '1' ? '대' : '임야';
            let apiDomainError = false;
            try {
                const url_char = `https://api.vworld.kr/ned/data/getLandCharacteristics?key=${VWORLD_KEY}&domain=http://127.0.0.1&pnu=${pnu}&numOfRows=50&pageNo=1`;
                const res_char = await fetchJSONP(url_char);
                const fields = res_char?.landCharacteristicss?.field || [];
                if (fields.length > 0) {
                    actualArea = fields[0].lndpclAr || '';
                    const jimok_code = fields[0].lndcgrCodeNm || '';
                    if (jimok_code) jimok = jimok_code;
                }
            } catch (e) { 
                console.error("토지특성정보 오류", e);
                apiDomainError = true;
            }
            
            if (!actualArea && reqData.area) {
                actualArea = reqData.area;
            }
            
            // 토지이용계획 조회
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
            row.dataset.fullAddr = isExcel ? reqData.address : row.querySelector('.p-addr').value;
            
            if (isExcel && actualArea) {
                row.querySelector('.p-area').value = actualArea;
            }
            
            totalVerifiedArea += parseFloat(actualArea || 0);
            updateTotalArea();
            
            if (verifyBtn) verifyBtn.style.display = 'none';
            row.querySelector('.verified-tag').classList.add('show');
            
            const areaStr = actualArea ? actualArea : '0';
            let zoningHtml = zoning_list.length > 0 
                ? `<br><strong>지역지구:</strong> ${zoning_list.join(', ')}`
                : '';
                
            resultDiv.innerHTML = `
                <strong style="color: #059669;">[검증 성공]</strong> 
                적용 면적: ${areaStr}㎡ (지목: ${jimok})${zoningHtml}
            `;
            resultDiv.classList.add('success');
            
        } catch (error) {
            console.error("verify_parcel 오류:", error);
            resultDiv.innerHTML = `<strong style="color: #dc2626;">[검증 실패]</strong> ${error.message || '알 수 없는 오류'}`;
            if (verifyBtn) {
                verifyBtn.textContent = '재검증';
                verifyBtn.disabled = false;
            }
        }
    }

    addParcelRow();

    function updateTotalArea() {
        totalAreaSpan.textContent = totalVerifiedArea.toLocaleString();
    }

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const parcels = [];
        document.querySelectorAll('.parcel-row').forEach(row => {
            if (row.dataset.verified === 'true') {
                const isExcel = !!row.dataset.excelAddress;
                let address = row.dataset.fullAddr;
                if (!isExcel) {
                    const sanStr = row.querySelector('.p-san').value === '2' ? '산 ' : '';
                    const bonbeon = row.querySelector('.p-bonbeon').value;
                    const bubeon = row.querySelector('.p-bubeon').value || '0';
                    const jibun = bubeon === '0' ? bonbeon : `${bonbeon}-${bubeon}`;
                    address = `${address} ${sanStr}${jibun}`;
                }
                
                parcels.push({
                    pnu: row.dataset.pnu,
                    area: row.dataset.actualArea,
                    zoning: row.dataset.zoning,
                    address: address
                });
            }
        });

        if (parcels.length === 0) {
            alert("검증이 완료된 편입 필지가 하나 이상 있어야 합니다.");
            return;
        }

        const requestData = {
            projectName: document.getElementById('projectName').value,
            budget: parseFloat(document.getElementById('budget').value),
            budgetNational: parseFloat(document.getElementById('budgetNational').value) || 0,
            budgetProvincial: parseFloat(document.getElementById('budgetProvincial').value) || 0,
            budgetMunicipal: parseFloat(document.getElementById('budgetMunicipal').value) || 0,
            totalArea: totalVerifiedArea,
            description: document.getElementById('description').value,
            parcels: parcels
        };

        btnText.textContent = '지역지구 및 법령 융합 분석 중...';
        spinner.classList.remove('hidden');
        analyzeBtn.disabled = true;
        resultSection.classList.add('hidden');

        try {
            const response = await fetch('/api/analyze', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(requestData)
            });

            if (!response.ok) {
                const errorText = await response.text();
                throw new Error(errorText);
            }

            const data = await response.json();
            renderResults(data);
            
            resultSection.classList.remove('hidden');
            resultSection.scrollIntoView({ behavior: 'smooth', block: 'start' });

        } catch (error) {
            console.error(error);
            alert("오류 발생: " + error.message);
        } finally {
            btnText.textContent = 'AI 기반 법규 및 지역지구 분석 시작';
            spinner.classList.add('hidden');
            analyzeBtn.disabled = false;
        }
    });

    function renderResults(data) {
        document.getElementById('risk-list').innerHTML = '';
        document.getElementById('permit-list').innerHTML = '';
        document.getElementById('timeline-list').innerHTML = '';
        document.getElementById('law-list').innerHTML = '';

        if (data.risks) data.risks.forEach(item => appendListItem('risk-list', `<strong>⚠️ 주의:</strong> ${item}`));
        if (data.permits) data.permits.forEach(item => appendListItem('permit-list', `✅ ${item}`));
        if (data.timeline) data.timeline.forEach(item => appendListItem('timeline-list', item));
        if (data.laws) data.laws.forEach(item => appendListItem('law-list', `📜 ${item}`));
    }

    function appendListItem(listId, htmlContent) {
        const li = document.createElement('li');
        li.innerHTML = htmlContent;
        document.getElementById(listId).appendChild(li);
    }
});
