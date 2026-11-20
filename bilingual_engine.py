"""
[오프라인 한·영 양방향 번역 및 교차 검색(Cross-Lingual RAG) 엔진]
- 위치: C:\\Users\\6250h\\Desktop\\war\\system\\bilingual_engine.py
- 역할:
  1) 한국어 질문 입력 시 오프라인 한영 전문용어 사전을 통해 [한국어 키워드 + 영어 번역 키워드]로 동시 확장
  2) 영어 PDF 청크를 오프라인 규칙/구문 번역기 및 사전 번역 캐시로 한국어로 변환
  3) 한글 PDF와 영문 PDF에서 검색된 결과를 통합하여 100% 한국어(🎯 핵심 답변 -> 💡 상세 해설 -> ✅ 행동수칙)로 출력
"""

import re

# ---------------------------------------------------------------------------
# 1. 오프라인 한↔영 전시·재난·생존·응급처치·매듭 전문용어 대역 사전 (350+ 핵심 어휘)
# ---------------------------------------------------------------------------
KO_TO_EN_DICT: dict[str, list[str]] = {
    # 핵·방사능·민방위·폭격
    "핵": ["nuclear", "detonation", "atomic", "blast", "fallout"],
    "핵폭발": ["nuclear detonation", "blast", "fallout", "radiation", "72-hour", "shelter"],
    "핵공격": ["nuclear attack", "nuclear detonation", "fallout", "missile"],
    "방사능": ["radiation", "radioactive", "fallout", "contamination", "roentgen", "sievert"],
    "낙진": ["fallout", "radioactive fallout", "radiation", "dust", "decontamination"],
    "72시간": ["72-hour", "72 hours", "first 72 hours", "three days"],
    "폭격": ["bombing", "explosion", "air raid", "blast", "shelling"],
    "폭발": ["explosion", "bombing", "blast", "detonation", "debris"],
    "공습": ["air raid", "attack", "warning", "siren", "shelter"],
    "공습경보": ["air raid warning", "attack warning", "siren", "evacuate", "underground shelter"],
    "경계경보": ["alert warning", "precautionary alert", "siren", "prepare"],
    "경보": ["alert", "warning", "siren", "emergency alert", "WEA", "EAS"],
    "사이렌": ["siren", "warning signal", "alert", "wavering tone"],
    "대피": ["evacuate", "evacuation", "shelter", "get inside", "stay inside"],
    "대피소": ["shelter", "fallout shelter", "basement", "underground", "bunker"],
    "지하": ["underground", "basement", "subway", "tunnel", "shelter"],
    "실내대피": ["shelter in place", "get inside", "stay inside", "seal windows"],
    # 화생방 (CBRN / NBC)
    "화생방": ["CBRN", "NBC", "chemical", "biological", "radiological", "nuclear", "gas mask"],
    "화학": ["chemical", "chemical emergency", "nerve agent", "blister agent", "toxic gas"],
    "화학무기": ["chemical weapon", "chemical agent", "nerve agent", "vapor", "aerosol"],
    "생물학": ["biological", "pathogen", "toxin", "infection", "disease"],
    "독가스": ["toxic gas", "poison gas", "chemical agent", "fumes", "upwind"],
    "방독면": ["gas mask", "protective mask", "respirator", "filter", "seal"],
    "제독": ["decontamination", "decontaminate", "wash", "remove clothing", "soap and water"],
    "오염": ["contamination", "contaminated", "decontamination", "fallout"],
    # 비상물품·생존배낭·식량·식수
    "생존배낭": ["emergency supply", "go bag", "bug out bag", "emergency kit", "72-hour kit"],
    "비상물품": ["emergency supply list", "kit", "supplies", "food", "water", "flashlight"],
    "비상식량": ["emergency food", "non-perishable food", "ration", "canned food", "water"],
    "준비물": ["supplies", "preparedness", "emergency kit", "checklist"],
    "물": ["water", "drinking water", "make water safe", "purification", "boil", "bleach"],
    "식수": ["drinking water", "safe water", "water purification", "boil", "chlorine", "bleach"],
    "정수": ["water purification", "make water safe", "boiling", "disinfection", "filtration", "bleach"],
    "소독": ["disinfection", "sanitize", "bleach", "chlorine", "iodine", "boil"],
    "락스": ["bleach", "household bleach", "sodium hypochlorite", "drops per gallon", "unscented"],
    "끓이기": ["boiling", "rolling boil", "1 minute", "water purification"],
    # 야전 생존 (US Army Survival FM 21-76 / ATP 3-50-21)
    "생존": ["survival", "survive", "evasion", "recovery", "wilderness"],
    "은신처": ["shelter", "bivouac", "lean-to", "poncho shelter", "debris hut", "snow cave"],
    "셸터": ["shelter", "poncho", "lean-to", "bivouac", "tarp"],
    "불": ["fire", "fire craft", "tinder", "kindling", "fuel", "ignition", "spark"],
    "불피우기": ["fire craft", "build a fire", "tinder", "kindling", "fuel", "bow drill", "tepee"],
    "부싯깃": ["tinder", "kindling", "fuel", "spark", "char cloth"],
    "식물": ["edible plants", "plant", "universal edibility test", "poisonous plants"],
    "식용식물": ["edible plants", "universal edibility test", "berries", "roots"],
    "독초": ["poisonous plants", "toxic", "mushroom", "avoid", "contact dermatitis"],
    "방향": ["navigation", "direction", "compass", "shadow-tip", "north star", "sun"],
    "길찾기": ["navigation", "land navigation", "shadow-tip method", "watch method", "Polaris"],
    "나침반": ["compass", "azimuth", "north", "navigation"],
    "신호": ["signaling", "signal mirror", "smoke", "fire signal", "SOS", "ground-to-air"],
    "구조": ["rescue", "recovery", "signaling", "distress signal"],
    "도하": ["water crossing", "river", "rapids", "raft", "flotation"],
    # 응급처치·의학 (FM 4-25-11 / ST 31-91B)
    "응급처치": ["first aid", "medical", "lifesaving", "airway", "bleeding", "shock"],
    "출혈": ["bleeding", "hemorrhage", "direct pressure", "pressure dressing", "tourniquet"],
    "지혈": ["stop bleeding", "control bleeding", "direct pressure", "elevation", "pressure point", "tourniquet"],
    "지혈대": ["tourniquet", "amputation", "arterial bleeding", "band"],
    "토니켓": ["tourniquet", "bleeding", "arterial"],
    "기도": ["airway", "open the airway", "head-tilt", "chin-lift", "jaw-thrust", "breathing"],
    "호흡": ["breathing", "rescue breathing", "airway", "CPR", "artificial respiration"],
    "심폐소생술": ["CPR", "cardiopulmonary resuscitation", "chest compressions", "rescue breathing"],
    "쇼크": ["shock", "hypovolemic shock", "elevate legs", "keep warm", "reassure"],
    "골절": ["fracture", "splint", "broken bone", "immobilize", "open fracture", "closed fracture"],
    "부목": ["splint", "immobilize", "fracture", "padding", "sling"],
    "화상": ["burn", "thermal burn", "chemical burn", "electrical burn", "blister", "dressing"],
    "상처": ["wound", "dressing", "bandage", "infection", "chest wound", "abdominal wound"],
    "저체온증": ["hypothermia", "cold injury", "frostbite", "rewarm", "trench foot"],
    "동상": ["frostbite", "cold injury", "hypothermia", "rewarm"],
    "열사병": ["heat stroke", "heat exhaustion", "heat cramps", "hydration", "cool"],
    "질병": ["illness", "preventing illness", "hygiene", "handwashing", "sanitation", "diarrhea"],
    "위생": ["hygiene", "sanitation", "handwashing", "clean water", "prevent illness"],
    # 로프 매듭법 (Scout Knots)
    "매듭": ["knot", "knots", "rope", "hitch", "bend", "loop", "lashing"],
    "로프": ["rope", "cord", "knot", "bight", "running end", "standing part"],
    "보우라인": ["bowline", "rescue loop", "fixed loop", "king of knots"],
    "클로브히치": ["clove hitch", "post", "pole", "lashing"],
    "스퀘어노트": ["square knot", "reef knot", "joining two ropes"],
    "사각매듭": ["square knot", "reef knot", "right over left"],
    "팔자매듭": ["figure eight", "figure-of-eight", "stopper knot", "figure 8 loop"],
    "도르래매듭": ["taut-line hitch", "adjustable loop", "tent guy line"],
    "시트벤드": ["sheet bend", "joining ropes of different thickness"],
    "투하프히치": ["two half hitches", "mooring", "tying to a post"],
    "팀버히치": ["timber hitch", "dragging logs", "wood"],
}

