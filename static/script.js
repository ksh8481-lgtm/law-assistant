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
            const res = await fetch('/api/verify_parcel', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(reqData)
            });
            
            const data = await res.json();
            
            if (res.ok && data.success) {
                row.dataset.verified = 'true';
                row.dataset.actualArea = data.actualArea;
                row.dataset.pnu = data.pnu;
                row.dataset.zoning = data.zoning.join(', ');
                row.dataset.fullAddr = isExcel ? row.dataset.excelAddress : row.querySelector('.p-addr').value;
                
                // 엑셀일 경우 면적 입력창에 자동 채우기
                if (isExcel && data.actualArea) {
                    row.querySelector('.p-area').value = data.actualArea;
                }
                
                totalVerifiedArea += parseFloat(data.actualArea || 0);
                updateTotalArea();
                
                if (verifyBtn) verifyBtn.style.display = 'none';
                row.querySelector('.verified-tag').classList.add('show');
                
                resultDiv.innerHTML = `
                    <strong style="color: #059669;">[검증 성공]</strong> 
                    적용 면적: ${data.actualArea}㎡ (지목: ${data.jimok})<br>
                    <strong>지역지구:</strong> ${data.zoning.join(', ')}
                `;
            } else {
                resultDiv.innerHTML = `<strong style="color: #dc2626;">[검증 실패]</strong> ${data.message || '토지대장에서 지번을 찾을 수 없습니다.'}`;
                if (verifyBtn) {
                    verifyBtn.textContent = '재검증';
                    verifyBtn.disabled = false;
                }
            }
        } catch (err) {
            resultDiv.innerHTML = `<strong style="color: #dc2626;">[통신 오류]</strong> 백엔드 서버와 연결할 수 없습니다.`;
            if (verifyBtn) {
                verifyBtn.textContent = '개별 검증';
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
