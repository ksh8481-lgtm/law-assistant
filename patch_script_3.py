import sys

with open('static/script.js', 'r', encoding='utf-8') as f:
    content = f.read()

clear_btn_logic = """
    // 전체 삭제 버튼
    const clearParcelsBtn = document.getElementById('clear-parcels-btn');
    if (clearParcelsBtn) {
        clearParcelsBtn.addEventListener('click', () => {
            if (confirm('모든 편입 필지 목록을 삭제하시겠습니까?')) {
                document.getElementById('parcel-container').innerHTML = '';
                updateTotalArea();
            }
        });
    }
"""

# Insert it after excelUploadInput event listener
search_str = "    excelUploadInput.addEventListener('change', async (e) => {"
idx = content.find(search_str)
if idx != -1:
    content = content[:idx] + clear_btn_logic + content[idx:]
    with open('static/script.js', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Added clear btn logic")
else:
    print("Failed to find excelUploadInput event listener")
