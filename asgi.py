import os
import asyncio
from contextlib import asynccontextmanager
import streamlit as st
from starlette.middleware import Middleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

# 1. 라이프사이클 훅 (Warm-up 기능 포함)
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

# 2. 헬스체크 엔드포인트 (서버 상태 및 메모리 사용량 확인)
async def health_handler(request):
    """서버 상태, 메모리 사용량, 가동 시간을 JSON으로 반환"""
    import psutil
    import time
    
    process = psutil.Process()
    mem_mb = process.memory_info().rss / (1024 * 1024)
    cpu_percent = process.cpu_percent(interval=0)
    create_time = process.create_time()
    uptime_seconds = int(time.time() - create_time)
    
    # 가동 시간을 사람이 읽기 좋은 형태로 변환
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{hours}시간 {minutes}분 {seconds}초"
    
    return JSONResponse({
        "status": "healthy",
        "memory_mb": round(mem_mb, 2),
        "memory_limit_mb": 2048,
        "cpu_percent": cpu_percent,
        "uptime": uptime_str,
        "uptime_seconds": uptime_seconds,
        "pid": process.pid
    })

# 3. REST API 엔드포인트 (외부 사내 시스템 연동용)
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

# 4. 글로벌 예외 핸들러 (API 라우트 에러 시 구조화된 응답)
async def server_error_handler(request: Request, exc: Exception):
    return JSONResponse({
        "status": "error",
        "message": "서버 내부 오류가 발생했습니다. 전산실에 문의해 주세요.",
        "detail": str(exc)
    }, status_code=500)

# 5. st.App 인스턴스화
app = st.App(
    script_path="pivot.py",
    lifespan=lifespan,
    routes=[
        Route("/api/pivot", api_pivot_handler, methods=["POST", "GET"]),
        Route("/health", health_handler),
    ],
    middleware=[
        Middleware(GZipMiddleware, minimum_size=500),  # 500바이트 이상 응답 자동 GZip 압축
    ],
    exception_handlers={500: server_error_handler},
)
