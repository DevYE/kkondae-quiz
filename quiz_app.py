# 꼰대력 측정 이벤트 (참여형 퀴즈) — Streamlit 단일 파일 앱
# =============================================================================
# 기존 대화 분석 앱(app.py)과 별개인 "이벤트용" 앱입니다.
#
# 흐름
#   - A QR (평가대상, 상무 이상): 이름 입력 → 퀴즈 → 결과 + 랭킹 풀에 반영
#   - B QR (체험용, 누구나):      익명 → 퀴즈 → 결과만 (저장 안 함)
#   - 관리자:                      TOP3 집계 + (선택) AI 코멘트
#
#   채점은 전부 "공식 계산" → 참가자 수와 무관하게 API 0회.
#   AI는 관리자 TOP3 코멘트에만 선택적으로 사용(3회). 키 없으면 템플릿으로 대체.
#
# QR 주소 (앱 배포 후)
#   A(평가): https://<배포주소>/?mode=exec
#   B(체험): https://<배포주소>/?mode=guest   (또는 그냥 https://<배포주소>/ )
#   관리자 : https://<배포주소>/?mode=admin
#
# 실행 방법
#   pip install -r requirements.txt
#   (선택) 환경변수 OPENAI_API_KEY = "sk-..."   ← TOP3 AI 코멘트 쓸 때만
#   streamlit run quiz_app.py
# =============================================================================

import os
import io
import csv
import json
import time
from statistics import mean

import streamlit as st
import plotly.graph_objects as go

# ---- 설정 -------------------------------------------------------------------
ACCENT = "#5B68C0"          # 포인트 컬러 (인디고/보라)
BORDER = "#E0E0E0"
ADMIN_PW_DEFAULT = "kkondae2026"   # 비밀설정(ADMIN_PW)이 없을 때만 쓰이는 기본값
TOP_N = 3                   # TOP 몇 위까지 발표할지

AXIS_LABELS = {
    "훈계": "훈계·설교",
    "라떼": "라떼·과거미화",
    "지시": "일방적 지시·강요",
    "권위": "권위·서열 강조",
    "공감부족": "공감·경청 부족",
    "오지랖": "오지랖·간섭",
    "하대": "반말·하대",
}

# 문항: 각 축에 2~3문항(총 17). '그렇다'에 가까울수록 꼰대력↑ (정방향 채점)
QUESTIONS = [
    ("훈계", "후배가 실수하면 짧게 넘기기보다 왜 그런지 처음부터 설명해주고 싶다."),
    ("훈계", "대화 중 '이건 하나 알려줄게', '내가 조언하자면' 같은 말을 자주 한다."),
    ("훈계", "후배 보고서를 보면 내용보다 형식(양식·오탈자)부터 눈에 들어온다."),
    ("라떼", "'내가 네 나이(신입) 때는 말이야' 같은 말을 해본 적이 있다."),
    ("라떼", "요즘 젊은 직원들은 예전보다 끈기나 열정이 부족하다고 느낀다."),
    ("라떼", "요즘은 회식·모임이 줄어 예전 같은 끈끈함이 없다고 느낀다."),
    ("지시", "회의에서 의견이 갈리면 결국 내 방향으로 정리하는 편이다."),
    ("지시", "길게 설명하기보다 '일단 이렇게 해'라고 지시하는 게 효율적이라 생각한다."),
    ("권위", "나이·직급·경력은 대화에서 어느 정도 대우받아야 한다고 생각한다."),
    ("권위", "이견이 있어도 윗사람 말은 일단 따르는 게 조직이라고 본다."),
    ("권위", "회식 자리에서 상석·건배사 같은 자리 예절은 지켜지는 게 좋다."),
    ("공감부족", "후배가 고민을 털어놓으면 공감보다 해결책부터 말해주는 편이다."),
    ("공감부족", "내 말이 길어져 상대의 말을 중간에 자를 때가 있다."),
    ("오지랖", "후배의 연애·결혼·자녀 계획 등 사생활을 종종 묻는다."),
    ("오지랖", "직원의 옷차림·헤어스타일·체중 등에 한마디 한 적이 있다."),
    ("하대", "나이 어린 직원에겐 자연스럽게 반말이 나온다."),
    ("하대", "답답할 때 '그것도 몰라?', '됐고' 같은 말이 나온 적 있다."),
]

