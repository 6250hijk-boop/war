"""
[Step 1] war 프로젝트 문서 수집 · 한·영 오프라인 번역 · 청킹 · 지식베이스 저장 파이프라인
- 원본 PDF 폴더: C:\\Users\\6250h\\Desktop\\war\\data
- 시스템/생성 파일 폴더: C:\\Users\\6250h\\Desktop\\war\\system
"""

import json
import logging
import os
import re
import time
from pathlib import Path

import pypdf
from dotenv import load_dotenv
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from bilingual_engine import (
    is_mostly_english,
    translate_en_to_ko_offline,
)

logging.getLogger("pypdf").setLevel(logging.ERROR)

SYSTEM_DIR = Path(__file__).resolve().parent
WAR_ROOT_DIR = SYSTEM_DIR.parent
DATA_DIR = WAR_ROOT_DIR / "data"
FAISS_DB_DIR = SYSTEM_DIR / "db" / "faiss"
KB_JSON_PATH = SYSTEM_DIR / "war_kb.json"
KB_JS_PATH = SYSTEM_DIR / "knowledge_base.js"

# 스캔 이미지 본으로만 구성된 PDF 2종에 대한 핵심 한·영 요약 보완 데이터
SCANNED_PDF_FALLBACK: dict[str, list[tuple[int, str]]] = {
    "ST31-91B.pdf": [
        (
            1,
            "[한국어 번역 요약] 미 육군 특수부대 의무 핸드북 (US Army Special Forces Medical Handbook ST 31-91B): "
            "야전 응급처치, 기도 확보(Airway, 윤상갑상막 절개술), 출혈 통제(지혈대 Tourniquet, 압박 드레싱), 쇼크(Shock) 및 수액 처치, "
            "전염병·감염증 예방 및 항생제 처치, 골절·부목(Splint), 화상·동상·열사병, 독사·곤충 교상 및 전술 응급의학 지침.\n"
            "[Original English] US Army Special Forces Medical Handbook (ST 31-91B): Comprehensive field medical guide covering "
            "lifesaving first aid, airway management, hemorrhage control, tourniquet, shock, fractures, splinting, burns, hypothermia, "
            "infectious diseases, water sanitation, and tactical emergency care.",
        )
    ],
    "FM-21-76-US-Army-Survival-Manual.pdf": [
        (
            1,
            "[한국어 번역 요약] 미 육군 생존 매뉴얼 (US Army Survival Manual FM 21-76): "
            "생존 심리(SURVIVAL 원칙), 생존 계획 및 생존 키트, 야전 의학 및 응급처치, 은신처(Shelter) 구축, 식수 확보 및 정수(Water Procurement), "
            "불 피우기(Fire Craft - Tinder, Kindling, Fuel), 식용 식물(Edible Plants & Universal Edibility Test) 및 독초 식별, "
            "야전 방향 찾기(Shadow-Tip Method, 북극성), 로프 매듭법(Knots), 구조 신호(Signaling) 및 화생방(Nuclear/Biological/Chemical) 생존 수칙.\n"
            "[Original English] US Army Survival Manual (FM 21-76): Psychology of survival, survival planning and survival kits, "
            "basic survival medicine, shelters, water procurement, fire craft, field-expedient weapons and tools, edible and medicinal plants, "
            "poisonous plants, dangerous animals, river crossings, direction finding, signaling techniques, and NBC survival.",
        )
    ],
}


def load_saved_api_key() -> str:
    try:
        import streamlit as st
        if "GEMINI_API_KEY" in st.secrets:
            return str(st.secrets["GEMINI_API_KEY"]).strip()
        if "GOOGLE_API_KEY" in st.secrets:
            return str(st.secrets["GOOGLE_API_KEY"]).strip()
    except Exception:
        pass

    load_dotenv(SYSTEM_DIR / ".env", override=True)
    if (SYSTEM_DIR / "api_key.txt").exists():
        load_dotenv(SYSTEM_DIR / "api_key.txt", override=True)

    key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    if key and key != "your_gemini_api_key_here":
        return key

    for fname in [".env", "api_key.txt"]:
        fpath = SYSTEM_DIR / fname
        if fpath.exists():
            for line in fpath.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    _, val = line.split("=", 1)
                    val = val.strip().strip("'\"")
                    if val and val != "your_gemini_api_key_here":
                        return val
                elif line.startswith("AIza") or line.startswith("sk-"):
                    return line
    return ""


def get_pdf_files() -> list[Path]:
    """C:\\Users\\6250h\\Desktop\\war\\data 폴더 내의 PDF 목록을 반환합니다 (' (1).pdf' 중복 사본 제외)."""
    if not DATA_DIR.exists():
        return []
    all_pdfs = sorted(DATA_DIR.glob("*.pdf"))
    unique_pdfs: list[Path] = []
    for p in all_pdfs:
        if " (1)" in p.stem:
            orig = DATA_DIR / (p.stem.replace(" (1)", "") + p.suffix)
            if orig.exists():
                continue
        unique_pdfs.append(p)
    return unique_pdfs


def get_embeddings(api_key: str | None = None) -> GoogleGenerativeAIEmbeddings:
    key = (api_key or "").strip() or load_saved_api_key()
    if not key:
        raise ValueError("GEMINI_API_KEY가 설정되지 않았습니다.")
    os.environ["GOOGLE_API_KEY"] = key
    os.environ["GEMINI_API_KEY"] = key
    return GoogleGenerativeAIEmbeddings(
        model="models/gemini-embedding-001",
        google_api_key=key,
    )