# 영어 → 한국어 핵심 문장·어휘 오프라인 번역 사전 (긴 구문부터 우선 매칭)
EN_TO_KO_PHRASES: list[tuple[str, str]] = [
    ("get inside, stay inside, stay tuned", "건물 내부로 즉시 대피(Get Inside)하고, 실내에 머물며(Stay Inside), 재난 방송을 청취(Stay Tuned)하십시오"),
    ("get inside", "즉시 실내(건물 내부·지하)로 대피"),
    ("stay inside", "실내에 계속 머무르기(최소 24~72시간)"),
    ("stay tuned", "공식 재난방송·라디오·경보에 귀 기울이기"),
    ("nuclear detonation", "핵폭발"),
    ("radioactive fallout", "방사능 낙진"),
    ("fallout shelter", "방사능 낙진 대피소"),
    ("first 72 hours", "초기 72시간(3일)"),
    ("shelter in place", "실내 대피(창문·환기구 밀폐 후 실내 대기)"),
    ("make water safe", "오염된 물을 안전한 식수로 정수·소독"),
    ("rolling boil for 1 minute", "1분 이상 팔팔 끓이기(가장 확실한 살균법)"),
    ("rolling boil", "팔팔 끓는 상태"),
    ("household bleach", "가정용 무향 락스(차아염소산나트륨 5~9%)"),
    ("unscented liquid household chlorine bleach", "무향 가정용 액체 염소 표백제(락스)"),
    ("universal edibility test", "식용 식물 판별 테스트(피부·입술·혀·소량 섭취 8시간 경과 관찰)"),
    ("control bleeding", "출혈 지혈"),
    ("direct pressure", "직접 압박 지혈"),
    ("pressure dressing", "압박 붕대 드레싱"),
    ("pressure point", "지압점(동맥 압박점)"),
    ("tourniquet", "지혈대(토니켓 - 직접 압박으로 멈추지 않는 절단·대량 동맥출혈 시 최후 수단)"),
    ("open the airway", "기도 확보(머리 기울임-턱 들어올리기)"),
    ("head-tilt/chin-lift", "머리 기울임-턱 들어올리기(기도 확보법)"),
    ("jaw-thrust", "턱 밀어올리기(경추 손상 의심 시 기도 확보법)"),
    ("rescue breathing", "인공호흡"),
    ("fracture", "골절"),
    ("splint", "부목(골절 부위 위·아래 관절까지 고정)"),
    ("shock", "쇼크(다리를 15~30cm 높이고 보온 유지)"),
    ("decontamination", "제독(오염된 겉옷 탈의 후 비누와 물로 세척)"),
    ("remove outer clothing", "오염된 겉옷을 즉시 벗어 비닐봉지에 밀봉(방사능·화학 오염의 최대 90% 제거)"),
    ("bowline", "보우라인 매듭(절대 풀리지 않는 고정 고리를 만드는 인명구조용 핵심 매듭)"),
    ("clove hitch", "클로브 히치(기둥이나 말뚝에 로프를 고정할 때 쓰는 기본 매듭)"),
    ("square knot", "스퀘어 노트(사각매듭/리프노트 - 굵기가 같은 두 로프를 잇거나 붕대를 묶는 매듭)"),
    ("sheet bend", "시트 벤드(굵기가 서로 다른 두 로프를 단단히 연결하는 매듭)"),
    ("figure-of-eight", "8자 매듭(로프 끝이 빠지지 않게 막는 스토퍼 매듭 및 고정 고리)"),
    ("figure eight", "8자 매듭(스토퍼 및 고리 매듭)"),
    ("taut-line hitch", "타우트라인 히치(텐트 줄처럼 길이를 자유롭게 조절하고 고정하는 매듭)"),
    ("two half hitches", "투 하프 히치(기둥이나 고리에 로프를 빠르게 묶는 매듭)"),
    ("timber hitch", "팀버 히치(통나무나 무거운 짐을 끌거나 들어 올릴 때 조여지는 매듭)"),
    ("tinder", "부싯깃(불씨를 처음 붙이는 마른 풀·자작나무 껍질·솜 등)"),
    ("kindling", "소형 땔감(부싯깃의 불을 키우는 잔가지)"),
    ("fuel", "주 땔감(불을 오래 유지하는 굵은 나무)"),
    ("shadow-tip method", "그림자 끝 법칙(막대기 그림자 이동으로 동서남북 방향을 찾는 방법)"),
    ("emergency supply", "비상 생존 물품"),
    ("first aid", "응급처치"),
    ("radiation", "방사능/방사선"),
    ("fallout", "낙진"),
    ("shelter", "대피소/은신처"),
    ("evacuate", "대피하다"),
    ("water", "물/식수"),
    ("food", "식량"),
    ("bleeding", "출혈"),
    ("wound", "상처"),
    ("burn", "화상"),
    ("bandage", "붕대"),
    ("rope", "로프"),
    ("knot", "매듭"),
]


