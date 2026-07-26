import os
import json
from dotenv import load_dotenv

import sys

sys.stdout.reconfigure(encoding='utf-8')

# LangChain imports
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document

def main():
    print("Loading environment variables...")
    # 1. 환경변수 설정
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
    load_dotenv(env_path)
    
    # app.py와 동일하게 환경변수에서 키를 가져오도록 함
    gemini_key = os.getenv('GEMINI_API_KEY')
    if not gemini_key:
        print("[Error] GEMINI_API_KEY가 환경변수나 .env 파일에 설정되어 있지 않습니다.")
        print("해결방법: 루트 폴더의 .env 파일에 GEMINI_API_KEY=당신의_구글_API_키 를 추가하세요.")
        return

    print("Loading JSON data...")
    data_path = os.path.join(os.path.dirname(__file__), 'data', 'kcsc_standards.json')
    if not os.path.exists(data_path):
        print(f"[Error] {data_path} 파일이 존재하지 않습니다. 먼저 kcsc_pipeline.py를 실행하세요.")
        return

    with open(data_path, 'r', encoding='utf-8') as f:
        kcsc_data = json.load(f)

    print(f"총 {len(kcsc_data)}개의 KCSC 코드를 찾았습니다.")
    
    # 2. Document 객체로 변환
    documents = []
    
    for item in kcsc_data:
        code = item.get("code")
        title = item.get("title")
        chunks = item.get("chunks", [])
        
        for chunk in chunks:
            # 내용이 비어있으면 스킵
            if not chunk.get("content", "").strip():
                continue
                
            # Document 생성 (메타데이터에 출처 기록)
            doc = Document(
                page_content=chunk.get("content"),
                metadata={
                    "source": f"KDS {code}",
                    "title": title,
                    "section": chunk.get("section")
                }
            )
            documents.append(doc)
            
    print(f"총 {len(documents)}개의 청크(Chunk) 문서가 준비되었습니다.")
    
    if len(documents) == 0:
        print("❌ 임베딩할 문서가 없습니다.")
        return

    # 3. 임베딩 모델 준비 (Google Gemini Embedding)
    print("Initializing Google Gemini Embeddings...")
    embeddings = GoogleGenerativeAIEmbeddings(
        model="models/gemini-embedding-2",
        google_api_key=gemini_key
    )
    
    # 4. Chroma DB 생성 및 문서 저장
    db_dir = os.path.join(os.path.dirname(__file__), 'chroma_db')
    print(f"Saving to Chroma DB at {db_dir}...")
    
    # 만약 기존 DB가 있으면 초기화를 위해 덮어씁니다.
    vectorstore = Chroma.from_documents(
        documents=documents,
        embedding=embeddings,
        persist_directory=db_dir
    )
    
    # 디스크에 저장 (최신 langchain_chroma 버전에서는 persist()가 자동화되어 있기도 하지만, 구버전 호환을 위해 호출)
    try:
        vectorstore.persist()
    except Exception as e:
        # Chroma v0.4.x 이후 persist()는 deprecate 되어 예외가 발생할 수 있음
        pass

    print("✅ Vector DB 구축이 완벽하게 완료되었습니다!")

if __name__ == "__main__":
    main()