# 리커트 5점 척도 → 점수 (0/25/50/75/100)
LIKERT = ["전혀 아니다", "아니다", "보통", "그렇다", "매우 그렇다"]
LIKERT_SCORE = {label: i * 25 for i, label in enumerate(LIKERT)}


# ---- 채점 -------------------------------------------------------------------
def compute_scores(answers: list) -> dict:
    """answers: QUESTIONS와 같은 순서의 리커트 라벨 리스트 → 점수 dict 반환."""
    buckets = {ax: [] for ax in AXIS_LABELS}
    for (axis, _q), ans in zip(QUESTIONS, answers):
        buckets[axis].append(LIKERT_SCORE[ans])
    axis_scores = {ax: round(mean(vals)) for ax, vals in buckets.items()}
    total = round(mean(list(axis_scores.values())))
    return {"axis_scores": axis_scores, "total": total, "grade": grade_name(total)}


def mask_name(name: str) -> str:
    """이름 첫 글자만 남기고 나머지를 *로 가린다. 예) 홍길동 → 홍**"""
    name = (name or "").strip()
    if len(name) <= 1:
        return name
    return name[0] + "*" * (len(name) - 1)


def grade_name(score: int) -> str:
    if score < 20:
        return "청정 청년"
    if score < 40:
        return "새싹 꼰대"
    if score < 60:
        return "대리급 꼰대"
    if score < 80:
        return "부장급 꼰대"
    return "회장님 꼰대"


def grade_color(score: int) -> str:
    if score < 20:
        return "#2E9E5B"
    if score < 40:
        return "#7DB23A"
    if score < 60:
        return "#E0A800"
    if score < 80:
        return "#E8732C"
    return "#D64545"


# ---- 레이더 차트 ------------------------------------------------------------
def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def radar_figure(axis_scores: dict, color: str = ACCENT, height: int = 360):
    """7축 점수를 각진 7각형(레이더) 차트로 그린다."""
    labels = list(AXIS_LABELS.values())
    vals = [int(axis_scores.get(k, 0)) for k in AXIS_LABELS]
    theta = labels + [labels[0]]
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=vals + [vals[0]], theta=theta, fill="toself",
        line=dict(color=color, width=2), fillcolor=_hex_to_rgba(color, 0.3),
        marker=dict(size=5, color=color),
        hovertemplate="%{theta}: %{r}<extra></extra>",
    ))
    fig.update_layout(
        polar=dict(
            gridshape="linear",
            radialaxis=dict(visible=True, range=[0, 100], tickvals=[20, 40, 60, 80, 100],
                            tickfont=dict(size=9, color="#aaa"), gridcolor=BORDER),
            angularaxis=dict(tickfont=dict(size=11, color="#333"), gridcolor=BORDER, linecolor=BORDER),
            bgcolor="rgba(0,0,0,0)",
        ),
        showlegend=False, margin=dict(l=60, r=60, t=20, b=30), height=height,
        paper_bgcolor="rgba(0,0,0,0)", font=dict(family='-apple-system, "Segoe UI", sans-serif'),
    )
    return fig


# ---- 공용 저장소 (평가대상 A만) ----------------------------------------------
@st.cache_resource
def get_store():
    """앱 실행 중 공유되는 평가대상 결과 저장소 (외부 DB 없이 메모리)."""
    return {"exec": []}   # [{name, total, axis_scores, grade, order}]


# ---- AI TOP3 코멘트 (선택) ---------------------------------------------------
def get_api_key():
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        try:
            key = st.secrets["OPENAI_API_KEY"]
        except Exception:
            key = None
    return key


