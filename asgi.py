import os
import asyncio
from contextlib import asynccontextmanager
import streamlit as st
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

# 1. 포털 토큰 + 세션 쿠키 하이브리드 검증 미들웨어 구현 (우회책)
class RefererCheckMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # 1) 포털 링크에 덧붙일 약속된 비밀 패스키 (사용자가 변경 가능)
        SECRET_PASSKEY = "kuh_secret_2026"
        
        # 2) 요청 정보 수집 (쿼리 파라미터 및 쿠키)
        query_params = request.query_params
        access_key = query_params.get("access_key")
        cookie_token = request.cookies.get("kcdw_auth_token")
        
        referer = request.headers.get("referer")
        origin = request.headers.get("origin")
        
        is_allowed = False
        
        # 3) 검증 로직
        # A) 포털 링크의 비밀 패스키(쿼리 스트링)가 일치하는 경우
        if access_key == SECRET_PASSKEY:
            is_allowed = True
        # B) 이미 이전에 접속에 성공하여 12시간 세션 쿠키가 발급된 브라우저인 경우
        elif cookie_token == SECRET_PASSKEY:
            is_allowed = True
        # C) 로컬 개발/테스트 접속인 경우
        elif request.url.hostname in ("localhost", "127.0.0.1"):
            is_allowed = True
        # D) 기존 Referer/Origin 헤더가 살아있어 도메인이 정상 감지되는 경우
        elif referer and "kcdw.kuh.ac.kr" in referer:
            is_allowed = True
        elif origin and "kcdw.kuh.ac.kr" in origin:
            is_allowed = True
            
        # 비인가 직접 접속(주소창 IP:포트 입력 등) 차단
        if not is_allowed:
            html_content = f"""
            <html>
                <head>
                    <meta charset="utf-8">
                    <title>Access Denied</title>
                </head>
                <body style="font-family: Arial, sans-serif; text-align: center; margin-top: 100px; background-color: #f8fafc; color: #0f172a;">
                    <div style="display: inline-block; padding: 40px; background: white; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); border: 1px solid #e2e8f0; max-width: 550px; text-align: left;">
                        <h2 style="color: #ef4444; margin-top: 0; text-align: center;">❌ 비인가 접근 차단 (Access Denied)</h2>
                        <p style="font-size: 1.1em; color: #334155; text-align: center;">본 시스템은 공식 사내 포털을 통해서만 접속이 가능합니다.</p>
                        <p style="color: #64748b; font-size: 0.9em; margin-bottom: 20px; text-align: center;">주소창에 직접 IP와 포트 번호를 입력하여 접근할 수 없습니다.</p>
                        
                        <div style="background-color: #f1f5f9; padding: 15px; border-radius: 8px; font-family: monospace; font-size: 0.85em; color: #475569; margin-bottom: 20px; line-height: 1.5;">
                            <div style="font-weight: bold; border-bottom: 1px solid #cbd5e1; padding-bottom: 5px; margin-bottom: 8px; font-size: 1.0em; color: #1e293b;">🔧 실시간 디버그 정보</div>
                            <div>• 감지된 보안 토큰: <span style="color: #2563eb; font-weight: bold;">{access_key or '없음 (직접 접속 시도)'}</span></div>
                            <div>• 감지된 Referer 헤더: <span style="color: #0d9488;">{referer or 'None (헤더 유실됨)'}</span></div>
                            <div style="color: #e11d48; margin-top: 10px; font-size: 0.93em; border-top: 1px dashed #cbd5e1; padding-top: 8px;">
                                💡 <b>우회 해결법 (포털 링크 수정)</b>:<br>
                                사내 포털에 등록한 분석기 URL 주소 맨 뒤에 아래와 같이 비밀 패스키를 덧붙여서 링크를 수정해 주세요.<br>
                                <code style="background: #e2e8f0; padding: 2px 4px; border-radius: 4px; display: inline-block; margin-top: 5px; font-weight: bold; color: #0f172a;">http://[분석기서버IP]:8502/?access_key={SECRET_PASSKEY}</code>
                            </div>
                        </div>
                        
                        <div style="font-size: 0.85em; color: #94a3b8; border-top: 1px solid #f1f5f9; padding-top: 15px; text-align: center;">
                            시스템 지원: 전산실 (내선 1234)
                        </div>
                    </div>
                </body>
            </html>
            """
            return HTMLResponse(html_content, status_code=403)
            
        # 4) 요청 통과 처리 및 세션 쿠키 부여
        response = await call_next(request)
        if access_key == SECRET_PASSKEY:
            # 1회 성공 시 브라우저 세션 쿠키 발급 (브라우저 창을 닫으면 즉시 만료되어 최고의 보안 제공)
            response.set_cookie(
                key="kcdw_auth_token",
                value=SECRET_PASSKEY,
                path="/",
                httponly=True,
                samesite="lax"
            )
        return response

