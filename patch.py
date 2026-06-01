import sys

with open('static/script.js', 'r', encoding='utf-8') as f:
    content = f.read()

start_str = '        try {'
end_str = '            if (verifyBtn) { verifyBtn.textContent = \'개별 검증\'; verifyBtn.disabled = false; }\n        }'

idx_start = content.find(start_str, content.find('async function verifyRow'))
idx_end = content.find(end_str, idx_start) + len(end_str)

if idx_start == -1 or idx_end < len(end_str):
    print('Failed to find block!')
    sys.exit(1)

new_try_block = r'''        try {
            const VWORLD_KEY = atob("RDNDMEEyNTktQjQ1QS0zQ0U2LTg0MUQtNjJFRkIxMDNEM0NC");
            let pnu = '';
            
            if (isExcel) {
                const full_address = reqData.address.trim();
                const url_search = `http://api.vworld.kr/req/search?service=search&request=search&version=2.0&size=10&page=1&query=${encodeURIComponent(full_address)}&type=address&category=parcel&key=${VWORLD_KEY}&domain=http://127.0.0.1`;
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
            try {
                const url_char = `http://api.vworld.kr/ned/data/getLandCharacteristics?key=${VWORLD_KEY}&domain=http://127.0.0.1&pnu=${pnu}&numOfRows=50&pageNo=1`;
                const res_char = await fetchJSONP(url_char);
                const fields = res_char?.landCharacteristicss?.field || [];
                if (fields.length > 0) {
                    actualArea = fields[0].lndpclAr || '';
                    const jimok_code = fields[0].lndcgrCodeNm || '';
                    if (jimok_code) jimok = jimok_code;
                }
            } catch (e) { console.error("토지특성정보 오류", e); }
            
            if (!actualArea && reqData.area) {
                actualArea = reqData.area;
            }
            
            // 토지이용계획 조회
            let zoning_list = [];
            try {
                const url_zoning = `http://api.vworld.kr/ned/data/getLandUseAttr?key=${VWORLD_KEY}&domain=http://127.0.0.1&pnu=${pnu}&numOfRows=50&pageNo=1`;
                const res_zoning = await fetchJSONP(url_zoning);
                const fields = res_zoning?.landUses?.field || [];
                for (const field of fields) {
                    if (field.prposAreaDstrcCodeNm) {
                        zoning_list.push(field.prposAreaDstrcCodeNm);
                    }
                }
            } catch (e) { 
                zoning_list.push("지역지구 통신 에러"); 
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
            
            const areaStr = actualArea ? actualArea : '0';
            let zoningHtml = zoning_list.length > 0 
                ? `<br><span style="color: #4b5563; font-size: 0.9em;">지역지구: ${zoning_list.join(', ')}</span>`
                : '';
                
            resultDiv.innerHTML = `<strong style="color: #10b981;">[검증 성공]</strong> 적용 면적: ${areaStr}m² (지목: ${jimok})${zoningHtml}`;
            resultDiv.classList.add('success');
            
            if (verifyBtn) {
                verifyBtn.textContent = '검증완료';
                verifyBtn.classList.replace('bg-blue-600', 'bg-green-500');
                verifyBtn.classList.replace('hover:bg-blue-700', 'hover:bg-green-600');
                verifyBtn.innerHTML = '✔ 검증완료';
            }
        } catch (error) {
            console.error("verify_parcel 오류:", error);
            resultDiv.innerHTML = `<strong style="color: #dc2626;">[검증 실패]</strong> ${error.message || '알 수 없는 오류'}`;
            resultDiv.classList.add('show');
            if (verifyBtn) {
                verifyBtn.textContent = '개별 검증';
                verifyBtn.disabled = false;
            }
        }'''

content = content[:idx_start] + new_try_block + content[idx_end:]

with open('static/script.js', 'w', encoding='utf-8') as f:
    f.write(content)
print('Patched successfully!')
