# 사내 메신저 꼰대력·성격 분석기 ("꼰대 측정기") — Streamlit 단일 파일 앱
# -----------------------------------------------------------------------------
# 실행 방법
#   1) 의존성 설치 : pip install -r requirements.txt
#   2) API 키 설정  : 환경변수 OPENAI_API_KEY 또는 .streamlit/secrets.toml
#                     (secrets.toml 예) OPENAI_API_KEY = "sk-..."
#                     키 발급/관리: https://platform.openai.com/api-keys
#   3) 앱 실행      : streamlit run app.py
# -----------------------------------------------------------------------------

import os
import json
import time
import streamlit as st
import plotly.graph_objects as go
from openai import OpenAI

MODEL = "gpt-4o-mini"
MAX_INPUT_CHARS = 12000
MAX_TOKENS = 4000          # 화자별 분석을 모두 담기 위해 상향
MAX_RETRIES = 3            # 503(과부하)/429 등 일시 오류 재시도 횟수

# 화자별 레이더/뱃지 색상 팔레트 (첫 번째가 포인트 컬러)
SPEAKER_COLORS = ["#5B68C0", "#E8732C", "#2E9E5B", "#D64545", "#9333EA"]

# 디자인 토큰 (md 디자인 가이드 기반 — MS Teams 유사 flat 업무용)
ACCENT = "#5B68C0"        # 포인트 컬러 (인디고/보라)
BG_SIDEBAR = "#F5F5F5"
BG_MAIN = "#FFFFFF"
BORDER = "#E0E0E0"
CARD_RADIUS = "10px"

SYSTEM_PROMPT = """너는 사내 메신저 대화를 읽고 "꼰대력"과 "성격"을 분석하는 유머러스한 분석가다.

[화자 구분]
- 입력은 Teams DM을 복사한 것이라 보낸 사람 이름이 빠져 있을 수 있다. 줄은 메시지 단위이고 빈 줄로 구분된다.
- 줄 앞에 "이름:" 형태의 라벨이 있으면 그 라벨을 화자로 그대로 신뢰한다.
- 라벨이 없으면 1:1 DM으로 보고, 문맥(인사·질문/답변·존댓말/반말·역할)으로 메시지를 두 화자(화자A/화자B)로 나눈다. 같은 사람이 연달아 여러 줄을 보낼 수도 있음에 유의한다.
- 추론이 불확실하면 가장 그럴듯한 구분을 택하되, 결과의 dialogue 필드에 화자별로 나눈 대화를 그대로 보여줘 사용자가 검증할 수 있게 한다.

[분석 대상]
- 대화에 등장하는 "모든 화자 각각"을 개별적으로 분석한다. (1:1 DM이면 두 명 모두)
- 화자별로 점수·등급·축점수·근거·성격·한줄평·팁을 각각 산출한다.
- 사용자가 강조 대상 힌트를 주면 그 화자를 speakers 배열의 맨 앞에 둔다.

[꼰대력 채점 — 7개 축, 각 0~100]
1) 훈계·설교 (가르치려 드는 태도)
2) 라떼·과거미화 ("내가 왕년에", "요즘 애들은")
3) 일방적 지시·강요
4) 권위·서열 강조 (나이/직급/경력 들먹임)
5) 공감·경청 부족
6) 오지랖·사생활 간섭
7) 반말·하대·무시하는 말투
- 종합 점수(kkondae_score)는 위 7축의 가중 평균으로 0~100 정수로 산출한다.

[채점 철학 — 후하게]
- 이건 재미용 앱이다. 점수를 너무 박하게 주지 마라.
- 기본 20점은 깔고 시작한다. 어떤 축도 0점은 거의 주지 말고 최소 15~20점은 준다.
- 평범하게 약간의 지시·훈계 기미만 보여도 50~70점대로 후하게 쳐준다.
- 80점 이상은 정말 노골적인 꼰대 발언이 여러 번 있을 때만.
- 단, 근거(evidence)는 실제 문장에 기반해 정직하게 인용한다(점수만 후하게).

[등급]
- 0~19  : 청정 청년
- 20~39 : 새싹 꼰대
- 40~59 : 대리급 꼰대
- 60~79 : 부장급 꼰대
- 80~100: 회장님 꼰대

[근거 — 점수가 있으면 설명도 반드시]
- evidence에는 대화 속 "실제 문장"을 그대로 인용(quote)하고 짧은 reason을 붙인다. 문장은 지어내지 않는다.
- 노골적인 꼰대 발언이 없더라도, 점수를 매겼다면 그 점수가 나온 이유를 evidence에 최소 1~2개는 반드시 적는다.
  - 인용할 만한 실제 문장이 있으면 quote에 넣고, 없으면 quote는 빈 문자열("")로 두고 reason에만 말투·태도에 대한 가벼운 관찰을 적는다.
  - 예) {"quote":"", "reason":"전반적으로 단호하고 자기주장이 또렷한 편 — 살짝 마이웨이 기운"}
- evidence를 절대 빈 배열로 두지 않는다. "꼰대 발언 없음"이어도 왜 그 점수인지 한 줄은 남긴다.

[성격]
- 가볍게: 한 단어 유형(type) + 특징(traits) 3개 + 1~2문장 요약(summary).

[톤]
- 유머러스하되 인신공격/모욕은 금지.
- 점수가 낮으면 칭찬도 섞어준다.

[출력 형식]
아래 JSON "만" 반환한다. 마크다운 펜스/설명/추가 텍스트 없이 순수 JSON만 출력한다.

{
  "dialogue": [{"speaker":"화자 라벨","text":"해당 메시지"}],
  "speakers": [
    {
      "speaker": "화자 이름/라벨",
      "kkondae_score": 0~100 정수,
      "grade": "등급명",
      "axis_scores": {"훈계":n,"라떼":n,"지시":n,"권위":n,"공감부족":n,"오지랖":n,"하대":n},
      "evidence": [{"quote":"실제 인용문","reason":"한 줄 이유"}],
      "personality": {"type":"유형명","traits":["특징1","특징2","특징3"],"summary":"요약"},
      "one_liner": "재치있는 한줄평",
      "advice": "가벼운 개선 팁 한 문장"
    }
  ]
}
"""