def load_and_translate_all_pdfs() -> list[Document]:
    """
    war/data 폴더의 모든 한글·영문 PDF를 읽고,
    영문 페이지는 오프라인 한·영 번역 해설을 결합하여 Document 리스트로 반환합니다.
    """
    pdf_files = get_pdf_files()
    all_docs: list[Document] = []

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=180,
        separators=["\n\n", "\n", ". ", " "],
    )

    for pdf_path in pdf_files:
        fname = pdf_path.name
        try:
            reader = pypdf.PdfReader(str(pdf_path))
            num_pages = len(reader.pages)
        except Exception as e:
            print(f"[경고] {fname} 읽기 실패: {e}")
            continue

        extracted_any = False
        # 초대형 영문 교범(200쪽 이상)은 핵심 텍스트 밀도가 높은 페이지를 선별해 속도와 검색 품질을 최적화
        page_docs: list[Document] = []
        for idx, page in enumerate(reader.pages):
            pno = idx + 1
            try:
                raw_text = (page.extract_text() or "").strip()
            except Exception:
                raw_text = ""

            raw_text = re.sub(r"\s+", " ", raw_text).strip()
            if len(raw_text) < 35:
                continue

            extracted_any = True
            lang = "en" if is_mostly_english(raw_text) else "ko"

            if lang == "en":
                ko_translated = translate_en_to_ko_offline(raw_text)
                combined_content = (
                    f"[{fname} - {pno}쪽 (영문 매뉴얼 → 한국어 번역)]\n"
                    f"{ko_translated}\n\n"
                    f"[영문 원문 (Original English)]\n{raw_text}"
                )
            else:
                combined_content = f"[{fname} - {pno}쪽 (한국어 매뉴얼)]\n{raw_text}"

            page_docs.append(
                Document(
                    page_content=combined_content,
                    metadata={
                        "file_name": fname,
                        "page_number": pno,
                        "lang": lang,
                        "source": str(pdf_path),
                    },
                )
            )

        if not extracted_any and fname in SCANNED_PDF_FALLBACK:
            for pno, fb_text in SCANNED_PDF_FALLBACK[fname]:
                page_docs.append(
                    Document(
                        page_content=f"[{fname} - {pno}쪽]\n{fb_text}",
                        metadata={
                            "file_name": fname,
                            "page_number": pno,
                            "lang": "en",
                            "source": str(pdf_path),
                        },
                    )
                )

        # 파일당 청크 분할 (초대형 영문 매뉴얼은 상위 핵심 60개 청크까지만 균형 색인하여 검색 속도 및 브라우저 로딩 보장)
        chunks = splitter.split_documents(page_docs)
        if len(chunks) > 60 and is_mostly_english(chunks[0].page_content if chunks else ""):
            step = max(1, len(chunks) // 60)
            chunks = chunks[::step][:60]

        all_docs.extend(chunks)
        print(f" - {fname} ({num_pages}쪽) -> {len(chunks)}개 한·영 청크 생성")

    return all_docs


def build_offline_knowledge_base() -> list[dict]:
    """
    모든 한글·영문 PDF를 색인하여 C:\\Users\\6250h\\Desktop\\war\\system 폴더에
    war_kb.json 및 knowledge_base.js로 저장합니다 (API 키 불필요 · 100% 오프라인 동작).
    """
    print(f"1. PDF 폴더 스캔 중: {DATA_DIR}")
    chunks = load_and_translate_all_pdfs()
    print(f"2. 총 {len(chunks)}개 한·영 통합 청크 생성 완료!")

    kb_records = []
    for i, c in enumerate(chunks):
        kb_records.append(
            {
                "id": i,
                "file_name": c.metadata.get("file_name", ""),
                "page": c.metadata.get("page_number", 1),
                "lang": c.metadata.get("lang", "ko"),
                "content": c.page_content.strip(),
            }
        )

    SYSTEM_DIR.mkdir(parents=True, exist_ok=True)
    KB_JSON_PATH.write_text(json.dumps(kb_records, ensure_ascii=False, indent=2), encoding="utf-8")
    KB_JS_PATH.write_text(
        "window.WAR_KB = " + json.dumps(kb_records, ensure_ascii=False) + ";",
        encoding="utf-8",
    )
    print(f"3. 오프라인 한·영 지식베이스 저장 완료:\n   - {KB_JSON_PATH}\n   - {KB_JS_PATH}")
    return kb_records


def build_vector_store(api_key: str | None = None) -> FAISS:
    """(선택) Gemini 임베딩 API를 사용하여 FAISS 인덱스를 ./db/faiss 에 저장합니다."""
    chunks = load_and_translate_all_pdfs()
    emb = get_embeddings(api_key=api_key)
    batch_size = 40
    vs = None
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        for attempt in range(3):
            try:
                if vs is None:
                    vs = FAISS.from_documents(batch, emb)
                else:
                    vs.add_documents(batch)
                break
            except Exception as e:
                if ("429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)) and attempt < 2:
                    time.sleep(35)
                else:
                    raise
    FAISS_DB_DIR.mkdir(parents=True, exist_ok=True)
    vs.save_local(str(FAISS_DB_DIR))
    return vs


if __name__ == "__main__":
    build_offline_knowledge_base()
