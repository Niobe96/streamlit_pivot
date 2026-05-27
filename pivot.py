import streamlit as st
import pandas as pd
from pandas.api.types import is_datetime64_any_dtype
import io, re
from datetime import datetime
import traceback
import time
import streamlit_authenticator as stauth
import stats_functions as sf
from pathlib import Path

# =============================================================================
# 핵심 로직: perform_pivot (변경 없음)
# =============================================================================
def perform_pivot(source_df, index_cols, values_col, agg_func='first',
                  max_n=None, sort_by_seq=False, custom_prefix=None,
                  classic_mode=False, columns_col=None, interleave_groups=None):
    needed_cols = list(set(index_cols + values_col + ([columns_col] if columns_col else [])))
    temp_df = source_df[needed_cols].copy()
    for col in index_cols:
        if temp_df[col].dtype == 'object':
            temp_df[col] = temp_df[col].fillna("(NULL)").astype(str)
        elif is_datetime64_any_dtype(temp_df[col]):
            has_time = (temp_df[col].dt.hour != 0).any() or (temp_df[col].dt.minute != 0).any() or (temp_df[col].dt.second != 0).any()
            fmt = '%Y-%m-%d %H:%M:%S' if has_time else '%Y-%m-%d'
            temp_df[col] = temp_df[col].dt.strftime(fmt).fillna("(NULL)").astype(str)
        else:
            temp_df[col] = temp_df[col].astype(str).replace('nan', '(NULL)')
    if classic_mode:
        fill_val = 0
        if columns_col:
            if temp_df[columns_col].dtype == 'object':
                temp_df[columns_col] = temp_df[columns_col].fillna("(NULL)").astype(str)
            elif is_datetime64_any_dtype(temp_df[columns_col]):
                has_time = (temp_df[columns_col].dt.hour != 0).any() or (temp_df[columns_col].dt.minute != 0).any() or (temp_df[columns_col].dt.second != 0).any()
                fmt = '%Y-%m-%d %H:%M:%S' if has_time else '%Y-%m-%d'
                temp_df[columns_col] = temp_df[columns_col].dt.strftime(fmt).fillna("(NULL)").astype(str)
            else:
                temp_df[columns_col] = temp_df[columns_col].astype(str).replace('nan', '(NULL)')
        pivot_col_target = columns_col
    else:
        fill_val = "-"
        for val_c in values_col:
            if is_datetime64_any_dtype(temp_df[val_c]):
                has_time = (temp_df[val_c].dt.hour != 0).any() or (temp_df[val_c].dt.minute != 0).any() or (temp_df[val_c].dt.second != 0).any()
                fmt = '%Y-%m-%d %H:%M:%S' if has_time else '%Y-%m-%d'
                temp_df[val_c] = temp_df[val_c].dt.strftime(fmt).fillna("(NULL)").astype(str)
        temp_df['__seq__'] = temp_df.groupby(index_cols).cumcount() + 1
        if max_n is not None:
            temp_df = temp_df[temp_df['__seq__'] <= max_n]
        pivot_col_target = '__seq__'
    # pivot_table 호출 전, PyArrow 직렬화 에러(mixed type category) 방지를 위해 범주형 컬럼을 문자열로 변환
    for col in values_col:
        if pd.api.types.is_categorical_dtype(temp_df[col].dtype):
            temp_df[col] = temp_df[col].astype(str)
            
    pivot_df = temp_df.pivot_table(index=index_cols, columns=pivot_col_target,
                                    values=values_col, aggfunc=agg_func, fill_value=fill_val)
    prefix_map = custom_prefix or {v: v for v in values_col}
    if isinstance(pivot_df.columns, pd.MultiIndex):
        pivot_df.columns = [f"{prefix_map.get(col[0], col[0])}_{col[1]}" for col in pivot_df.columns]
    else:
        if not classic_mode:
            val_name = values_col[0]
            prefix = prefix_map.get(val_name, val_name)
            pivot_df.columns = [f"{prefix}_{col}" for col in pivot_df.columns]
    if sort_by_seq and not classic_mode and len(values_col) > 1:
        # interleave_groups: [[A, B], [C, D]] 형식의 리스트
        # 결과 순서: A_1, B_1, A_2, B_2, ..., C_1, D_1, C_2, D_2, ...
        
        # 그룹 정보가 없으면 전체를 하나의 그룹으로 처리 (기존 방식)
        if not interleave_groups:
            interleave_groups = [values_col]

        # 정렬을 위한 맵 생성
        group_map = {}
        order_map = {}
        for g_idx, grp in enumerate(interleave_groups):
            for c_idx, col in enumerate(grp):
                group_map[col] = g_idx
                order_map[col] = c_idx

        def col_sort_key_grouped(col_name):
            match = re.search(r'_(\d+)$', col_name)
            seq = int(match.group(1)) if match else 0
            
            # prefix_map(커스텀 접두어)을 고려하여 원본 컬럼명 찾기
            original = None
            for orig, pref in prefix_map.items():
                if col_name.startswith(pref + '_'):
                    original = orig
                    break
            
            # 그룹 번호, 시퀀스, 그룹 내 순서 반환
            g_idx = group_map.get(original, 999)
            c_idx = order_map.get(original, 999)
            return (g_idx, seq, c_idx)

        pivot_df = pivot_df[sorted(pivot_df.columns, key=col_sort_key_grouped)]
    pivot_df_reset = pivot_df.reset_index()
    unique_indices = temp_df[index_cols].drop_duplicates()
    final_df = pd.merge(unique_indices, pivot_df_reset, on=index_cols, how='left')
    final_df = final_df.fillna(fill_val).set_index(index_cols)
    return final_df


# =============================================================================
# 페이지 설정
# =============================================================================
st.set_page_config(page_title="KCDW 분석 어시스턴트", layout="wide", page_icon="🏥")

# --- Custom CSS (Notion/shadcn Style) ---
st.markdown("""
<style>
    /* 버튼 스타일링 */
    div.stButton > button {
        border-radius: 8px !important;
        border: 1px solid #e2e8f0 !important;
        background-color: #ffffff !important;
        color: #0f172a !important;
        font-weight: 500 !important;
        box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05) !important;
        transition: all 0.2s ease-in-out !important;
    }
    div.stButton > button:hover {
        background-color: #f8fafc !important;
        border-color: #cbd5e1 !important;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06) !important;
    }
    
    /* Primary 버튼 (type="primary") 강조 스타일 */
    div.stButton > button[kind="primary"] {
        background-color: #0f172a !important;
        color: #ffffff !important;
        border: none !important;
    }
    div.stButton > button[kind="primary"]:hover {
        background-color: #334155 !important;
    }
    
    /* Metric (지표) 스타일링 */
    div[data-testid="metric-container"] {
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 16px;
        box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.1), 0 1px 2px 0 rgba(0, 0, 0, 0.06);
        text-align: center; /* 텍스트 가운데 정렬 추가 */
    }
    
    /* 뱃지처럼 보이게 할 caption 스타일 약간 조정 */
    .stCaption {
        font-size: 0.85rem !important;
        color: #475569 !important;
    }

    /* Sidebar native navigation */
    section[data-testid="stSidebar"] div[class*="st-key-nav_"] {
        margin-bottom: 6px;
    }

    section[data-testid="stSidebar"] div[class*="st-key-nav_"] button {
        min-height: 42px;
        width: 100%;
        justify-content: flex-start;
        padding: 0 14px !important;
        border-radius: 9px !important;
        font-size: 0.94rem !important;
        font-weight: 700 !important;
        text-align: left !important;
        white-space: nowrap;
    }

    section[data-testid="stSidebar"] div[class*="st-key-nav_"] button p {
        width: 100%;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
</style>
""", unsafe_allow_html=True)

# =============================================================================
# 인증
# =============================================================================
try:
    config = st.secrets.to_dict()
    credentials = config['credentials']
    cookie_settings = config['cookie']
except FileNotFoundError:
    st.error("❌ .streamlit/secrets.toml 파일이 없습니다.")
    st.stop()
except KeyError:
    st.error("❌ secrets.toml 형식 오류.")
    st.stop()

authenticator = stauth.Authenticate(
    credentials, cookie_settings['name'],
    cookie_settings['key'], cookie_settings['expiry_days']
)
authenticator.login(location='main')

if st.session_state["authentication_status"] is False:
    st.error('❌ 아이디 또는 비밀번호가 틀렸습니다.')
elif st.session_state["authentication_status"] is None:
    st.warning('🔒 로그인이 필요합니다.')
