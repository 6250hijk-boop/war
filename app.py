"""
[Step 2] 전시·재난·생존 한·영 통합 RAG 챗봇 (Streamlit UI)
- 원본 PDF 폴더: C:\\Users\\6250h\\Desktop\\war\\data (한글 + 영문 PDF 32종)
- 시스템/생성 파일 폴더: C:\\Users\\6250h\\Desktop\\war\\system
- 핵심 기능:
  1) 한국어 질문 입력 시 오프라인 한·영 사전을 통해 [한국어 + 영어] 양방향 검색어로 자동 번역·확장
  2) 한글 PDF와 영문 PDF를 동시 검색(Cross-Lingual MMR Retrieval)하여 결과는 100% 한국어로 통합 출력
  3) 3가지 모드 선택: ⚡ 오프라인 한·영 RAG 엔진 / 🦙 무료 오픈소스 LLM(Ollama) / ☁️ 클라우드 API(Gemini Flash-Lite)
  4) 새로운 한글·영문 PDF 추가 업로드 및 특정 PDF 선택 검색 지원
"""

import json
import math
import os
import re
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

import pypdf
import streamlit as st
from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_text_splitters import RecursiveCharacterTextSplitter

from bilingual_engine import (
    WAR_TOPIC_GUIDES,
    is_mostly_english,
    rewrite_bilingual_query,
    translate_en_to_ko_offline,
)
from ingest import (
    DATA_DIR,
    KB_JSON_PATH,
    SYSTEM_DIR,
    build_offline_knowledge_base,
    get_pdf_files,
    load_saved_api_key,
)

load_dotenv(SYSTEM_DIR / ".env")

st.set_page_config(
    page_title="전시·재난·생존 한·영 통합 AI 챗봇",
    page_icon="🛡️",
    layout="wide",
)


# ---------------------------------------------------------------------------
# 오프라인 한·영 통합 지식베이스 로드 (war/system/war_kb.json 캐싱)
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner="C:\\Users\\6250h\\Desktop\\war\\data 폴더의 한글·영문 PDF를 색인 및 번역 중입니다...")
def load_war_knowledge_base() -> list[Document]:
    if not KB_JSON_PATH.exists():
        records = build_offline_knowledge_base()
    else:
        try:
            records = json.loads(KB_JSON_PATH.read_text(encoding="utf-8"))
        except Exception:
            records = build_offline_knowledge_base()

    docs: list[Document] = []
    for r in records:
        docs.append(
            Document(
                page_content=r.get("content", ""),
                metadata={
                    "file_name": r.get("file_name", ""),
                    "page_number": r.get("page", 1),
                    "lang": r.get("lang", "ko"),
                    "ko_text": r.get("ko_text", ""),
                    "en_text": r.get("en_text", ""),
                },
            )
        )
    return docs


def tokenize_bilingual(text: str) -> list[str]:
    tokens = [t for t in re.split(r"[^\w가-힣]+", (text or "").lower()) if len(t) >= 2]
    expanded = list(tokens)
    for t in tokens:
        # 한글 단어가 3글자 이상이면 앞 2~3글자 어근도 함께 매칭
        if len(t) >= 3 and re.search(r"[가-힣]", t):
            expanded.append(t[:2])
            expanded.append(t[:3])
    return expanded