# 2. 라이프사이클 훅 (Warm-up 기능 포함)
@asynccontextmanager
async def lifespan(app):
    print("[Lifespan] KCDW 어시스턴트 서버 구동 중...")
    
    # [Warm-up] 무거운 통계/시각화 모듈 사전 로드 및 연산 수행
    try:
        print("[Warmup] 통계 패키지(scipy, statsmodels) 및 Plotly 사전 로드 중...")
        import scipy.stats as stats
        import statsmodels.api as sm
        import plotly.graph_objects as go
        
        # 더미 분포 연산 수행 (모듈 컴파일/캐싱 유도)
        stats.norm.cdf(0)
        go.Figure(data=go.Scatter(x=[1, 2], y=[1, 2]))
        print("[Warmup] 패키지 웜업 완료! 첫 접속자가 딜레이 없이 이용 가능합니다.")
    except Exception as e:
        print(f"[Warmup Warning] 웜업 중 일부 오류 발생 (무시 가능): {e}")
        
    yield
    print("[Lifespan] KCDW 어시스턴트 서버 종료 중...")

# 3. 임시 REST API 엔드포인트 예시 (Phase 4 대비)
async def api_pivot_handler(request):
    import pandas as pd
    try:
        # sys.path에 현재 폴더를 추가하여 임포트 예외 방지
        import sys
        from pathlib import Path
        sys.path.append(str(Path(__file__).resolve().parent))
        from pivot import perform_pivot
    except Exception as e:
        return JSONResponse({
            "status": "error",
            "message": f"모듈 로드 실패: {str(e)}"
        }, status_code=500)

    try:
        body = await request.json()
        raw_data = body.get("data") # 레코드 리스트
        index_cols = body.get("index_cols")
        values_col = body.get("values_col")
        agg_func = body.get("agg_func", "first")
        columns_col = body.get("columns_col", None)
        classic_mode = body.get("classic_mode", False)
        
        if not raw_data or not index_cols or not values_col:
            return JSONResponse({
                "status": "error",
                "message": "필수 파라미터가 누락되었습니다: data, index_cols, values_col"
            }, status_code=400)
            
        df = pd.DataFrame(raw_data)
        
        # 비동기로 perform_pivot 호출하여 메인 루프 지연 방지
        result_df = await asyncio.to_thread(
            perform_pivot,
            df,
            index_cols=index_cols,
            values_col=values_col,
            agg_func=agg_func,
            columns_col=columns_col,
            classic_mode=classic_mode
        )
        
        # 결과를 딕셔너리 레코드 형태의 리스트로 변환
        output_data = result_df.reset_index().to_dict(orient="records")
        
        return JSONResponse({
            "status": "success",
            "rows": len(output_data),
            "data": output_data
        })
    except Exception as e:
        return JSONResponse({
            "status": "error",
            "message": f"연산 처리 중 서버 오류 발생: {str(e)}"
        }, status_code=500)

# 4. st.App 인스턴스화 (script_path를 pivot.py로 변경)
app = st.App(
    script_path="pivot.py",
    lifespan=lifespan,
    routes=[Route("/api/pivot", api_pivot_handler, methods=["POST", "GET"])],
    middleware=[
        Middleware(RefererCheckMiddleware)
    ]
)