elif st.session_state["authentication_status"]:

    # ── 세션 상태 초기화 ──────────────────────────────────────────
    _defaults = {
        'df': None, 'source_name': '', 'loaded_file_key': None,
        '_pivot_key': None, '_pivot_result': None, '_excel_buffer': None,
        'chat_history': [],       # 통합 대화 기록
        'tree_path': [],          # 트리 경로 e.g. ["basic","distribution"]
        'tree_step': 0,           # 현재 레벨
        'auto_analyzed': False,   # 자동분석 완료 여부
        'export_buffer': [],      # 전체 내보내기용
        'result_section': None,
        # 데이터 설정
        'patient_id_col': None,        # 환자 ID 컬럼
        'dependent_var_col': None,     # 종속변수 컬럼
        'dep_var_as_cat': False,       # 종속변수를 범주형으로 변환 여부
        'data_configured': False,      # 데이터 설정 완료 여부
        'config_step': 0,              # 설정 단계 (0=웰컴, 1=ID/종속변수, 2=타입변환, 3=완료)
        'dtype_originals': {},         # {컬럼명: 원본 Series} — 되돌리기용
        'dtype_overrides': {},         # {컬럼명: 변환 타입 라벨}
        'dtype_summary': None,         # auto_analyze 요약 DataFrame
        'type_recommendations': [],    # 타입 변환 추천 목록
        # 피벗 위자드 상태
        'pivot_mode': None,
        'pivot_index_cols': [],
        'pivot_values_col': [],
        'pivot_columns_col': None,
        'pivot_agg_func': 'first',
        'pivot_max_n': None,
        'pivot_sort_by_seq': False,
        'pivot_custom_prefix': {},
        'pivot_classic_mode': False,
        # 분석 파라미터 (레벨3 위젯 상태)
        'pending_intent': None,
        'pending_col': None,
        'pending_group': None,
        '_guide_reset': None,
        '_show_guide_dialog': False,
    }
    for k, v in _defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # ── 헬퍼 함수 ─────────────────────────────────────────────────
    def stream_text(text):
        for char in text:
            yield char
            time.sleep(0.015)

    def add_user_msg(txt):
        st.session_state.chat_history.append({"role": "user", "content": txt})

    def add_bot_msg(txt, figure=None, result_df=None, export_data=None, nav=True):
        st.session_state.chat_history.append({
            "role": "assistant", "content": txt,
            "figure": figure, "result_df": result_df,
            "export_data": export_data, "nav": nav,
            "is_new": True,
        })

    def go_to(path, user_msg, bot_msg):
        add_user_msg(user_msg)
        add_bot_msg(bot_msg, nav=False)
        st.session_state.tree_path = path
        st.session_state.tree_step = len(path)
        st.rerun()

    def reset_tree():
        """완전 초기화 (Level 0)"""
        st.session_state.tree_path = []
        st.session_state.tree_step = 0
        st.session_state.result_section = None
        st.session_state.pending_intent = None
        st.session_state.pending_col = None
        st.session_state.pending_group = None

    def go_back_to_section(section: str):
        """분석 완료 후 해당 섹션의 Level 1로 복귀"""
        st.session_state.tree_path = [section]
        st.session_state.tree_step = 1
        st.session_state.result_section = section
        st.session_state.pending_intent = None
        st.session_state.pending_col = None
        st.session_state.pending_group = None

    def ts():
        return datetime.now().strftime('%Y%m%d_%H%M%S')

    # ── 파일 로드 함수 ────────────────────────────────────────────
    def load_file(uploaded_file):
        file_key = f"{uploaded_file.name}_{uploaded_file.size}"
        if st.session_state.loaded_file_key == file_key:
            return
        try:
            if uploaded_file.name.endswith('.csv'):
                try:
                    df_temp = pd.read_csv(uploaded_file, encoding='utf-8')
                except UnicodeDecodeError:
                    uploaded_file.seek(0)
                    df_temp = pd.read_csv(uploaded_file, encoding='cp949')
            else:
                df_temp = pd.read_excel(uploaded_file, engine='calamine')
            st.session_state.df = df_temp
            st.session_state.source_name = uploaded_file.name
            st.session_state.loaded_file_key = file_key
            st.session_state._pivot_key = None
            st.session_state._pivot_result = None
            st.session_state._excel_buffer = None
            st.session_state.auto_analyzed = False
            st.session_state.chat_history = []
            st.session_state.patient_id_col = None
            st.session_state.dependent_var_col = None
            st.session_state.dep_var_as_cat = False
            st.session_state.data_configured = False
            st.session_state.config_step = 0
            st.session_state.dtype_originals = {}
            st.session_state.dtype_overrides = {}
            st.session_state.dtype_summary = None
            reset_tree()
        except Exception as e:
            st.error(f"파일 오류: {e}")

    # ── 사이드바 ──────────────────────────────────────────────────
    with st.sidebar:

        # 가이드 선택 시 즉시 "데이터 관리"(인덱스 0)로 복귀 + 팝업 플래그
        _show_guide = st.session_state.get("_show_guide_dialog", False)
        _manual = st.session_state.get("_guide_reset", None)

        menu_options = ["데이터 관리", "빠른 분석", "내보내기", "가이드"]
        menu_labels = {
            "데이터 관리": "▦  데이터 관리",
            "빠른 분석": "🎢  빠른 분석",
            "내보내기": "⬇  내보내기",
            "가이드": "📖  가이드",
        }
        menu_keys = {
            "데이터 관리": "nav_data",
            "빠른 분석": "nav_quick",
            "내보내기": "nav_export",
            "가이드": "nav_guide",
        }
        if "sidebar_menu" not in st.session_state:
            st.session_state["sidebar_menu"] = menu_options[0]
        if _manual is not None:
            st.session_state["sidebar_menu"] = menu_options[_manual]

        selected_menu = st.session_state["sidebar_menu"]
        for menu in menu_options:
            if st.button(
                menu_labels[menu],
                key=menu_keys[menu],
                type="primary" if selected_menu == menu else "secondary",
                use_container_width=True,
            ):
                selected_menu = menu
                st.session_state["sidebar_menu"] = menu
                st.rerun()
        # manual_select 사용 후 즉시 초기화 (다음 클릭 시 재감지 가능하도록)
        if _manual is not None:
            st.session_state["_guide_reset"] = None
        # st.divider()

        if selected_menu == "데이터 관리":
            uploaded = st.file_uploader("데이터 파일 업로드", type=['csv', 'xlsx'], label_visibility="collapsed")
            if uploaded:
                load_file(uploaded)

            if st.session_state.df is not None:
                df = st.session_state.df
                # st.caption(f"📂 {st.session_state.source_name}")
                c1, c2 = st.columns(2)
                
                def make_metric_card(title, value):
                    return f"""
                    <div style="background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; text-align: center; box-shadow: 0 1px 2px 0 rgba(0,0,0,0.05); margin-bottom: 1rem;">
                        <div style="color: #64748b; font-size: 0.85rem; font-weight: 600; margin-bottom: 4px;">{title}</div>
                        <div style="color: #0f172a; font-size: 1.5rem; font-weight: 700;">{value}</div>
                    </div>
                    """
                
                c1.markdown(make_metric_card("행 (Rows)", f"{len(df):,}"), unsafe_allow_html=True)
                c2.markdown(make_metric_card("열 (Columns)", f"{len(df.columns):,}"), unsafe_allow_html=True)
                # st.divider()

                # ── 데이터 설정 요약 (메인에서 설정, 여기는 요약만) ──────
                if st.session_state.data_configured:
                    pid = st.session_state.patient_id_col
                    dep = st.session_state.dependent_var_col
                    
                    html_card = f"""
                    <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px; margin-bottom: 12px;">
                        <div style="font-size: 0.9rem; font-weight: 600; color: #334155; margin-bottom: 8px;">⚙️ 데이터 설정</div>
                        <div style="font-size: 0.85rem; color: #475569; margin-bottom: 4px;">🆔 환자 ID: <b>{pid or '미설정'}</b></div>
                        <div style="font-size: 0.85rem; color: #475569; margin-bottom: 4px;">🎯 종속변수: <b>{dep or '미설정'}</b></div>
                    """
                    if st.session_state.dtype_overrides:
                        html_card += f'<div style="font-size: 0.85rem; color: #475569; margin-top: 4px;">🔧 타입 변환: <b>{len(st.session_state.dtype_overrides)}건</b></div>'
                    html_card += "</div>"
                    
                    st.markdown(html_card, unsafe_allow_html=True)
                    
                    if st.button("⚙️ 설정 변경", use_container_width=True, key="btn_reconfig"):
                        st.session_state.data_configured = False
                        st.session_state.config_step = 1
                        st.rerun()

        elif selected_menu == "빠른 분석":
            # 빠른 분석 버튼 (데이터 로드 후)
            if st.session_state.df is not None:
                st.caption("⚡ 빠른 분석")
                quick_map = {
                    "📊 분포 확인": ("basic", "distribution"),
                    "🔗 상관관계": ("basic", "correlation"),
                    "❓ 결측/요약": ("basic", "missing"),
                    "⚖️ 두 그룹 비교(T-test)": ("stats", "ttest"),
                    "📊 여러 그룹 비교(ANOVA)": ("stats", "anova"),
                    "📈 회귀분석": ("stats", "regression"),
                    "📐 데이터 펼치기": ("pivot", "1n"),
                }
                for label, (p1, p2) in quick_map.items():
                    if st.button(label, width="stretch", key=f"quick_{p2}"):
                        path = [p1, p2]
                        st.session_state.tree_path = path
                        st.session_state.tree_step = len(path)
                        st.rerun()
            else:
                st.info("데이터를 먼저 업로드해주세요.")

        elif selected_menu == "내보내기":
            # 전체 결과 내보내기
            if st.session_state.export_buffer:
                excel_all = sf.export_to_excel(st.session_state.export_buffer)
                st.download_button(
                    "📋 전체 분석 Excel 저장",
                    data=excel_all,
                    file_name=f"전체분석_{ts()}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    width="stretch",
                )

                # 전체 이미지 ZIP 저장
                import zipfile
                png_items = [
                    (item.get("png", b""), item.get("sheet_name", f"차트_{i+1}"))
                    for i, item in enumerate(st.session_state.export_buffer)
                    if item.get("fig") is not None and item.get("png")
                ]
                if png_items:
                    zip_buf = io.BytesIO()
                    with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                        for png_bytes, name in png_items:
                            safe_name = re.sub(r'[\\/*?:"<>|]', '_', name)
                            zf.writestr(f"{safe_name}.png", png_bytes)
                    st.download_button(
                        "🖼️ 전체 분석 이미지 저장 (ZIP)",
                        data=zip_buf.getvalue(),
                        file_name=f"전체분석_이미지_{ts()}.zip",
                        mime="application/zip",
                        use_container_width=True,
                    )
            else:
                st.info("내보낼 분석 결과가 없습니다.")

        elif selected_menu == "가이드":
            # 즉시 "데이터 관리"(인덱스 0)로 전환 + 다이얼로그 표시 플래그
            st.session_state["_guide_reset"] = 0
            st.session_state["_show_guide_dialog"] = True
            st.rerun()

        st.markdown(f"<div style=' margin-bottom: 10px; color: #334155;'>👤 <b>{st.session_state['name']}</b>님</div>", unsafe_allow_html=True)
        c_empty, c_btn = st.columns([1, 1])
        with c_btn:
            authenticator.logout('로그아웃')

    # ── 가이드 다이얼로그 (사이드바 밖에서 표시) ──────────────────
    def _get_tutorial_file():
        guide_dir = Path(__file__).resolve().parent
        html_path = guide_dir / "KCDW_Tutorial.html"
        md_path = guide_dir / "KCDW_Tutorial.md"
        if html_path.exists():
            return "html", str(html_path), html_path.stat().st_mtime_ns
        if md_path.exists():
            return "md", str(md_path), md_path.stat().st_mtime_ns
        return None, None, None

    @st.cache_data(show_spinner=False)
    def _load_tutorial_html(fmt, path_str, mtime_ns):
        """가이드 HTML을 캐싱하여 매번 디스크 I/O를 방지한다."""
        if not path_str:
            return (None, None)
        path = Path(path_str)
        try:
            return (fmt, path.read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            return (fmt, path.read_text(encoding="cp949"))

    # @st.dialog("📖 가이드", width="large")
    # def _load_tutorial_html():
    #     st.iframe(Path("KCDW_Tutorial.html"), width="stretch",height=600)
    @st.dialog("📖 가이드", width="large")
    def show_tutorial_dialog():
        fmt, path_str, mtime_ns = _get_tutorial_file()
        fmt, data = _load_tutorial_html(fmt, path_str, mtime_ns)
        if fmt == "html":
            st.iframe(data, width="stretch",height=600)
        elif fmt == "md":
            st.markdown(data, unsafe_allow_html=True)
        else:
            st.error("튜토리얼 파일을 찾을 수 없습니다.")

    if _show_guide:
        show_tutorial_dialog()
        st.session_state["_show_guide_dialog"] = False
        st.session_state["_guide_reset"] = None

    # ── 메인 영역 ─────────────────────────────────────────────────
    df = st.session_state.df

    # 파일 미업로드 시 챗봇 웰컴 메시지 (1회)
    if df is None and not st.session_state.chat_history:
        with st.chat_message("assistant"):
            st.markdown(
                "안녕하세요! 👋 저는 **KCDW 데이터 분석 어시스턴트**예요.\n\n"
                "데이터를 업로드하면 아래 기능들을 사용할 수 있어요:\n"
                "- 📊 **데이터 탐색** — 분포, 상관관계, 결측값 확인\n"
                "- 🔬 **통계 검정** — 그룹 비교(t검정·ANOVA), 회귀분석\n"
                "- 📐 **데이터 펼치기** — 1:N 구조를 가로로 정리\n\n"
                " **왼쪽 사이드바**에서 CSV 또는 Excel 파일을 업로드해주세요!\n"
                "업로드하면 자동으로 데이터를 분석하고 안내해드릴게요 😊"
            )

    # 자동 분석 (파일 업로드 직후 1회)
    if df is not None and not st.session_state.auto_analyzed:
        info = sf.auto_analyze(df)

        # DATE 후보 자동 변환
        date_auto_txt = ""
        if info["date_candidates"]:
            for col in info["date_candidates"]:
                st.session_state.dtype_originals[col] = df[col].copy()
                st.session_state.df[col] = pd.to_datetime(df[col], errors='coerce')
                st.session_state.dtype_overrides[col] = "날짜형 (자동)"
            date_auto_txt = "\n\n   📅 날짜로 자동 변환: " + ", ".join(
                f"**{c}**" for c in info["date_candidates"])

        # 시간형 컬럼 텍스트
        date_txt = ""
        if info["date_cols"]:
            date_txt = f"\n   - 날짜/시간형: {', '.join(info['date_cols'][:5])}"

        missing_txt = ""
        if info["missing"]:
            missing_txt = "\n\n   ⚠️ 결측값: " + ", ".join(
                f"**{c}** {n}개" for c, n in list(info["missing"].items())[:5]
            )
        one_n = info["one_n"]
        one_n_txt = ""
        if one_n["is_1n"]:
            top = one_n["candidates"][0]
            one_n_txt = (
                f"\n\n   💡 **{top['col']}** 기준으로 1명당 평균 **{top['avg_rows']}행**이 "
                f"반복되는 구조예요. 데이터 펼치기가 필요할 수 있어요!"
            )
        welcome = (
            f"데이터를 받았어요 😊\n\n"
            f"   📋 **{st.session_state.source_name}**\n"
            f"   - 행: **{info['rows']:,}개** / 열: **{info['cols']}개**\n"
            f"   - 수치형: {', '.join(info['num_cols'][:5]) or '없음'}\n"
            f"   - 범주형: {', '.join(info['cat_cols'][:5]) or '없음'}"
            f"{date_txt}"
            f"{missing_txt}{date_auto_txt}{one_n_txt}\n\n"
            f"   데이터에 대한 설명입니다. 우선 아래에서 환자 ID와 종속변수를 지정해주세요!. ⬇️"
        )
        add_bot_msg(welcome, result_df=info["dtype_summary"], nav=False)
        st.session_state.dtype_summary = info["dtype_summary"]
        st.session_state.type_recommendations = info.get("type_recommendations", [])
        st.session_state.auto_analyzed = True
        st.session_state.config_step = 1

    # ── 대화 기록 렌더링 ─────────────────────────────────────────
    for i, msg in enumerate(st.session_state.chat_history):
        with st.chat_message(msg["role"]):
            if msg["role"] == "assistant" and msg.get("is_new", False):
                st.write_stream(stream_text(msg["content"]))
                msg["is_new"] = False
            else:
                st.markdown(msg["content"])
                
            if msg.get("figure"):
                st.plotly_chart(msg["figure"], width='stretch', key=f"chart_{i}")
            if msg.get("result_df") is not None and not msg["result_df"].empty:
                st.dataframe(msg["result_df"], width='stretch', key=f"df_{i}")

            if msg.get("export_data"):
                ed = msg["export_data"]
                ec1, ec2, ec3 = st.columns(3)
                if ed.get("excel"):
                    ec1.download_button("📥 Excel 다운로드", data=ed["excel"],
                        file_name=f"결과_{ts()}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key=f"xl_{i}")
                if ed.get("csv"):
                    ec2.download_button("📥 CSV 다운로드", data=ed["csv"],
                        file_name=f"결과_{ts()}.csv", mime="text/csv", key=f"csv_{i}")
                if ed.get("png"):
                    ec3.download_button("🖼️ PNG 이미지 저장", data=ed["png"],
                        file_name=f"차트_{ts()}.png", mime="image/png", key=f"png_{i}")


    # ── 현재 레벨 위젯 렌더링 ────────────────────────────────────
    def do_export(fig, result_df, label):
        """결과 내보내기 데이터 생성"""
        png = sf.export_chart_png(fig) if fig else b""
        csv = sf.export_csv(result_df) if result_df is not None else ""
        excel = sf.export_single_excel(result_df, label[:31]) if result_df is not None else b""
        ed = {"excel": excel, "csv": csv, "png": png}
        st.session_state.export_buffer.append({"sheet_name": label, "df": result_df, "fig": fig, "png": png})
        return ed

    def show_nav(back_path=None):
        """결과 후 네비게이션 버튼 (항상 3개)"""
        n1, n2, n3 = st.columns(3)
        if back_path and n1.button("🔁 다시 설정", key=f"nav_back_{len(st.session_state.chat_history)}"):
            st.session_state.tree_path = back_path
            st.session_state.tree_step = len(back_path)
            st.rerun()
        if n2.button("🏠 처음으로 돌아갈게", key=f"nav_home_{len(st.session_state.chat_history)}"):
            add_user_msg("처음으로 돌아갈게")
            add_bot_msg("다시 처음부터 시작해볼까요? 어떤 분석을 해볼까요? 😊", nav=False)
            reset_tree()
            st.rerun()

    def run_analysis(path):
        """트리 경로에 따라 분석 실행"""
        p = path
        pid = st.session_state.patient_id_col
        num_cols = [c for c in df.select_dtypes("number").columns if c != pid]
        cat_cols = [c for c in df.select_dtypes(["object", "category"]).columns if c != pid]
        analysis_df = df.drop(columns=[pid], errors='ignore') if pid else df

        # ── 기초: 상관관계 (파라미터 없음) ──
        if p == ["basic", "correlation"]:
            fig, pairs_df = sf.plot_correlation(analysis_df)
            if fig is None:
                add_bot_msg("수치형 컬럼이 2개 이상 필요해요!", nav=False)
            else:
                ed = do_export(fig, pairs_df, "상관관계")
                add_bot_msg("📊 상관관계 분석 결과예요!\n\n아래 히트맵에서 색이 진할수록 관계가 강해요.",
                            figure=fig, result_df=pairs_df, export_data=ed)
            go_back_to_section("basic")

        # ── 기초: 결측/요약 (파라미터 없음) ──
        elif p == ["basic", "missing"]:
            desc = sf.describe_extended(analysis_df)
            fig, miss_df = sf.plot_missing(df)
            result = miss_df if not miss_df.empty else desc
            ed = do_export(fig, result, "결측요약")
            msg = ("❓ 결측값 현황이에요!" if not miss_df.empty
                   else "✅ 결측값이 없어요! 아래는 기술통계 요약이에요.")
            add_bot_msg(msg, figure=fig, result_df=result, export_data=ed)
            go_back_to_section("basic")

        # ── 기초: 분포 ── (컬럼 선택 필요 → LEVEL 3에서 처리)
        elif p[:2] == ["basic", "distribution"] and len(p) == 3:
            cols = p[2]
            if isinstance(cols, str):
                cols = [cols]
            
            for col in cols:
                fig, stat = sf.plot_histogram(df, col)
                stat_df = pd.DataFrame([stat])
                ed = do_export(fig, stat_df, f"{col}_분포")
                add_bot_msg(
                    f" **{col}** 분포 분석 결과예요!\n\n"
                    f"평균 **{stat['평균']}** / 중앙값 **{stat['중앙값']}** / "
                    f"표준편차 **{stat['표준편차']}** / 이상치(참고) 있음",
                    figure=fig, result_df=stat_df, export_data=ed,
                )
                
            go_back_to_section("basic")

        # ── 기초: 빈도 ──
        elif p[:2] == ["basic", "frequency"] and len(p) == 3:
            cols = p[2]
            if isinstance(cols, str):
                cols = [cols]
            
            for col in cols:
                fig, freq_df = sf.plot_frequency(df, col)
                ed = do_export(fig, freq_df, f"{col}_빈도")
                add_bot_msg(f"📂 **{col}** 빈도 분석 결과예요!", figure=fig, result_df=freq_df, export_data=ed)
                
            go_back_to_section("basic")

        # ── 고급: t검정 ──
        elif p[:2] == ["stats", "ttest"] and len(p) == 4:
            col, group = p[2], p[3]
            result, summary, fig = sf.test_ttest(df, col, group)
            ed = do_export(fig, summary, f"t검정_{col}")
            result_txt = "\n\n".join([f"**{k}**: {v}" for k, v in result.items()])
            add_bot_msg(f"⚖️ **{group}별 {col}** t검정 결과예요!\n\n{result_txt}",
                        figure=fig, result_df=summary, export_data=ed)
            go_back_to_section("stats")

        # ── 고급: ANOVA ──
        elif p[:2] == ["stats", "anova"] and len(p) == 4:
            col, group = p[2], p[3]
            result, summary, tukey_df, fig = sf.test_anova(df, col, group)
            
            if "오류" in result:
                add_bot_msg(f"❌ ANOVA 분석 불가: {result['오류']}", nav=False)
            else:
                ed = do_export(fig, summary, f"ANOVA_{col}")
                result_txt = "\n\n".join([f"**{k}**: {v}" for k, v in result.items()])
                add_bot_msg(f"📊 **{group}별 {col}** ANOVA 결과예요!\n\n{result_txt}\n\n📌 Tukey 사후검정:",
                            figure=fig, result_df=tukey_df, export_data=ed)
            
            go_back_to_section("stats")

        # ── 고급: 회귀 ──
        elif p[:2] == ["stats", "regression"] and len(p) >= 4:
            y_col = p[2]
            x_cols = p[3:]
            result, coef_df, fig = sf.run_regression(df, x_cols, y_col)
            ed = do_export(fig, coef_df, f"회귀_{y_col}")
            result_txt = "\n\n".join([f"**{k}**: {v}" for k, v in result.items()])
            add_bot_msg(f"📈 **{y_col}** 회귀분석 결과예요!\n\n{result_txt}",
                        figure=fig, result_df=coef_df, export_data=ed)
            go_back_to_section("stats")

        # ── 고급: 정규성 ──
        elif p[:2] == ["stats", "normality"] and len(p) == 3:
            col = p[2]
            result = sf.test_normality(df, col)
            result_df = pd.DataFrame([result])
            ed = do_export(None, result_df, f"정규성_{col}")
            result_txt = "\n\n".join([f"**{k}**: {v}" for k, v in result.items()])
            add_bot_msg(f"📐 **{col}** 정규성 검정 결과예요!\n\n{result_txt}",
                        result_df=result_df, export_data=ed)
            go_back_to_section("stats")

        # ── 고급: 그룹 비교 ──
        elif p[:2] == ["stats", "group_compare"] and len(p) == 4:
            col, group = p[2], p[3]
            summary, fig = sf.compare_groups(df, col, group)
            ed = do_export(fig, summary, f"그룹비교_{col}")
            add_bot_msg(f"📋 **{group}별 {col}** 그룹 비교 결과예요!",
                        figure=fig, result_df=summary, export_data=ed)
            go_back_to_section("stats")

        # ── 기초: 스피어만 상관관계 ──
        elif p == ["basic", "spearman"]:
            fig, pairs_df = sf.plot_spearman_correlation(analysis_df)
            if fig is None:
                add_bot_msg("수치형 컬럼이 2개 이상 필요해요!", nav=False)
            else:
                ed = do_export(fig, pairs_df, "스피어만상관")
                add_bot_msg("🔗 스피어만 상관분석 결과예요!\n\n비선형 관계도 잡아낼 수 있는 분석이에요.",
                            figure=fig, result_df=pairs_df, export_data=ed)
            go_back_to_section("basic")

        # ── 기초: 이상치 상세 탐지 ──
        elif p[:2] == ["basic", "outlier"] and len(p) == 3:
            cols = p[2]
            if isinstance(cols, str):
                cols = [cols]
            
            for col in cols:
                fig, summary = sf.detect_outliers_detail(df, col)
                ed = do_export(fig, summary, f"이상치_{col}")
                add_bot_msg(f"🔍 **{col}** 이상치 탐지 결과예요!\n\nIQR과 Z-score 두 가지 방법으로 확인했어요.",
                            figure=fig, result_df=summary, export_data=ed)
                
            go_back_to_section("basic")

        # ── 기초: 산점도 행렬 ──
        elif p == ["basic", "pairplot"]:
            fig, corr_df = sf.plot_pairplot(analysis_df)
            if fig is None:
                add_bot_msg("수치형 컬럼이 2개 이상 필요해요!", nav=False)
            else:
                ed = do_export(fig, corr_df, "산점도행렬")
                add_bot_msg("🪮 산점도 행렬이에요!\n\n대각선은 각 변수의 분포, 나머지는 변수 간 관계를 보여줘요.",
                            figure=fig, result_df=corr_df, export_data=ed)
            go_back_to_section("basic")

        # ── 기초: VIF 다중공선성 ──
        elif p == ["basic", "vif"]:
            fig, vif_df = sf.calculate_vif(analysis_df)
            if fig is None:
                add_bot_msg("수치형 컬럼이 2개 이상 필요해요!", nav=False)
            else:
                ed = do_export(fig, vif_df, "다중공선성")
                add_bot_msg("📐 다중공선성(VIF) 결과예요!\n\nVIF≥10이면 해당 변수를 제거하는 것을 권장해요.",
                            figure=fig, result_df=vif_df, export_data=ed)
            go_back_to_section("basic")

        # ── 기초: 바이올린 플롯 ──
        elif p[:2] == ["basic", "violin"] and len(p) == 4:
            col, group = p[2], p[3]
            fig, summary = sf.plot_violin(df, col, group)
            ed = do_export(fig, summary, f"바이올린_{col}")
            add_bot_msg(f"🎻 **{group}별 {col}** 바이올린 플롯이에요!\n\n분포 형태와 박스플롯을 동시에 확인할 수 있어요.",
                        figure=fig, result_df=summary, export_data=ed)
            go_back_to_section("basic")

        # ── 고급: 카이제곱 검정 ──
        elif p[:2] == ["stats", "chi2"] and len(p) == 4:
            col1, col2 = p[2], p[3]
            result, cross = sf.test_chi2(df, col1, col2)
            ed = do_export(None, cross, f"카이제곱_{col1}")
            result_txt = "\n\n".join([f"**{k}**: {v}" for k, v in result.items()])
            add_bot_msg(f"🔀 **{col1} × {col2}** 카이제곱 검정 결과예요!\n\n{result_txt}",
                        result_df=cross, export_data=ed)
            go_back_to_section("stats")

        # ── 고급: 대응표본 t검정 ──
        elif p[:2] == ["stats", "paired"] and len(p) == 4:
            col1, col2 = p[2], p[3]
            result, summary, fig = sf.test_paired_ttest(df, col1, col2)
            ed = do_export(fig, summary, f"대응t_{col1}")
            result_txt = "\n\n".join([f"**{k}**: {v}" for k, v in result.items()])
            add_bot_msg(f"🔄 **{col1} vs {col2}** 전후 비교 결과예요!\n\n{result_txt}",
                        figure=fig, result_df=summary, export_data=ed)
            go_back_to_section("stats")

        # ── 고급: Kruskal-Wallis ──
        elif p[:2] == ["stats", "kruskal"] and len(p) == 4:
            col, group = p[2], p[3]
            result, summary, fig = sf.test_kruskal(df, col, group)
            ed = do_export(fig, summary, f"Kruskal_{col}")
            result_txt = "\n\n".join([f"**{k}**: {v}" for k, v in result.items()])
            add_bot_msg(f"📊 **{group}별 {col}** Kruskal-Wallis 결과예요!\n\n{result_txt}",
                        figure=fig, result_df=summary, export_data=ed)
            go_back_to_section("stats")

        # ── 고급: 비율 검정 ──
        elif p[:2] == ["stats", "proportion"] and len(p) == 4:
            col, group = p[2], p[3]
            result, summary, fig = sf.test_proportion(df, col, group)
            ed = do_export(fig, summary, f"비율_{col}")
            result_txt = "\n\n".join([f"**{k}**: {v}" for k, v in result.items()])
            add_bot_msg(f"📊 **{group}별 {col}** 비율 비교 결과예요!\n\n{result_txt}",
                        figure=fig, result_df=summary, export_data=ed)
            go_back_to_section("stats")

        # ── 고급: 로지스틱 회귀 ──
        elif p[:2] == ["stats", "logistic"] and len(p) >= 4:
            y_col = p[2]
            x_cols = p[3:]
            result, coef_df, fig = sf.run_logistic_regression(df, x_cols, y_col)
            if coef_df is None:
                add_bot_msg(f"❌ {result.get('오류', '오류 발생')}", nav=False)
            else:
                ed = do_export(fig, coef_df, f"로지스틱_{y_col}")
                result_txt = "\n\n".join([f"**{k}**: {v}" for k, v in result.items()])
                add_bot_msg(f"🎯 **{y_col}** 로지스틱 회귀 결과예요!\n\n{result_txt}",
                            figure=fig, result_df=coef_df, export_data=ed)
            go_back_to_section("stats")

        # ── 고급: 생존분석 (Kaplan-Meier) ──
        elif p[:2] == ["stats", "survival"] and len(p) >= 4:
            time_col, event_col = p[2], p[3]
            group_col = p[4] if len(p) > 4 else None
            result, summary_df, fig = sf.run_kaplan_meier(df, time_col, event_col, group_col)
            ed = do_export(fig, summary_df, "생존분석")
            result_txt = "\n\n".join([f"**{k}**: {v}" for k, v in result.items()])
            add_bot_msg(f"⏱️ Kaplan-Meier 생존분석 결과예요!\n\n{result_txt}",
                        figure=fig, result_df=summary_df, export_data=ed)
            go_back_to_section("stats")

        # ── 고급: Cox 회귀 ──
        elif p[:2] == ["stats", "cox"] and len(p) >= 5:
            time_col, event_col = p[2], p[3]
            x_cols = p[4:]
            result, coef_df, fig = sf.run_cox_regression(df, time_col, event_col, x_cols)
            ed = do_export(fig, coef_df, "Cox회귀")
            result_txt = "\n\n".join([f"**{k}**: {v}" for k, v in result.items()])
            add_bot_msg(f"📉 Cox 비례위험 모델 결과예요!\n\n{result_txt}",
                        figure=fig, result_df=coef_df, export_data=ed)
            go_back_to_section("stats")

    def render_level():
        path = st.session_state.tree_path
        step = st.session_state.tree_step
        df = st.session_state.df
        pid = st.session_state.patient_id_col
        num_cols = [c for c in df.select_dtypes("number").columns if c != pid]
        cat_cols = [c for c in df.select_dtypes(["object", "category"]).columns if c != pid]

        # ── 즉시 실행 경로 (사이드바 빠른 버튼 → 파라미터 없는 분석) ──
        if step == 2 and path == ["basic", "correlation"]:
            add_bot_msg("상관관계 분석은 수치형 컬럼들이 서로 얼마나 함께 움직이는지 "
                        "히트맵으로 보여줘요. 바로 실행할게요! 🔗", nav=False)
            run_analysis(["basic", "correlation"])
            st.rerun()

        elif step == 2 and path == ["basic", "missing"]:
            add_bot_msg("결측값 현황과 기술통계를 한번에 보여드릴게요! ❓", nav=False)
            run_analysis(["basic", "missing"])
            st.rerun()

        elif step == 2 and path == ["basic", "spearman"]:
            add_bot_msg("스피어만 상관분석을 실행할게요! 비선형 관계도 확인할 수 있어요 🔗", nav=False)
            run_analysis(["basic", "spearman"])
            st.rerun()

        elif step == 2 and path == ["basic", "pairplot"]:
            add_bot_msg("산점도 행렬을 그릴게요! 변수 간 관계를 한눈에 볼 수 있어요 📊", nav=False)
            run_analysis(["basic", "pairplot"])
            st.rerun()

        elif step == 2 and path == ["basic", "vif"]:
            add_bot_msg("다중공선성(VIF)을 확인할게요! 회귀분석 전에 꼭 체크해야 해요 📐", nav=False)
            run_analysis(["basic", "vif"])
            st.rerun()

        # ── LEVEL 0: 첫 선택 ──────────────────────────────────────
        if step == 0:
            c1, c2, c3 = st.columns(3)
            if c1.button("데이터 탐색", width="stretch", key="l0_basic"):
                go_to(["basic"], "데이터 탐색",
                      "데이터 탐색은 데이터의 전반적인 특성을 파악하는 단계예요. "
                      "분포가 어떤지, 변수 간 관계, 결측값 등을 확인할 수 있어요! 😊\n\n"
                      "어떤 부분을 먼저 볼까요?")
            if c2.button("통계 검정", width="stretch", key="l0_stats"):
                go_to(["stats"], "통계 검정",
                      "통계 검정은 발견한 패턴이 우연인지, 실제로 의미 있는 건지 "
                      "수학적으로 확인하는 방법이에요! 📐\n\n"
                      "어떤 검정을 할까요?")
            if c3.button("데이터 펼치기", width="stretch", key="l0_pivot"):
                go_to(["pivot"], "데이터 펼치기",
                      "데이터 펼치기는 여러 행에 반복된 데이터를 한 행으로 "
                      "가로로 정리해주는 기능이에요! 📋\n\n"
                      "어떤 방식으로 할까요?")

        # ── LEVEL 1: basic ────────────────────────────────────────
        elif step == 1 and path[0] == "basic":
            # Row 1
            c1, c2, c3 = st.columns(3)
            if c1.button("📊 분포 / 이상치 분석", width="stretch", key="l1_dist"):
                go_to(["basic", "distribution"], "분포 / 이상치 분석",
                      "분포 분석은 데이터가 어떤 형태로 퍼져 있는지 히스토그램으로 보여주고, "
                      "이상치도 박스플롯으로 확인할 수 있어요!\n\n어떤 컬럼을 볼까요?")
            if c2.button("🔗 상관관계 (피어슨)", width="stretch", key="l1_corr"):
                add_user_msg("상관관계 분석")
                add_bot_msg("피어슨 상관관계를 분석할게요! 🔗", nav=False)
                run_analysis(["basic", "correlation"])
                st.rerun()
            if c3.button("❓ 결측값 / 기술통계 분석", width="stretch", key="l1_miss"):
                add_user_msg("결측값 / 기술통계 분석")
                add_bot_msg("결측값 현황과 기술통계를 한번에 보여드릴게요! ❓", nav=False)
                run_analysis(["basic", "missing"])
                st.rerun()
            # Row 2
            c4, c5, c6 = st.columns(3)
            if c4.button("🔍 이상치 탐지", width="stretch", key="l1_outlier"):
                go_to(["basic", "outlier"], "이상치 탐지",
                      "IQR과 Z-score 두 가지 방법으로 이상치를 정밀 탐지해요! 🔍\n\n어떤 컬럼을 볼까요?")
            if c5.button("📂 빈도 분석", width="stretch", key="l1_freq"):
                go_to(["basic", "frequency"], "빈도 분석",
                      "범주형 데이터의 빈도와 비율을 분석해요! 📂\n\n어떤 컬럼을 볼까요?")
            if c6.button("🔗 스피어만 상관분석", width="stretch", key="l1_spearman"):
                add_user_msg("스피어만 상관분석")
                add_bot_msg("스피어만 상관분석을 실행할게요! 비선형 관계도 확인할 수 있어요 🔗", nav=False)
                run_analysis(["basic", "spearman"])
                st.rerun()
            # Row 3
            c7, c8, c9 = st.columns(3)
            if c7.button("🪮 산점도 행렬", width="stretch", key="l1_pairplot"):
                add_user_msg("산점도 행렬")
                add_bot_msg("산점도 행렬을 그릴게요! 변수 간 관계를 한눈에 볼 수 있어요 📊", nav=False)
                run_analysis(["basic", "pairplot"])
                st.rerun()
            if c8.button("📐 다중공선성 확인", width="stretch", key="l1_vif"):
                add_user_msg("다중공선성 확인")
                add_bot_msg("다중공선성(VIF)을 확인할게요! 회귀분석 전에 꼭 체크해야 해요 📐", nav=False)
                run_analysis(["basic", "vif"])
                st.rerun()
            if c9.button("🎻 바이올린 플롯", width="stretch", key="l1_violin"):
                go_to(["basic", "violin"], "바이올린 플롯 분석",
                      "바이올린 플롯은 그룹별 분포 형태를 동시에 비교할 수 있어요! 🎻\n\n"
                      "수치 컬럼과 그룹 기준을 골라주세요!")

        # ── LEVEL 1: stats ────────────────────────────────────────
        elif step == 1 and path[0] == "stats":
            # Row 1
            c1, c2, c3 = st.columns(3)
            if c1.button("⚖️ 두 그룹 비교(T-test)", width="stretch", key="l1_ttest"):
                go_to(["stats", "ttest"], "두 그룹 비교(T-test)",
                      "두 그룹 비교(t검정)는 두 집단의 평균이 통계적으로 다른지 "
                      "확인해줘요! ⚖️ p<0.05이면 유의한 차이가 있는 거예요.\n\n"
                      "비교할 수치와 그룹 기준을 골라주세요!")
            if c2.button("📊 여러 그룹 비교(ANOVA)", width="stretch", key="l1_anova"):
                go_to(["stats", "anova"], "여러 그룹 비교(ANOVA)",
                      "여러 그룹 비교(ANOVA)는 3개 이상 그룹의 평균 차이를 "
                      "한번에 검정해줘요! 📊 사후검정도 자동으로 실행돼요.\n\n"
                      "비교할 수치와 그룹 기준을 골라주세요!")
            if c3.button("📈 영향 분석(Regression)", width="stretch", key="l1_reg"):
                go_to(["stats", "regression"], "영향 분석",
                      "회귀분석은 어떤 변수가 목표값에 얼마나 영향을 미치는지 "
                      "수치로 보여줘요! 📈\n\n"
                      "예측할 목표(Y)와 사용할 변수(X)를 골라주세요!")
            # Row 2
            c4, c5, c6 = st.columns(3)
            if c4.button("🔀 카이제곱 검정(Chi-squared Test)", width="stretch", key="l1_chi2"):
                go_to(["stats", "chi2"], "카이제곱 검정(Chi-squared Test)",
                      "카이제곱 검정은 두 범주형 변수가 서로 관련 있는지 확인해요! 🔀\n\n"
                      "비교할 두 범주형 컬럼을 골라주세요!")
            if c5.button("🔄 전후 비교(Paired T-test)", width="stretch", key="l1_paired"):
                go_to(["stats", "paired"], "전후 비교(Paired T-test)",
                      "대응표본 t검정은 같은 대상의 전/후 수치를 비교해요! 🔄\n\n"
                      "비교할 두 수치 컬럼(전/후)을 골라주세요!")
            if c6.button("📊 Kruskal-Wallis", width="stretch", key="l1_kruskal"):
                go_to(["stats", "kruskal"], "Kruskal-Wallis",
                      "Kruskal-Wallis는 ANOVA의 비모수 버전이에요. "
                      "정규분포가 아닐 때 사용해요! 📊\n\n"
                      "비교할 수치와 그룹 기준을 골라주세요!")
            # Row 3
            c7, c8, c9 = st.columns(3)
            if c7.button("📊 비율 비교(Proportion Test)", width="stretch", key="l1_prop"):
                go_to(["stats", "proportion"], "비율 비교(Proportion Test)",
                      "비율 검정은 두 그룹 간 특정 값의 비율 차이를 검정해요! 📊\n\n"
                      "비교할 컬럼과 그룹 기준을 골라주세요!")
            if c8.button("🎯 로지스틱 회귀(Logistic Regression)", width="stretch", key="l1_logistic"):
                go_to(["stats", "logistic"], "로지스틱 회귀(Logistic Regression)",
                      "로지스틱 회귀는 이진 결과(예/아니오)를 예측하는 분석이에요! 🎯\n\n"
                      "예측할 목표(Y, 2개 값)와 사용할 수치 변수(X)를 골라주세요!")
            if c9.button("⏱️ 생존분석(Kaplan-Meier)", width="stretch", key="l1_survival"):
                go_to(["stats", "survival"], "생존분석(Kaplan-Meier)",
                      "Kaplan-Meier 생존분석은 시간에 따른 생존 확률을 보여줘요! ⏱️\n\n"
                      "시간 컬럼과 이벤트(0/1) 컬럼을 골라주세요!")
            # Row 4
            c10, c11, _ = st.columns(3)
            if c10.button("📉 Cox 회귀 분석(Cox Regression)", width="stretch", key="l1_cox"):
                go_to(["stats", "cox"], "Cox 회귀 분석(Cox Regression)",
                      "Cox 비례위험 모델은 여러 변수가 생존에 미치는 영향을 분석해요! 📉\n\n"
                      "시간·이벤트 컬럼과 공변량을 골라주세요!")

        # ── LEVEL 1: pivot ────────────────────────────────────────
        elif step == 1 and path[0] == "pivot":
            c1, c2 = st.columns(2)
            if c1.button("1:N으로 펼쳐줘", width="stretch", key="l1_1n"):
                go_to(["pivot", "1n"], "1:N으로 펼쳐줘",
                      "1:N 펼치기는 한 기준(예: 환자ID)에 대해 여러 행에 걸친 "
                      "데이터를 한 행 안에 나란히 정리해줘요! 📋\n\n"
                      "기준 컬럼과 펼칠 데이터를 선택해주세요!")
            if c2.button("집계하여 요약", width="stretch", key="l1_classic"):
                go_to(["pivot", "classic"], "집계하여 요약",
                      "집계 피벗은 sum·mean·count 등으로 데이터를 요약해줘요! 📊\n\n"
                      "기준·열·값 컬럼을 선택해주세요!")

        # ── LEVEL 2: distribution → 컬럼 선택 ───────────────────
        elif step == 2 and path == ["basic", "distribution"]:
            if not num_cols:
                st.warning("수치형 컬럼이 없어요!")
                if st.button("🏠 홈으로 가기", width="stretch", key="warn_home_dist"):
                    reset_tree()
                    st.rerun()
            else:
                sel_cols = st.multiselect(
                    "어떤 컬럼의 분포를 볼까요? (선택하지 않으면 전체 분석)",
                    num_cols,
                    default=[],
                    key="sel_dist"
                )
                if st.button("✅ 분포 분석 시작", type="primary", width="stretch", key="btn_dist"):
                    target_cols = sel_cols if sel_cols else num_cols
                    
                    if len(target_cols) <= 3:
                        msg_cols = ", ".join(target_cols)
                    else:
                        msg_cols = f"{len(target_cols)}개 수치형 컬럼"
                        
                    add_user_msg(f"{msg_cols} 분포 분석해줘")
                    add_bot_msg(f"**{msg_cols}**의 분포를 분석할게요! 📊", nav=False)
                    run_analysis(["basic", "distribution", target_cols])
                    st.rerun()

        # ── LEVEL 2: ttest → 컬럼+그룹 선택 ─────────────────────
        elif step == 2 and path == ["stats", "ttest"]:
            if not num_cols or not cat_cols:
                st.warning("수치형 컬럼과 범주형 컬럼이 모두 필요해요!")
                if st.button("🏠 홈으로 가기", width="stretch", key="warn_home_ttest"):
                    reset_tree()
                    st.rerun()
            else:
                c1, c2 = st.columns(2)
                with c1:
                    dep = st.session_state.dependent_var_col
                    col_default = num_cols.index(dep) if dep and dep in num_cols else 0
                    sel_col = st.selectbox("비교할 수치 컬럼", num_cols, index=col_default, key="ttest_col")
                with c2:
                    sel_group = st.selectbox("그룹 기준 컬럼", cat_cols, key="ttest_grp")
                if st.button("✅ 비교 시작", type="primary", width="stretch", key="btn_ttest"):
                    add_user_msg(f"{sel_col}을 {sel_group}으로 비교해줘")
                    add_bot_msg(f"**{sel_group}별 {sel_col}**을 비교할게요! "
                                "먼저 정규성을 자동으로 확인하고 적합한 검정을 실행해요 🔍", nav=False)
                    run_analysis(["stats", "ttest", sel_col, sel_group])
                    st.rerun()

        # ── LEVEL 2: anova → 컬럼+그룹 선택 ─────────────────────
        elif step == 2 and path == ["stats", "anova"]:
            if not num_cols or not cat_cols:
                st.warning("수치형 컬럼과 범주형 컬럼이 모두 필요해요!")
                if st.button("🏠 홈으로 가기", width="stretch", key="warn_home_anova"):
                    reset_tree()
                    st.rerun()
            else:
                c1, c2 = st.columns(2)
                with c1:
                    dep = st.session_state.dependent_var_col
                    col_default = num_cols.index(dep) if dep and dep in num_cols else 0
                    sel_col = st.selectbox("비교할 수치 컬럼", num_cols, index=col_default, key="anova_col")
                with c2:
                    sel_group = st.selectbox("그룹 기준 컬럼", cat_cols, key="anova_grp")
                if st.button("✅ 비교 시작", type="primary", width="stretch", key="btn_anova"):
                    add_user_msg(f"{sel_col}을 {sel_group}으로 ANOVA 분석해줘")
                    add_bot_msg(f"**{sel_group}별 {sel_col}** ANOVA를 실행할게요! "
                                "Tukey 사후검정도 자동으로 포함돼요 📊", nav=False)
                    run_analysis(["stats", "anova", sel_col, sel_group])
                    st.rerun()

        # ── LEVEL 2: regression → Y + X 선택 ────────────────────
        elif step == 2 and path == ["stats", "regression"]:
            if len(num_cols) < 2:
                st.warning("수치형 컬럼이 2개 이상 필요해요!")
                if st.button("🏠 홈으로 가기", width="stretch", key="warn_home_reg"):
                    reset_tree()
                    st.rerun()
            else:
                dep = st.session_state.dependent_var_col
                y_idx = num_cols.index(dep) if dep and dep in num_cols else 0
                y_col = st.selectbox("예측 목표 (Y)", num_cols, index=y_idx, key="reg_y")
                x_opts = [c for c in num_cols if c != y_col]
                x_cols = st.multiselect("사용할 변수 (X)", x_opts, default=x_opts[:2], key="reg_x")
                if x_cols and st.button("✅ 회귀분석 시작", type="primary", width="stretch", key="btn_reg"):
                    add_user_msg(f"{y_col}에 대한 회귀분석해줘")
                    add_bot_msg(f"**{y_col}** 회귀분석을 실행할게요! "
                                f"X변수: {', '.join(x_cols)} 📈", nav=False)
                    run_analysis(["stats", "regression", y_col] + x_cols)
                    st.rerun()

        # ── LEVEL 2: outlier → 컬럼 선택 ─────────────────────────
        elif step == 2 and path == ["basic", "outlier"]:
            if not num_cols:
                st.warning("수치형 컬럼이 없어요!")
                if st.button("🏠 홈으로 가기", width="stretch", key="warn_home_outlier"):
                    reset_tree()
                    st.rerun()
            else:
                sel_cols = st.multiselect(
                    "어떤 컬럼의 이상치를 볼까요? (선택하지 않으면 전체 분석)",
                    num_cols,
                    default=[],
                    key="sel_outlier"
                )
                if st.button("✅ 이상치 탐지 시작", type="primary", width="stretch", key="btn_outlier"):
                    target_cols = sel_cols if sel_cols else num_cols
                    
                    if len(target_cols) <= 3:
                        msg_cols = ", ".join(target_cols)
                    else:
                        msg_cols = f"{len(target_cols)}개 수치형 컬럼"
                        
                    add_user_msg(f"{msg_cols} 이상치 탐지해줘")
                    add_bot_msg(f"**{msg_cols}**의 이상치를 탐지할게요! 🔍", nav=False)
                    run_analysis(["basic", "outlier", target_cols])
                    st.rerun()

        # ── LEVEL 2: frequency → 컬럼 선택 ───────────────────────
        elif step == 2 and path == ["basic", "frequency"]:
            if not cat_cols:
                st.warning("범주형 컬럼이 없어요!")
                if st.button("🏠 홈으로 가기", width="stretch", key="warn_home_freq"):
                    reset_tree()
                    st.rerun()
            else:
                sel_cols = st.multiselect(
                    "어떤 컬럼의 빈도를 볼까요? (선택하지 않으면 전체 분석)",
                    cat_cols,
                    default=[],
                    key="sel_freq"
                )
                if st.button("✅ 빈도 분석 시작", type="primary", width="stretch", key="btn_freq"):
                    target_cols = sel_cols if sel_cols else cat_cols
                    
                    if len(target_cols) <= 3:
                        msg_cols = ", ".join(target_cols)
                    else:
                        msg_cols = f"{len(target_cols)}개 범주형 컬럼"
                        
                    add_user_msg(f"{msg_cols} 빈도 분석해줘")
                    add_bot_msg(f"**{msg_cols}**의 빈도를 분석할게요! 📂", nav=False)
                    run_analysis(["basic", "frequency", target_cols])
                    st.rerun()

        # ── LEVEL 2: violin → 수치+그룹 선택 ─────────────────────
        elif step == 2 and path == ["basic", "violin"]:
            if not num_cols or not cat_cols:
                st.warning("수치형 컬럼과 범주형 컬럼이 모두 필요해요!")
                if st.button("🏠 홈으로 가기", width="stretch", key="warn_home_violin"):
                    reset_tree()
                    st.rerun()
            else:
                c1, c2 = st.columns(2)
                with c1:
                    sel_col = st.selectbox("수치 컬럼", num_cols, key="violin_col")
                with c2:
                    sel_group = st.selectbox("그룹 기준 컬럼", cat_cols, key="violin_grp")
                if st.button("✅ 바이올린 플롯 분석", type="primary", width="stretch", key="btn_violin"):
                    add_user_msg(f"{sel_group}별 {sel_col} 바이올린 플롯")
                    add_bot_msg(f"**{sel_group}별 {sel_col}** 바이올린 플롯을 그릴게요! 🎻", nav=False)
                    run_analysis(["basic", "violin", sel_col, sel_group])
                    st.rerun()

        # ── LEVEL 2: chi2 → 범주형 2개 선택 ──────────────────────
        elif step == 2 and path == ["stats", "chi2"]:
            if len(cat_cols) < 2:
                st.warning("범주형 컬럼이 2개 이상 필요해요!")
                if st.button("🏠 홈으로 가기", width="stretch", key="warn_home_chi2"):
                    reset_tree()
                    st.rerun()
            else:
                c1, c2 = st.columns(2)
                with c1:
                    sel_col1 = st.selectbox("첫 번째 범주형 컬럼", cat_cols, key="chi2_col1")
                with c2:
                    opts2 = [c for c in cat_cols if c != sel_col1]
                    sel_col2 = st.selectbox("두 번째 범주형 컬럼", opts2, key="chi2_col2")
                if st.button("✅ 카이제곱 검정 시작", type="primary", width="stretch", key="btn_chi2"):
                    add_user_msg(f"{sel_col1}와 {sel_col2} 카이제곱 검정해줘")
                    add_bot_msg(f"**{sel_col1} × {sel_col2}** 카이제곱 검정을 실행할게요! 🔀", nav=False)
                    run_analysis(["stats", "chi2", sel_col1, sel_col2])
                    st.rerun()

        # ── LEVEL 2: paired → 수치형 2개 선택 ────────────────────
        elif step == 2 and path == ["stats", "paired"]:
            if len(num_cols) < 2:
                st.warning("수치형 컬럼이 2개 이상 필요해요!")
                if st.button("🏠 홈으로 가기", width="stretch", key="warn_home_paired"):
                    reset_tree()
                    st.rerun()
            else:
                c1, c2 = st.columns(2)
                with c1:
                    sel_col1 = st.selectbox("전(Before) 컬럼", num_cols, key="paired_col1")
                with c2:
                    opts2 = [c for c in num_cols if c != sel_col1]
                    sel_col2 = st.selectbox("후(After) 컬럼", opts2, key="paired_col2")
                if st.button("✅ 전후 비교 시작", type="primary", width="stretch", key="btn_paired"):
                    add_user_msg(f"{sel_col1}와 {sel_col2} 전후 비교해줘")
                    add_bot_msg(f"**{sel_col1} vs {sel_col2}** 전후 비교를 실행할게요! 🔄", nav=False)
                    run_analysis(["stats", "paired", sel_col1, sel_col2])
                    st.rerun()

        # ── LEVEL 2: kruskal → 수치+그룹 선택 ────────────────────
        elif step == 2 and path == ["stats", "kruskal"]:
            if not num_cols or not cat_cols:
                st.warning("수치형 컬럼과 범주형 컬럼이 모두 필요해요!")
                if st.button("🏠 홈으로 가기", width="stretch", key="warn_home_kruskal"):
                    reset_tree()
                    st.rerun()
            else:
                c1, c2 = st.columns(2)
                with c1:
                    dep = st.session_state.dependent_var_col
                    col_default = num_cols.index(dep) if dep and dep in num_cols else 0
                    sel_col = st.selectbox("비교할 수치 컬럼", num_cols, index=col_default, key="kruskal_col")
                with c2:
                    sel_group = st.selectbox("그룹 기준 컬럼", cat_cols, key="kruskal_grp")
                if st.button("✅ Kruskal-Wallis 시작", type="primary", width="stretch", key="btn_kruskal"):
                    add_user_msg(f"{sel_col}을 {sel_group}으로 Kruskal-Wallis")
                    add_bot_msg(f"**{sel_group}별 {sel_col}** Kruskal-Wallis를 실행할게요! 📊", nav=False)
                    run_analysis(["stats", "kruskal", sel_col, sel_group])
                    st.rerun()

        # ── LEVEL 2: proportion → 컬럼+그룹 선택 ─────────────────
        elif step == 2 and path == ["stats", "proportion"]:
            all_cols_list = df.columns.tolist()
            if not cat_cols or len(all_cols_list) < 2:
                st.warning("범주형 컬럼이 2개 이상 필요해요!")
                if st.button("🏠 홈으로 가기", width="stretch", key="warn_home_prop"):
                    reset_tree()
                    st.rerun()
            else:
                c1, c2 = st.columns(2)
                with c1:
                    sel_col = st.selectbox("비율 비교할 컬럼", all_cols_list, key="prop_col")
                with c2:
                    sel_group = st.selectbox("그룹 기준 컬럼", cat_cols, key="prop_grp")
                if st.button("✅ 비율 비교 시작", type="primary", width="stretch", key="btn_prop"):
                    add_user_msg(f"{sel_col}을 {sel_group}으로 비율 비교")
                    add_bot_msg(f"**{sel_group}별 {sel_col}** 비율을 비교할게요! 📊", nav=False)
                    run_analysis(["stats", "proportion", sel_col, sel_group])
                    st.rerun()

        # ── LEVEL 2: logistic → Y(이진) + X 선택 ─────────────────
        elif step == 2 and path == ["stats", "logistic"]:
            all_cols_list = df.columns.tolist()
            binary_cols = [c for c in all_cols_list if df[c].nunique() == 2]
            if not binary_cols or len(num_cols) < 1:
                st.warning("이진(2개 값) 컬럼과 수치형 컬럼이 필요해요!")
                if st.button("🏠 홈으로 가기", width="stretch", key="warn_home_logistic"):
                    reset_tree()
                    st.rerun()
            else:
                dep = st.session_state.dependent_var_col
                y_idx = binary_cols.index(dep) if dep and dep in binary_cols else 0
                y_col = st.selectbox("예측 목표 (Y, 2개 값)", binary_cols, index=y_idx, key="log_y")
                x_opts = [c for c in num_cols if c != y_col]
                x_cols = st.multiselect("사용할 변수 (X, 수치형)", x_opts,
                                        default=x_opts[:3] if len(x_opts) >= 3 else x_opts, key="log_x")
                if x_cols and st.button("✅ 로지스틱 회귀 시작", type="primary", width="stretch", key="btn_logistic"):
                    add_user_msg(f"{y_col} 로지스틱 회귀")
                    add_bot_msg(f"**{y_col}** 로지스틱 회귀를 실행할게요! 🎯", nav=False)
                    run_analysis(["stats", "logistic", y_col] + x_cols)
                    st.rerun()

        # ── LEVEL 2: survival → 시간+이벤트+그룹 선택 ─────────────
        elif step == 2 and path == ["stats", "survival"]:
            event_opts = [c for c in df.columns if set(df[c].dropna().unique()).issubset({0, 1, '0', '1', 0.0, 1.0})]
            if len(num_cols) < 1 or not event_opts:
                st.warning("시간을 나타내는 수치형 컬럼과 0/1로 이루어진 이벤트 컬럼이 필요해요!")
                if st.button("🏠 홈으로 가기", width="stretch", key="warn_home_survival"):
                    reset_tree()
                    st.rerun()
            else:
                c1, c2 = st.columns(2)
                with c1:
                    time_col = st.selectbox("시간 컬럼 (생존 기간)", num_cols, key="surv_time")
                with c2:
                    event_col = st.selectbox("이벤트 컬럼 (0/1)", event_opts, key="surv_event")
                group_col = st.selectbox("그룹 비교 (선택사항)", [None] + cat_cols, key="surv_group")
                if st.button("✅ 생존분석 시작", type="primary", width="stretch", key="btn_survival"):
                    add_user_msg("생존분석")
                    add_bot_msg("Kaplan-Meier 생존분석을 실행할게요! ⏱️", nav=False)
                    path_args = ["stats", "survival", time_col, event_col]
                    if group_col:
                        path_args.append(group_col)
                    run_analysis(path_args)
                    st.rerun()

        # ── LEVEL 2: cox → 시간+이벤트+공변량 선택 ────────────────
        elif step == 2 and path == ["stats", "cox"]:
            event_opts = [c for c in df.columns if set(df[c].dropna().unique()).issubset({0, 1, '0', '1', 0.0, 1.0})]
            if len(num_cols) < 1 or not event_opts:
                st.warning("시간을 나타내는 수치형 컬럼과 0/1로 이루어진 이벤트 컬럼이 필요해요!")
                if st.button("🏠 홈으로 가기", width="stretch", key="warn_home_cox"):
                    reset_tree()
                    st.rerun()
            else:
                c1, c2 = st.columns(2)
                with c1:
                    time_col = st.selectbox("시간 컬럼", num_cols, key="cox_time")
                with c2:
                    event_col = st.selectbox("이벤트 컬럼 (0/1)", event_opts, key="cox_event")
                x_opts = [c for c in num_cols if c not in [time_col, event_col]]
                x_cols = st.multiselect("공변량 (분석 변수)", x_opts,
                                        default=x_opts[:3] if len(x_opts) >= 3 else x_opts, key="cox_x")
                if x_cols and st.button("✅ Cox 회귀 시작", type="primary", width="stretch", key="btn_cox"):
                    add_user_msg("Cox 회귀 분석")
                    add_bot_msg("Cox 비례위험 모델을 실행할게요! 📉", nav=False)
                    run_analysis(["stats", "cox", time_col, event_col] + x_cols)
                    st.rerun()
        # ── LEVEL 2: pivot 1:N ───────────────────────────────────
        elif step == 2 and path == ["pivot", "1n"]:
            all_cols = df.columns.tolist()
            pid = st.session_state.patient_id_col
            default_idx = [pid] if pid and pid in all_cols else []
            index_sel = st.multiselect("기준 컬럼 (같은 값끼리 묶기)", all_cols, default=default_idx, key="piv_idx")
            if index_sel:
                remaining = [c for c in all_cols if c not in index_sel]
                n_counts = df.groupby(index_sel).size()
                st.caption(f"📊 기준별 데이터 수: 최소 {n_counts.min()} / 최대 {int(n_counts.max())} / 평균 {n_counts.mean():.1f}")
                values_sel = st.multiselect("펼칠 데이터 컬럼", remaining, key="piv_vals")

                if values_sel:
                    st.divider()
                    st.markdown("##### ⚙️ 펼치기 옵션")

                    # ── 정렬 옵션 ──
                    sort_col_opts = ["정렬 안 함"] + remaining
                    sc1, sc2 = st.columns(2)
                    with sc1:
                        sort_col = st.selectbox(
                            "📋 정렬 기준 컬럼",
                            sort_col_opts,
                            help="펼치기 전에 각 그룹 내 데이터를 정렬합니다. 예: 날짜 기준 오름차순 → _1이 가장 오래된 날짜",
                            key="piv_sort_col"
                        )
                    with sc2:
                        sort_dir = st.selectbox(
                            "↕️ 정렬 방향",
                            ["오름차순 (작은 값 → 큰 값)", "내림차순 (큰 값 → 작은 값)"],
                            key="piv_sort_dir"
                        )

                    # ── 인터리브 옵션 (펼칠 컬럼 2개 이상일 때) ──
                    interleave = False
                    interleave_groups = None
                    if len(values_sel) >= 2:
                        interleave = st.checkbox(
                            "🔀 컬럼 순서 인터리브 (A_1, B_1, A_2, B_2 형식)",
                            value=False ,
                            help="체크하면 같은 순번끼리 묶어서 배치해요. "
                                 "해제하면 A_1, A_2, A_3, B_1, B_2, B_3 순으로 나와요.",
                            key="piv_interleave"
                        )
                        if interleave:
                            mode = st.radio("인터리브 방식", ["묶음 크기로 자동 지정", "그룹 직접 지정"], horizontal=True, key="piv_inter_mode")
                            
                            if mode == "묶음 크기로 자동 지정":
                                g_size = st.number_input("📦 묶음 크기", min_value=1, max_value=len(values_sel), value=len(values_sel), step=1, key="piv_g_size")
                                interleave_groups = [values_sel[i:i+g_size] for i in range(0, len(values_sel), g_size)]
                            else:
                                st.caption("💡 각 컬럼이 속할 그룹 번호와 그룹 내 순서를 지정하세요.")
                                group_data = pd.DataFrame({
                                    "컬럼": values_sel,
                                    "그룹": [1] * len(values_sel),
                                    "순서": list(range(1, len(values_sel) + 1))
                                })
                                edited_df = st.data_editor(
                                    group_data,
                                    column_config={
                                        "컬럼": st.column_config.TextColumn("컬럼", disabled=True),
                                        "그룹": st.column_config.NumberColumn("그룹", min_value=1, step=1),
                                        "순서": st.column_config.NumberColumn("순서", min_value=1, step=1),
                                    },
                                    hide_index=True,
                                    use_container_width=True,
                                    key="piv_group_editor"
                                )
                                # 그룹화 로직
                                g_dict = {}
                                for _, row in edited_df.sort_values(["그룹", "순서"]).iterrows():
                                    gn = row["그룹"]
                                    if gn not in g_dict: g_dict[gn] = []
                                    g_dict[gn].append(row["컬럼"])
                                interleave_groups = [g_dict[k] for k in sorted(g_dict.keys())]

                            # 미리보기
                            if interleave_groups:
                                groups_preview = [" + ".join(g) for g in interleave_groups]
                                st.markdown(
                                    f"<div style='font-size:1.0rem; color:#475569; margin-top:1px; margin-bottom:8px'>"
                                    f"📋 <b>그룹 구성:</b> {' | '.join(f'[{gp}]' for gp in groups_preview)}</div>",
                                    unsafe_allow_html=True
                                )

                    if st.button("✅ 펼치기 시작", type="primary", width="stretch", key="btn_1n"):
                        # 정렬 메시지 생성
                        sort_msg = ""
                        if sort_col != "정렬 안 함":
                            dir_label = "오름차순" if "오름차순" in sort_dir else "내림차순"
                            sort_msg = f" ({sort_col} {dir_label} 정렬)"

                        add_user_msg(f"{', '.join(index_sel)} 기준으로 {', '.join(values_sel)} 펼쳐줘{sort_msg}")
                        add_bot_msg("선택한 설정으로 데이터를 펼칠게요! 🎉", nav=False)
                        with st.spinner("데이터를 처리하는 중이에요..."):
                            try:
                                # 정렬 적용
                                pivot_source = df.copy()
                                if sort_col != "정렬 안 함":
                                    ascending = "오름차순" in sort_dir
                                    pivot_source = pivot_source.sort_values(
                                        by=index_sel + [sort_col],
                                        ascending=[True]*len(index_sel) + [ascending]
                                    ).reset_index(drop=True)

                                result_df = perform_pivot(
                                    pivot_source, index_sel, values_sel,
                                    agg_func='first', sort_by_seq=interleave,
                                    classic_mode=False,
                                    interleave_groups=interleave_groups
                                )
                                buf = io.BytesIO()
                                with pd.ExcelWriter(buf, engine='openpyxl') as w:
                                    result_df.reset_index().to_excel(w, sheet_name='Result', index=False)
                                csv_data = result_df.reset_index().to_csv(index=False, encoding='utf-8-sig')
                                add_bot_msg(
                                    f"✅ 완료! **{len(result_df):,}행 × {len(result_df.columns)}열** 결과예요 🎉",
                                    result_df=result_df.head(1000),
                                    export_data={"excel": buf.getvalue(), "csv": csv_data, "png": b""},
                                )
                            except Exception as e:
                                add_bot_msg(f"❌ 오류가 발생했어요: {e}")
                        reset_tree()
                        st.rerun()

        # ── LEVEL 2: pivot classic ────────────────────────────────
        elif step == 2 and path == ["pivot", "classic"]:
            all_cols = df.columns.tolist()
            num_c = df.select_dtypes("number").columns.tolist()
            index_sel = st.multiselect("기준 컬럼 (행)", all_cols, key="cpiv_idx")
            col_sel = st.selectbox("열 컬럼", [None] + all_cols, key="cpiv_col")
            val_sel = st.multiselect("값 컬럼 (숫자)", num_c, key="cpiv_val")
            agg = st.selectbox("집계 방법", ["sum", "mean", "count", "min", "max", "first"], key="cpiv_agg")

            if index_sel and val_sel:
                st.divider()
                st.markdown("##### ⚙️ 정렬 옵션")
                sort_col_opts = ["정렬 안 함"] + all_cols
                sc1, sc2 = st.columns(2)
                with sc1:
                    sort_col = st.selectbox(
                        "📋 정렬 기준 컬럼",
                        sort_col_opts,
                        help="피벗 전에 데이터를 정렬합니다.",
                        key="cpiv_sort_col"
                    )
                with sc2:
                    sort_dir = st.selectbox(
                        "↕️ 정렬 방향",
                        ["오름차순 (작은 값 → 큰 값)", "내림차순 (큰 값 → 작은 값)"],
                        key="cpiv_sort_dir"
                    )

            if index_sel and val_sel and st.button("✅ 피벗 시작", type="primary", width="stretch", key="btn_cpiv"):
                sort_msg = ""
                if sort_col != "정렬 안 함":
                    dir_label = "오름차순" if "오름차순" in sort_dir else "내림차순"
                    sort_msg = f" / {sort_col} {dir_label}"
                add_user_msg(f"집계하여 요약 ({agg}{sort_msg})")
                add_bot_msg(f"**{agg}** 방식으로 피벗을 실행할게요! 📊", nav=False)
                with st.spinner("처리 중..."):
                    try:
                        pivot_source = df.copy()
                        if sort_col != "정렬 안 함":
                            ascending = "오름차순" in sort_dir
                            pivot_source = pivot_source.sort_values(
                                by=[sort_col], ascending=ascending
                            ).reset_index(drop=True)
                        result_df = perform_pivot(pivot_source, index_sel, val_sel, agg_func=agg,
                                                   classic_mode=True, columns_col=col_sel)
                        buf = io.BytesIO()
                        with pd.ExcelWriter(buf, engine='openpyxl') as w:
                            result_df.reset_index().to_excel(w, sheet_name='Result', index=False)
                        csv_data = result_df.reset_index().to_csv(index=False, encoding='utf-8-sig')
                        add_bot_msg(
                            f"✅ 완료! **{len(result_df):,}행** 결과예요 🎉",
                            result_df=result_df.head(1000),
                            export_data={"excel": buf.getvalue(), "csv": csv_data, "png": b""},
                        )
                    except Exception as e:
                        add_bot_msg(f"❌ 오류: {e}")
                go_back_to_section("pivot")
                st.rerun()

    # ── 메인 영역: 설정 단계 UI ─────────────────────────────────
    def render_config_steps():
        """메인 영역: 데이터 설정 단계별 UI"""
        df = st.session_state.df
        config_step = st.session_state.config_step
        all_cols = [""] + df.columns.tolist()

        # ═══ Step 1: 환자 ID · 종속변수 설정 ═══
        if config_step >= 1:
            with st.chat_message("assistant"):
                st.markdown(
                    "다음으로 분석에 필요한 기본 설정을 해볼게요! ⚙️\n\n"
                    "**🆔 환자 ID 컬럼**: 개인을 식별하는 컬럼이에요. "
                    "설정하면 분석 변수에서 자동으로 제외돼요.\n\n"
                    "**🎯 종속변수 컬럼**: 분석의 목표(결과) 변수예요. "
                    "회귀분석 등에서 Y변수로 자동 선택돼요."
                )

            if config_step == 1:
                with st.bottom:
                    c1, c2 = st.columns(2)
                    with c1:
                        pid_idx = all_cols.index(st.session_state.patient_id_col) if st.session_state.patient_id_col in all_cols else 0
                        pid = st.selectbox("🆔 환자 ID 컬럼", all_cols, index=pid_idx,
                                           help="개인 식별자 (분석에서 제외됨)", key="cfg_pid")
                        st.session_state.patient_id_col = pid if pid else None
                    with c2:
                        dep_idx = all_cols.index(st.session_state.dependent_var_col) if st.session_state.dependent_var_col in all_cols else 0
                        dep = st.selectbox("🎯 종속변수 컬럼", all_cols, index=dep_idx,
                                           help="분석의 목표 변수", key="cfg_dep")
                        st.session_state.dependent_var_col = dep if dep else None

                    # 종속변수 범주형 변환 옵션
                    dep = st.session_state.dependent_var_col
                    if dep and dep in df.columns and pd.api.types.is_numeric_dtype(df[dep]):
                        unique_n = df[dep].nunique()
                        st.caption(f"ℹ️ **{dep}**는 수치형 (고유값 {unique_n}개)")
                        convert = st.checkbox(
                            f"🔄 '{dep}'을 범주형으로 변환 (예: 0/1 코드)",
                            value=st.session_state.dep_var_as_cat,
                            key="cfg_dep_cat")
                        st.session_state.dep_var_as_cat = convert
                        if convert and df[dep].dtype != "object":
                            st.session_state.df[dep] = df[dep].astype(str)
                        elif not convert and df[dep].dtype == "object":
                            try:
                                st.session_state.df[dep] = pd.to_numeric(df[dep])
                            except ValueError:
                                pass
                    elif dep and dep in df.columns:
                        st.caption(f"ℹ️ **{dep}**는 범주형 (고유값 {df[dep].nunique()}개)")

                    c_skip, c_next = st.columns(2)
                    if c_skip.button("⏭️ 건너뛰기", width="stretch", key="cfg_skip1"):
                        st.session_state.config_step = 2
                        st.rerun()
                    if c_next.button("✅ 다음 단계로", type="primary",
                                      width='stretch', key="cfg_next1"):
                        pid = st.session_state.patient_id_col
                        dep = st.session_state.dependent_var_col
                        add_user_msg("데이터 설정 완료")
                        add_bot_msg(f"환자 ID: **{pid or '미설정'}** / "
                                   f"종속변수: **{dep or '미설정'}** 으로 설정했어요! 👍",
                                   nav=False)
                        st.session_state.config_step = 2
                        st.rerun()

        # ═══ Step 2: 데이터 타입 확인 · 변환 ═══
        if config_step >= 2:
            with st.chat_message("assistant"):
                st.markdown(
                    "이제 각 컬럼의 **데이터 타입**을 확인해볼게요! 📋\n\n"
                    "아래 표에서 변환이 필요한 컬럼의 **행을 클릭**하면 "
                    "타입을 변경할 수 있어요."
                )
                # DATE 자동 변환 결과 안내
                auto_dates = [c for c, t in st.session_state.dtype_overrides.items()
                              if "자동" in t]
                if auto_dates:
                    st.info(f"📅 날짜로 자동 변환됨: {', '.join(auto_dates)}")

            if config_step == 2:
                # ── 타입 변환 추천 ──
                recs = st.session_state.get("type_recommendations", [])
                # 이미 변환된 컬럼은 제외
                recs = [r for r in recs if r["col"] not in st.session_state.dtype_overrides]
                if recs:
                    st.markdown("##### 💡 타입 변환 추천")
                    
                    # 모두 적용 버튼 (추천이 2개 이상일 때만)
                    if len(recs) > 1:
                        if st.button("✨ 추천 모두 적용하기", type="primary", width='stretch', key="rec_apply_all"):
                            for rec in recs:
                                if rec["action_type"] == "id_candidate":
                                    st.session_state.patient_id_col = rec["col"]
                                else:
                                    col = rec["col"]
                                    if col not in st.session_state.dtype_originals:
                                        st.session_state.dtype_originals[col] = df[col].copy()
                                    st.session_state.df[col] = df[col].astype("category")
                                    st.session_state.dtype_overrides[col] = "범주형 (추천)"
                            st.rerun()
                            
                    with st.container(height=300):
                        for idx, rec in enumerate(recs):
                            rc1, rc2 = st.columns([4, 1])
                            rc1.markdown(f"{rec['icon']} **{rec['col']}**: {rec['reason']}")
                            if rec["action_type"] == "id_candidate":
                                if rc2.button("🆔 ID 설정", key=f"rec_id_{idx}",
                                               width='stretch'):
                                    st.session_state.patient_id_col = rec["col"]
                                    st.rerun()
                            else:
                                if rc2.button(f"🔄 변환", key=f"rec_apply_{idx}",
                                               width='stretch'):
                                    col = rec["col"]
                                    if col not in st.session_state.dtype_originals:
                                        st.session_state.dtype_originals[col] = df[col].copy()
                                    st.session_state.df[col] = df[col].astype("category")
                                    st.session_state.dtype_overrides[col] = "범주형 (추천)"
                                    st.rerun()
                    st.divider()

                # dtype 요약 테이블 (st.dataframe + 행 선택)
                dtype_df = pd.DataFrame({
                    "컬럼명": df.columns,
                    "현재 타입": [sf._dtype_label_kr(df[c].dtype) for c in df.columns],
                    "고유값": [int(df[c].nunique()) for c in df.columns],
                    "결측": [int(df[c].isna().sum()) for c in df.columns],
                    "샘플": [str(df[c].dropna().iloc[0])[:30]
                             if df[c].notna().any() else "-" for c in df.columns],
                })

                event = st.dataframe(
                    dtype_df,
                    on_select="rerun",
                    selection_mode="multi-row",
                    width='stretch',
                    hide_index=True,
                    key="dtype_selector",
                )

                # 행 선택 시 변환 UI 표시
                selected_rows = event.selection.get("rows", [])
                if selected_rows:
                    selected_cols = [df.columns[i] for i in selected_rows]
                    st.caption(f"✅ 선택: **{', '.join(selected_cols)}**")

                    type_options = ["수치형 (float)", "정수형 (int)",
                                    "문자형 (object)", "범주형 (category)",
                                    "날짜형 (date)"]
                    target = st.selectbox("변환할 타입", type_options,
                                           key="cfg_dtype_target")

                    if st.button("🔄 선택 컬럼 변환", type="primary",
                                  width='stretch', key="btn_dtype"):
                        for col in selected_cols:
                            # 원본 백업 (최초 1회만)
                            if col not in st.session_state.dtype_originals:
                                st.session_state.dtype_originals[col] = df[col].copy()
                            try:
                                if "수치형" in target:
                                    st.session_state.df[col] = pd.to_numeric(
                                        df[col], errors='coerce')
                                elif "정수형" in target:
                                    st.session_state.df[col] = pd.to_numeric(
                                        df[col], errors='coerce').astype('Int64')
                                elif "문자형" in target:
                                    st.session_state.df[col] = df[col].astype(str)
                                elif "범주형" in target:
                                    st.session_state.df[col] = df[col].astype("category")
                                elif "날짜형" in target:
                                    st.session_state.df[col] = pd.to_datetime(
                                        df[col], errors='coerce')
                                st.session_state.dtype_overrides[col] = target
                            except Exception as e:
                                st.error(f"❌ {col} 변환 실패: {e}")
                        st.rerun()

                # 변환 이력 + 되돌리기
                if st.session_state.dtype_overrides:
                    st.divider()
                    st.caption("📋 변환 이력")
                    with st.container(height=200):
                        for col, t in list(st.session_state.dtype_overrides.items()):
                            c1, c2 = st.columns([3, 1])
                            c1.caption(f"• **{col}** → {t}")
                            if c2.button("↩️", key=f"undo_{col}",
                                          help=f"{col} 원본으로 되돌리기"):
                                st.session_state.df[col] = (
                                    st.session_state.dtype_originals[col].copy())
                                del st.session_state.dtype_overrides[col]
                                del st.session_state.dtype_originals[col]
                                st.rerun()

                # 완료 버튼
                with st.bottom:
                    c_skip2, c_done = st.columns(2)
                    if c_skip2.button("⏭️ 건너뛰기", width='stretch',
                                       key="cfg_skip2"):
                        st.session_state.data_configured = True
                        st.session_state.config_step = 3
                        add_bot_msg("설정을 완료했어요! 어떤 분석을 해볼까요? 😊", nav=False)
                        st.rerun()
                    if c_done.button("✅ 설정 완료 → 분석 시작!", type="primary",
                                      width='stretch', key="cfg_done"):
                        st.session_state.data_configured = True
                        st.session_state.config_step = 3
                        add_bot_msg("모든 설정이 완료됐어요! 🎉 어떤 분석을 해볼까요?", nav=False)
                        st.rerun()

    # ── 메인 영역 렌더링 분기 ─────────────────────────────────────
    if df is None:
        pass  # 웰컴 메시지는 위에서 chat_message로 표시
    elif not st.session_state.data_configured:
        render_config_steps()
    else:
        with st.bottom:
            render_level()
            # 하단 네비게이션:
            # - 분석 완료 후 tree_step==1 (같은 섹션 Level 2 보여주는 중)
            #   일 때만 표시 → "다른 분석 해줘"는 Level 1(최상위)로 복귀
            if (st.session_state.result_section is not None
                    and st.session_state.tree_step == 1):
                # st.divider()
                if st.button("🏠 홈으로 가기", width="stretch", key="nav_home_bottom"):
                    add_user_msg("홈으로 가기")
                    add_bot_msg("처음으로 돌아왔어요! 어떤 분석을 해볼까요? 😊", nav=False)
                    reset_tree()  # 완전 리셋 → Level 0 (최상위 선택)
                    st.rerun()

    # ── 자동 스크롤 로직 ──────────────────────────────────────────────
    if "last_msg_count" not in st.session_state:
        st.session_state.last_msg_count = len(st.session_state.chat_history)
        
    current_msg_count = len(st.session_state.chat_history)
    
    # 새로운 대화(채팅)가 추가되었을 때만 스크롤을 내리도록 제한
    if current_msg_count > st.session_state.last_msg_count:
        js_scroll = """
        <script>
            setTimeout(function() {
                var doc = window.parent.document || document;
                // Streamlit 메인 스크롤 컨테이너를 찾아 맨 아래로 스크롤
                var selectors = [
                    'section.stMain',
                    '[data-testid="stMain"]',
                    '.main',
                    '[data-testid="stAppViewContainer"]'
                ];
                for (var i = 0; i < selectors.length; i++) {
                    var el = doc.querySelector(selectors[i]);
                    if (el && el.scrollHeight > el.clientHeight) {
                        el.scrollTo({top: el.scrollHeight, behavior: 'smooth'});
                        return;
                    }
                }
                // 폴백: 부모 윈도우 전체 스크롤
                window.parent.scrollTo({top: doc.body.scrollHeight, behavior: 'smooth'});
            }, 150);
        </script>
        """
        st.html(js_scroll, unsafe_allow_javascript=True)
        st.session_state.last_msg_count = current_msg_count