def retrieve_bilingual_mmr(
    chunks: list[Document],
    ko_keywords: list[str],
    en_keywords: list[str],
    raw_query: str,
    top_k: int = 4,
    search_type: str = "mmr",
) -> list[Document]:
    """
    한글 키워드와 번역된 영문 키워드를 동시에 사용하여
    한글 PDF와 영문 PDF 양쪽에서 가장 관련성 높은 청크를 균형 있게(MMR) 검색합니다.
    """
    all_terms = tokenize_bilingual(f"{raw_query} {' '.join(ko_keywords)} {' '.join(en_keywords)}")
    if not all_terms:
        return chunks[:top_k]

    term_counts = Counter(all_terms)
    scored: list[tuple[float, Document]] = []

    for doc in chunks:
        text_lower = doc.page_content.lower()
        score = 0.0
        for tok, freq in term_counts.items():
            if tok in text_lower:
                weight = 4.5 if len(tok) >= 3 else 1.8
                score += weight * (1.0 + math.log1p(freq))
        # 핵심 영문 구문이 정확히 일치하면 추가 가중치
        for en_phrase in en_keywords:
            if len(en_phrase) >= 4 and en_phrase.lower() in text_lower:
                score += 6.0
        for ko_kw in ko_keywords:
            if len(ko_kw) >= 2 and ko_kw.lower() in text_lower:
                score += 6.0

        if "table of contents" in text_lower or "목 차" in text_lower:
            score *= 0.45

        scored.append((score, doc))

    scored.sort(key=lambda x: x[0], reverse=True)

    if search_type != "mmr":
        return [doc for _, doc in scored[:top_k]]

    candidates = scored[: max(20, top_k * 5)]
    selected: list[Document] = []
    while len(selected) < top_k and candidates:
        best_idx = 0
        best_mmr = -1e9
        for i, (base_score, cand_doc) in enumerate(candidates):
            penalty = 0.0
            c_file = cand_doc.metadata.get("file_name", "")
            c_page = cand_doc.metadata.get("page_number", 0)
            for sel_doc in selected:
                s_file = sel_doc.metadata.get("file_name", "")
                s_page = sel_doc.metadata.get("page_number", 0)
                if c_file == s_file and c_page == s_page:
                    penalty = max(penalty, 8.0)
                elif c_file == s_file and abs(c_page - s_page) <= 2:
                    penalty = max(penalty, 3.5)
            mmr_score = base_score - penalty
            if mmr_score > best_mmr:
                best_mmr = mmr_score
                best_idx = i
        selected.append(candidates.pop(best_idx)[1])

    return selected


# ---------------------------------------------------------------------------
# 오프라인 한·영 통합 한국어 답변 생성기 (영문 PDF 결과도 100% 한국어로 정리)
# ---------------------------------------------------------------------------
def synthesize_offline_korean_answer(
    query: str,
    docs: list[Document],
    ko_keywords: list[str],
    en_keywords: list[str],
) -> str:
    if not docs:
        return "질문하신 내용과 일치하는 매뉴얼 조항을 찾지 못했습니다. 다른 키워드(예: 핵폭발, 식수 정수, 지혈대, 매듭, 화생방, 생존배낭, 공습경보, 은신처)로 질문해 주세요."

    search_context = f"{query} {' '.join(ko_keywords)} {' '.join(en_keywords)}".lower()

    # 1. 주제별 심층 한국어 가이드 매칭 + 검색된 실제 한글/영문 문서 구절 결합
    for guide in WAR_TOPIC_GUIDES:
        if guide["match"](search_context):
            steps_md = "\n".join(f"- {s}" for s in guide["steps"])
            # 실제 검색된 문서에서 추가 근거 표시
            matched_files = " / ".join(
                dict.fromkeys(
                    f"{d.metadata.get('file_name')} ({d.metadata.get('page_number')}쪽)"
                    for d in docs[:4]
                )
            )
            return (
                f"### 🎯 핵심 답변 ({guide['title']})\n"
                f"{guide['direct_answer']}\n\n"
                f"### 💡 원리 및 상세 해설 (한·영 매뉴얼 통합)\n"
                f"{guide['explanation']}\n\n"
                f"### ✅ 단계별 생존·행동 수칙\n"
                f"{steps_md}\n\n"
                f"### ⚠️ 핵심 주의사항\n"
                f"- {guide['warning']}\n\n"
                f"> 📖 **참고 매뉴얼 출처:** [{guide['sources']}] 및 검색된 문서 [{matched_files}]"
            )

    # 2. 일반 자유 질문: 검색된 한글 문서 + 영문 문서의 한국어 번역본에서 핵심 문장 추출
    extracted_points: list[str] = []
    source_labels: list[str] = []

    for doc in docs[:4]:
        fname = doc.metadata.get("file_name", "매뉴얼")
        page = doc.metadata.get("page_number", 1)
        lang_tag = "🇺🇸 영문→한국어 번역" if doc.metadata.get("lang") == "en" else "🇰🇷 한국어 매뉴얼"
        src_str = f"{fname} ({page}쪽 · {lang_tag})"
        if src_str not in source_labels:
            source_labels.append(src_str)

        # [영문 원문] 이전의 한국어 영역만 우선 추출
        ko_section = doc.page_content.split("[영문 원문 (Original English)]")[0]
        for line in ko_section.splitlines():
            cleaned = line.strip()
            if (
                len(cleaned) < 8
                or cleaned.startswith("[")
                or cleaned.startswith("🌐")
                or cleaned.startswith("📄")
            ):
                continue
            if len(extracted_points) < 6 and cleaned not in extracted_points:
                extracted_points.append(f"- **[{fname} {page}쪽]** {cleaned[:280]}")

    bullets_md = "\n".join(extracted_points) if extracted_points else "- 아래 참고한 매뉴얼 출처 및 번역 원문을 확인해 주세요."
    return (
        f"### 🎯 핵심 답변\n"
        f"질문하신 **'{query}'**에 대해 한글 및 영문 생존·재난 매뉴얼에서 교차 검색된 한국어 핵심 지침입니다.\n\n"
        f"### ✅ 매뉴얼 검색 및 한국어 번역 요약\n"
        f"{bullets_md}\n\n"
        f"> 📖 **출처:** [{' / '.join(source_labels)}]"
    )