def get_admin_pw():
    """관리자 암호: 환경변수/비밀설정 우선, 없으면 기본값."""
    pw = os.environ.get("ADMIN_PW")
    if not pw:
        try:
            pw = st.secrets["ADMIN_PW"]
        except Exception:
            pw = None
    return pw or ADMIN_PW_DEFAULT


MC_SYSTEM = """너는 '꼰대 시상식'의 센스있는 MC다. 수상자에게 바치는 짧은 시상 멘트를 쓴다.

무엇이 웃긴가 (이것만 지키면 됨):
- 정확한 관찰: 직장인이라면 누구나 "아 그 사람 있지" 하고 공감할 그 장면을 콕 집는다.
- 따뜻한 반전: 놀리다가 끝에 살짝 인정/애정으로 마무리해 기분 좋게 웃게 한다.
- 담백함: 과장·억지 비유 금지. 랜덤 사물에 빗대지 말고(예: '정수기보다 시원' 같은 억지 직유 금지), 실제 행동을 그대로 위트있게 묘사한다.

절대 금지: 인신공격, 외모·나이·능력 비하, 조롱, 욕설, 뻔한 표현. 당사자가 옆에서 들어도 웃을 수 있어야 한다.

형식: 1~2문장, 한국어, 55자 이내, 이모지는 0~1개. 따옴표·설명·머리말 없이 멘트만.

좋은 예시(이 톤을 따라):
- "왕년 이야기 나오면 눈이 반짝이는 분. 그 시절 무용담, 이제 후배들 사이 전설입니다 😌"
- "고민 상담이 어느새 해결책 브리핑으로 바뀌는 스타일. 답을 아니까 어쩔 수 없죠, 인정합니다."
- "회식 상석이 자동으로 비워지는 짬바. 그래도 계산은 늘 먼저 하신다는 후문입니다."
- "한마디 하면 세 마디가 따라오는 설명력. 알고 보면 다 챙겨주려는 마음인 거 압니다."
"""


def ai_comment(scores: dict) -> str:
    """TOP3용 재치있는 시상 멘트. 실명은 쓰지 않는다(화면에 마스킹 표시됨).
    API 키 없거나 실패하면 템플릿으로 대체."""
    ranked = sorted(scores["axis_scores"].items(), key=lambda kv: kv[1], reverse=True)
    top_axis = ranked[0][0]
    top_label = AXIS_LABELS[top_axis]
    top2 = ", ".join(f"{AXIS_LABELS[a]}({v}점)" for a, v in ranked[:2])
    key = get_api_key()
    if key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=key)
            user = (
                f"꼰대력 종합: {scores['total']}점 / 등급: {scores['grade']}\n"
                f"두드러진 축: {top2}\n"
                "위 정보를 살려 시상 멘트를 써라. 두드러진 축의 특징을 콕 집어 위트있게. "
                "수상자의 실제 이름은 모르니 이름을 지어내지 말고, '수상자'·'이 분' 또는 특징으로만 지칭하라."
            )
            resp = client.chat.completions.create(
                model="gpt-4o-mini", max_tokens=120, temperature=0.9,
                messages=[{"role": "system", "content": MC_SYSTEM},
                          {"role": "user", "content": user}],
            )
            return resp.choices[0].message.content.strip().strip('"')
        except Exception:
            pass
    # 템플릿 fallback (축별 위트 — 관찰 + 따뜻한 반전)
    quips = {
        "훈계": "한마디 하면 세 마디가 따라오는 설명력. 알고 보면 다 챙겨주려는 마음인 거 압니다 😌",
        "라떼": "왕년 이야기 나오면 눈이 반짝이는 분. 그 시절 무용담, 이제 후배들 사이 전설입니다.",
        "지시": "회의가 길어지면 '자, 이렇게 갑시다'로 딱 정리되는 든든함. 우유부단과는 거리가 머시네요.",
        "권위": "회식 상석이 자동으로 비워지는 짬바. 그래도 계산은 늘 먼저 하신다는 후문입니다 🍶",
        "공감부족": "고민 상담이 어느새 해결책 브리핑으로 바뀌는 스타일. 답을 아니까 어쩔 수 없죠, 인정합니다.",
        "오지랖": "후배 근황을 회사에서 제일 먼저 아는 정보통. 무관심보단 낫다는 데 한 표 던집니다.",
        "하대": "친해지면 반말이 먼저 나오는 스타일. 거리감 없애는 데는 확실히 일등이시네요 🎤",
    }
    return quips.get(top_axis, f"'{scores['grade']}' 등극을 축하드립니다. 오늘의 주인공이십니다 🏅")


