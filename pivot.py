import streamlit as st
import pandas as pd
from pandas.api.types import is_datetime64_any_dtype
import io
import re
from datetime import datetime
import traceback
import streamlit_authenticator as stauth


# =============================================================================
# 핵심 로직: 1:N 펼치기 / 일반 피벗 수행 함수
# =============================================================================
def perform_pivot(source_df, index_cols, values_col, agg_func='first',
                  max_n=None, sort_by_seq=False, custom_prefix=None,
                  classic_mode=False, columns_col=None):
    """
    데이터를 피벗/펼치기 처리하는 핵심 함수.

    Args:
        source_df: 원본 DataFrame
        index_cols: 기준(행) 컬럼 리스트
        values_col: 값 컬럼 리스트
        agg_func: 집계 함수
        max_n: 1:N 펼치기 시 최대 N 값
        sort_by_seq: True면 순번별 정렬 (진단_1, 약품_1, 진단_2, 약품_2...)
        custom_prefix: 컬럼 접두어 딕셔너리 {원본명: 접두어}
        classic_mode: True면 일반 피벗 모드
        columns_col: 일반 피벗 시 열(Columns) 컬럼

    Returns:
        피벗 결과 DataFrame
    """
    # 필요한 컬럼만 복사 (메모리 최적화)
    needed_cols = list(set(
        index_cols + values_col + ([columns_col] if columns_col else [])
    ))
    temp_df = source_df[needed_cols].copy()

    # --- NULL 처리 및 데이터 타입 통일 ---
    for col in index_cols:
        if temp_df[col].dtype == 'object':
            temp_df[col] = temp_df[col].fillna("(NULL)").astype(str)
        elif is_datetime64_any_dtype(temp_df[col]):
            temp_df[col] = temp_df[col].dt.strftime('%Y-%m-%d').fillna("(NULL)").astype(str)
        else:
            temp_df[col] = temp_df[col].astype(str).replace('nan', '(NULL)')

    if classic_mode:
        # --- 일반 피벗 모드 ---
        fill_val = 0
        if columns_col:
            if temp_df[columns_col].dtype == 'object':
                temp_df[columns_col] = temp_df[columns_col].fillna("(NULL)").astype(str)
            elif is_datetime64_any_dtype(temp_df[columns_col]):
                temp_df[columns_col] = temp_df[columns_col].dt.strftime('%Y-%m-%d').fillna("(NULL)").astype(str)
            else:
                temp_df[columns_col] = temp_df[columns_col].astype(str).replace('nan', '(NULL)')
        pivot_col_target = columns_col
    else:
        # --- 1:N 펼치기 모드 ---
        fill_val = "-"
        # Values 컬럼 날짜 타입 처리
        for val_c in values_col:
            if is_datetime64_any_dtype(temp_df[val_c]):
                temp_df[val_c] = temp_df[val_c].dt.strftime('%Y-%m-%d %H:%M:%S').fillna("(NULL)").astype(str)

        # 순번 생성
        temp_df['__seq__'] = temp_df.groupby(index_cols).cumcount() + 1

        # 최대 N 제한
        if max_n is not None:
            temp_df = temp_df[temp_df['__seq__'] <= max_n]

        pivot_col_target = '__seq__'

    # --- 피벗 테이블 생성 ---
    pivot_df = temp_df.pivot_table(
        index=index_cols,
        columns=pivot_col_target,
        values=values_col,
        aggfunc=agg_func,
        fill_value=fill_val
    )

    # --- MultiIndex 컬럼 평탄화 ---
    prefix_map = custom_prefix or {v: v for v in values_col}

    if isinstance(pivot_df.columns, pd.MultiIndex):
        pivot_df.columns = [
            f"{prefix_map.get(col[0], col[0])}_{col[1]}"
            for col in pivot_df.columns
        ]
    else:
        if not classic_mode:
            val_name = values_col[0]
            prefix = prefix_map.get(val_name, val_name)
            pivot_df.columns = [f"{prefix}_{col}" for col in pivot_df.columns]

    # --- 순번별 정렬 (요청 시) ---
    if sort_by_seq and not classic_mode and len(values_col) > 1:
        def col_sort_key(col_name):
            match = re.search(r'_(\d+)$', col_name)
            seq = int(match.group(1)) if match else 0
            return (seq, col_name)
        pivot_df = pivot_df[sorted(pivot_df.columns, key=col_sort_key)]

    # --- 원본 순서 유지 (Left Merge) ---
    pivot_df_reset = pivot_df.reset_index()
    unique_indices = temp_df[index_cols].drop_duplicates()

    final_df = pd.merge(unique_indices, pivot_df_reset, on=index_cols, how='left')
    final_df = final_df.fillna(fill_val)
    final_df = final_df.set_index(index_cols)

    return final_df