def call_opensource_ollama_llm(
    ollama_url: str,
    ollama_model: str,
    temperature: float,
    context_text: str,
    history_text: str,
    question: str,
) -> str:
    endpoint = f"{ollama_url.rstrip('/')}/api/chat"
    system_msg = (
        "너는 전시·재난·생존·응급처치 전문 AI 튜터다.\n"
        "[참고 문서]에는 한국어 매뉴얼과 영어 매뉴얼이 함께 포함되어 있다. "
        "영어 문서의 내용도 반드시 자연스러운 한국어로 번역·통합하여 답변은 100% 한국어로만 작성하라.\n"
        "1) 🎯 핵심 답변 → 2) 💡 원리 및 상세 해설 → 3) ✅ 단계별 행동수칙 → 4) 📖 출처 문서명·페이지 순서로 답하라.\n\n"
        f"[참고 문서]\n{context_text}"
    )
    payload = json.dumps(
        {
            "model": ollama_model,
            "stream": False,
            "options": {"temperature": temperature},
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": f"[이전 대화]\n{history_text}\n\n[질문]\n{question}"},
            ],
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        endpoint, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        return data.get("message", {}).get("content", "").strip()


@st.cache_data(show_spinner=False, ttl=3600)
def generate_cached_llm_answer(
    api_key: str,
    primary_model: str,
    temperature: float,
    context_text: str,
    history_text: str,
    question: str,
) -> tuple[str, str]:
    candidate_models = [primary_model]
    for fb in ["gemini-2.5-flash-lite", "gemini-2.0-flash-lite", "gemini-2.5-flash", "gemini-2.0-flash"]:
        if fb not in candidate_models:
            candidate_models.append(fb)

    rag_prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "너는 전시·재난·생존·응급처치 전문 AI 튜터다.\n"
                "[참고 문서]에는 한국어 문서와 영문 문서(FEMA, 미 육군 생존·응급처치 교범 등)가 함께 들어 있다.\n"
                "영문 문서에서 찾은 내용도 반드시 자연스럽고 정확한 **한국어**로 번역·통합하여 다음 4단계 구조로 설명하라:\n"
                "1) ### 🎯 핵심 답변: 질문에 대한 명확한 한국어 결론 2~3문장\n"
                "2) ### 💡 원리 및 상세 해설: 왜 그렇게 행동해야 하는지 원리·배경 설명\n"
                "3) ### ✅ 단계별 생존·행동 수칙: 구체적인 절차와 수치(시간, 비율, 거리 등)를 3~5개 항목으로 정리\n"
                "4) > 📖 **출처:** 참고한 한글·영문 문서명과 페이지 번호 표기\n\n"
                "[참고 문서]\n{context}",
            ),
            ("human", "[이전 대화]\n{chat_history}\n\n[질문]\n{question}"),
        ]
    )

    last_err = None
    for m_name in candidate_models:
        try:
            llm = ChatGoogleGenerativeAI(
                model=m_name,
                temperature=temperature,
                max_output_tokens=1100,
                google_api_key=api_key,
            )
            ans = (rag_prompt | llm | StrOutputParser()).invoke(
                {"context": context_text, "chat_history": history_text, "question": question}
            )
            return ans, m_name
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"API 호출 실패: {last_err}")