AXIS_LABELS = {
    "훈계": "훈계·설교",
    "라떼": "라떼·과거미화",
    "지시": "일방적 지시·강요",
    "권위": "권위·서열 강조",
    "공감부족": "공감·경청 부족",
    "오지랖": "오지랖·간섭",
    "하대": "반말·하대",
}


def get_api_key():
    """환경변수 또는 secrets.toml 에서 API 키를 읽는다."""
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        try:
            key = st.secrets["OPENAI_API_KEY"]
        except Exception:
            key = None
    return key


def strip_json_fence(text: str) -> str:
    """응답이 ```json 펜스로 감싸여 오면 제거한다."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.replace("```json", "").replace("```", "").strip()
    return t


def relabel_hyphen(text: str):
    """하이픈(-) 규칙으로 화자를 확정적으로 라벨링한다.
    - '-' 로 시작하는 줄 → '나'
    - 그 외 줄          → '상대'
    하이픈이 하나도 없으면 원문을 그대로 반환(AI 추론에 맡김).
    반환: (라벨링된_텍스트, 하이픈규칙_적용여부)
    """
    lines = text.split("\n")
    has_hyphen = any(ln.strip().startswith("-") for ln in lines)
    if not has_hyphen:
        return text, False
    out = []
    for ln in lines:
        s = ln.strip()
        if not s:
            out.append("")            # 빈 줄은 메시지 구분자로 유지
        elif s.startswith("-"):
            out.append(f"나: {s[1:].strip()}")
        else:
            out.append(f"상대: {s}")
    return "\n".join(out), True


def analyze(conversation: str, target_hint: str = "") -> dict:
    """OpenAI 를 1회 호출해 분석 결과 dict 를 반환한다."""
    key = get_api_key()
    if not key:
        raise RuntimeError(
            "OPENAI_API_KEY 가 설정되지 않았습니다. 환경변수 또는 .streamlit/secrets.toml 을 확인하세요."
        )

    hint = (f"\n\n[강조 화자] 이 화자를 speakers 배열 맨 앞에 두세요: {target_hint}"
            if target_hint.strip() else "")
    user_msg = f"다음은 사내 메신저 대화입니다. 분석해 주세요.{hint}\n\n---\n{conversation}\n---"

    client = OpenAI(api_key=key)
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
            )
            cleaned = strip_json_fence(resp.choices[0].message.content)
            data = json.loads(cleaned)
            return apply_generous_scores(data)
        except Exception as ex:
            last_err = ex
            msg = str(ex)
            # 503/과부하/429(레이트리밋)만 재시도, 그 외(키 오류 등)는 즉시 중단
            transient = ("503" in msg or "UNAVAILABLE" in msg
                         or "overloaded" in msg or "429" in msg
                         or "rate limit" in msg.lower())
            if transient and attempt < MAX_RETRIES - 1:
                time.sleep(1.5 * (attempt + 1))   # 1.5s, 3s 백오프
                continue
            raise last_err


# ----------------------------------------------------------------------------
# UI
# ----------------------------------------------------------------------------

st.set_page_config(page_title="꼰대 측정기", page_icon="🧓", layout="wide")

# 전역 스타일 (md 디자인 가이드: Teams 유사 flat, 인디고 포인트)
st.markdown(
    f"""
    <style>
      html, body, [class*="css"] {{
        font-family: -apple-system, "Segoe UI", "Malgun Gothic", sans-serif;
      }}
      .stApp {{ background: {BG_MAIN}; }}
      section[data-testid="stSidebar"] {{
        background: {BG_SIDEBAR};
        border-right: 0.5px solid {BORDER};
      }}
      .kk-title {{
        font-size: 26px; font-weight: 700; color: #1F1F1F; margin-bottom: 2px;
      }}
      .kk-sub {{ color: #6B6B6B; font-size: 14px; margin-bottom: 8px; }}
      .kk-card {{
        background: {BG_MAIN};
        border: 0.5px solid {BORDER};
        border-radius: {CARD_RADIUS};
        padding: 18px 20px;
        margin-bottom: 14px;
      }}
      .kk-badge {{
        display: inline-block; padding: 4px 14px; border-radius: 999px;
        color: #fff; font-weight: 700; font-size: 15px;
      }}
      .kk-score {{
        font-size: 56px; font-weight: 800; line-height: 1; color: {ACCENT};
      }}
      .kk-axis-label {{ font-size: 14px; color: #333; margin-bottom: -6px; }}
      .stProgress > div > div > div > div {{ background-color: {ACCENT}; }}
      .kk-quote {{
        border-left: 3px solid {ACCENT}; padding-left: 10px; color: #333;
        font-style: italic; margin-bottom: 2px;
      }}
      .kk-reason {{ color: #6B6B6B; font-size: 13px; padding-left: 13px; }}
      div.stButton > button {{
        background: {ACCENT}; color: #fff; border: none; border-radius: 8px;
        font-weight: 600; padding: 8px 0;
      }}
      div.stButton > button:hover {{ background: #4a56a8; color: #fff; }}
    </style>
    """,
    unsafe_allow_html=True,
)


def grade_color(score: int) -> str:
    """점수 구간별 뱃지 색상."""
    if score < 20:
        return "#2E9E5B"   # 초록 — 청정
    if score < 40:
        return "#7DB23A"   # 연두 — 새싹
    if score < 60:
        return "#E0A800"   # 노랑 — 대리급
    if score < 80:
        return "#E8732C"   # 주황 — 부장급
    return "#D64545"       # 빨강 — 회장님


def grade_name(score: int) -> str:
    """점수로 등급명을 산출한다 (표시 점수와 항상 일치하도록 코드에서 계산)."""
    if score < 20:
        return "청정 청년"
    if score < 40:
        return "새싹 꼰대"
    if score < 60:
        return "대리급 꼰대"
    if score < 80:
        return "부장급 꼰대"
    return "회장님 꼰대"


def boost(v: int) -> int:
    """점수를 후하게 보정한다. 하한 20점 + 보통 행동은 50~70점대로."""
    try:
        v = int(v)
    except (TypeError, ValueError):
        v = 0
    return max(20, min(100, round(20 + v * 0.8)))


def apply_generous_scores(data: dict) -> dict:
    """화자별 종합점수·축점수를 후하게 보정하고 등급을 점수에 맞춰 재계산한다."""
    speakers = data.get("speakers") or [data]
    for sp in speakers:
        sp["kkondae_score"] = boost(sp.get("kkondae_score", 0))
        sp["grade"] = grade_name(sp["kkondae_score"])
        axis = sp.get("axis_scores", {}) or {}
        sp["axis_scores"] = {k: boost(axis.get(k, 0)) for k in AXIS_LABELS}
    return data


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def radar_figure(sp: dict, color: str):
    """한 화자의 7축 점수를 각진 7각형(레이더) 차트로 그린다."""
    labels = list(AXIS_LABELS.values())
    axis = sp.get("axis_scores", {})
    vals = [int(axis.get(k, 0)) for k in AXIS_LABELS]
    theta = labels + [labels[0]]      # 폐곡선을 위해 첫 축을 끝에 한 번 더
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=vals + [vals[0]],
        theta=theta,
        fill="toself",
        line=dict(color=color, width=2),
        fillcolor=_hex_to_rgba(color, 0.3),
        marker=dict(size=5, color=color),
        hovertemplate="%{theta}: %{r}<extra></extra>",
    ))
    fig.update_layout(
        polar=dict(
            gridshape="linear",   # 원형이 아니라 각진 다각형(7각형) 격자
            radialaxis=dict(visible=True, range=[0, 100], tickvals=[20, 40, 60, 80, 100],
                            tickfont=dict(size=9, color="#aaa"), gridcolor="#E0E0E0"),
            angularaxis=dict(tickfont=dict(size=12, color="#333"), gridcolor="#E0E0E0",
                             linecolor="#E0E0E0"),
            bgcolor="rgba(0,0,0,0)",
        ),
        showlegend=False,
        margin=dict(l=70, r=70, t=20, b=30),
        height=360,
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family='-apple-system, "Segoe UI", sans-serif'),
    )
    return fig


def render_speaker_detail(sp: dict, color: str):
    """한 화자의 점수·등급·성격·근거·한줄평을 카드로 렌더링한다."""
    score = int(sp.get("kkondae_score", 0))
    grade = sp.get("grade", "")
    gcolor = grade_color(score)

    st.markdown('<div class="kk-card">', unsafe_allow_html=True)
    # 그래프 상단 화자 이름
    st.markdown(
        f'<div style="font-size:20px;font-weight:700;margin-bottom:2px;text-align:center">'
        f'<span style="display:inline-block;width:11px;height:11px;border-radius:50%;'
        f'background:{color};margin-right:8px"></span>{sp.get("speaker", "?")}</div>',
        unsafe_allow_html=True)

    # 각진 7각형 레이더
    st.plotly_chart(radar_figure(sp, color), use_container_width=True,
                    config={"displayModeBar": False})

    # 종합 점수 + 등급
    c1, c2 = st.columns([1, 2])
    with c1:
        st.markdown(f'<div class="kk-score">{score}<span style="font-size:22px;color:#999"> / 100</span></div>',
                    unsafe_allow_html=True)
        st.markdown(f'<span class="kk-badge" style="background:{gcolor}">{grade}</span>',
                    unsafe_allow_html=True)
    with c2:
        st.markdown('<div style="height:18px"></div>', unsafe_allow_html=True)
        st.markdown('<div class="kk-axis-label">종합 꼰대력</div>', unsafe_allow_html=True)
        st.progress(min(max(score, 0), 100) / 100)

    # 성격
    p = sp.get("personality", {})
    st.markdown("**🧬 성격**", unsafe_allow_html=True)
    pc1, pc2 = st.columns([1, 2])
    with pc1:
        st.markdown(f'<span class="kk-badge" style="background:{ACCENT}">{p.get("type", "?")}</span>',
                    unsafe_allow_html=True)
    with pc2:
        for t in p.get("traits", []):
            st.markdown(f"- {t}")
    if p.get("summary"):
        st.markdown(f'<div style="margin:6px 0;color:#444">{p["summary"]}</div>', unsafe_allow_html=True)

    # 근거 (인용문 또는 점수 설명)
    evidence = sp.get("evidence", [])
    if evidence:
        with st.expander(f"🔍 근거·점수 설명 ({len(evidence)}건)", expanded=True):
            for e in evidence:
                q = (e.get("quote", "") or "").strip()
                if q:
                    st.markdown(f'<div class="kk-quote">“{q}”</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="kk-reason">→ {e.get("reason", "")}</div>', unsafe_allow_html=True)
    else:
        # 근거가 비어도 점수에 맞는 설명을 보여준다 (숫자-설명 모순 방지)
        if score >= 40:
            note = "콕 집을 꼰대 발언은 없지만, 은근한 기운이 점수에 살짝 반영됐어요 😏"
        elif score >= 25:
            note = "큰 꼰대 발언은 없어요. 기본 점수만 가볍게 깔린 정도! 😌"
        else:
            note = "인용할 만한 꼰대 발언이 없습니다. 아주 깨끗하네요! ✨"
        st.caption(note)

    if sp.get("one_liner"):
        st.info(f"💬 {sp['one_liner']}")
    if sp.get("advice"):
        st.success(f"💡 {sp['advice']}")
    st.markdown("</div>", unsafe_allow_html=True)


def render_result(data: dict):
    # 구버전(단일 화자) 호환: speakers 키가 없으면 전체를 한 화자로 감싼다
    speakers = data.get("speakers")
    if not speakers:
        speakers = [data]

    # 점수 한눈에 보기 (화자별 metric)
    st.markdown('<div class="kk-card">', unsafe_allow_html=True)
    st.markdown("#### 🏆 화자별 꼰대력")
    cols = st.columns(len(speakers))
    for i, (col, sp) in enumerate(zip(cols, speakers)):
        color = SPEAKER_COLORS[i % len(SPEAKER_COLORS)]
        with col:
            st.markdown(
                f'<div style="font-size:14px;color:#555">'
                f'<span style="display:inline-block;width:9px;height:9px;border-radius:50%;'
                f'background:{color};margin-right:6px"></span>{sp.get("speaker", f"화자{i+1}")}</div>'
                f'<div style="font-size:34px;font-weight:800;color:{color}">{int(sp.get("kkondae_score", 0))}'
                f'<span style="font-size:15px;color:#999"> /100</span></div>'
                f'<div style="font-size:13px;color:#777">{sp.get("grade", "")}</div>',
                unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    # 화자 구분 결과 (검증용) — Teams 복붙은 화자가 빠지므로 어떻게 나눴는지 보여준다
    dialogue = data.get("dialogue", [])
    if dialogue:
        with st.expander(f"🗣️ 화자 구분 결과 ({len(dialogue)}개 메시지) — 잘못 나뉘었다면 내 메시지 앞에 `-`를 붙여 다시 분석하세요"):
            spk_color = {sp.get("speaker"): SPEAKER_COLORS[i % len(SPEAKER_COLORS)]
                         for i, sp in enumerate(speakers)}
            for d in dialogue:
                spk = d.get("speaker", "?")
                badge_bg = spk_color.get(spk, "#9AA0B5")
                st.markdown(
                    f'<div style="margin-bottom:6px">'
                    f'<span class="kk-badge" style="background:{badge_bg};font-size:12px;padding:2px 10px">{spk}</span> '
                    f'<span style="color:#333">{d.get("text", "")}</span></div>',
                    unsafe_allow_html=True)

    # 화자별 상세 (점수/성격/근거/한줄평)
    st.markdown("#### 🧑‍🤝‍🧑 화자별 상세 분석")
    detail_cols = st.columns(len(speakers)) if len(speakers) <= 2 else [st.container() for _ in speakers]
    for i, sp in enumerate(speakers):
        color = SPEAKER_COLORS[i % len(SPEAKER_COLORS)]
        with detail_cols[i]:
            render_speaker_detail(sp, color)


# ---- 사이드바 (입력) --------------------------------------------------------
with st.sidebar:
    st.markdown('<div class="kk-title">🧓 꼰대 측정기</div>', unsafe_allow_html=True)
    st.markdown('<div class="kk-sub">사내 메신저 대화를 붙여넣으세요</div>', unsafe_allow_html=True)

    conversation = st.text_area(
        "대화 붙여넣기",
        height=300,
        placeholder="예) 내 메시지 앞에만 - 를 붙이세요\n-안녕하세요\n\n네 안녕하세요\n\n-점검서 어디 있나요?",
        label_visibility="collapsed",
    )
    target_hint = st.text_input(
        "강조할 화자 (선택)",
        placeholder="예: 나 / 상대",
        help="대화의 모든 화자를 분석합니다. 여기에 적은 화자는 맨 앞에 표시됩니다.",
    )
    st.caption("💡 **내가 보낸 메시지 앞에만 `-`(하이픈)** 을 붙이세요. "
               "그러면 `-` 있는 줄은 **나**, 없는 줄은 **상대**로 정확히 나눕니다. "
               "하이픈을 하나도 안 쓰면 AI가 문맥으로 추정합니다. (`이름:` 라벨도 인식)")
    run = st.button("분석하기", use_container_width=True)
    if st.session_state.get("result"):
        if st.button("다시 분석", use_container_width=True):
            st.session_state.pop("result", None)
            st.rerun()
    st.caption(f"모델: {MODEL} · 세션 메모리에서만 처리 (저장 없음)")


# ---- 메인 (결과) ------------------------------------------------------------
st.markdown('<div class="kk-title">꼰대력·성격 분석 결과</div>', unsafe_allow_html=True)
st.markdown('<div class="kk-sub">재미로 보는 가벼운 분석입니다 😉</div>', unsafe_allow_html=True)

if run:
    text = (conversation or "").strip()
    if len(text) < 10:
        st.warning("대화 내용이 너무 짧습니다. 10자 이상 붙여넣어 주세요.")
    else:
        if len(text) > MAX_INPUT_CHARS:
            text = text[:MAX_INPUT_CHARS]
            st.caption(f"입력이 길어 앞 {MAX_INPUT_CHARS}자만 분석합니다.")
        # 하이픈(-) 규칙으로 화자를 확정 라벨링 (있을 때만)
        text, hyphen_used = relabel_hyphen(text)
        if hyphen_used:
            st.caption("✅ 하이픈 규칙 적용: `-` 있는 줄은 '나', 없는 줄은 '상대'로 구분했습니다.")
        with st.spinner("AI 가 꼰대력을 측정하는 중... 🔍"):
            try:
                st.session_state["result"] = analyze(text, target_hint)
            except json.JSONDecodeError:
                st.error("분석 결과를 해석하지 못했습니다. 잠시 후 다시 시도해 주세요.")
            except Exception as ex:
                m = str(ex).lower()
                if "503" in m or "unavailable" in m or "overloaded" in m:
                    st.error("OpenAI 서버가 잠시 혼잡합니다(503). 잠깐 후 다시 시도해 주세요.")
                elif "429" in m or "rate limit" in m:
                    st.error("요청 한도에 도달했습니다(429). 1~2분 후 다시 시도해 주세요.")
                elif "insufficient_quota" in m or "quota" in m or "billing" in m:
                    st.error("계정 크레딧/결제 한도를 확인해 주세요. platform.openai.com 의 Billing 에서 "
                             "사용 가능한 크레딧이 있는지 보세요.")
                else:
                    st.error(f"분석 중 문제가 발생했습니다: {ex}")

if st.session_state.get("result"):
    render_result(st.session_state["result"])
elif not run:
    st.markdown(
        f'<div class="kk-card" style="color:#777">'
        f'왼쪽 사이드바에 대화를 붙여넣고 <b style="color:{ACCENT}">분석하기</b>를 누르면 '
        f'여기에 결과 카드가 나타납니다.</div>',
        unsafe_allow_html=True,
    )