# ---- 스타일 -----------------------------------------------------------------
def inject_css():
    st.markdown(
        f"""
        <style>
          html, body, [class*="css"] {{
            font-family: -apple-system, "Segoe UI", "Malgun Gothic", sans-serif;
          }}
          .kk-title {{ font-size: 24px; font-weight: 800; color: #1F1F1F; }}
          .kk-sub {{ color: #6B6B6B; font-size: 14px; margin-bottom: 10px; }}
          .kk-card {{ background:#fff; border:0.5px solid {BORDER}; border-radius:10px;
                      padding:16px 18px; margin-bottom:12px; }}
          .kk-badge {{ display:inline-block; padding:4px 14px; border-radius:999px;
                       color:#fff; font-weight:700; font-size:15px; }}
          .kk-score {{ font-size:54px; font-weight:800; line-height:1; color:{ACCENT}; }}
          .kk-q {{ font-size:15px; font-weight:600; color:#222; margin-bottom:-4px; }}
          .stProgress > div > div > div > div {{ background-color:{ACCENT}; }}
          div.stButton > button {{ background:{ACCENT}; color:#fff; border:none;
             border-radius:8px; font-weight:700; padding:10px 0; font-size:16px; }}
          div.stButton > button:hover {{ background:#4a56a8; color:#fff; }}
          .kk-rank {{ font-size:22px; font-weight:800; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


# ---- 결과 렌더 --------------------------------------------------------------
def render_result(scores: dict, name: str = None, compare_avg: float = None):
    total = scores["total"]
    color = grade_color(total)

    st.markdown('<div class="kk-card">', unsafe_allow_html=True)
    if name:
        st.markdown(f'<div style="font-size:17px;color:#555;margin-bottom:4px">'
                    f'<b style="color:{ACCENT}">{name}</b> 님의 결과</div>', unsafe_allow_html=True)
    c1, c2 = st.columns([1, 2])
    with c1:
        st.markdown(f'<div class="kk-score">{total}<span style="font-size:20px;color:#999">/100</span></div>',
                    unsafe_allow_html=True)
        st.markdown(f'<span class="kk-badge" style="background:{color}">{scores["grade"]}</span>',
                    unsafe_allow_html=True)
    with c2:
        st.markdown('<div style="height:14px"></div>', unsafe_allow_html=True)
        st.markdown('<div style="font-size:13px;color:#666">종합 꼰대력</div>', unsafe_allow_html=True)
        st.progress(total / 100)
    st.markdown("</div>", unsafe_allow_html=True)

    st.plotly_chart(radar_figure(scores["axis_scores"]), use_container_width=True,
                    config={"displayModeBar": False})

    if compare_avg is not None:
        diff = total - compare_avg
        if diff > 0:
            msg = f"오늘 참여한 임원 평균보다 **{diff:.0f}점 높습니다** 😏"
        elif diff < 0:
            msg = f"오늘 참여한 임원 평균보다 **{abs(diff):.0f}점 낮습니다** 😌"
        else:
            msg = "오늘 참여한 임원 평균과 **딱 같습니다** 🤝"
        st.info(f"📊 {msg} (임원 평균 {compare_avg:.0f}점)")


def render_quiz(mode_key: str):
    """퀴즈 폼을 그리고, 제출되면 답변 리스트를 반환. 아니면 None."""
    st.markdown(f'<div class="kk-sub">각 문항에 솔직하게 답해주세요. ({len(QUESTIONS)}문항, 약 1분)</div>',
                unsafe_allow_html=True)
    with st.form(f"quiz_{mode_key}"):
        answers = []
        for i, (axis, q) in enumerate(QUESTIONS, 1):
            st.markdown(f'<div class="kk-q">Q{i}. {q}</div>', unsafe_allow_html=True)
            ans = st.radio(f"q{i}", options=LIKERT, index=None, horizontal=True,
                           label_visibility="collapsed", key=f"{mode_key}_q{i}")
            st.markdown('<div style="height:6px"></div>', unsafe_allow_html=True)
            answers.append(ans)
        submitted = st.form_submit_button("결과 보기 🔍", use_container_width=True)
    if not submitted:
        return None
    unanswered = [i for i, a in enumerate(answers, 1) if a is None]
    if unanswered:
        st.warning(f"아직 답하지 않은 문항이 있어요: Q{', Q'.join(map(str, unanswered))}")
        return None
    return answers


# ---- 모드별 페이지 ----------------------------------------------------------
def page_exec():
    """A: 평가대상(상무 이상) — 이름 입력 → 퀴즈 → 결과 + 저장."""
    st.markdown('<div class="kk-title">🧓 꼰대력 측정 · 평가 참여</div>', unsafe_allow_html=True)
    store = get_store()

    if st.session_state.get("exec_done"):
        render_result(st.session_state["exec_scores"], name=st.session_state["exec_name"])
        st.success(f"제출 완료! 현재 {len(store['exec'])}명 참여 중입니다. TOP3는 발표 화면에서 공개됩니다 🎤")
        return

    name = st.text_input("이름을 입력하세요", placeholder="예: 홍길동 상무", key="exec_name_input")
    answers = render_quiz("exec")
    if answers is not None:
        if not name.strip():
            st.warning("이름을 입력해 주세요. (TOP3 발표에 사용됩니다)")
            return
        scores = compute_scores(answers)
        store["exec"].append({
            "name": name.strip(), "total": scores["total"],
            "axis_scores": scores["axis_scores"], "grade": scores["grade"],
            "order": len(store["exec"]) + 1,
        })
        st.session_state["exec_done"] = True
        st.session_state["exec_scores"] = scores
        st.session_state["exec_name"] = name.strip()
        st.rerun()


def page_guest():
    """B: 체험용(누구나) — 익명, 결과만, 저장 안 함."""
    st.markdown('<div class="kk-title">🧓 꼰대력 측정 · 체험판</div>', unsafe_allow_html=True)
    store = get_store()

    if st.session_state.get("guest_done"):
        avg = mean([r["total"] for r in store["exec"]]) if store["exec"] else None
        render_result(st.session_state["guest_scores"], compare_avg=avg)
        if st.button("다시 하기", use_container_width=True):
            for k in ("guest_done", "guest_scores"):
                st.session_state.pop(k, None)
            st.rerun()
        return

    answers = render_quiz("guest")
    if answers is not None:
        st.session_state["guest_done"] = True
        st.session_state["guest_scores"] = compute_scores(answers)
        st.rerun()


def page_admin():
    """관리자: 진행 현황 + TOP3 발표."""
    st.markdown('<div class="kk-title">🎤 관리자 · TOP3 발표</div>', unsafe_allow_html=True)
    pw = st.text_input("관리자 암호", type="password")
    if pw != get_admin_pw():
        st.info("관리자 암호를 입력하면 발표 화면이 열립니다.")
        return

    store = get_store()
    rows = store["exec"]
    st.markdown(f"**현재 참여(평가대상): {len(rows)}명**")
    if not rows:
        st.warning("아직 제출된 평가대상이 없습니다.")
        return

    avg = mean([r["total"] for r in rows])
    st.caption(f"임원 평균 꼰대력: {avg:.0f}점")

    top = sorted(rows, key=lambda r: (-r["total"], r["order"]))[:TOP_N]
    medals = ["🥇", "🥈", "🥉"]

    if st.button("TOP3 AI 코멘트 생성", use_container_width=True):
        for r in top:
            r["comment"] = ai_comment({
                "total": r["total"], "grade": r["grade"], "axis_scores": r["axis_scores"]})
        st.rerun()

    st.caption("아래로 스크롤하며 3위 → 2위 → 1위 순으로 공개하세요 👇")
    # 3위부터 1위까지 세로로 나열 (스크롤 내리며 극적으로 공개)
    for i in reversed(range(len(top))):   # i=2(3위) → 1(2위) → 0(1위)
        r = top[i]
        gc = grade_color(r["total"])
        medal = medals[i] if i < len(medals) else f"{i+1}위"
        rank_label = ["1위", "2위", "3위"][i] if i < 3 else f"{i+1}위"
        # 다음 순위와 화면상 분리되도록 위쪽 여백 (스크롤 공개 효과)
        st.markdown('<div style="height:120px"></div>', unsafe_allow_html=True)
        st.markdown('<div class="kk-card">', unsafe_allow_html=True)
        st.markdown(f'<div style="text-align:center;color:#888;font-size:15px;font-weight:700">{rank_label}</div>',
                    unsafe_allow_html=True)
        st.markdown(f'<div class="kk-rank" style="text-align:center;font-size:30px">{medal} {mask_name(r["name"])}</div>',
                    unsafe_allow_html=True)
        st.markdown(f'<div class="kk-score" style="text-align:center">{r["total"]}'
                    f'<span style="font-size:18px;color:#999">/100</span></div>', unsafe_allow_html=True)
        st.markdown(f'<div style="text-align:center"><span class="kk-badge" style="background:{gc}">{r["grade"]}</span></div>',
                    unsafe_allow_html=True)
        st.plotly_chart(radar_figure(r["axis_scores"], color=gc, height=340),
                        use_container_width=True, config={"displayModeBar": False},
                        key=f"radar_top_{i}")
        if r.get("comment"):
            st.info(f"💬 {r['comment']}")
        st.markdown("</div>", unsafe_allow_html=True)

    ordered = sorted(rows, key=lambda r: (-r["total"], r["order"]))
    with st.expander("전체 순위 보기 (이름 마스킹)"):
        for rank, r in enumerate(ordered, 1):
            st.markdown(f"{rank}. **{mask_name(r['name'])}** — {r['total']}점 ({r['grade']})")

    # 결과 CSV 다운로드 (앱 재시작 대비 백업)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["순위", "이름", "종합"] + [AXIS_LABELS[a] for a in AXIS_LABELS] + ["등급"])
    for rank, r in enumerate(ordered, 1):
        w.writerow([rank, r["name"], r["total"]]
                   + [r["axis_scores"].get(a, 0) for a in AXIS_LABELS] + [r["grade"]])
    st.download_button("📥 결과 CSV 다운로드", buf.getvalue().encode("utf-8-sig"),
                       file_name="kkondae_results.csv", mime="text/csv",
                       use_container_width=True)

    st.divider()
    st.caption("⚠️ 결과는 앱 실행 중 메모리에만 있습니다. 앱을 재시작하면 초기화됩니다.")
    if st.button("전체 초기화 (주의)"):
        store["exec"].clear()
        st.rerun()


# ---- 라우팅 -----------------------------------------------------------------
st.set_page_config(page_title="꼰대력 측정", page_icon="🧓", layout="centered")
inject_css()

mode = st.query_params.get("mode", "guest")
if mode == "exec":
    page_exec()
elif mode == "admin":
    page_admin()
else:
    page_guest()