def split_brief_and_detail(markdown_text: str) -> tuple[str, str]:
    """답변을 [간단한 핵심 답변]과 [자세히 보기용 상세 해설]로 분리합니다."""
    text = (markdown_text or "").strip()
    # 숫자 범위 물결표(~)가 GFM 취소선으로 오인식되지 않도록 이스케이프 및 따옴표 굵게(**) 교정
    text = text.replace("~", r"\~")
    text = re.sub(r'\*\*"([^"]+)"\*\*', r'"**\1**"', text)
    text = re.sub(r"\*\*'([^']+)'\*\*", r"'**\1**'", text)
    m = re.search(r"\n+(?=###\s*(?:💡|✅|📌|⚠️|2\.|원리|상세|단계별|매뉴얼|관련))", text)
    if m and m.start() > 0:
        return text[: m.start()].strip(), text[m.start() :].strip()
    paras = re.split(r"\n\n+", text)
    if len(paras) >= 3:
        cut = 2 if paras[0].startswith("###") else 1
        return "\n\n".join(paras[:cut]).strip(), "\n\n".join(paras[cut:]).strip()
    return text, ""


def format_chat_history(messages: list[dict], max_turns: int = 2) -> str:
    recent = messages[-(max_turns * 2) :]
    if not recent:
        return "없음"
    return "\n".join(
        f"{'사용자' if m['role'] == 'user' else 'AI'}: {m['content'][:200]}" for m in recent
    )


def format_docs_compact(docs: list[Document], max_chars_per_doc: int = 750) -> str:
    formatted = []
    for i, doc in enumerate(docs, 1):
        fname = doc.metadata.get("file_name", "매뉴얼")
        page = doc.metadata.get("page_number", 1)
        lang = "영문→한글번역" if doc.metadata.get("lang") == "en" else "한국어"
        snippet = doc.page_content.strip()[:max_chars_per_doc]
        formatted.append(f"[문서 {i} | 출처: {fname} ({page}쪽, {lang})]\n{snippet}")
    return "\n\n---\n\n".join(formatted)


# ---------------------------------------------------------------------------
# 사이드바 설정
# ---------------------------------------------------------------------------
if "extra_chunks" not in st.session_state:
    st.session_state.extra_chunks = []
if "uploaded_pdf_names" not in st.session_state:
    st.session_state.uploaded_pdf_names = []

