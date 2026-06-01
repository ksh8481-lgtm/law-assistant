import sys
import re

with open('static/script.js', 'r', encoding='utf-8') as f:
    content = f.read()

def patch_verify_row(content):
    start_str = "row.dataset.verified = 'true';"
    end_str = "updateTotalArea();\n    }"
    
    idx_start = content.find(start_str)
    if idx_start == -1: return content
    
    idx_end = content.find(end_str, idx_start) + len(end_str)
    
    new_logic = """row.dataset.verified = 'true';
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
    }"""
    
    return content[:idx_start] + new_logic + content[idx_end:]

content = patch_verify_row(content)

# Also need to make sure verifyBtn logic is removed from the top of verifyRow
content = re.sub(
    r"const verifyBtn = row\.querySelector\('\.verify-btn'\);\s*if \(verifyBtn\) \{\s*verifyBtn\.textContent = '로딩 중\.\.\.';\s*verifyBtn\.disabled = true;\s*\}",
    "const statusBadge = row.querySelector('.status-badge');\n        if (statusBadge) {\n            statusBadge.textContent = '검증 중...';\n            statusBadge.style.color = '#3b82f6';\n        }",
    content
)

with open('static/script.js', 'w', encoding='utf-8') as f:
    f.write(content)
print('verifyRow Patched!')
