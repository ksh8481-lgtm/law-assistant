import sys
with open('templates/index.html', 'r', encoding='utf-8') as f:
    content = f.read()

start_str = '<div id="parcel-container">'
end_str = '</button>\n                        </div>'

idx_start = content.find(start_str)
idx_end = content.find(end_str, idx_start) + len(end_str)

new_block = '''<div class="parcel-controls" style="display: flex; gap: 0.5rem; margin-bottom: 1rem; align-items: center;">
                            <button type="button" id="add-parcel-btn" class="secondary-btn" style="padding: 0.5rem; font-size: 0.9rem; flex: 1;">➕ 1개 수동 추가</button>
                            <input type="file" id="excel-upload" accept=".xlsx, .xls" style="display: none;">
                            <button type="button" id="upload-excel-btn" class="secondary-btn" style="padding: 0.5rem; font-size: 0.9rem; background-color: #10b981; color: white; border-color: #059669; flex: 1.5;">📊 엑셀 불러오기</button>
                            <button type="button" id="download-template-btn" class="secondary-btn" style="padding: 0.5rem; font-size: 0.9rem; background-color: #f8fafc; border-color: #cbd5e1; color: #475569; flex: 1;">📥 엑셀 양식</button>
                            <button type="button" id="clear-parcels-btn" class="secondary-btn" style="padding: 0.5rem; font-size: 0.9rem; margin-left: auto; color: #ef4444; border-color: #fca5a5; flex: 0.8;">🗑️ 전체 삭제</button>
                        </div>

                        <div style="overflow-x: auto; border: 1px solid #e2e8f0; border-radius: 8px; margin-bottom: 1rem;">
                            <table id="parcel-table" style="width: 100%; border-collapse: collapse; text-align: left; font-size: 0.9rem; min-width: 800px;">
                                <thead>
                                    <tr style="background-color: #f8fafc; border-bottom: 1px solid #e2e8f0;">
                                        <th style="padding: 0.75rem; width: 60px; text-align: center;">상태</th>
                                        <th style="padding: 0.75rem; width: 250px;">주소 (수동 추가시 돋보기)</th>
                                        <th style="padding: 0.75rem; width: 140px;">상세지번</th>
                                        <th style="padding: 0.75rem; width: 90px;">면적(㎡)</th>
                                        <th style="padding: 0.75rem;">지목 및 지역지구 요약</th>
                                        <th style="padding: 0.75rem; width: 60px; text-align: center;">관리</th>
                                    </tr>
                                </thead>
                                <tbody id="parcel-container">
                                </tbody>
                            </table>
                        </div>'''

if idx_start != -1:
    content = content[:idx_start] + new_block + content[idx_end:]
    with open('templates/index.html', 'w', encoding='utf-8') as f:
        f.write(content)
    print('Patched successfully!')
else:
    print('Failed to find block!')