def is_mostly_english(text: str) -> bool:
    ascii_cnt = len(re.findall(r"[A-Za-z]", text or ""))
    ko_cnt = len(re.findall(r"[가-힣]", text or ""))
    return ascii_cnt > 20 and ascii_cnt > ko_cnt * 1.5


def translate_en_to_ko_offline(en_text: str) -> str:
    """
    100% 오프라인 환경에서도 영문 매뉴얼 구절의 핵심 의미와 전문용어를 한국어로 변환합니다.
    """
    if not en_text:
        return ""
    if not is_mostly_english(en_text):
        return en_text

    # 1. 문장 안에 포함된 핵심 영어 구문/전문용어 한국어 해설 추출
    lower_txt = en_text.lower()
    matched_meanings: list[str] = []
    translated_inline = en_text

    for en_phrase, ko_meaning in EN_TO_KO_PHRASES:
        if en_phrase in lower_txt:
            short_ko = ko_meaning.split("(")[0].strip()
            if f"• {en_phrase}: {ko_meaning}" not in matched_meanings:
                matched_meanings.append(f"• **{en_phrase}** → {ko_meaning}")
            # 본문 내에도 한국어 병기
            pattern = re.compile(re.escape(en_phrase), re.IGNORECASE)
            translated_inline = pattern.sub(f"{short_ko}({en_phrase})", translated_inline, count=2)

    # 2. 숫자와 단위(시간, 거리, 온도, 용량) 한국어 변환
    translated_inline = re.sub(r"\b(\d+)\s*hours?\b", r"\1시간", translated_inline, flags=re.IGNORECASE)
    translated_inline = re.sub(r"\b(\d+)\s*minutes?\b", r"\1분", translated_inline, flags=re.IGNORECASE)
    translated_inline = re.sub(r"\b(\d+)\s*seconds?\b", r"\1초", translated_inline, flags=re.IGNORECASE)
    translated_inline = re.sub(r"\b(\d+)\s*days?\b", r"\1일", translated_inline, flags=re.IGNORECASE)
    translated_inline = re.sub(r"\b(\d+)\s*gallons?\b", r"\1갤런(약 3.8L×\1)", translated_inline, flags=re.IGNORECASE)
    translated_inline = re.sub(r"\b(\d+)\s*quarts?\b", r"\1쿼트(약 0.95L×\1)", translated_inline, flags=re.IGNORECASE)
    translated_inline = re.sub(r"\b(\d+)\s*drops?\b", r"\1방울", translated_inline, flags=re.IGNORECASE)
    translated_inline = re.sub(r"\b(\d+)\s*feet\b", r"\1피트", translated_inline, flags=re.IGNORECASE)
    translated_inline = re.sub(r"\b(\d+)\s*miles?\b", r"\1마일", translated_inline, flags=re.IGNORECASE)

    if matched_meanings:
        summary_header = "🌐 **[오프라인 한·영 핵심 번역 해설]**\n" + "\n".join(matched_meanings[:8])
        return f"{summary_header}\n\n📄 **[영문-한글 병기 본문]**\n{translated_inline}"
    return f"📄 **[영문-한글 병기 본문]**\n{translated_inline}"


# ---------------------------------------------------------------------------
# 2. 한국어 질문 → [한국어 + 영어] 양방향 검색어 확장기 (Offline Cross-Lingual Query Rewriter)
# ---------------------------------------------------------------------------
STOP_SUFFIX_RE = re.compile(
    r"(은|는|이|가|을|를|에|에서|으로|로|과|와|도|만|의|에게|께|한테|부터|까지|이란|란|에는|에서는|할\s*때|할때|시에|시에는|대해|대한|관련|어떻게|어떡해|어케|무엇인가요|무엇인지|뭔가요|뭔지|뭐야|뭔데|알려줘|알려주세요|설명해줘|설명해주세요|해줘|해주세요|되나요|돼요|할까요|있나요|있어|이유는|이유가|왜)$"
)


def extract_ko_keywords(text: str) -> list[str]:
    cleaned = re.sub(r"[?!.,~\"'()\[\]{}]", " ", text or "")
    cleaned = re.sub(
        r"(어떻게|어떡해|어케|무엇인가요|뭔가요|뭐야|알려줘|알려주세요|설명해줘|설명해주세요|해줘|해주세요|되나요|있나요|있어)",
        " ",
        cleaned,
    ).strip()
    kws: list[str] = []
    for w in cleaned.split():
        if len(w) < 2:
            continue
        stripped = STOP_SUFFIX_RE.sub("", w).strip()
        cand = stripped if len(stripped) >= 2 else w
        if cand not in {"그냥", "그러면", "그럼", "그리고", "혹시", "만약", "어떤", "무슨", "얼마나", "무엇", "방법"}:
            if cand not in kws:
                kws.append(cand)
    return kws


