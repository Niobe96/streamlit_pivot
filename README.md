# 🏥 KUH 분석 플랫폼

CSV/Excel 데이터를 업로드하면 **챗봇 형태의 인터랙티브 UI**를 통해 데이터 탐색, 통계 검정, 데이터 펼치기까지 한 곳에서 수행할 수 있는 Streamlit 웹 애플리케이션입니다.

---

## 📋 주요 기능

### 1. 로그인 인증
- `streamlit-authenticator` 기반 **쿠키 인증**
- `.streamlit/secrets.toml`에서 계정 및 쿠키 설정 관리
- 사이드바에 사용자 정보, 업로드 데이터 현황, 빠른 분석 버튼 제공

### 2. 데이터 업로드 & 자동 분석
- **CSV**: UTF-8/CP949 인코딩 자동 감지
- **Excel**: `calamine` 엔진으로 고속 로드
- 업로드 즉시 행/열 수, 수치/범주형 컬럼, 결측값, 1:N 구조 자동 감지

### 3. 데이터 탐색 (9가지)

| 분석 | 설명 | 파라미터 |
|------|------|---------|
| 📊 **분포 & 이상치** | 히스토그램 + 박스플롯 | 수치 컬럼 선택 |
| 🔗 **피어슨 상관관계** | 피어슨 상관계수 히트맵 | 즉시 실행 |
| ❓ **결측값 & 요약** | 결측 현황 + 기술통계 | 즉시 실행 |
| 🔍 **이상치 탐지** | IQR + Z-score 정밀 탐지 | 수치 컬럼 선택 |
| 📂 **빈도 분석** | 범주형 빈도 + 파이차트 | 범주 컬럼 선택 |
| 🔗 **스피어만 상관분석** | 비선형/순서형 대응 히트맵 | 즉시 실행 |
| 📊 **산점도 행렬** | 변수 간 관계 한눈에 (최대 6개) | 즉시 실행 |
| 📐 **다중공선성(VIF)** | 회귀 전 변수 간 공선성 검사 | 즉시 실행 |
| 🎻 **바이올린 플롯** | 그룹별 분포 형태 시각화 | 수치 + 그룹 컬럼 선택 |

### 4. 통계 검정 (10가지)

| 분석 | 설명 | 파라미터 |
|------|------|---------|
| ⚖️ **두 그룹 비교 (t검정)** | 독립 t검정 / Mann-Whitney U (정규성 자동 판단) | 수치 + 그룹 컬럼 |
| 📊 **여러 그룹 비교 (ANOVA)** | 일원 ANOVA + Tukey 사후검정 | 수치 + 그룹 컬럼 |
| 📈 **영향 분석 (회귀)** | 선형 회귀분석 + R² + 산점도 | Y + X 컬럼들 |
| 🔀 **카이제곱 검정** | 범주형 변수 간 독립성 검정 | 범주 컬럼 2개 |
| 🔄 **전후 비교 (대응표본)** | 대응표본 t검정 / Wilcoxon (정규성 자동 판단) | 수치 컬럼 2개 (전/후) |
| 📊 **Kruskal-Wallis** | 비모수 다중 그룹 비교 | 수치 + 그룹 컬럼 |
| 📊 **비율 비교** | 두 그룹 비율 z-검정 | 비교 컬럼 + 그룹 컬럼 |
| 🎯 **로지스틱 회귀** | 이진 결과 예측 + 오즈비(OR) | Y(이진) + X 컬럼들 |
| ⏱️ **생존분석 (Kaplan-Meier)** | 생존곡선 + Log-rank 검정 | 시간 + 이벤트 + 그룹(선택) |
| 📉 **Cox 회귀** | 비례위험 모델 + 위험비(HR) | 시간 + 이벤트 + 공변량 |

### 5. 데이터 펼치기 (피벗)

