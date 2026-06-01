import sys

with open('static/script.js', 'r', encoding='utf-8') as f:
    content = f.read()

def replace_add_parcel_row(content):
    start_str = "function addParcelRow(initAddr = null, initArea = '') {"
    end_str = "        updateTotalArea();\n    }"
    idx_start = content.find(start_str)
    if idx_start == -1:
        print("addParcelRow start not found")
        return content
    idx_end = content.find(end_str, idx_start) + len(end_str)
    
    new_func = """function addParcelRow(initAddr = null, initArea = '') {
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
    }"""
    return content[:idx_start] + new_func + content[idx_end:]

content = replace_add_parcel_row(content)
with open('static/script.js', 'w', encoding='utf-8') as f:
    f.write(content)
print('addParcelRow Replaced!')
