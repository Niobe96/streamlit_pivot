import os
import asyncio
from contextlib import asynccontextmanager
import streamlit as st
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

# 1. Referer 및 Origin 검증 미들웨어 구현 (방식 1)
class RefererCheckMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # WebSocket 핸드셰이크 헤더와 HTTP 헤더를 모두 점검
        referer = request.headers.get("referer")
        origin = request.headers.get("origin")
        
        # [샘플 URL 지정] 사용자가 원내 인트라넷/포털 도메인으로 교체 가능
        allowed_origin = "http://portal.kuh.co.kr"
        
        is_allowed = False
        
        # 1) 허용된 공식 포털로부터의 유입인지 검증
        if referer and referer.startswith(allowed_origin):
            is_allowed = True
        elif origin and origin.startswith(allowed_origin):
            is_allowed = True
        # 2) 현재 방문한 호스트가 localhost 또는 127.0.0.1인 경우 (개발용 직접 접속 허용)
        elif request.url.hostname in ("localhost", "127.0.0.1"):
            is_allowed = True
        # 3) 경유지(Referer/Origin)에 로컬 호스트 주소가 포함되어 있는 경우
        elif referer and ("localhost" in referer or "127.0.0.1" in referer):
            is_allowed = True
        elif origin and ("localhost" in origin or "127.0.0.1" in origin):
            is_allowed = True
            
        # 비인가 직접 접속(주소창 IP:포트 입력 등) 차단
        if not is_allowed:
            html_content = """
            <html>
                <head>
                    <meta charset="utf-8">
                    <title>Access Denied</title>
                </head>
                <body style="font-family: Arial, sans-serif; text-align: center; margin-top: 100px; background-color: #f8fafc; color: #0f172a;">
                    <div style="display: inline-block; padding: 40px; background: white; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); border: 1px solid #e2e8f0;">
                        <h2 style="color: #ef4444; margin-top: 0;">❌ 비인가 접근 차단 (Access Denied)</h2>
                        <p style="font-size: 1.1em; color: #334155;">본 시스템은 사내 포털을 통해서만 접속이 가능합니다.</p>
                        <p style="color: #64748b; font-size: 0.9em; margin-bottom: 20px;">주소창에 직접 IP와 포트 번호를 입력하여 접근할 수 없습니다.</p>
                        <div style="font-size: 0.85em; color: #94a3b8; border-top: 1px solid #f1f5f9; padding-top: 15px;">
                            시스템 지원: 전산실 (내선 1234)
                        </div>
                    </div>
                </body>
            </html>
            """
            return HTMLResponse(html_content, status_code=403)
            
        return await call_next(request)

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