def rewrite_bilingual_query(raw_query: str, history_messages: list[dict] | None = None) -> tuple[str, str, list[str], list[str]]:
    """
    한국어 질문을 받아:
    1) 한국어 핵심 키워드 추출 (ko_keywords)
    2) 오프라인 한영 사전을 통해 대응하는 영어 검색 키워드 자동 번역 (en_keywords)
    3) 화면 표시용 한·영 교차 검색어 문자열 (display_rewritten)
    4) 실제 한·영 문서 통합 검색용 쿼리 (effective_search_query)
    를 반환합니다.
    """
    base = (raw_query or "").strip()
    prev_kws: list[str] = []

    if history_messages and (
        bool(re.match(r"^(그거|그건|그때|거기|이\s*경우|그럼|그러면|여기서|또|추가로)", base))
        or len(base) <= 10
    ):
        prev_user = next(
            (m["content"] for m in reversed(history_messages[:-1]) if m.get("role") == "user"),
            "",
        )
        prev_kws = extract_ko_keywords(prev_user)[:3]

    ko_keywords = list(dict.fromkeys(prev_kws + extract_ko_keywords(base)))
    en_keywords: list[str] = []

    full_ko_context = f"{' '.join(prev_kws)} {base}".lower()
    for ko_term, en_list in KO_TO_EN_DICT.items():
        if ko_term in full_ko_context:
            for en_w in en_list:
                if en_w not in en_keywords:
                    en_keywords.append(en_w)

    # 만약 사전에 직접 매칭된 단어가 없더라도 기본 생존/비상 키워드 보강
    if not en_keywords and ko_keywords:
        for kw in ko_keywords:
            for ko_term, en_list in KO_TO_EN_DICT.items():
                if kw in ko_term or ko_term in kw:
                    for en_w in en_list[:3]:
                        if en_w not in en_keywords:
                            en_keywords.append(en_w)

    ko_str = ", ".join(ko_keywords[:6]) if ko_keywords else base
    en_str = ", ".join(en_keywords[:8]) if en_keywords else "emergency survival guide"

    display_rewritten = f"🇰🇷 한글 검색어: [{ko_str}] ⇄ 🇺🇸 영문 번역 검색어: [{en_str}]"
    effective_search_query = f"{base} {' '.join(ko_keywords)} {' '.join(en_keywords)}".strip()
    return display_rewritten, effective_search_query, ko_keywords, en_keywords


