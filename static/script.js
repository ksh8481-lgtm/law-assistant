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
                    alert(`총 ${addedCount}개의 주소를 성공적으로 불러왔습니다.`);
                    bulkVerifyBtn.style.display = 'block'; // 일괄 검증 버튼 표시
                } else {
                    alert('엑셀에서 "주소" 열을 찾을 수 없거나 데이터가 없습니다. (첫 줄에 "주소"라고 적혀 있어야 합니다)');
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
                    alert(`AI가 도면에서 총 ${addedCount}개의 편입 지번을 성공적으로 추출했습니다!\\n이제 [✅ 일괄 검증] 버튼을 눌러 토지이음 정보를 매칭하세요.`);
                    bulkVerifyBtn.style.display = 'block';
                } else {
                    alert('도면에서 식별 가능한 주소/지번 정보를 찾지 못했습니다.');
                }
                
            } catch (error) {
                console.error(error);
                alert('도면 AI 분석 중 오류가 발생했습니다: ' + error.message);
            } finally {
                uploadDrawingBtn.textContent = originalText;
                uploadDrawingBtn.disabled = false;
                drawingUploadInput.value = ''; // Reset
            }
        });
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

    if (form) {
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

            const pubArea = parseFloat(publicWaterInput ? publicWaterInput.value : 0) || 0;
            
            if (parcels.length === 0 && pubArea <= 0) {
                alert("검증이 완료된 편입 필지 또는 공유수면 면적이 하나 이상 있어야 합니다.");
                return;
            }

            const projectTypeElement = document.querySelector('input[name="projectType"]:checked');
            const projectType = projectTypeElement ? projectTypeElement.value : '복합공사';

            const requestData = {
                projectName: document.getElementById('projectName').value,
                projectType: projectType,
                budget: parseFloat(document.getElementById('budget').value),
                budgetNational: parseFloat(document.getElementById('budgetNational').value) || 0,
                budgetProvincial: parseFloat(document.getElementById('budgetProvincial').value) || 0,
                budgetMunicipal: parseFloat(document.getElementById('budgetMunicipal').value) || 0,
                totalArea: totalVerifiedArea + pubArea,
                publicWaterArea: pubArea,
                description: document.getElementById('description').value,
                parcels: parcels
            };

            btnText.textContent = 'AI 기반 법규 및 지역지구 분석 중... (최대 2~3분 소요)';
            spinner.classList.remove('hidden');
            analyzeBtn.disabled = true;


            try {
                // 1. 분석 작업 시작 요청
                const startResponse = await fetch('/api/analyze/start', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(requestData)
                });

                if (!startResponse.ok) {
                    const errorText = await startResponse.text();
                    throw new Error(errorText);
                }

                const startData = await startResponse.json();
                const jobId = startData.job_id;
                
                // 2. 3초 간격으로 폴링 (최대 5분 = 100회 시도 후 포기)
                const MAX_POLL_ATTEMPTS = 100;
                let pollAttempts = 0;
                while (true) {
                    await new Promise(r => setTimeout(r, 3000));
                    pollAttempts++;

                    if (pollAttempts > MAX_POLL_ATTEMPTS) {
                        throw new Error("응답 시간이 너무 오래 걸립니다 (5분 초과). 서버가 지연 중일 수 있으니 잠시 후 다시 시도해주세요.");
                    }

                    const statusResponse = await fetch(`/api/analyze/status/${jobId}`);
                    if (!statusResponse.ok) {
                        const errorText = await statusResponse.text();
                        throw new Error(errorText);
                    }

                    const statusData = await statusResponse.json();

                    if (statusData.status === 'completed') {
                        sessionStorage.setItem('aiResult', JSON.stringify(statusData.result));
                        sessionStorage.setItem('projectData', JSON.stringify(requestData));
                        window.open('/report', '_blank');
                        break;
                    } else if (statusData.status === 'error') {
                        throw new Error(statusData.message || "알 수 없는 서버 오류");
                    }
                    // status === 'processing' 인 경우 계속 대기
                }

            } catch (error) {
                console.error(error);
                alert("오류 발생: " + error.message);
            } finally {
                btnText.textContent = 'AI 기반 법규 및 지역지구 분석 시작';
                spinner.classList.add('hidden');
                analyzeBtn.disabled = false;
            }
        });
    }

    // === 스마트 공사 프로파일러 & AI 템플릿 마법사 로직 ===
    const domainTabs = document.querySelectorAll('.domain-tab-btn');
    const smartTagsContainer = document.getElementById('smart-tags-container');
    const generateTemplateBtn = document.getElementById('generate-template-btn');
    const descriptionTextarea = document.getElementById('description');

    const domainTagsData = {
        building: [
            { id: 'b_excavation', label: '⛏️ 지하 10m 이상 굴착 동반', text: '지하 터파기 굴착 깊이 약 11.5m (흙막이 가시설 및 지반보강 동반, 지하안전평가 대상)' },
            { id: 'b_demo', label: '🏗️ 기존 노후 구조물 철거/석면', text: '기존 노후 건축물 해체 및 철거 작업 동반 (석면조사 및 해체계획서 승인 필수)' },
            { id: 'b_area', label: '🏢 연면적 1,000㎡ 이상 신축', text: '지하 2층 / 지상 5층 규모 (연면적 약 3,500㎡, 안전관리계획서 수립 의무)' },
            { id: 'b_green', label: '🌱 녹색건축/BF 인증 의무', text: '제로에너지건축물 5등급, 녹색건축 최우수 및 장애인 BF(배리어프리) 최우수 등급 인증 대상' },
            { id: 'b_contest', label: '🏆 설계공모 대상 (설계비 1억↑)', text: '설계비 1억원 이상 공공건축물로서 건축서비스산업 진흥법에 따른 설계공모 및 공공건축심의 대상' },
            { id: 'b_dfs', label: '🛡️ 설계안전성검토(DFS) 필수', text: '건설기술 진흥법 제62조에 따른 10층 이상 또는 굴착 10m 이상 위험공종 설계안전성검토(DFS) 수행' }
        ],
        civil: [
            { id: 'c_road', label: '🛣️ 노선장 4km 이상 도로개설', text: '총 연장 L=4.5km, 폭 B=20m(4차로) 신설 및 선형 개량 공사 (소규모 환경영향평가 대상)' },
            { id: 'c_land', label: '📜 사유지 편입 및 토지수용', text: '사업부지 내 사유지 25필지 편입에 따른 토지보상법상 보상협의 및 공익사업 사업인정 고시 필요' },
            { id: 'c_mountain', label: '🌲 산지(임야)/농지 전용 동반', text: '노선 통과 구간 내 보전산지 및 농지 편입 (산지전용허가 및 농지전용허가/부담금 협의 필수)' },
            { id: 'c_river_cross', label: '🌉 하천 및 철도 횡단 교량', text: '지방하천 횡단 교량 1개소(L=120m) 신설 동반 (하천점용허가 및 재해영향평가 협의 필요)' },
            { id: 'c_urban_plan', label: '🗺️ 도시계획시설(도로) 결정', text: '국토계획법에 따른 도시·군계획시설(중로1류) 결정 및 실시계획 인가, 주민공람 절차 진행' }
        ],
        water: [
            { id: 'w_river', label: '🌊 소하천 정비 및 제방 축조', text: '소하천 정비 L=2.0km 및 축제/호안 공사 (소하천정비 종합계획 부합 여부 및 소하천점용 검토)' },
            { id: 'w_pump', label: '🏭 배수펌프장 및 유수지 신설', text: '분당 500㎥ 용량 배수펌프장 1개소 및 유수지 설치 (자연재해대책법상 재해영향평가 필수)' },
            { id: 'w_pipe', label: '🔧 상·하수관로 개체(L=5km↑)', text: '노후 하수관로 정비 L=6.5km 및 맨홀 설치 (도로굴착 심의 및 지하안전평가 협의)' },
            { id: 'w_public_water', label: '⚓ 공유수면(바다/하천) 점용', text: '공유수면 내 배수관로 및 물양장 설치 (공유수면 관리 및 매립에 관한 법률상 점용·사용허가)' }
        ],
        park: [
            { id: 'p_park', label: '🌳 도시공원 및 체육시설 조성', text: '부지면적 45,000㎡ 규모 근린공원 및 다목적 체육관 조성 (도시계획시설 결정 및 실시계획 인가)' },
            { id: 'p_cut', label: '⛏️ 대규모 절·성토 및 사방사업', text: '부지 조성 위한 절토 50,000㎥, 성토 30,000㎥ 발생 (개발행위허가 및 산지복구·사방계획 수립)' },
            { id: 'p_culture', label: '🏺 문화재(매장유산) 지표조사', text: '사업 면적 3만㎡ 이상 대상지로 공사 착공 전 매장유산 보호 및 조사에 관한 법률상 지표조사 필수' },
            { id: 'p_disaster', label: '🌧️ 재해영향평가 (5,000㎡↑)', text: '부지조성 면적 5,000㎡ 이상으로 자연재해대책법에 따른 소규모 재해영향평가 협의 대상' }
        ]
    };

    let currentDomain = 'building';
    let selectedTags = new Set();

    function renderSmartTags(domain) {
        if (!smartTagsContainer) return;
        smartTagsContainer.innerHTML = '';
        const tags = domainTagsData[domain] || [];
        
        tags.forEach(tag => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'smart-tag-btn';
            btn.dataset.id = tag.id;
            btn.dataset.text = tag.text;
            
            const isSelected = selectedTags.has(tag.id);
            btn.style.cssText = `
                padding: 0.5rem 0.9rem;
                border-radius: 999px;
                font-size: 0.85rem;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.2s;
                border: 1px solid ${isSelected ? '#7c3aed' : '#cbd5e1'};
                background: ${isSelected ? '#f5f3ff' : '#f8fafc'};
                color: ${isSelected ? '#6d28d9' : '#475569'};
                box-shadow: ${isSelected ? '0 2px 4px rgba(124, 58, 237, 0.15)' : 'none'};
                display: flex;
                align-items: center;
                gap: 0.4rem;
            `;
            btn.innerHTML = `<span>${isSelected ? '☑️' : '◻️'}</span> <span>${tag.label}</span>`;
            
            btn.addEventListener('click', () => {
                if (selectedTags.has(tag.id)) {
                    selectedTags.delete(tag.id);
                } else {
                    selectedTags.add(tag.id);
                }
                renderSmartTags(currentDomain);
            });
            
            smartTagsContainer.appendChild(btn);
        });
    }

    if (domainTabs.length > 0) {
        domainTabs.forEach(tab => {
            tab.addEventListener('click', () => {
                domainTabs.forEach(t => {
                    t.classList.remove('active');
                    t.style.background = 'white';
                    t.style.color = '#475569';
                });
                tab.classList.add('active');
                tab.style.background = '#3b82f6';
                tab.style.color = 'white';
                
                currentDomain = tab.dataset.domain;
                renderSmartTags(currentDomain);
            });
        });
        
        // 초기 로딩
        renderSmartTags(currentDomain);
    }

    if (generateTemplateBtn && descriptionTextarea) {
        generateTemplateBtn.addEventListener('click', () => {
            let domainTitle = "공공건축 복합건립공사";
            if (currentDomain === 'civil') domainTitle = "도로개설 및 선형개량 토목공사";
            if (currentDomain === 'water') domainTitle = "하천정비 및 상하수도 관로개체 공사";
            if (currentDomain === 'park') domainTitle = "근린공원 및 부지조성 공사";

            let compiledText = `[1. 사업 개요]\n- 사업명: OO ${domainTitle}\n- 사업목적: 지역 주민의 편의 증진 및 안전한 기반시설 구축을 위한 공공 건설사업 추진\n\n[2. 주요 공사 내용 및 제원]\n`;
            
            let selectedTexts = [];
            Object.values(domainTagsData).flat().forEach(tag => {
                if (selectedTags.has(tag.id)) {
                    selectedTexts.push(`- ${tag.text}`);
                }
            });

            if (selectedTexts.length === 0) {
                compiledText += `- 일반적인 공사 진행 (※ 위에 나열된 핵심 조건 태그를 클릭하면 맞춤형 법규 제원이 자동 추가됩니다.)\n`;
            } else {
                compiledText += selectedTexts.join('\n') + '\n';
            }

            compiledText += `\n[3. 적용 검토 필수 법령 및 인허가 사항]\n- 국토계획법, 건설기술진흥법, 시특법, 환경영향평가법 등 관련 법령 부합 여부 및 절차 준수\n- 공종별 필수 행정 의무사항 및 감사 지적 예방 체크리스트 검토 요망`;

            descriptionTextarea.value = compiledText;
            
            descriptionTextarea.style.transition = 'all 0.3s';
            descriptionTextarea.style.backgroundColor = '#fef08a';
            setTimeout(() => {
                descriptionTextarea.style.backgroundColor = 'white';
            }, 600);

            alert('✨ 선택하신 핵심 조건들이 반영된 표준 사업내용이 텍스트칸에 자동 입력되었습니다!');
        });
    }

});