# =============================================================================
# 1. 페이지 설정 (가장 먼저 와야 함)
# =============================================================================
st.set_page_config(page_title="데이터 펼치기 도구", layout="wide")


# =============================================================================
# 2. 인증 (Authentication)
# =============================================================================
try:
    config = st.secrets.to_dict()
    credentials = config['credentials']
    cookie_settings = config['cookie']
except FileNotFoundError:
    st.error("❌ .streamlit/secrets.toml 파일이 없습니다. 설정을 확인해주세요.")
    st.stop()
except KeyError:
    st.error("❌ secrets.toml 형식 오류. [credentials]와 [cookie] 섹션을 확인하세요.")
    st.stop()

authenticator = stauth.Authenticate(
    credentials,
    cookie_settings['name'],
    cookie_settings['key'],
    cookie_settings['expiry_days']
)

authenticator.login(location='main')

if st.session_state["authentication_status"] is False:
    st.error('❌ 아이디 또는 비밀번호가 틀렸습니다.')
elif st.session_state["authentication_status"] is None:
    st.warning('🔒 로그인이 필요합니다.')
elif st.session_state["authentication_status"]:
    # ================================================================
    # 로그인 성공 → 메인 애플리케이션
    # ================================================================

    # --- 세션 상태 초기화 ---
    for key, default in {
        'df': None, 'source_name': '', 'loaded_file_key': None,
        '_pivot_key': None, '_pivot_result': None, '_excel_buffer': None
    }.items():
        if key not in st.session_state:
            st.session_state[key] = default

    # --- 사이드바: 로그아웃 + 데이터 현황 ---
    with st.sidebar:
        st.write(f"👤 **{st.session_state['name']}**님")
        authenticator.logout('로그아웃', 'sidebar')
        st.divider()

        if st.session_state.df is not None:
            _sb_df = st.session_state.df
            st.subheader("📋 데이터 현황")
            st.caption(f"📂 {st.session_state.source_name}")
            sc1, sc2 = st.columns(2)
            sc1.metric("행", f"{len(_sb_df):,}")
            sc2.metric("열", f"{len(_sb_df.columns):,}")

            num_c = len(_sb_df.select_dtypes(include=['int64', 'float64']).columns)
            str_c = len(_sb_df.select_dtypes(include=['object']).columns)
            date_c = sum(1 for c in _sb_df.columns if is_datetime64_any_dtype(_sb_df[c]))
            st.caption(f"숫자 {num_c}개 · 문자 {str_c}개 · 날짜 {date_c}개")
        else:
            st.info("파일을 업로드하면\n여기에 정보가 표시됩니다.")

    # --- 메인 타이틀 ---
    st.title("📊 데이터 펼치기 도구")
    st.caption("1:N 관계의 데이터를 가로로 펼쳐서 보기 쉽게 정리합니다.")

    # ================================================================
    # Step 1. 데이터 업로드
    # ================================================================
    st.markdown("---")
    st.markdown("## 📁 Step 1. 데이터 업로드")

    uploaded_file = st.file_uploader(
        "CSV 또는 Excel 파일을 업로드하세요",
        type=['csv', 'xlsx'],
        help="UTF-8/CP949 인코딩의 CSV, Excel(.xlsx) 파일을 지원합니다."
    )

    if uploaded_file is not None:
        file_key = f"{uploaded_file.name}_{uploaded_file.size}"
        if st.session_state.loaded_file_key != file_key:
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
                # 새 파일 → 이전 피벗 결과 초기화
                st.session_state._pivot_key = None
                st.session_state._pivot_result = None
                st.session_state._excel_buffer = None
            except Exception as e:
                st.error(f"파일을 읽는 중 오류가 발생했습니다: {e}")

    # --- 데이터 미리보기 ---
    if st.session_state.df is not None:
        df = st.session_state.df

        st.success(
            f"✅ **{st.session_state.source_name}** — "
            f"{len(df):,}행 × {len(df.columns)}열"
        )
        st.dataframe(df.head(5), width='stretch')

        # 컬럼 상세 정보
        with st.expander("🔍 컬럼 상세 정보 보기"):
            col_info = pd.DataFrame({
                '데이터 타입': df.dtypes.astype(str),
                '고유값 수': df.nunique(),
                'NULL 수': df.isnull().sum(),
                'NULL 비율(%)': (df.isnull().sum() / len(df) * 100).round(1)
            })
            st.dataframe(col_info, width='stretch')

        # ================================================================
        # Step 2. 펼치기 설정
        # ================================================================
        st.markdown("---")
        st.markdown("## ⚙️ Step 2. 펼치기 설정")

        all_columns = df.columns.tolist()
        numeric_columns = df.select_dtypes(include=['int64', 'float64']).columns.tolist()

        # --- 모드 선택 ---
        pivot_mode = st.radio(
            "모드 선택",
            ["📊 1:N 데이터 펼치기", "📈 일반 집계 피벗 (sum, count 등)"],
            horizontal=True,
            help="1:N 펼치기: 상세 데이터를 가로로 나열 | 일반 피벗: 수치 데이터 집계"
        )
        classic_mode = pivot_mode.startswith("📈")

        if not classic_mode:
            st.info("💡 **1:N 펼치기 모드**: 기준 컬럼으로 묶은 뒤, 상세 데이터를 가로로 나열합니다.")
        else:
            st.info("💡 **일반 피벗 모드**: Excel 피벗 테이블처럼 수치 데이터를 집계합니다.")

        # --- B-1: 1:N 관계 자동 분석 ---
        with st.expander("💡 어떤 컬럼을 기준으로 잡아야 할지 모르겠다면?"):
            analysis_data = []
            for col in all_columns:
                unique_count = df[col].nunique()
                ratio = unique_count / len(df) if len(df) > 0 else 0
                if ratio < 0.3:
                    role = "📌 기준 컬럼 후보 (값이 반복됨)"
                elif ratio > 0.8:
                    role = "📋 펼칠 데이터 후보 (값이 다양함)"
                else:
                    role = "— 어느 쪽이든 활용 가능"
                analysis_data.append({
                    '컬럼명': col,
                    '고유값 수': f"{unique_count:,}",
                    '전체 행': f"{len(df):,}",
                    '유일 비율': f"{ratio:.1%}",
                    '추천': role
                })
            st.dataframe(
                pd.DataFrame(analysis_data),
                width='stretch', hide_index=True
            )
            st.caption(
                "💡 고유값이 적은(반복 많은) 컬럼 → **기준 컬럼** | "
                "고유값이 다양한 컬럼 → **펼칠 데이터**"
            )

        # --- Step 2-1: 기준 컬럼 ---
        st.markdown("### 2-1️⃣ 기준 컬럼을 선택하세요")
        index_cols = st.multiselect(
            "📌 기준 컬럼",
            all_columns,
            help="이 컬럼의 값이 같은 행들이 하나로 묶입니다. 예: 환자ID, 주문번호"
        )

        if index_cols:
            remaining = [c for c in all_columns if c not in index_cols]

            # --- 기본값 설정 (모든 경로에서 사용) ---
            columns_col = None
            values_col = []
            agg_func = 'first'
            max_n = None
            sort_by_seq = False
            custom_prefix = {}

            if classic_mode:
                # ========================================
                # 일반 피벗 모드 UI
                # ========================================
                st.markdown("### 2-2️⃣ 열(Columns)과 값(Values)을 선택하세요")
                pc1, pc2 = st.columns(2)
                with pc1:
                    columns_col = st.selectbox(
                        "📊 열 (가로축이 될 컬럼)",
                        [None] + remaining,
                        help="이 컬럼의 고유값이 결과의 열 헤더가 됩니다"
                    )
                with pc2:
                    values_col = st.multiselect(
                        "📋 값 (집계할 숫자 데이터)",
                        [c for c in numeric_columns if c not in index_cols],
                        help="sum, count 등으로 집계할 숫자 컬럼"
                    )

                agg_func = st.selectbox(
                    "집계 함수",
                    ['sum', 'mean', 'count', 'min', 'max', 'first'],
                    help="데이터를 어떻게 요약할지 선택"
                )
                max_n = None
                sort_by_seq = False
                custom_prefix = {v: v for v in values_col} if values_col else {}
            else:
                # ========================================
                # 1:N 펼치기 모드 UI
                # ========================================
                st.markdown("### 2-2️⃣ 옆으로 펼칠 데이터를 선택하세요")
                values_col = st.multiselect(
                    "📋 펼칠 데이터",
                    remaining,
                    help="이 항목들이 _1, _2, _3... 형태로 옆으로 나열됩니다"
                )
                columns_col = None

                if values_col:
                    # --- N 분포 분석 ---
                    n_counts = df.groupby(index_cols).size()
                    max_n_val = int(n_counts.max())

                    st.caption(
                        f"📊 기준별 상세 데이터 수: "
                        f"최소 **{n_counts.min()}**건 / "
                        f"최대 **{max_n_val}**건 / "
                        f"평균 **{n_counts.mean():.1f}**건"
                    )

                    # --- 상세 설정 ---
                    with st.expander("⚙️ 상세 설정 (선택사항)"):
                        set_c1, set_c2 = st.columns(2)

                        with set_c1:
                            # B-3: 최대 N 제한
                            if max_n_val > 1:
                                if max_n_val > 20:
                                    st.warning(
                                        f"⚠️ 최대 {max_n_val}건이 가로로 펼쳐집니다. "
                                        f"너무 많으면 아래에서 제한해주세요."
                                    )
                                max_n = st.slider(
                                    "최대 펼치기 수",
                                    min_value=1, max_value=max_n_val,
                                    value=min(20, max_n_val),
                                    help="기준 하나당 최대 몇 개까지 옆으로 나열할지"
                                )
                            else:
                                max_n = 1

                        with set_c2:
                            # 중복 시 처리 방법
                            agg_label = st.selectbox(
                                "중복 시 처리 방법",
                                ["첫 번째 값 사용", "마지막 값 사용",
                                 "가장 작은 값", "가장 큰 값"],
                                help="같은 기준+순번에 값이 여러 개일 때"
                            )
                            agg_map = {
                                "첫 번째 값 사용": "first",
                                "마지막 값 사용": "last",
                                "가장 작은 값": "min",
                                "가장 큰 값": "max"
                            }
                            agg_func = agg_map[agg_label]

                        # B-4: 컬럼 정렬 순서
                        if len(values_col) > 1:
                            sort_option = st.radio(
                                "결과 컬럼 정렬 방식",
                                [
                                    "항목별 그룹 (진단_1, 진단_2, ..., 약품_1, 약품_2, ...)",
                                    "순번별 그룹 (진단_1, 약품_1, ..., 진단_2, 약품_2, ...)"
                                ],
                                horizontal=True,
                                help="여러 항목을 펼칠 때 결과 컬럼의 배치 순서"
                            )
                            sort_by_seq = sort_option.startswith("순번별")
                        else:
                            sort_by_seq = False

                        # C-3: 컬럼 접두어 커스터마이징
                        st.markdown("**결과 컬럼 접두어 설정**")
                        custom_prefix = {}
                        num_prefix_cols = min(len(values_col), 4)
                        prefix_cols_ui = st.columns(num_prefix_cols)
                        for i, vc in enumerate(values_col):
                            with prefix_cols_ui[i % num_prefix_cols]:
                                custom_prefix[vc] = st.text_input(
                                    f"'{vc}' 접두어",
                                    value=vc,
                                    key=f"pfx_{vc}"
                                )

            # --- 데이터 필터링 (공통) ---
            filter_mask = pd.Series(True, index=df.index)

            with st.expander("🔍 데이터 필터링 (선택사항)"):
                filter_col = st.selectbox(
                    "필터 컬럼", [None] + all_columns, key="filter_col_sel"
                )
                if filter_col:
                    unique_vals = df[filter_col].dropna().unique()
                    if len(unique_vals) <= 100:
                        selected_filter = st.multiselect(
                            f"'{filter_col}' 값 선택",
                            sorted(unique_vals.astype(str))
                        )
                        if selected_filter:
                            filter_mask = df[filter_col].astype(str).isin(selected_filter)
                    else:
                        keyword = st.text_input(
                            f"'{filter_col}' 검색어 (포함)",
                            help="입력한 텍스트가 포함된 행만 남깁니다"
                        )
                        if keyword:
                            filter_mask = df[filter_col].astype(str).str.contains(
                                keyword, case=False, na=False
                            )

                    filtered_count = int(filter_mask.sum())
                    if filtered_count < len(df):
                        st.info(
                            f"✅ 필터 적용: **{filtered_count:,}**행 / "
                            f"전체 {len(df):,}행"
                        )

            # ================================================================
            # Step 3. 결과
            # ================================================================
            if values_col:
                st.markdown("---")
                st.markdown("## 📊 Step 3. 결과")

                # 필터 적용
                if filter_mask.all():
                    working_df = df
                else:
                    working_df = df[filter_mask]

                if len(working_df) == 0:
                    st.warning(
                        "⚠️ 필터 적용 후 데이터가 없습니다. "
                        "필터 조건을 확인해주세요."
                    )
                else:
                    try:
                        # --- B-2: 미리보기 (상위 3건) ---
                        sample_keys = working_df[index_cols].drop_duplicates().head(3)
                        sample_df = working_df.merge(
                            sample_keys, on=index_cols, how='inner'
                        )

                        preview_result = perform_pivot(
                            sample_df, index_cols, values_col,
                            agg_func=agg_func, max_n=max_n,
                            sort_by_seq=sort_by_seq,
                            custom_prefix=custom_prefix,
                            classic_mode=classic_mode,
                            columns_col=columns_col
                        )

                        total_groups = working_df.groupby(index_cols).ngroups
                        st.markdown(
                            f"#### 👀 미리보기 "
                            f"(상위 {min(3, total_groups)}건 / "
                            f"전체 {total_groups:,}건)"
                        )
                        st.dataframe(
                            preview_result, width='stretch'
                        )

                        # --- C-2: 원본 ↔ 결과 비교 ---
                        with st.expander("🔄 원본과 결과 비교 (첫 번째 그룹)"):
                            cmp1, cmp2 = st.columns(2)

                            # 첫 번째 키 값으로 원본 데이터 추출
                            first_key_values = sample_keys.iloc[0].to_dict()
                            orig_mask = pd.Series(True, index=sample_df.index)
                            for k, v in first_key_values.items():
                                if pd.isna(v):
                                    orig_mask &= sample_df[k].isna()
                                else:
                                    orig_mask &= (sample_df[k] == v)

                            with cmp1:
                                st.markdown("**📝 원본 (세로 구조)**")
                                display_cols = index_cols + [
                                    c for c in values_col
                                    if c in sample_df.columns
                                ]
                                st.dataframe(
                                    sample_df[orig_mask][display_cols],
                                    width='stretch',
                                    hide_index=True
                                )
                            with cmp2:
                                st.markdown("**📊 결과 (가로로 펼침)**")
                                st.dataframe(
                                    preview_result.head(1),
                                    width='stretch'
                                )

                        # --- 전체 실행 ---
                        current_key = str((
                            tuple(index_cols), tuple(values_col),
                            agg_func, max_n, sort_by_seq,
                            str(custom_prefix), classic_mode,
                            columns_col, int(filter_mask.sum())
                        ))

                        cached = (
                            st.session_state.get('_pivot_key') == current_key
                        )

                        btn_col, info_col = st.columns([1, 3])
                        with btn_col:
                            execute_btn = st.button(
                                "✅ 전체 데이터로 펼치기"
                                if not classic_mode
                                else "✅ 전체 데이터로 피벗",
                                type="primary"
                            )
                        with info_col:
                            if cached:
                                st.success(
                                    f"✅ 이전 결과 캐시됨 "
                                    f"({len(st.session_state._pivot_result):,}행)"
                                )

                        if execute_btn or cached:
                            if not cached:
                                with st.spinner("데이터를 처리하고 있습니다..."):
                                    final_df = perform_pivot(
                                        working_df, index_cols, values_col,
                                        agg_func=agg_func, max_n=max_n,
                                        sort_by_seq=sort_by_seq,
                                        custom_prefix=custom_prefix,
                                        classic_mode=classic_mode,
                                        columns_col=columns_col
                                    )

                                # 결과 & Excel 캐싱
                                st.session_state._pivot_key = current_key
                                st.session_state._pivot_result = final_df

                                buffer = io.BytesIO()
                                with pd.ExcelWriter(
                                    buffer, engine='openpyxl'
                                ) as writer:
                                    final_df.reset_index().to_excel(
                                        writer,
                                        sheet_name='Result',
                                        index=False
                                    )
                                st.session_state._excel_buffer = (
                                    buffer.getvalue()
                                )

                            final_df = st.session_state._pivot_result

                            # --- 결과 표시 ---
                            MAX_DISPLAY = 5000
                            total_rows = len(final_df)

                            st.markdown(
                                f"#### 📊 전체 결과 "
                                f"({total_rows:,}행 × "
                                f"{len(final_df.columns)}열)"
                            )

                            if total_rows > MAX_DISPLAY:
                                st.warning(
                                    f"⚠️ 결과가 {total_rows:,}행으로 많아 "
                                    f"상위 {MAX_DISPLAY:,}행만 표시합니다. "
                                    f"전체 데이터는 다운로드해주세요."
                                )
                                st.dataframe(
                                    final_df.head(MAX_DISPLAY),
                                    width='stretch'
                                )
                            else:
                                st.dataframe(
                                    final_df,
                                    width='stretch'
                                )

                            # --- 요약 통계 (일반 피벗) ---
                            if classic_mode:
                                numeric_result = final_df.select_dtypes(
                                    include=['int64', 'float64']
                                )
                                if not numeric_result.empty:
                                    st.markdown("#### 📈 요약 통계")
                                    mc1, mc2, mc3 = st.columns(3)
                                    mc1.metric(
                                        "합계",
                                        f"{numeric_result.sum().sum():,.0f}"
                                    )
                                    mc2.metric(
                                        "평균",
                                        f"{numeric_result.mean().mean():,.2f}"
                                    )
                                    mc3.metric(
                                        "최대값",
                                        f"{numeric_result.max().max():,.0f}"
                                    )

                            # --- 다운로드 ---
                            st.markdown("#### 📥 다운로드")
                            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                            mode_label = (
                                "펼치기" if not classic_mode else "피벗"
                            )

                            dl1, dl2 = st.columns(2)
                            with dl1:
                                st.download_button(
                                    label="📥 Excel(.xlsx) 다운로드",
                                    data=st.session_state._excel_buffer,
                                    file_name=(
                                        f"결과_{mode_label}_{timestamp}.xlsx"
                                    ),
                                    mime=(
                                        "application/vnd.openxmlformats-"
                                        "officedocument.spreadsheetml.sheet"
                                    )
                                )
                            with dl2:
                                csv_data = final_df.reset_index().to_csv(
                                    index=False, encoding='utf-8-sig'
                                )
                                st.download_button(
                                    label="📥 CSV 다운로드",
                                    data=csv_data,
                                    file_name=(
                                        f"결과_{mode_label}_{timestamp}.csv"
                                    ),
                                    mime='text/csv'
                                )

                    except KeyError as e:
                        st.error(
                            f"⚠️ 선택한 컬럼 '{e}'이 "
                            f"데이터에 존재하지 않습니다."
                        )
                    except ValueError as e:
                        st.error(f"⚠️ 데이터 처리 중 오류: {e}")
                        st.info(
                            "💡 기준 컬럼으로 데이터가 유일하게 구분되지 않아 "
                            "중복이 발생했을 수 있습니다."
                        )
                    except Exception as e:
                        st.error(f"❌ 예상치 못한 오류: {e}")
                        with st.expander("🔧 상세 오류 로그"):
                            st.code(traceback.format_exc())

            elif not values_col and classic_mode:
                st.info(
                    "👆 **기준 컬럼**, **열**, **값**을 모두 선택하면 "
                    "결과가 표시됩니다."
                )
            elif not values_col and not classic_mode:
                st.info(
                    "👆 **펼칠 데이터**를 선택하면 결과가 표시됩니다."
                )
        else:
            st.info("👆 먼저 **기준 컬럼**을 선택해주세요.")

    else:
        st.info("📂 데이터 파일을 업로드하면, 여기에 펼치기 도구가 표시됩니다.")