with st.sidebar:
    st.header("🎛️ 전시·재난 챗봇 모드 선택")

    saved_env_key = load_saved_api_key()
    default_mode_index = 2 if saved_env_key else 0

    engine_mode = st.radio(
        "사용할 챗봇 버전을 선택하세요",
        options=["offline_rag", "opensource_llm", "cloud_api"],
        index=default_mode_index,
        format_func=lambda x: {
            "offline_rag": "⚡ 1. 오프라인 한·영 번역 RAG 엔진 (API 불필요 · 0원)",
            "opensource_llm": "🦙 2. 무료 오픈소스 LLM (Ollama · 0원)",
            "cloud_api": "☁️ 3. API 사용 버전 (Gemini 초경량 · 권장)",
        }[x],
    )

    api_key_input = ""
    model_name = "gemini-2.5-flash-lite"
    ollama_model = "qwen2.5:3b"
    ollama_url = "http://localhost:11434"
    temperature = 0.1

    if engine_mode == "offline_rag":
        st.success(
            "✅ **오프라인 한·영 번역 RAG 활성**: 인터넷이나 API 키 없이 한글 질문을 한글+영어로 자동 확장해 검색하고 결과를 100% 한국어로 보여줍니다."
        )
    elif engine_mode == "opensource_llm":
        st.info("🦙 **무료 오픈소스 LLM (Ollama)**: 로컬 오픈소스 AI가 한·영 매뉴얼을 읽고 한국어로 답변합니다.")
        ollama_model = st.selectbox(
            "오픈소스 LLM 모델",
            options=["qwen2.5:3b", "exaone3.5:2.4b", "gemma2:2b", "llama3.2:3b"],
            index=0,
        )
        ollama_url = st.text_input("Ollama 주소", value="http://localhost:11434")
    else:
        if saved_env_key:
            st.success("🔒 Gemini API 키가 연결됨")
            custom_key = st.text_input("🔑 다른 API 키 사용 (선택)", value="", type="password")
            api_key_input = custom_key.strip() or saved_env_key
        else:
            api_key_input = st.text_input("🔑 Gemini API Key 입력", value="", type="password").strip()
        model_name = st.selectbox(
            "Gemini 모델 (크레딧 최소 소모 순)",
            options=["gemini-2.5-flash-lite", "gemini-2.0-flash-lite", "gemini-2.5-flash", "gemini-2.0-flash"],
            index=0,
        )

    st.divider()
    st.subheader("🔍 한·영 교차 리트리버 설정")
    search_type = st.radio(
        "검색 방식",
        options=["mmr", "similarity"],
        index=0,
        format_func=lambda x: "MMR (다양성 + 관련성 균형)" if x == "mmr" else "Similarity (단순 유사도)",
    )
    top_k = st.slider("검색할 문서 조각 수 (top-k)", 2, 6, 4)

    st.divider()
    st.subheader("📁 경로 정보")
    st.caption(f"• **PDF 데이터 폴더:** `{DATA_DIR}`")
    st.caption(f"• **시스템 폴더:** `{SYSTEM_DIR}`")

    if st.button("🔄 war/data 폴더 PDF 전체 재색인", use_container_width=True):
        with st.spinner("war/data 폴더의 모든 한글·영문 PDF를 재색인 및 오프라인 번역 중..."):
            build_offline_knowledge_base()
            st.cache_resource.clear()
            st.success("재색인 완료!")
            st.rerun()

    if st.button("🗑️ 대화 기록 초기화", use_container_width=True):
        st.session_state.messages = []
        st.rerun()


# ---------------------------------------------------------------------------
# 메인 화면
# ---------------------------------------------------------------------------
base_chunks = load_war_knowledge_base()
local_pdfs = [p.name for p in get_pdf_files()]
kb_pdf_names = sorted({c.metadata.get("file_name", "") for c in base_chunks if c.metadata.get("file_name")})
all_known_pdf_names = local_pdfs if local_pdfs else kb_pdf_names

st.title("🛡️ 전시·재난·생존 매뉴얼 한·영 통합 AI 챗봇")
st.caption(
    f"📂 **한글·영문 PDF {len(all_known_pdf_names)}종 ({len(base_chunks)}개 청크)** 학습 완료 | "
    "한국어로 질문하면 **한글+영문 매뉴얼을 동시 검색**하여 **한국어**로 답변합니다."
)