# ---------------------------------------------------------------------------
# 3. 한·영 PDF 통합 매뉴얼 핵심 주제별 심층 한국어 가이드 (오프라인 100% 한국어 완벽 응답)
# ---------------------------------------------------------------------------
WAR_TOPIC_GUIDES = [
    {
        "match": lambda q: any(k in q for k in ["핵", "핵폭발", "방사능", "낙진", "72시간", "nuclear", "fallout"]),
        "title": "핵폭발 및 방사능 낙진 발생 시 생존 행동요령 (초기 72시간 가이드)",
        "direct_answer": (
            "핵폭발 발생 시 가장 중요한 생존 원칙은 **'즉시 실내 대피(Get Inside) → 최소 24~72시간 실내 대기(Stay Inside) → 재난방송 청취(Stay Tuned)'**입니다. "
            "섬광을 목격하면 절대 바라보지 말고 즉시 바닥에 엎드려 충격파가 지나간 뒤 **10~15분 이내에 지하시설이나 콘크리트 건물 중앙**으로 대피해야 방사능 낙진 피폭을 막을 수 있습니다."
        ),
        "explanation": (
            "미 연방재난관리청(FEMA)의 『핵폭발 후 초기 72시간 가이드(Nuclear Detonation 72-Hour Guide)』와 행정안전부 『2026 비상시 국민행동요령』에 따르면, "
            "핵폭발 직후 하늘로 솟구친 방사성 물질(낙진, Fallout)은 폭발 후 **약 10~15분 뒤부터 지상으로 떨어지기 시작**하며 처음 24~72시간 동안 방사선량이 가장 치명적입니다. "
            "다행히 방사능 낙진의 강도는 시간이 지날수록 급격히 감소(7시간 경과 시 초기의 1/10, 49시간 경과 시 1/100로 감쇠)하므로, 초기 24~72시간 동안 두꺼운 콘크리트나 지하 공간 안에 머무는 것만으로도 생존율을 극적으로 높일 수 있습니다."
        ),
        "steps": [
            "**[폭발 순간 - 즉시 방호]:** 밝은 섬광을 보면 절대 쳐다보지 말고 즉시 폭발 반대 방향으로 엎드려 **양손으로 눈과 귀를 막고 입을 약간 벌려** 고막 파열과 실명을 예방합니다.",
            "**[10~15분 이내 - 실내·지하 대피 (Get Inside)]:** 폭풍(충격파)이 지나간 즉시 낙진이 내리기 전에 **지하철역, 지하주차장, 또는 다층 콘크리트 건물의 정중앙**으로 대피합니다. 차량 내부는 방사능 차폐력이 거의 없으므로 차를 버리고 건물 안으로 들어가야 합니다.",
            "**[오염 제거 - 겉옷 탈의 및 세척 (Decontamination)]:** 외부에 있었다면 건물 진입 직후 **겉옷을 조심히 벗어 비닐봉지에 밀봉**(방사성 오염물질의 **최대 90% 제거**)하고, 노출된 피부와 머리카락을 비누와 미지근한 물로 씻습니다(피부를 세게 문지르거나 린스/컨디셔너를 쓰면 방사성 입자가 모발에 달라붙으므로 사용 금지).",
            "**[24~72시간 실내 대기 (Stay Inside)]:** 창문과 출입문, 환기구·에어컨을 모두 닫고 테이프로 밀폐한 뒤, 정부의 공식 이동 안내가 있을 때까지 **최소 24~72시간 동안 외출하지 말고 실내에 머뭅니다**.",
            "**[식수·식량 섭취]:** 밀폐된 용기·캔·병에 들어있던 물과 음식은 외부를 닦아낸 후 안전하게 섭취할 수 있습니다.",
        ],
        "warning": "가족을 찾으러 낙진이 쏟아지는 초기 24시간 내에 밖으로 나가는 것이 가장 위험합니다. 가족들도 각자 있는 곳의 실내에 머무는 것이 가장 안전합니다.",
        "sources": "2026_비상시국민행동요령_홍보책자(최종).pdf (16~21쪽) / fema-nuclear-detonation-72-hour-2023.pdf (1~18쪽) / GTA11-1-6.pdf",
    },
    {
        "match": lambda q: any(k in q for k in ["물", "식수", "정수", "끓이", "락스", "소독", "water", "bleach", "boil"]),
        "title": "비상·전시 상황에서 오염된 물을 안전한 식수로 정수·소독하는 방법",
        "direct_answer": (
            "비상시 오염된 물을 가장 확실하게 식수로 만드는 방법은 **① 거름망/천으로 부유물 여과 후 '1분 이상 팔팔 끓이기(Boiling)'**이며, "
            "불을 쓸 수 없을 때는 **② 무향 가정용 락스(염소 소독제)를 물 1갤런(약 3.8L)당 8방울(물 1L당 약 2방울) 넣고 30분간 두는 염소 소독법**을 사용합니다."
        ),
        "explanation": (
            "미 연방재난관리청(FEMA) 『Make Water Safe During an Emergency』 및 미 육군 생존교범(FM 21-76 / ATP 3-50-21)에 따르면, "
            "전시나 재난 시 상수도가 단수·오염되면 수인성 전염병(콜레라, 이질, 설사병)과 탈수가 생명을 위협합니다. "
            "끓이기는 박테리아, 바이러스, 기생충을 모두 사멸시키는 가장 확실한 방법이며, 락스(차아염소산나트륨)나 정수 알약(요오드·이산화염소)은 연료가 없을 때 대량의 물을 안전하게 살균할 수 있습니다."
        ),
        "steps": [
            "**1단계 [사전 여과 (Filtration)]:** 물이 탁하거나 이물질이 있으면 끓이거나 소독하기 전에 깨끗한 천, 커피 필터, 페이퍼 타월, 또는 모래·숯·자갈 간이 여과기로 부유물을 먼저 걸러냅니다.",
            "**2단계 방법 A [끓이기 (Boiling - 가장 권장)]:** 물을 **1분 이상 팔팔 끓인 뒤(해발 2,000m 이상 고지대에서는 3분간)** 자연 냉각시켜 마십니다.",
            "**2단계 방법 B [가정용 락스 소독 (Bleach Disinfection)]:** 향이나 세제가 첨가되지 않은 **무향 가정용 액체 락스(차아염소산나트륨 5~9%)**를 사용합니다. **맑은 물 1갤런(3.8L)당 8방울(1L당 약 2방울)**을 넣고(물이 탁하면 2배인 16방울), 잘 저은 뒤 **30분간 대기**합니다. 30분 후 약간의 염소 냄새가 나야 정상 살균된 것입니다.",
            "**2단계 방법 C [야전 식수 확보 (FM 21-76)]:** 빗물, 이슬, 흐르는 계곡물, 식물 증산작용(비닐봉지를 나뭇가지에 묶어 수증기 채취), 태양열 증류기(Solar Still)로 수분을 확보할 수 있습니다.",
        ],
        "warning": "방사능이나 독성 화학물질(중금속·연료·살충제)에 오염된 물은 끓이거나 락스를 넣어도 독성이 제거되지 않으므로 절대 마시면 안 되며, 밀폐 보관된 병물만 마셔야 합니다.",
        "sources": "make-water-safe-during-emergency-p.pdf (1쪽) / Preventing_Illness_During_an_Emergency_KO_final.pdf (1~2쪽) / FM_3-05.70_(FM_21-76)_Survival_-_May_2002.pdf (Chapter 6 Water)",
    },
    {
        "match": lambda q: any(k in q for k in ["출혈", "지혈", "지혈대", "토니켓", "응급처치", "기도", "쇼크", "골절", "부목", "bleeding", "tourniquet", "first aid"]),
        "title": "전시·재난 야전 응급처치 (지혈·지혈대·기도확보·쇼크·골절 처치)",
        "direct_answer": (
            "전시 및 재난 야전 응급처치의 최우선 순위는 **① 기도 확보(Airway) → ② 출혈 지혈(Bleeding) → ③ 쇼크 예방(Shock)**입니다. "
            "출혈 시에는 **직접 압박 → 거상(심장보다 높이기) → 지압점 압박** 순으로 지혈하고, 팔다리가 절단되거나 직접 압박으로 멈추지 않는 치명적 동맥 출혈에만 **지혈대(Tourniquet)**를 상처 5~10cm 위쪽에 묶습니다."
        ),
        "explanation": (
            "미 육군 응급처치 야전교범(FM 4-25-11 First Aid)과 특수부대 의무 핸드북(ST 31-91B)에서는 생명을 구하는 4대 기본 조치(4 Lifesaving Steps)로 "
            "① 기도 개방 및 호흡 회복, ② 출혈 중지 및 상처 보호, ③ 쇼크 확인 및 처치, ④ 골절 고정(부목)을 규정하고 있습니다."
        ),
        "steps": [
            "**1. 기도 확보 및 호흡 (Airway & Breathing):** 의식이 없는 환자는 **머리 기울임-턱 들어올리기(Head-tilt / Chin-lift)**(목·척추 손상 의심 시에는 **턱 밀어올리기 Jaw-thrust**)로 기도를 열고 호흡을 확인합니다.",
            "**2. 단계별 지혈법 (Control Bleeding):** ① 상처 위에 멸균 거즈(드레싱)를 대고 손으로 **5~10분간 강하게 직접 압박(Direct Pressure)** → ② 골절이 없다면 출혈 부위를 **심장보다 높게 올림(Elevation)** → ③ 멈추지 않으면 상처와 심장 사이의 동맥 **지압점(Pressure Point)**을 함께 압박합니다. (피가 젖어도 처음 댄 드레싱을 떼어내지 말고 그 위에 덧대어 묶습니다.)",
            "**3. 지혈대(Tourniquet) 사용법:** 팔·다리 절단이나 대량 동맥 출혈로 생명이 위독할 때만 **상처 바로 위 5~10cm(2~4인치) 지점(관절 부위 제외)**에 폭 5cm 이상의 띠를 감고 막대기로 비틀어 피가 멈출 때까지 조인 뒤, **환자 이마에 'T'자와 묶은 시각을 반드시 표시**합니다(한 번 묶은 지혈대는 의료진 외에 절대 풀지 않음).",
            "**4. 쇼크(Shock) 처치:** 환자를 평평하게 눕히고(두부·흉부 손상이 없다면) **다리를 15~30cm 높여** 뇌와 심장으로 혈류를 보내며, 담요로 체온을 유지합니다.",
            "**5. 골절 및 부목(Splint):** 부러진 뼈를 억지로 맞추려 하지 말고, **골절 부위 위·아래 관절까지 포함하여 부목**을 대고 고정한 뒤 말단 맥박(혈액순환)을 확인합니다.",
        ],
        "warning": "개방성 흉부 상처(폐 관통상)는 공기가 새어 들어가지 않도록 즉시 비닐이나 밀폐 드레싱으로 3면을 테이프로 막아 긴장성 기흉을 예방해야 합니다.",
        "sources": "us-army-fm-4-25-11-first-aid-2002.pdf (Chapter 2~4) / ST31-91B.pdf / 한국어_종합_재난전쟁_생존매뉴얼.pdf",
    },
    {
        "match": lambda q: any(k in q for k in ["매듭", "로프", "보우라인", "클로브", "스퀘어", "사각매듭", "팔자매듭", "도르래", "knot", "bowline", "hitch"]),
        "title": "생존 및 구조용 필수 로프 매듭법 (Basic Survival & Scout Knots)",
        "direct_answer": (
            "재난·야전 생존에서 가장 중요한 6대 매듭은 **① 보우라인(절대 조여지지 않는 구조용 고정 고리), ② 클로브 히치(기둥 고정), ③ 스퀘어 노트/사각매듭(같은 굵기 로프 연결·붕대 묶기), ④ 시트 벤드(다른 굵기 로프 연결), ⑤ 8자 매듭(스토퍼·고리), ⑥ 타우트라인 히치(텐트·셸터 길이 조절)**입니다."
        ),
        "explanation": (
            "『Basic Scout Knots』, 『Step By Step Basic Knots』, 미 육군 생존교범(FM 21-76)에 수록된 매듭법은 은신처(셸터) 구축, 인명 구조, 응급 부목·붕대 결속, 하천 도하 및 장비 고정에 필수적입니다. "
            "좋은 생존 매듭은 **묶기 쉽고, 하중이 걸릴수록 단단해지며, 작업 후에는 쉽게 풀 수 있어야** 합니다."
        ),
        "steps": [
            "**1. 보우라인 (Bowline - '매듭의 왕' / 인명 구조용):** 로프 끝에 작은 고리(토끼 굴)를 만든 뒤, 끝줄(토끼)이 **고리 아래로 나와 → 원줄(나무) 뒤를 돌아 → 다시 고리 안으로 들어가는** 방식입니다. 큰 하중이 걸려도 고리가 절대 조여들지 않아 인명 구조 및 고정 고리로 최우선 사용됩니다.",
            "**2. 클로브 히치 (Clove Hitch - 말뚝·기둥 고정):** 기둥에 로프를 X자로 교차해 두 번 감아 두 번째 감은 줄 아래로 끝줄을 통과시킵니다. 은신처 지지대나 말뚝에 로프를 시작·고정할 때 사용합니다.",
            "**3. 스퀘어 노트 (Square Knot / 사각매듭):** **'오른줄을 왼줄 위로 감고(Right over Left), 다시 왼줄을 오른줄 위로 감는(Left over Right)'** 매듭으로, 굵기가 같은 두 줄을 잇거나 삼각건·붕대를 묶을 때 사용합니다(무거운 하중에는 풀릴 수 있으므로 인명 구조에는 사용 금지).",
            "**4. 시트 벤드 (Sheet Bend - 다른 굵기 로프 연결):** 굵은 로프 끝을 U자(Bight)로 접고, 가는 로프를 그 사이로 통과시켜 U자 전체를 감싼 뒤 자기 줄 아래로 끼워 넣습니다.",
            "**5. 8자 매듭 (Figure-Eight Knot):** 로프 끝이 도르래나 구멍에서 빠지지 않게 막는 스토퍼 매듭이며, 두 줄로 묶으면(Figure-8 on a bight) 등반·구조용 고리가 됩니다.",
            "**6. 타우트라인 히치 (Taut-Line Hitch - 길이 조절 매듭):** 고리 안쪽으로 원줄에 두 번 감고 바깥쪽에 한 번 감아 묶으며, 매듭을 위아래로 밀어 텐트나 타프(셸터) 줄의 장력을 자유롭게 조절할 수 있습니다.",
        ],
        "warning": "로프에 매듭을 묶으면 로프 자체의 인장 강도가 약 30~50% 감소하므로, 생명줄로 쓸 때는 로프의 마모 상태와 매듭 종류(보우라인·8자 고리)를 반드시 확인해야 합니다.",
        "sources": "BasicScoutKnots-All.pdf (1~20쪽) / Step_By_Step_Basic_Knots.pdf (1~2쪽) / scout-adventures-simple-knots-guide.pdf (1~4쪽)",
    },
    {
        "match": lambda q: any(k in q for k in ["화생방", "화학", "생물학", "방독면", "독가스", "제독", "chemical", "cbrn", "nbc"]),
        "title": "화생방(화학·생물학·방사능) 공격 및 화학 비상사태 행동요령",
        "direct_answer": (
            "화학·생물학(화생방) 무기나 독가스 유출 시에는 **즉시 방독면(또는 젖은 수건·비닐)으로 호흡기를 보호**하고, 대부분의 화학 작용제는 공기보다 무거워 바닥에 깔리므로 **바람이 불어오는 방향(풍상측)이나 고지대·건물 위층**으로 대피한 뒤 모든 창문과 환기구를 밀폐해야 합니다."
        ),
        "explanation": (
            "『Chemical_Emergencies_KO_final.pdf』, 『2026 비상시 국민행동요령』, 미 육군 화생방 교범(FM 203-5 / GTA 11-1-7)에 따르면, "
            "신경작용제·수포작용제 등 화학 가스는 호흡기와 피부·눈을 통해 수 초~수 분 내에 치명적인 중독을 일으킵니다. 핵·폭격 시에는 '지하'로 대피하지만, **화학 가스는 공기보다 무거워 지하에 고이므로 지하 대피가 아닌 '지상 고층 건물 상층부'나 '고지대'로 대피**하는 것이 결정적 차이점입니다."
        ),
        "steps": [
            "**1. 호흡기 즉각 보호:** 화생방 경보가 울리거나 이상한 냄새·연기·안개·자극이 느껴지면 즉시 숨을 멈추고 **방독면**을 착용합니다(방독면이 없으면 손수건·휴지에 물을 적셔 코와 입을 막고 비닐이나 우의로 피부를 가림).",
            "**2. 대피 방향 선택 (바람 방향 및 고층 대피):** 실외에 있다면 **바람이 불어오는 쪽(풍상측) 또는 바람 방향의 직각 방향**으로 이동하고, 공기보다 무거운 가스를 피해 **건물 위층(상층부)이나 높은 지대**로 대피합니다.",
            "**3. 실내 밀폐 (Shelter-in-Place):** 실내로 들어오면 에어컨·히터·환풍기를 즉시 끄고, 창문과 문틈, 환기구를 젖은 수건과 접착테이프·비닐로 완전히 밀폐합니다.",
            "**4. 오염 의복 제거 및 제독 (Decontamination):** 가스에 노출되었다면 옷을 머리 위로 벗지 말고 **가위로 잘라 벗어 비닐봉지에 이중 밀봉**한 뒤, 흐르는 다량의 물과 비누로 피부와 눈(물은 10~15분 이상)을 씻어냅니다.",
        ],
        "warning": "폭격/핵공격은 '지하'로 대피하지만, 독가스/화학무기는 지하로 가라앉으므로 '건물 상층부·고지대'로 대피해야 한다는 점을 반드시 구분하세요!",
        "sources": "Chemical_Emergencies_KO_final.pdf (1~3쪽) / 2026_비상시국민행동요령_홍보책자(최종).pdf (14~19쪽) / FM203-5.pdf / GTA11-1-7.pdf",
    },
    {
        "match": lambda q: any(k in q for k in ["생존배낭", "비상물품", "준비물", "비상식량", "키트", "가방", "supply", "kit"]),
        "title": "비상 생존배낭 (72시간 비상 대비 물품 체크리스트)",
        "direct_answer": (
            "전시 및 대형 재난 시 외부 지원 없이 가족이 **최소 72시간(3일)~2주간 버틸 수 있도록 ① 식수(1인당 하루 4L/1갤런), ② 조리 불필요 비상식량(3일분 이상), ③ 구급함·상비약, ④ 손전등·건전지식 라디오, ⑤ 방독면·마스크·보온포**를 생존배낭(Go-Bag)에 상시 구비해야 합니다."
        ),
        "explanation": (
            "행정안전부 『2026 비상시 국민행동요령』과 FEMA 『emergency-supply-list_korean.pdf』, 『kit-supplies-check.pdf』에서는 "
            "단전·단수·통신 두절 상황을 가정하여 즉시 들고 대피할 수 있는 비상용 백팩(생존배낭)과 가정 내 비축 물품을 나누어 준비할 것을 권장합니다."
        ),
        "steps": [
            "**1. 식수 및 비상식량:** **1인당 하루 최소 2~4L(1갤런)의 생수**(최소 3일분, 가능하면 2주분)와 불 없이 바로 먹을 수 있는 **통조림(캔 따개 포함), 건빵, 에너지바, 초콜릿, 레토르트 식품**",
            "**2. 정보 수신 및 조명·통신:** 건전지식 또는 자가발전(수동 크랭크) **휴대용 라디오**, LED **손전등**, 보조배터리, 여유 건전지, 호루라기(매몰 시 구조 신호용)",
            "**3. 의료 및 위생용품:** **구급상자**(소독약, 압박붕대, 거즈, 지혈대, 반창고), 개인 복용 처방약( 최소 7일분), 해열진통제, 물티슈, 쓰레기봉투, 가정용 무향 락스(식수 소독용)",
            "**4. 방호 및 보온·도구:** **방독면**(또는 N95 방진마스크), 우의·비닐시트, 접착테이프(실내 밀폐용), **은박 보온포(생존 담요)**, 침낭·여벌 옷, 다용도 칼(멀티툴), 라이터·방수성냥, 로프",
            "**5. 중요 서류 및 현금:** 신분증 사본, 가족 비상연락망 및 집결지 지도, **소액 현금**(정전 시 카드·ATM 사용 불가 대비)",
        ],
        "warning": "비상식량과 생수, 건전지, 의약품은 유통기한이 있으므로 매년 1~2회 정기적으로 점검하여 새것으로 교체(순환 비축)해야 합니다.",
        "sources": "emergency-supply-list_korean.pdf (1~2쪽) / 2026_비상시국민행동요령_리플릿(최종).pdf (1~2쪽) / kit-supplies-check.pdf",
    },
    {
        "match": lambda q: any(k in q for k in ["경보", "공습경보", "경계경보", "사이렌", "민방위", "폭격", "폭발", "alert", "siren", "bombing"]),
        "title": "민방위 경보(경계·공습·화생방) 구분 및 폭격·폭발 시 행동요령",
        "direct_answer": (
            "**경계경보**(1분간 평탄한 사이렌 음)가 울리면 즉시 대피 준비를 하고, **공습경보**(3분간 파상형 오르내리는 사이렌 음)가 울리면 **즉시 가장 가까운 지하대피소(지하철역·지하주차장)로 대피**해야 합니다. 폭격·폭발 발생 시에는 유리창에서 멀리 떨어져 책상 밑이나 내력벽 모서리에 엎드려 머리를 보호합니다."
        ),
        "explanation": (
            "『2026 비상시 국민행동요령』, 『Bombing_Explosions_KO_final.pdf』, 『ready_know-alerts-warnings_korean.pdf』에 따르면 "
            "적의 항공기·미사일·장사정포 공격 징후나 실제 공격 여부에 따라 민방위 경보가 발령되며, 사이렌 소리와 재난문자(WEA)를 즉시 식별해 행동하는 것이 생사를 가릅니다."
        ),
        "steps": [
            "**1. 경계경보 (1분간 평탄한 사이렌 음):** 적의 공격이 예상되는 상태입니다. 가스 밸브를 잠그고 전기 코드를 뽑은 뒤 **비상 생존배낭을 챙겨 대피할 준비**를 하며 방송을 청취합니다.",
            "**2. 공습경보 (3분간 물결치듯 오르내리는 파상음):** 적의 공격이 임박하거나 진행 중인 상태입니다. 생존배낭을 들고 엘리베이터 대신 **계단을 이용해 가장 가까운 지하 민방위 대피소**로 신속히 대피합니다. (운전 중이면 도로 오른쪽에 정차 후 키를 꽂아둔 채 대피)",
            "**3. 화생방경보 (음성방송 및 재난문자):** 즉시 방독면이나 젖은 수건으로 호흡기를 막고, 지하가 아닌 **고지대나 건물 상층부 실내**로 대피해 창문과 환기구를 밀폐합니다.",
            "**4. 폭격·폭발 발생 순간 (Bombing & Explosion):** 파편과 유리창 비산을 피해 창문·유리문에서 멀리 떨어지고, 튼튼한 책상·식탁 아래로 들어가 머리와 가슴을 보호합니다. 건물 밖으로 나갈 때는 엘리베이터를 절대 타지 말고, 연기가 있으면 자세를 낮추고 젖은 천으로 코와 입을 막습니다.",
            "**5. 건물 붕괴 매몰 시:** 불필요하게 소리를 질러 체력과 산소를 소모하지 말고(먼지 흡입 위험), 손전등이나 **배관·벽을 금속/돌로 규칙적으로 두드려** 구조대에 위치를 알립니다.",
        ],
        "warning": "폭발 직후 건물 밖으로 대피할 때는 낙하물(유리·간판)과 2차 폭발 위험이 있으므로 머리 위와 전선·가스 누출 여부를 반드시 살피며 이동해야 합니다.",
        "sources": "2026_비상시국민행동요령_홍보책자(최종).pdf (6~15쪽) / Bombing_Explosions_KO_final.pdf (1~3쪽) / ready_know-alerts-warnings_korean.pdf",
    },
    {
        "match": lambda q: any(k in q for k in ["은신처", "셸터", "불피우", "부싯깃", "식용식물", "독초", "길찾기", "나침반", "신호", "야전", "shelter", "fire", "edible"]),
        "title": "야전 생존 기술 (은신처 구축 · 불 피우기 · 식용식물 판별 · 방향 찾기)",
        "direct_answer": (
            "고립된 야전 생존(US Army Survival FM 21-76 / ATP 3-50-21)의 핵심은 **① 체온 유지를 위한 은신처(Shelter)와 불 피우기(부싯깃 Tinder → 잔가지 Kindling → 주땔감 Fuel), ② 그림자 끝 법칙·북극성을 이용한 방향 찾기, ③ 식용 식물 판별 테스트(Universal Edibility Test)**입니다."
        ),
        "explanation": (
            "미 육군 야전 생존교범(FM 21-76 / FM 3-05.70 / ATP 3-50-21)에서는 생존의 기본 요소로 추위·바람·비를 막아 저체온증을 예방하는 은신처와 불, 식수 확보, 식량 채집, 그리고 구조 신호 및 방향 탐색을 제시합니다."
        ),
        "steps": [
            "**1. 은신처(Shelter) 구축:** 산사태·낙석·범람 위험이 없고 바람을 막아주며 땔감과 물이 가까운 평탄한 곳을 선정합니다. 우의(판초)나 타프를 이용한 **경사형 셸터(Lean-to)**나 낙엽·나뭇가지를 두껍게 덮은 **낙엽 은신처(Debris Hut)**를 만들고, 바닥에 반드시 마른 나뭇가지·낙엽을 깔아 지면으로 빼앗기는 체온(전도열 손실)을 차단합니다.",
            "**2. 야전 불 피우기 (Fire Craft 3요소):** 불을 피우기 전 **① 부싯깃(Tinder: 마른 풀, 부들 솜, 자작나무 껍질, 보풀), ② 소형 땔감(Kindling: 연필 굵기의 마른 잔가지), ③ 주 땔감(Fuel: 팔뚝 굵기 마른 나무)**을 충분히 모아둔 뒤, 원뿔형(Tepee)이나 우물 정(井)자형(Log Cabin)으로 쌓아 아래쪽 부싯깃에 점화합니다.",
            "**3. 나침반 없이 방향 찾기 (Shadow-Tip Method):** 평평한 땅에 1m 길이의 막대기를 수직으로 꽂고 첫 번째 그림자 끝에 돌을 놓습니다. 15~20분 뒤 이동한 두 번째 그림자 끝에 돌을 놓아 **첫 번째 돌(서쪽 West)과 두 번째 돌(동쪽 East)을 선으로 이으면 동-서 축**이 만들어지고, 서쪽을 왼발에, 동쪽을 오른발에 두고 서면 정면이 **북쪽(North)**입니다.",
            "**4. 야생 식물 식용 가능 여부 테스트 (Universal Edibility Test):** 정체를 모르는 식물은 ① 한 번에 한 종류의 한 부위만 테스트 → ② 피부(팔 안쪽)에 문질러 반응 확인 → ③ 입술→입안(15분)→씹기(15분, 삼키지 않음) → ④ 이상이 없으면 소량 삼키고 **8시간 동안** 메스꺼움·복통이 없는지 확인한 뒤 섭취합니다. (우유빛 수액이 나오는 식물이나 야생 버섯은 절대 섭취 금지!)",
        ],
        "warning": "야생 버섯은 식용 판별 테스트로도 독성을 알아낼 수 없으며 치명적인 간·신장 손상을 일으키므로 야전 생존 시 절대 섭취해서는 안 됩니다.",
        "sources": "FM_3-05.70_(FM_21-76)_Survival_-_May_2002.pdf (Chapter 5, 7, 9, 18) / Survival (ATP 3-50-21).pdf",
    },
]
