"""부처별/기관별 실무 지침 문서 상시 보관함.

KCSC 국가건설기준과 달리, 각 부처가 자체 배포하는 실무 지침·매뉴얼은 공개
API가 없어 자동으로 가져올 수 없다. 그래서 사용자가 직접 PDF/문서를 업로드해
쌓아두면, 이후 모든 "설계도서 표준·지침 검토"에서 자동으로 참고 자료로
활용한다. 지침이 개정되면 기존 것을 지우고 새 버전을 다시 올리는 식으로 그때
그때 수동 관리한다(자동 갱신 파이프라인은 만들지 않음 - 개정 빈도가 낮고
발주기관마다 문서가 달라 자동화 실익이 적음).

⚠️ 저장 위치는 로컬 디스크(data/guidelines/)이고, Cloudtype은 재배포 시
디스크가 초기화되는 구조라서, 반드시 "로컬에서 업로드 → git commit/push →
배포" 흐름을 따라야 배포된 서비스에도 반영된다. 배포된 사이트에서 직접
업로드해도 당장은 동작하지만 다음 재배포 때 사라진다.
"""
import os
import json
import uuid
from datetime import datetime

from doc_extract import extract_text_from_file

GUIDELINE_DIR = os.path.join(os.path.dirname(__file__), 'data', 'guidelines')
FILES_DIR = os.path.join(GUIDELINE_DIR, 'files')
INDEX_PATH = os.path.join(GUIDELINE_DIR, 'index.json')

# 프롬프트에 한 번에 넣을 지침 텍스트 총량 상한. 지침 문서 수가 적다는 전제로
# (KCSC처럼 키워드 검색해서 일부만 뽑는 대신) 전문을 그대로 넣는 게 기본
# 방침이라, 문서가 늘어나 이 한도를 넘기 시작하면 그때 검색 방식으로 바꾸면 됨.
MAX_CONTEXT_CHARS = 20000


def _ensure_dirs():
    os.makedirs(FILES_DIR, exist_ok=True)


def _load_index():
    _ensure_dirs()
    if not os.path.exists(INDEX_PATH):
        return []
    try:
        with open(INDEX_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"[guideline_store] index.json 로드 실패: {e}")
        return []


def _save_index(items):
    _ensure_dirs()
    with open(INDEX_PATH, 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def list_guidelines():
    """메타데이터만 반환한다(본문 텍스트는 제외 - 목록 화면에는 필요 없음)."""
    items = _load_index()
    return [
        {
            "id": it["id"],
            "label": it["label"],
            "filename": it["filename"],
            "uploaded_at": it["uploaded_at"],
            "char_count": len(it.get("text", "")),
        }
        for it in items
    ]


def add_guideline(temp_path: str, original_filename: str, label: str):
    """업로드된 임시 파일을 영구 보관하고 텍스트를 추출해 인덱스에 추가한다."""
    _ensure_dirs()
    guideline_id = uuid.uuid4().hex[:12]
    ext = os.path.splitext(original_filename)[1]
    stored_name = f"{guideline_id}{ext}"
    stored_path = os.path.join(FILES_DIR, stored_name)

    with open(temp_path, 'rb') as src, open(stored_path, 'wb') as dst:
        dst.write(src.read())

    text = extract_text_from_file(stored_path)

    items = _load_index()
    entry = {
        "id": guideline_id,
        "label": (label or '').strip() or original_filename,
        "filename": original_filename,
        "stored_filename": stored_name,
        "uploaded_at": datetime.now().isoformat(timespec="seconds"),
        "text": text,
    }
    items.append(entry)
    _save_index(items)

    return {
        "id": entry["id"], "label": entry["label"], "filename": entry["filename"],
        "uploaded_at": entry["uploaded_at"], "char_count": len(text),
    }


def delete_guideline(guideline_id: str) -> bool:
    items = _load_index()
    target = next((it for it in items if it["id"] == guideline_id), None)
    if not target:
        return False

    stored_path = os.path.join(FILES_DIR, target["stored_filename"])
    if os.path.exists(stored_path):
        try:
            os.remove(stored_path)
        except Exception as e:
            print(f"[guideline_store] 파일 삭제 실패({stored_path}): {e}")

    items = [it for it in items if it["id"] != guideline_id]
    _save_index(items)
    return True


def build_guideline_context_for_llm() -> str:
    """저장된 모든 지침 문서의 텍스트를 프롬프트용 컨텍스트 문자열로 합친다."""
    items = _load_index()
    if not items:
        return ""

    context = "=== [발주기관/각 부처 실무 지침 문서함 (사용자 업로드 원문)] ===\n"
    context += (
        "(아래는 사용자가 직접 업로드한 부처별·기관별 실무 지침/매뉴얼 원문입니다. "
        "KCSC 국가건설기준과는 별개의 자료이니, 이 지침들에 어긋나는 부분이 있는지도 반드시 함께 검토하십시오.)\n"
    )

    remaining = MAX_CONTEXT_CHARS
    for it in items:
        label = it.get("label", it.get("filename", "(제목없음)"))
        if remaining <= 0:
            context += f"\n[{label}] - 지면 제한으로 이번 검토에서는 생략됨(문서함에 지침이 너무 많이 쌓였습니다)\n"
            continue
        text = (it.get("text") or "").strip()
        chunk = text[:remaining]
        context += f"\n--- [{label}] (원본파일: {it.get('filename', '')}) ---\n{chunk}\n"
        remaining -= len(chunk)

    return context