# 메인 화면 상단: PDF 추가 업로드 및 검색 범위 필터
with st.expander("📄 + 새로운 한글/영문 PDF 추가 업로드 및 검색 문서 선택 (war/data 폴더 자동 저장 지원)", expanded=False):
    col1, col2 = st.columns([3, 2])
    with col1:
        uploaded_files = st.file_uploader(
            "추가할 한글 또는 영문 PDF 파일을 선택하세요 (영문 PDF는 자동으로 오프라인 한국어 번역 색인됩니다)",
            type=["pdf"],
            accept_multiple_files=True,
        )
        save_to_data_dir = st.checkbox("업로드한 PDF를 C:\\Users\\6250h\\Desktop\\war\\data 폴더에도 영구 저장", value=True)
        if uploaded_files:
            splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=180)
            for uf in uploaded_files:
                if uf.name not in st.session_state.uploaded_pdf_names:
                    with st.spinner(f"[{uf.name}] 추출 및 오프라인 한국어 번역 색인 중..."):
                        target_save_path = DATA_DIR / uf.name
                        raw_bytes = uf.getvalue()
                        if save_to_data_dir:
                            DATA_DIR.mkdir(parents=True, exist_ok=True)
                            target_save_path.write_bytes(raw_bytes)
                        else:
                            target_save_path = SYSTEM_DIR / f"_tmp_{uf.name}"
                            target_save_path.write_bytes(raw_bytes)

                        try:
                            reader = pypdf.PdfReader(str(target_save_path))
                            new_docs = []
                            for idx, page in enumerate(reader.pages):
                                pno = idx + 1
                                txt = re.sub(r"\s+", " ", (page.extract_text() or "").strip())
                                if len(txt) < 20:
                                    continue
                                lang = "en" if is_mostly_english(txt) else "ko"
                                if lang == "en":
                                    ko_trans = translate_en_to_ko_offline(txt)
                                    content = (
                                        f"[{uf.name} - {pno}쪽 (영문 매뉴얼 → 한국어 번역)]\n"
                                        f"{ko_trans}\n\n[영문 원문 (Original English)]\n{txt}"
                                    )
                                else:
                                    content = f"[{uf.name} - {pno}쪽 (한국어 매뉴얼)]\n{txt}"
                                new_docs.append(
                                    Document(
                                        page_content=content,
                                        metadata={"file_name": uf.name, "page_number": pno, "lang": lang},
                                    )
                                )
                            split_new = splitter.split_documents(new_docs)
                            st.session_state.extra_chunks.extend(split_new)
                            st.session_state.uploaded_pdf_names.append(uf.name)
                            st.success(f"✅ {uf.name}: {len(split_new)}개 한·영 청크 추가 완료!")
                        finally:
                            if not save_to_data_dir and target_save_path.exists():
                                target_save_path.unlink()

    with col2:
        doc_filter_options = (
            ["전체 한글+영문 PDF 통합 검색"]
            + ["🇰🇷 한국어 PDF 문서만 검색", "🇺🇸 영문 PDF 문서(한국어 번역)만 검색"]
            + all_known_pdf_names
            + st.session_state.uploaded_pdf_names
        )
        selected_pdf_filter = st.selectbox("📚 검색 대상 PDF 범위 선택", options=doc_filter_options, index=0)

if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": (
                "안녕하세요! `C:\\Users\\6250h\\Desktop\\war\\data` 폴더의 **한글 및 영문 전시·재난·생존 매뉴얼 32종**(행정안전부 비상시 국민행동요령, FEMA 핵폭발 72시간 가이드, 미 육군 생존교범 FM 21-76/ATP 3-50-21, 야전 응급처치 FM 4-25-11, 스카우트 로프 매듭법 등)을 통합 학습한 AI 생존 도우미입니다.\n\n"
                "**한국어로 질문**하시면 오프라인에서도 **한글 + 영어 검색어로 자동 변환**하여 영문 매뉴얼까지 모두 검색한 뒤 **한국어로 번역·정리**해 드립니다!"
            ),
        }
    ]

sample_questions = [
    "핵폭발 및 방사능 낙진 발생 후 초기 72시간 동안 어떻게 행동해야 하나요?",
    "비상시 오염된 물을 안전하게 정수·소독해서 식수로 만드는 방법은?",
    "출혈이 심할 때 지혈대(토니켓) 사용법과 야전 응급처치 순서를 알려줘",
    "생존 및 구조에 꼭 필요한 보우라인·클로브히치 등 로프 매듭법 알려줘",
    "화생방(화학·독가스) 공격 시 대피 요령은 핵·폭격 대피와 무엇이 다른가요?",
    "전시·재난 대비 72시간 생존배낭(비상물품)에는 무엇을 챙겨야 하나요?",
]

cols = st.columns(3)
selected_sample = None
for i, sq in enumerate(sample_questions):
    if cols[i % 3].button(f"💡 {sq}", use_container_width=True):
        selected_sample = sq

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg["role"] == "assistant":
            brief_md, detail_md = split_brief_and_detail(msg["content"])
            st.markdown(brief_md)
            if detail_md:
                with st.expander("🔍 자세히 보기 (원리 · 단계별 행동수칙 · 주의사항 펼치기)"):
                    st.markdown(detail_md)
        else:
            st.markdown(msg["content"])
        if msg.get("bilingual_query"):
            st.caption(f"🌐 **한·영 교차 검색어:** `{msg['bilingual_query']}`")
        if msg.get("sources"):
            with st.expander("📖 참고한 한글·영문 매뉴얼 출처 및 한국어 번역 원문 보기"):
                for s in msg["sources"]:
                    st.markdown(f"**• {s['title']}**")
                    st.caption(s["preview"])

