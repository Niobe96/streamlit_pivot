"""
stats_functions.py
통계 계산 + Plotly 차트 + 내보내기 모듈
"""
import io
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from scipy import stats as scipy_stats
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import r2_score, accuracy_score, classification_report
from sklearn.preprocessing import StandardScaler
from datetime import datetime
from statsmodels.stats.outliers_influence import variance_inflation_factor
from statsmodels.stats.proportion import proportions_ztest


# ──────────────────────────────────────────────────────────────────
# 기초 분석
# ──────────────────────────────────────────────────────────────────

def auto_analyze(df: pd.DataFrame) -> dict:
    """파일 업로드 직후 자동 실행 — 기본 정보 + 결측값 + 1:N 감지"""
    num_cols = df.select_dtypes(include=["number"]).columns.tolist()
    cat_cols = df.select_dtypes(include=["object", "category"]).columns.tolist()
    date_cols = [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])]

    missing = df.isnull().sum()
    missing = missing[missing > 0].to_dict()

    one_n = detect_1n_structure(df)

    return {
        "rows": len(df),
        "cols": len(df.columns),
        "num_cols": num_cols,
        "cat_cols": cat_cols,
        "date_cols": date_cols,
        "missing": missing,
        "one_n": one_n,
    }


def detect_1n_structure(df: pd.DataFrame) -> dict:
    """1:N 구조 감지"""
    candidates = []
    for col in df.columns:
        if df[col].nunique() == 0:
            continue
        ratio = df[col].nunique() / len(df)
        if ratio < 0.3:
            avg_rows = len(df) / df[col].nunique()
            if avg_rows >= 2.0:
                candidates.append({
                    "col": col,
                    "unique": df[col].nunique(),
                    "avg_rows": round(avg_rows, 1),
                })
    return {"is_1n": len(candidates) > 0, "candidates": candidates}


def describe_extended(df: pd.DataFrame) -> pd.DataFrame:
    """기술통계 (왜도·첨도 포함)"""
    num_df = df.select_dtypes(include=["number"])
    if num_df.empty:
        return pd.DataFrame()
    desc = num_df.describe().T
    desc["왜도"] = num_df.skew().round(3)
    desc["첨도"] = num_df.kurt().round(3)
    desc["결측수"] = num_df.isnull().sum()
    desc.index.name = "컬럼"
    return desc.round(3)


def plot_histogram(df: pd.DataFrame, col: str) -> tuple:
    """히스토그램 + 박스플롯 서브플롯"""
    data = df[col].dropna()
    fig = make_subplots(rows=1, cols=2,
                        subplot_titles=["분포 (히스토그램)", "이상치 (박스플롯)"],
                        column_widths=[0.65, 0.35])

    # 히스토그램
    fig.add_trace(
        go.Histogram(x=data, nbinsx=30, name=col,
                     marker_color="#4F86C6", opacity=0.8),
        row=1, col=1
    )
    # 박스플롯
    fig.add_trace(
        go.Box(y=data, name=col, marker_color="#4F86C6",
               boxmean="sd"),
        row=1, col=2
    )

    fig.update_layout(
        title=f"📊 {col} 분포 분석",
        showlegend=False,
        height=420,
        plot_bgcolor="white",
        paper_bgcolor="white",
        margin=dict(t=60, b=40, l=40, r=40),
    )
    fig.update_xaxes(showgrid=True, gridcolor="#E8E8E8")
    fig.update_yaxes(showgrid=True, gridcolor="#E8E8E8")

    stat_dict = {
        "컬럼": col,
        "개수": int(data.count()),
        "평균": round(float(data.mean()), 3),
        "중앙값": round(float(data.median()), 3),
        "표준편차": round(float(data.std()), 3),
        "최솟값": round(float(data.min()), 3),
        "최댓값": round(float(data.max()), 3),
        "왜도": round(float(data.skew()), 3),
        "결측수": int(df[col].isnull().sum()),
    }
    return fig, stat_dict


def plot_correlation(df: pd.DataFrame) -> tuple:
    """피어슨 상관계수 히트맵"""
    num_df = df.select_dtypes(include=["number"]).dropna()
    if num_df.shape[1] < 2:
        return None, pd.DataFrame()

    corr = num_df.corr().round(3)
    mask = np.triu(np.ones_like(corr, dtype=bool), k=1)
    pairs = []
    cols = corr.columns.tolist()
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            pairs.append({
                "변수1": cols[i],
                "변수2": cols[j],
                "r": corr.iloc[i, j],
                "강도": _corr_label(corr.iloc[i, j]),
            })
    pairs_df = pd.DataFrame(pairs).sort_values("r", key=abs, ascending=False)

    fig = px.imshow(
        corr,
        color_continuous_scale="RdBu_r",
        zmin=-1, zmax=1,
        text_auto=".2f",
        title="🔗 수치형 컬럼 상관관계 히트맵",
        aspect="auto",
    )
    fig.update_layout(height=450, margin=dict(t=60, b=40, l=40, r=40))
    return fig, pairs_df