| 모드 | 설명 |
|------|------|
| **1:N 펼치기** | 기준 컬럼에 대해 반복 행을 가로로 정리 (모든 데이터 타입 지원) |
| **집계 피벗** | sum/mean/count/min/max/first 집계 함수로 요약 |

### 6. 결과 내보내기
- 각 분석 결과마다 **Excel / CSV / PNG 이미지** 개별 다운로드
- 사이드바에서 **전체 분석 결과 일괄 Excel 저장**

---

## 🔄 네비게이션 구조

```
Level 0:  [데이터 탐색] [통계 검정] [데이터 펼치기]
              │              │              │
Level 1:   9개 버튼       10개 버튼       2개 버튼
              │              │              │
Level 2:   파라미터 선택 → 분석 실행 → 결과 표시
              │              │
              └── 같은 섹션 서브메뉴로 복귀
                      │
              [🏠 홈으로 가기] → Level 0 복귀
```

---

## 🛠️ 기술 스택

| 구분 | 기술 |
|---|---|
| **프레임워크** | [Streamlit](https://streamlit.io/) |
| **데이터 처리** | [Pandas](https://pandas.pydata.org/), [NumPy](https://numpy.org/) |
| **차트** | [Plotly](https://plotly.com/python/) |
| **통계** | [SciPy](https://scipy.org/), [statsmodels](https://www.statsmodels.org/) |
| **머신러닝** | [scikit-learn](https://scikit-learn.org/) |
| **생존분석** | [lifelines](https://lifelines.readthedocs.io/) |
| **엑셀** | [calamine](https://github.com/tafia/calamine) (읽기), [openpyxl](https://openpyxl.readthedocs.io/) (쓰기) |
| **인증** | [streamlit-authenticator](https://github.com/mkhorasani/Streamlit-Authenticator) |

---

## 📁 프로젝트 구조

```text
pivot/
├── .streamlit/
│   └── secrets.toml          # 인증 정보 및 쿠키 설정 (비공개)
├── pivot.py                  # 메인 애플리케이션 (UI + 네비게이션)
├── stats_functions.py        # 통계 분석 + 차트 + 내보내기 모듈
├── generate_keys.py          # 비밀번호 해시 생성 보조 스크립트
└── README.md
```

---

## ⚙️ 설치 및 실행

### 1. 의존성 패키지 설치

```bash
pip install streamlit pandas numpy plotly scipy scikit-learn \
            statsmodels lifelines streamlit-authenticator \
            openpyxl python-calamine
```

### 2. 비밀번호 해시 생성

`generate_keys.py`를 실행하여 비밀번호를 bcrypt 해시로 변환합니다.

### 3. 인증 설정

`.streamlit/secrets.toml` 파일을 생성합니다:

```toml
[credentials.usernames.admin]
name = "관리자"
password = "$2b$12$..."   # 해시화된 비밀번호

[cookie]
name = "pivot_auth_cookie"
key = "your-random-secret-key"
expiry_days = 30
```

### 4. 앱 실행

```bash
streamlit run pivot.py
```

---

## 📌 핵심 아키텍처 특성

- **챗봇 형태 UI**: 대화 기록 기반으로 분석 흐름을 자연스럽게 안내하며, 버튼 기반 3단계 트리 구조로 비전문가도 쉽게 분석 가능
- **자동 검정 방법 선택**: t검정 시 정규성을 자동 확인하여 Mann-Whitney U / Wilcoxon으로 대체, ANOVA 시 Tukey 사후검정 자동 포함
- **세션 상태 관리**: `st.session_state`를 통한 대화 기록, 분석 결과, 네비게이션 경로 캐싱으로 Streamlit 리렌더링에 대응
- **다중 인덱스 평탄화**: Pandas `pivot_table` 산출 MultiIndex를 `진단명_1`, `약품명_2` 형태로 자동 변환
- **Null/타입 자동 변환**: 날짜, NaN 등 혼합 타입을 안전하게 처리

---

## 📝 라이선스

자유롭게 활용하세요.