user_input = st.chat_input("한국어로 질문하세요 (예: 핵폭발 72시간 행동요령, 식수 소독법, 지혈대 사용법, 보우라인 매듭법, 야전 불 피우기)...")
query = selected_sample or user_input

if query:
    st.session_state.messages.append({"role": "user", "content": query})
    with st.chat_message("user"):
        st.markdown(query)

    with st.chat_message("assistant"):
        all_chunks = base_chunks + st.session_state.extra_chunks
        if selected_pdf_filter == "🇰🇷 한국어 PDF 문서만 검색":
            pool = [c for c in all_chunks if c.metadata.get("lang") == "ko"] or all_chunks
        elif selected_pdf_filter == "🇺🇸 영문 PDF 문서(한국어 번역)만 검색":
            pool = [c for c in all_chunks if c.metadata.get("lang") == "en"] or all_chunks
        elif selected_pdf_filter != "전체 한글+영문 PDF 통합 검색":
            pool = [c for c in all_chunks if c.metadata.get("file_name") == selected_pdf_filter] or all_chunks
        else:
            pool = all_chunks

        # 1. 한국어 질문 → [한글 + 영문 번역] 양방향 검색어 확장
        display_bilingual, effective_search, ko_kws, en_kws = rewrite_bilingual_query(
            query, st.session_state.messages
        )
        st.caption(f"🌐 **오프라인 한·영 교차 검색:** `{display_bilingual}`")

        # 2. 한글 + 영문 PDF 통합 MMR 검색
        retrieved_docs = retrieve_bilingual_mmr(
            pool, ko_kws, en_kws, effective_search, top_k=top_k, search_type=search_type
        )
        context_text = format_docs_compact(retrieved_docs)
        history_text = format_chat_history(st.session_state.messages[:-1])

        # 3. 선택된 모드에 따라 100% 한국어 답변 생성
        if engine_mode == "offline_rag":
            answer = synthesize_offline_korean_answer(query, retrieved_docs, ko_kws, en_kws)
        elif engine_mode == "opensource_llm":
            with st.spinner(f"🦙 무료 오픈소스 LLM ({ollama_model})이 한·영 문서를 한국어로 종합 중..."):
                try:
                    answer = call_opensource_ollama_llm(
                        ollama_url, ollama_model, temperature, context_text, history_text, query
                    )
                except Exception:
                    answer = synthesize_offline_korean_answer(query, retrieved_docs, ko_kws, en_kws)
        else:
            if not api_key_input:
                answer = synthesize_offline_korean_answer(query, retrieved_docs, ko_kws, en_kws)
            else:
                with st.spinner(f"☁️ 초경량 모델({model_name})이 한·영 문서를 한국어로 종합 중..."):
                    try:
                        answer, _ = generate_cached_llm_answer(
                            api_key_input, model_name, temperature, context_text, history_text, query
                        )
                    except Exception:
                        answer = synthesize_offline_korean_answer(query, retrieved_docs, ko_kws, en_kws)

        brief_md, detail_md = split_brief_and_detail(answer)
        st.markdown(brief_md)
        if detail_md:
            with st.expander("🔍 자세히 보기 (원리 · 단계별 행동수칙 · 주의사항 펼치기)"):
                st.markdown(detail_md)

        sources_info = []
        for doc in retrieved_docs:
            fname = doc.metadata.get("file_name", "매뉴얼")
            page = doc.metadata.get("page_number", 1)
            lang_badge = "🇺🇸 영문→🇰🇷 한국어 완역" if doc.metadata.get("lang") == "en" else "🇰🇷 한국어 원문"
            ko_body = (doc.metadata.get("ko_text") or doc.page_content.split("[🇺🇸 영문 원문")[0]).strip()
            preview = f"🇰🇷 [한국어 완역본]: {ko_body[:450]}"
            sources_info.append({"title": f"[{lang_badge}] {fname} ({page}쪽)", "preview": preview})

        with st.expander("📖 참고한 한글·영문 매뉴얼 출처 및 한국어 번역 원문 보기"):
            for s in sources_info:
                st.markdown(f"**• {s['title']}**")
                st.caption(s["preview"])

        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": answer,
                "bilingual_query": display_bilingual,
                "sources": sources_info,
            }
        )