def _corr_label(r: float) -> str:
    a = abs(r)
    if a >= 0.7:
        return "강함"
    elif a >= 0.4:
        return "중간"
    elif a >= 0.2:
        return "약함"
    return "거의 없음"


def plot_missing(df: pd.DataFrame) -> tuple:
    """결측값 현황 차트"""
    missing = df.isnull().sum().reset_index()
    missing.columns = ["컬럼", "결측수"]
    missing["결측률(%)"] = (missing["결측수"] / len(df) * 100).round(2)
    missing = missing[missing["결측수"] > 0].sort_values("결측수", ascending=False)

    if missing.empty:
        return None, missing

    fig = px.bar(
        missing, x="컬럼", y="결측률(%)",
        text="결측수",
        color="결측률(%)",
        color_continuous_scale=["#4CAF50", "#FF9800", "#F44336"],
        title="❓ 컬럼별 결측값 현황",
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(
        height=400, showlegend=False,
        plot_bgcolor="white", paper_bgcolor="white",
        margin=dict(t=60, b=40, l=40, r=40),
    )
    return fig, missing


def plot_frequency(df: pd.DataFrame, col: str) -> tuple:
    """범주형 빈도 분석"""
    freq = df[col].value_counts().reset_index()
    freq.columns = ["값", "빈도"]
    freq["비율(%)"] = (freq["빈도"] / len(df) * 100).round(1)

    fig = make_subplots(
        rows=1, cols=2,
        subplot_titles=["빈도 막대 그래프", "비율 파이 차트"],
        specs=[[{"type": "bar"}, {"type": "pie"}]],
    )
    colors = px.colors.qualitative.Pastel
    fig.add_trace(
        go.Bar(x=freq["값"].astype(str), y=freq["빈도"],
               marker_color=colors[:len(freq)], text=freq["빈도"],
               textposition="outside"),
        row=1, col=1,
    )
    fig.add_trace(
        go.Pie(labels=freq["값"].astype(str), values=freq["빈도"],
               hole=0.35, marker_colors=colors[:len(freq)]),
        row=1, col=2,
    )
    fig.update_layout(
        title=f"📂 {col} 빈도 분석",
        showlegend=False, height=420,
        plot_bgcolor="white", paper_bgcolor="white",
        margin=dict(t=60, b=40, l=40, r=40),
    )
    return fig, freq


# ──────────────────────────────────────────────────────────────────
# 고급 분석
# ──────────────────────────────────────────────────────────────────

def test_normality(df: pd.DataFrame, col: str) -> dict:
    """Shapiro-Wilk 정규성 검정"""
    data = df[col].dropna()
    # Shapiro는 최대 5000개 권장
    sample = data.sample(min(len(data), 5000), random_state=42) if len(data) > 5000 else data
    stat, p = scipy_stats.shapiro(sample)
    normal = p > 0.05
    return {
        "컬럼": col,
        "n": len(data),
        "검정통계량(W)": round(stat, 4),
        "p값": round(p, 4),
        "정규분포 여부": "✅ 예 (p > 0.05)" if normal else "❌ 아니오 (p ≤ 0.05)",
        "해석": (
            f"{col}은 정규분포를 따릅니다 (W={stat:.4f}, p={p:.4f})."
            if normal
            else f"{col}은 정규분포를 따르지 않습니다 (W={stat:.4f}, p={p:.4f}). "
                 "비모수 검정 사용을 권장합니다."
        ),
    }


def test_ttest(df: pd.DataFrame, col: str, group_col: str) -> tuple:
    """독립 t검정 (정규성 자동 확인 → Mann-Whitney 대안)"""
    groups = df[group_col].dropna().unique()
    if len(groups) < 2:
        return {"오류": "그룹이 2개 미만입니다."}, None

    g1_label, g2_label = groups[0], groups[1]
    g1 = df.loc[df[group_col] == g1_label, col].dropna()
    g2 = df.loc[df[group_col] == g2_label, col].dropna()

    # 정규성 확인
    _, p1 = scipy_stats.shapiro(g1.sample(min(len(g1), 5000), random_state=42))
    _, p2 = scipy_stats.shapiro(g2.sample(min(len(g2), 5000), random_state=42))
    normal = (p1 > 0.05) and (p2 > 0.05)

    if normal:
        t_stat, p_val = scipy_stats.ttest_ind(g1, g2)
        method = "독립 t검정"
    else:
        t_stat, p_val = scipy_stats.mannwhitneyu(g1, g2, alternative="two-sided")
        method = "Mann-Whitney U검정 (비정규분포)"

    # Cohen's d
    pooled_std = np.sqrt((g1.std() ** 2 + g2.std() ** 2) / 2)
    cohens_d = abs(g1.mean() - g2.mean()) / pooled_std if pooled_std != 0 else 0
    effect = "작음" if cohens_d < 0.2 else "중간" if cohens_d < 0.5 else "큼"

    summary = pd.DataFrame({
        "그룹": [str(g1_label), str(g2_label)],
        "N": [len(g1), len(g2)],
        "평균": [round(g1.mean(), 3), round(g2.mean(), 3)],
        "표준편차": [round(g1.std(), 3), round(g2.std(), 3)],
    })

    result = {
        "분석 방법": method,
        "정규성 충족": "✅ 예" if normal else "❌ 아니오 → 비모수 검정 적용",
        "검정통계량": round(t_stat, 4),
        "p값": round(p_val, 4),
        "유의성(α=0.05)": "✅ 유의한 차이 있음" if p_val < 0.05 else "❌ 유의한 차이 없음",
        "Cohen's d": round(cohens_d, 3),
        "효과 크기": effect,
        "해석": (
            f"{group_col}에 따라 {col}에 통계적으로 유의한 차이가 있습니다 "
            f"(p={p_val:.4f} < 0.05)."
            if p_val < 0.05
            else f"{group_col}에 따라 {col}에 통계적으로 유의한 차이가 없습니다 "
                 f"(p={p_val:.4f} ≥ 0.05)."
        ),
    }

    # 박스플롯
    plot_df = df[[col, group_col]].dropna()
    fig = px.box(
        plot_df, x=group_col, y=col,
        color=group_col,
        title=f"⚖️ {group_col}별 {col} 분포 비교",
        points="outliers",
        color_discrete_sequence=px.colors.qualitative.Pastel,
    )
    fig.update_layout(
        height=420, showlegend=False,
        plot_bgcolor="white", paper_bgcolor="white",
        margin=dict(t=60, b=40, l=40, r=40),
    )
    return result, summary, fig


def test_anova(df: pd.DataFrame, col: str, group_col: str) -> tuple:
    """일원 ANOVA + Tukey 사후검정"""
    groups = df.groupby(group_col)[col].apply(lambda x: x.dropna().tolist())
    if len(groups) < 3:
        return {"오류": "그룹이 3개 미만입니다."}, None, None

    f_stat, p_val = scipy_stats.f_oneway(*groups)

    summary = df.groupby(group_col)[col].agg(
        N="count", 평균="mean", 표준편차="std"
    ).round(3).reset_index()

    # Tukey HSD
    from itertools import combinations
    tukey_rows = []
    group_names = list(groups.index)
    for g1, g2 in combinations(group_names, 2):
        d1 = df.loc[df[group_col] == g1, col].dropna()
        d2 = df.loc[df[group_col] == g2, col].dropna()
        _, p = scipy_stats.ttest_ind(d1, d2)
        # Bonferroni 보정
        n_comp = len(list(combinations(group_names, 2)))
        p_adj = min(p * n_comp, 1.0)
        tukey_rows.append({
            "비교": f"{g1} vs {g2}",
            "p값(보정)": round(p_adj, 4),
            "유의성": "✅ *" if p_adj < 0.05 else "ns",
        })
    tukey_df = pd.DataFrame(tukey_rows)

    result = {
        "F통계량": round(f_stat, 4),
        "p값": round(p_val, 4),
        "유의성(α=0.05)": "✅ 그룹 간 유의한 차이 있음" if p_val < 0.05 else "❌ 유의한 차이 없음",
        "해석": (
            f"그룹에 따라 {col}에 통계적으로 유의한 차이가 있습니다 (F={f_stat:.4f}, p={p_val:.4f})."
            if p_val < 0.05
            else f"그룹에 따라 {col}에 유의한 차이가 없습니다 (F={f_stat:.4f}, p={p_val:.4f})."
        ),
    }

    plot_df = df[[col, group_col]].dropna()
    fig = px.box(
        plot_df, x=group_col, y=col, color=group_col,
        title=f"📊 {group_col}별 {col} 분포 (ANOVA)",
        points="outliers",
        color_discrete_sequence=px.colors.qualitative.Pastel,
    )
    fig.update_layout(
        height=420, showlegend=False,
        plot_bgcolor="white", paper_bgcolor="white",
        margin=dict(t=60, b=40, l=40, r=40),
    )
    return result, summary, tukey_df, fig


def run_regression(df: pd.DataFrame, x_cols: list, y_col: str) -> tuple:
    """선형 회귀분석"""
    data = df[x_cols + [y_col]].dropna()
    X = data[x_cols].values
    y = data[y_col].values

    reg = LinearRegression().fit(X, y)
    y_pred = reg.predict(X)
    r2 = r2_score(y, y_pred)

    coef_df = pd.DataFrame({
        "변수": x_cols,
        "계수(β)": reg.coef_.round(4),
    })
    coef_df["절편"] = ""
    intercept_row = pd.DataFrame({"변수": ["(절편)"], "계수(β)": [round(reg.intercept_, 4)], "절편": ["✓"]})
    coef_df = pd.concat([intercept_row, coef_df], ignore_index=True)

    # 산점도 (x_cols 중 첫 번째 vs y)
    x_main = x_cols[0]
    fig = px.scatter(
        data, x=x_main, y=y_col,
        trendline="ols",
        title=f"📈 {x_main} → {y_col} 회귀분석",
        color_discrete_sequence=["#4F86C6"],
    )
    fig.update_layout(
        height=420,
        plot_bgcolor="white", paper_bgcolor="white",
        margin=dict(t=60, b=40, l=40, r=40),
    )

    result = {
        "R² (설명력)": round(r2, 4),
        "해석": f"모델이 {y_col} 변동의 {r2*100:.1f}%를 설명합니다.",
    }
    return result, coef_df, fig


def test_chi2(df: pd.DataFrame, col1: str, col2: str) -> tuple:
    """카이제곱 독립성 검정"""
    cross = pd.crosstab(df[col1], df[col2])
    chi2, p, dof, expected = scipy_stats.chi2_contingency(cross)

    result = {
        "카이제곱 통계량": round(chi2, 4),
        "자유도": dof,
        "p값": round(p, 4),
        "유의성(α=0.05)": "✅ 두 변수는 독립적이지 않음 (관련 있음)" if p < 0.05 else "❌ 두 변수는 독립적 (관련 없음)",
        "해석": (
            f"{col1}와 {col2}는 통계적으로 유의한 관련이 있습니다 (χ²={chi2:.4f}, p={p:.4f})."
            if p < 0.05
            else f"{col1}와 {col2}는 독립적입니다 (χ²={chi2:.4f}, p={p:.4f})."
        ),
    }
    return result, cross


def compare_groups(df: pd.DataFrame, col: str, group_col: str) -> tuple:
    """그룹별 평균 비교"""
    summary = df.groupby(group_col)[col].agg(
        N="count", 평균="mean", 표준편차="std", 최솟값="min", 최댓값="max"
    ).round(3).reset_index()

    fig = px.bar(
        summary, x=group_col, y="평균",
        error_y="표준편차",
        color=group_col,
        title=f"📋 {group_col}별 {col} 평균 비교",
        color_discrete_sequence=px.colors.qualitative.Pastel,
        text="평균",
    )
    fig.update_traces(textposition="outside", texttemplate="%{text:.2f}")
    fig.update_layout(
        height=420, showlegend=False,
        plot_bgcolor="white", paper_bgcolor="white",
        margin=dict(t=60, b=40, l=40, r=40),
    )
    return summary, fig


# ──────────────────────────────────────────────────────────────────
# 추가 기초 분석
# ──────────────────────────────────────────────────────────────────

def plot_spearman_correlation(df: pd.DataFrame) -> tuple:
    """스피어만 상관계수 히트맵 (비선형/순서형 대응)"""
    num_df = df.select_dtypes(include=["number"]).dropna()
    if num_df.shape[1] < 2:
        return None, pd.DataFrame()

    corr = num_df.corr(method="spearman").round(3)
    pairs = []
    cols = corr.columns.tolist()
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            pairs.append({
                "변수1": cols[i], "변수2": cols[j],
                "ρ(rho)": corr.iloc[i, j],
                "강도": _corr_label(corr.iloc[i, j]),
            })
    pairs_df = pd.DataFrame(pairs).sort_values("ρ(rho)", key=abs, ascending=False)

    fig = px.imshow(
        corr, color_continuous_scale="RdBu_r", zmin=-1, zmax=1,
        text_auto=".2f", title="🔗 스피어만 상관관계 히트맵", aspect="auto",
    )
    fig.update_layout(height=450, margin=dict(t=60, b=40, l=40, r=40))
    return fig, pairs_df


def detect_outliers_detail(df: pd.DataFrame, col: str) -> tuple:
    """IQR + Z-score 기반 이상치 상세 탐지"""
    data = df[col].dropna()
    q1, q3 = data.quantile(0.25), data.quantile(0.75)
    iqr = q3 - q1
    lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    iqr_outliers = data[(data < lower) | (data > upper)]

    z_scores = np.abs((data - data.mean()) / data.std())
    z_outliers = data[z_scores > 3]

    summary = pd.DataFrame({
        "방법": ["IQR (1.5×IQR)", "Z-score (|z|>3)"],
        "이상치 수": [len(iqr_outliers), len(z_outliers)],
        "비율(%)": [round(len(iqr_outliers)/len(data)*100, 2),
                    round(len(z_outliers)/len(data)*100, 2)],
        "기준(하한)": [round(lower, 3), round(data.mean()-3*data.std(), 3)],
        "기준(상한)": [round(upper, 3), round(data.mean()+3*data.std(), 3)],
    })

    fig = make_subplots(rows=1, cols=2,
                        subplot_titles=["박스플롯 (IQR)", "Z-score 분포"])
    fig.add_trace(go.Box(y=data, name=col, marker_color="#E74C3C",
                         boxmean="sd"), row=1, col=1)
    fig.add_trace(go.Histogram(x=z_scores, nbinsx=30, name="Z-score",
                               marker_color="#3498DB", opacity=0.8), row=1, col=2)
    fig.add_vline(x=3, line_dash="dash", line_color="red",
                  annotation_text="z=3", row=1, col=2)
    fig.update_layout(title=f"🔍 {col} 이상치 탐지", showlegend=False,
                      height=420, plot_bgcolor="white", paper_bgcolor="white",
                      margin=dict(t=60, b=40, l=40, r=40))
    return fig, summary


def plot_pairplot(df: pd.DataFrame) -> tuple:
    """산점도 행렬 (수치형 변수)"""
    num_df = df.select_dtypes(include=["number"]).dropna()
    cols = num_df.columns.tolist()[:6]  # 최대 6개
    if len(cols) < 2:
        return None, pd.DataFrame()

    fig = make_subplots(rows=len(cols), cols=len(cols),
                        shared_xaxes=True, shared_yaxes=True,
                        horizontal_spacing=0.02, vertical_spacing=0.02)
    colors = px.colors.qualitative.Pastel
    for i, cy in enumerate(cols):
        for j, cx in enumerate(cols):
            if i == j:
                fig.add_trace(go.Histogram(x=num_df[cx], marker_color=colors[i % len(colors)],
                                           opacity=0.7, showlegend=False), row=i+1, col=j+1)
            else:
                fig.add_trace(go.Scatter(x=num_df[cx], y=num_df[cy], mode="markers",
                                         marker=dict(size=3, color=colors[i % len(colors)], opacity=0.5),
                                         showlegend=False), row=i+1, col=j+1)
            if i == len(cols) - 1:
                fig.update_xaxes(title_text=cx, title_font_size=9, row=i+1, col=j+1)
            if j == 0:
                fig.update_yaxes(title_text=cy, title_font_size=9, row=i+1, col=j+1)

    fig.update_layout(title="📊 산점도 행렬", height=150*len(cols),
                      plot_bgcolor="white", paper_bgcolor="white",
                      margin=dict(t=60, b=40, l=60, r=20))
    corr = num_df[cols].corr().round(3)
    return fig, corr


def calculate_vif(df: pd.DataFrame) -> tuple:
    """VIF 다중공선성 검사"""
    num_df = df.select_dtypes(include=["number"]).dropna()
    if num_df.shape[1] < 2:
        return None, pd.DataFrame()

    vif_data = pd.DataFrame()
    vif_data["변수"] = num_df.columns
    vif_data["VIF"] = [round(variance_inflation_factor(num_df.values, i), 2)
                       for i in range(num_df.shape[1])]
    vif_data["판정"] = vif_data["VIF"].apply(
        lambda x: "✅ 양호 (VIF<5)" if x < 5
        else "⚠️ 주의 (5≤VIF<10)" if x < 10
        else "❌ 심각 (VIF≥10)"
    )
    vif_data = vif_data.sort_values("VIF", ascending=False)

    fig = px.bar(vif_data, x="변수", y="VIF", text="VIF",
                 color="VIF", color_continuous_scale=["#2ECC71", "#F39C12", "#E74C3C"],
                 title="📐 다중공선성 (VIF)")
    fig.add_hline(y=5, line_dash="dash", line_color="orange",
                  annotation_text="주의 기준 (VIF=5)")
    fig.add_hline(y=10, line_dash="dash", line_color="red",
                  annotation_text="심각 기준 (VIF=10)")
    fig.update_traces(textposition="outside")
    fig.update_layout(height=420, showlegend=False,
                      plot_bgcolor="white", paper_bgcolor="white",
                      margin=dict(t=60, b=40, l=40, r=40))
    return fig, vif_data


def plot_violin(df: pd.DataFrame, col: str, group_col: str) -> tuple:
    """바이올린 플롯 (분포 형태 + 박스플롯)"""
    plot_df = df[[col, group_col]].dropna()
    fig = px.violin(plot_df, x=group_col, y=col, color=group_col,
                    box=True, points="outliers",
                    title=f"🎻 {group_col}별 {col} 분포",
                    color_discrete_sequence=px.colors.qualitative.Pastel)
    fig.update_layout(height=420, showlegend=False,
                      plot_bgcolor="white", paper_bgcolor="white",
                      margin=dict(t=60, b=40, l=40, r=40))

    summary = df.groupby(group_col)[col].agg(
        N="count", 평균="mean", 중앙값="median", 표준편차="std"
    ).round(3).reset_index()
    return fig, summary


# ──────────────────────────────────────────────────────────────────
# 추가 통계 검정
# ──────────────────────────────────────────────────────────────────

def test_paired_ttest(df: pd.DataFrame, col1: str, col2: str) -> tuple:
    """대응표본 t검정 (전/후 비교)"""
    data = df[[col1, col2]].dropna()
    d1, d2 = data[col1], data[col2]

    _, p_norm = scipy_stats.shapiro(
        (d1 - d2).sample(min(len(data), 5000), random_state=42))
    normal = p_norm > 0.05

    if normal:
        t_stat, p_val = scipy_stats.ttest_rel(d1, d2)
        method = "대응표본 t검정"
    else:
        t_stat, p_val = scipy_stats.wilcoxon(d1, d2)
        method = "Wilcoxon 부호순위 검정 (비정규분포)"

    diff = d1 - d2
    result = {
        "분석 방법": method,
        "정규성 충족": "✅ 예" if normal else "❌ 아니오 → 비모수 검정 적용",
        "검정통계량": round(t_stat, 4),
        "p값": round(p_val, 4),
        "유의성(α=0.05)": "✅ 유의한 차이 있음" if p_val < 0.05 else "❌ 유의한 차이 없음",
        "평균 차이": round(float(diff.mean()), 4),
        "해석": (
            f"{col1}와 {col2} 사이에 통계적으로 유의한 차이가 있습니다 (p={p_val:.4f})."
            if p_val < 0.05
            else f"{col1}와 {col2} 사이에 유의한 차이가 없습니다 (p={p_val:.4f})."
        ),
    }
    summary = pd.DataFrame({
        "변수": [col1, col2, "차이(1-2)"],
        "N": [len(d1), len(d2), len(diff)],
        "평균": [round(d1.mean(), 3), round(d2.mean(), 3), round(diff.mean(), 3)],
        "표준편차": [round(d1.std(), 3), round(d2.std(), 3), round(diff.std(), 3)],
    })

    fig = make_subplots(rows=1, cols=2,
                        subplot_titles=["전/후 비교", "차이 분포"])
    fig.add_trace(go.Box(y=d1, name=col1, marker_color="#3498DB"), row=1, col=1)
    fig.add_trace(go.Box(y=d2, name=col2, marker_color="#E74C3C"), row=1, col=1)
    fig.add_trace(go.Histogram(x=diff, nbinsx=20, name="차이",
                               marker_color="#2ECC71", opacity=0.8), row=1, col=2)
    fig.update_layout(title=f"🔄 {col1} vs {col2} 전후 비교",
                      showlegend=False, height=420,
                      plot_bgcolor="white", paper_bgcolor="white",
                      margin=dict(t=60, b=40, l=40, r=40))
    return result, summary, fig


def test_kruskal(df: pd.DataFrame, col: str, group_col: str) -> tuple:
    """Kruskal-Wallis 검정 (비모수 다중 그룹 비교)"""
    groups = df.groupby(group_col)[col].apply(lambda x: x.dropna().tolist())
    if len(groups) < 3:
        return {"오류": "그룹이 3개 미만입니다."}, None, None

    h_stat, p_val = scipy_stats.kruskal(*groups)
    summary = df.groupby(group_col)[col].agg(
        N="count", 중앙값="median", 평균="mean", 표준편차="std"
    ).round(3).reset_index()

    result = {
        "분석 방법": "Kruskal-Wallis H검정 (비모수)",
        "H통계량": round(h_stat, 4),
        "p값": round(p_val, 4),
        "유의성(α=0.05)": "✅ 그룹 간 유의한 차이 있음" if p_val < 0.05 else "❌ 유의한 차이 없음",
        "해석": (
            f"그룹에 따라 {col}에 통계적으로 유의한 차이가 있습니다 (H={h_stat:.4f}, p={p_val:.4f})."
            if p_val < 0.05
            else f"그룹에 따라 {col}에 유의한 차이가 없습니다 (H={h_stat:.4f}, p={p_val:.4f})."
        ),
    }

    plot_df = df[[col, group_col]].dropna()
    fig = px.box(plot_df, x=group_col, y=col, color=group_col,
                 title=f"📊 {group_col}별 {col} (Kruskal-Wallis)",
                 points="outliers",
                 color_discrete_sequence=px.colors.qualitative.Pastel)
    fig.update_layout(height=420, showlegend=False,
                      plot_bgcolor="white", paper_bgcolor="white",
                      margin=dict(t=60, b=40, l=40, r=40))
    return result, summary, fig


def test_proportion(df: pd.DataFrame, col: str, group_col: str) -> tuple:
    """두 그룹 비율 비교 (z-검정)"""
    groups = df[group_col].dropna().unique()
    if len(groups) < 2:
        return {"오류": "그룹이 2개 미만입니다."}, None, None

    g1_label, g2_label = groups[0], groups[1]
    g1 = df.loc[df[group_col] == g1_label, col].dropna()
    g2 = df.loc[df[group_col] == g2_label, col].dropna()

    # 가장 빈번한 값을 "성공"으로 간주
    target = df[col].mode()[0]
    count1 = (g1 == target).sum()
    count2 = (g2 == target).sum()
    n1, n2 = len(g1), len(g2)

    z_stat, p_val = proportions_ztest([count1, count2], [n1, n2])
    prop1, prop2 = count1/n1, count2/n2

    result = {
        "기준값": str(target),
        "검정통계량(z)": round(z_stat, 4),
        "p값": round(p_val, 4),
        f"{g1_label} 비율": f"{prop1:.1%} ({count1}/{n1})",
        f"{g2_label} 비율": f"{prop2:.1%} ({count2}/{n2})",
        "유의성(α=0.05)": "✅ 비율 차이 유의함" if p_val < 0.05 else "❌ 비율 차이 없음",
        "해석": (
            f"{group_col}에 따라 {col}='{target}' 비율에 유의한 차이가 있습니다 (p={p_val:.4f})."
            if p_val < 0.05
            else f"{group_col}에 따라 {col}='{target}' 비율에 유의한 차이가 없습니다 (p={p_val:.4f})."
        ),
    }

    summary = pd.DataFrame({
        "그룹": [str(g1_label), str(g2_label)],
        "N": [n1, n2],
        f"'{target}' 수": [count1, count2],
        "비율": [f"{prop1:.1%}", f"{prop2:.1%}"],
    })

    fig = px.bar(summary, x="그룹", y=f"'{target}' 수", text=f"'{target}' 수",
                 color="그룹", title=f"📊 {group_col}별 '{target}' 비율 비교",
                 color_discrete_sequence=px.colors.qualitative.Pastel)
    fig.update_traces(textposition="outside")
    fig.update_layout(height=420, showlegend=False,
                      plot_bgcolor="white", paper_bgcolor="white",
                      margin=dict(t=60, b=40, l=40, r=40))
    return result, summary, fig


def run_logistic_regression(df: pd.DataFrame, x_cols: list, y_col: str) -> tuple:
    """로지스틱 회귀분석 (이진 결과 예측)"""
    data = df[x_cols + [y_col]].dropna()
    y = data[y_col]

    # 이진 변환 (2개 값이면 0/1로)
    unique_vals = y.unique()
    if len(unique_vals) != 2:
        return {"오류": f"Y변수는 2개 값이어야 합니다 (현재: {len(unique_vals)}개)"}, None, None

    label_map = {unique_vals[0]: 0, unique_vals[1]: 1}
    y_binary = y.map(label_map)

    X = data[x_cols].values
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    model = LogisticRegression(max_iter=1000, random_state=42)
    model.fit(X_scaled, y_binary)
    y_pred = model.predict(X_scaled)
    acc = accuracy_score(y_binary, y_pred)

    coef_df = pd.DataFrame({
        "변수": x_cols,
        "계수(β)": model.coef_[0].round(4),
        "OR(오즈비)": np.exp(model.coef_[0]).round(4),
    })
    coef_df = coef_df.sort_values("OR(오즈비)", ascending=False)

    result = {
        "정확도": f"{acc:.1%}",
        f"기준": f"'{unique_vals[1]}' = 1, '{unique_vals[0]}' = 0",
        "해석": f"모델 정확도 {acc:.1%}. OR>1이면 해당 변수 증가 시 '{unique_vals[1]}' 확률 증가.",
    }

    fig = px.bar(coef_df, x="변수", y="OR(오즈비)", text="OR(오즈비)",
                 color="OR(오즈비)",
                 color_continuous_scale=["#3498DB", "#E8E8E8", "#E74C3C"],
                 title=f"🎯 {y_col} 로지스틱 회귀 — 오즈비(OR)")
    fig.add_hline(y=1, line_dash="dash", line_color="gray",
                  annotation_text="OR=1 (영향 없음)")
    fig.update_traces(textposition="outside", texttemplate="%{text:.2f}")
    fig.update_layout(height=420, showlegend=False,
                      plot_bgcolor="white", paper_bgcolor="white",
                      margin=dict(t=60, b=40, l=40, r=40))
    return result, coef_df, fig


def run_kaplan_meier(df: pd.DataFrame, time_col: str, event_col: str,
                     group_col: str = None) -> tuple:
    """Kaplan-Meier 생존분석"""
    from lifelines import KaplanMeierFitter
    from lifelines.statistics import logrank_test

    data = df[[time_col, event_col] + ([group_col] if group_col else [])].dropna()
    T = data[time_col]
    E = data[event_col].astype(int)

    fig = go.Figure()
    colors = px.colors.qualitative.Pastel
    result = {}

    if group_col and data[group_col].nunique() >= 2:
        groups = data[group_col].unique()
        for i, g in enumerate(groups[:5]):
            mask = data[group_col] == g
            kmf = KaplanMeierFitter()
            kmf.fit(T[mask], E[mask], label=str(g))
            sf = kmf.survival_function_
            fig.add_trace(go.Scatter(
                x=sf.index, y=sf.iloc[:, 0], mode="lines",
                name=str(g), line=dict(color=colors[i % len(colors)], width=2)))
            result[f"{g} 중앙 생존시간"] = (
                round(float(kmf.median_survival_time_), 2)
                if not np.isinf(kmf.median_survival_time_) else "도달하지 않음"
            )

        if len(groups) == 2:
            g1_mask = data[group_col] == groups[0]
            lr = logrank_test(T[g1_mask], T[~g1_mask], E[g1_mask], E[~g1_mask])
            result["Log-rank p값"] = round(lr.p_value, 4)
            result["유의성(α=0.05)"] = (
                "✅ 생존 차이 유의함" if lr.p_value < 0.05
                else "❌ 생존 차이 없음"
            )
    else:
        kmf = KaplanMeierFitter()
        kmf.fit(T, E)
        sf = kmf.survival_function_
        fig.add_trace(go.Scatter(
            x=sf.index, y=sf.iloc[:, 0], mode="lines",
            name="전체", line=dict(color=colors[0], width=2)))
        result["중앙 생존시간"] = (
            round(float(kmf.median_survival_time_), 2)
            if not np.isinf(kmf.median_survival_time_) else "도달하지 않음"
        )

    fig.update_layout(
        title="⏱️ Kaplan-Meier 생존곡선",
        xaxis_title=time_col, yaxis_title="생존 확률",
        height=420, plot_bgcolor="white", paper_bgcolor="white",
        margin=dict(t=60, b=40, l=40, r=40),
        yaxis=dict(range=[0, 1.05]),
    )
    summary_df = pd.DataFrame([result])
    return result, summary_df, fig


def run_cox_regression(df: pd.DataFrame, time_col: str, event_col: str,
                       x_cols: list) -> tuple:
    """Cox 비례위험 모델"""
    from lifelines import CoxPHFitter

    cols = [time_col, event_col] + x_cols
    data = df[cols].dropna()
    data[event_col] = data[event_col].astype(int)

    # 수치형만 사용
    for c in x_cols:
        if data[c].dtype == "object":
            data[c] = data[c].astype("category").cat.codes

    cph = CoxPHFitter()
    cph.fit(data, duration_col=time_col, event_col=event_col)

    coef_df = cph.summary[["coef", "exp(coef)", "p", "exp(coef) lower 95%", "exp(coef) upper 95%"]].round(4)
    coef_df = coef_df.reset_index()
    coef_df.columns = ["변수", "계수(β)", "HR(위험비)", "p값", "HR 하한(95%CI)", "HR 상한(95%CI)"]
    coef_df["유의성"] = coef_df["p값"].apply(lambda p: "✅ *" if p < 0.05 else "ns")

    result = {
        "Concordance": round(cph.concordance_index_, 4),
        "해석": (
            f"Concordance={cph.concordance_index_:.4f}. "
            "HR>1이면 위험(이벤트) 증가, HR<1이면 보호 효과."
        ),
    }

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=coef_df["HR(위험비)"], y=coef_df["변수"],
        orientation="h", text=coef_df["HR(위험비)"],
        marker_color=["#E74C3C" if hr > 1 else "#2ECC71"
                       for hr in coef_df["HR(위험비)"]],
    ))
    fig.add_vline(x=1, line_dash="dash", line_color="gray",
                  annotation_text="HR=1")
    fig.update_traces(textposition="outside", texttemplate="%{text:.2f}")
    fig.update_layout(title="📉 Cox 회귀 — 위험비(HR)",
                      xaxis_title="Hazard Ratio",
                      height=max(300, len(x_cols)*50+100),
                      plot_bgcolor="white", paper_bgcolor="white",
                      margin=dict(t=60, b=40, l=120, r=40))
    return result, coef_df, fig


# ──────────────────────────────────────────────────────────────────
# 내보내기
# ──────────────────────────────────────────────────────────────────

def export_to_excel(results: list) -> bytes:
    """
    results = [{"sheet_name": str, "df": DataFrame, "fig": Figure or None}]
    → 다중 시트 Excel bytes
    """
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for item in results:
            sheet = item.get("sheet_name", "결과")[:31]
            df_item = item.get("df")
            if df_item is not None and not df_item.empty:
                df_item.to_excel(writer, sheet_name=sheet, index=True)
    return buf.getvalue()


def export_chart_png(fig) -> bytes:
    """Plotly Figure → PNG bytes"""
    try:
        return fig.to_image(format="png", width=900, height=500, scale=2)
    except Exception:
        return b""


def export_single_excel(df_result: pd.DataFrame, sheet_name: str = "결과") -> bytes:
    """단일 DataFrame → Excel bytes"""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df_result.to_excel(writer, sheet_name=sheet_name, index=True)
    return buf.getvalue()


def export_csv(df_result: pd.DataFrame) -> str:
    """DataFrame → CSV string"""
    return df_result.to_csv(encoding="utf-8-sig")
