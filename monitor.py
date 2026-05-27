import os
import sys
import subprocess
import time
from datetime import datetime
import psutil

# 1. 모니터링 및 재시작 설정
TARGET_PORT = 8502
MEMORY_LIMIT_MB = 2048  # 2GB 임계값
LIMIT_BYTES = MEMORY_LIMIT_MB * 1024 * 1024
ASGI_APP_DIR = os.path.dirname(os.path.abspath(__file__))  # pivot 폴더 경로
LOG_FILE_PATH = os.path.join(ASGI_APP_DIR, "로그.txt")
HEALTH_URL = f"http://localhost:{TARGET_PORT}/health"

def write_log(message, level="INFO"):
    """날짜시간 타임스탬프와 로그 레벨을 함께 '로그.txt' 파일에 누적 기록"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] [{level}] {message}\n"
    print(log_line.strip())  # 콘솔에도 출력
    try:
        with open(LOG_FILE_PATH, "a", encoding="utf-8") as f:
            f.write(log_line)
    except Exception as e:
        print(f"❌ 로그 파일 쓰기 실패: {e}")

def check_health():
    """헬스체크 엔드포인트(/health)에 HTTP 요청을 보내 실제 앱 응답 여부를 확인"""
    import urllib.request
    import json
    
    try:
        req = urllib.request.Request(HEALTH_URL, headers={"User-Agent": "KCDW-Monitor/1.0"})
        with urllib.request.urlopen(req, timeout=5) as res:
            data = json.loads(res.read().decode("utf-8"))
            mem_mb = data.get("memory_mb", 0)
            uptime = data.get("uptime", "알 수 없음")
            pid = data.get("pid", "알 수 없음")
            write_log(
                f"헬스체크 정상 - PID: {pid}, 메모리: {mem_mb:.2f} MB, 가동: {uptime}",
                "INFO"
            )
            return {"healthy": True, "memory_mb": mem_mb, "pid": pid}
    except Exception as e:
        write_log(f"헬스체크 실패 (서버 미응답): {e}", "WARNING")
        return {"healthy": False, "memory_mb": 0, "pid": None}

def find_uvicorn_processes():
    """cmdline에 uvicorn과 asgi:app이 포함된 프로세스를 모두 탐색"""
    uvicorn_processes = []
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = proc.info.get('cmdline') or []
            cmdline_str = " ".join(cmdline).lower()
            if "uvicorn" in cmdline_str and "asgi:app" in cmdline_str:
                uvicorn_processes.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return uvicorn_processes

def kill_server():
    """Uvicorn 서버 프로세스를 안전하게 종료"""
    processes = find_uvicorn_processes()
    for proc in processes:
        try:
            pid = proc.pid
            write_log(f"기존 프로세스(PID: {pid}) 종료 시도...", "ALERT")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except psutil.TimeoutExpired:
                proc.kill()
            write_log(f"프로세스(PID: {pid}) 종료 완료", "INFO")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    # 포트 반환 대기
    if processes:
        time.sleep(3)

CONSECUTIVE_FAILURES_LIMIT = 3
consecutive_failures = 0

def start_server():
    """Uvicorn 서버를 HTTP(8502) 백그라운드 기동"""
    write_log(f"Uvicorn HTTP 서버를 포트 {TARGET_PORT}로 기동합니다...", "INFO")
    
    cmd = [
        sys.executable, "-m", "uvicorn", "asgi:app",
        "--host", "0.0.0.0",
        "--port", str(TARGET_PORT),
        "--log-level", "info"
    ]
    
    # 윈도우 스케줄러가 종료되어도 백그라운드에 구동되도록 DETACHED_PROCESS 설정
    creation_flags = 0x00000008 | 0x00000200
    
    try:
        subprocess.Popen(
            cmd,
            cwd=ASGI_APP_DIR,
            creationflags=creation_flags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        write_log("Uvicorn HTTP 서버 백그라운드 기동 완료", "INFO")
        # 서버 기동 및 Warm-up 대기 시간 부여 (15초)
        write_log("서버 초기 기동 및 Warm-up 대기를 위해 15초간 대기합니다...", "INFO")
        time.sleep(15)
    except Exception as e:
        write_log(f"HTTP 서버 기동 실패: {e}", "ERROR")

def check_and_restart():
    global consecutive_failures
    
    # 1) Uvicorn 프로세스가 돌고 있는지 확인
    processes = find_uvicorn_processes()
    
    # 프로세스가 아예 없다면 -> 서버 즉시 시작 (대기 없음)
    if not processes:
        write_log("Uvicorn 서버 프로세스가 실행 중이 아닙니다! 즉시 서버를 시작합니다.", "WARNING")
        start_server()
        consecutive_failures = 0
        return
        
    # 2) 프로세스가 존재한다면 /health 엔드포인트로 응답 여부 확인
    health = check_health()
    
    # 3) 서버가 응답하지 않는 경우 -> 누적 실패 횟수 차감 후 한도 초과 시 재시작
    if not health["healthy"]:
        consecutive_failures += 1
        write_log(
            f"서버가 응답하지 않습니다. (누적 실패: {consecutive_failures}/{CONSECUTIVE_FAILURES_LIMIT})",
            "WARNING"
        )
        if consecutive_failures >= CONSECUTIVE_FAILURES_LIMIT:
            write_log("누적 헬스체크 실패 임계값을 초과하여 서버를 재시작합니다.", "ALERT")
            kill_server()
            start_server()
            consecutive_failures = 0
        return

    # 정상 응답 시 실패 횟수 초기화
    consecutive_failures = 0

    # 4) 메모리가 2GB 임계값을 넘을 때 강제 재시작
    mem_mb = health["memory_mb"]
    if mem_mb > MEMORY_LIMIT_MB:
        write_log(
            f"메모리 점유량({mem_mb:.2f} MB)이 임계값({MEMORY_LIMIT_MB} MB)을 초과하였습니다. 서버를 재시작합니다.",
            "WARNING"
        )
        kill_server()
        start_server()

if __name__ == "__main__":
    write_log("=== KCDW 모니터링 시스템 기동 ===", "INFO")
    while True:
        try:
            check_and_restart()
        except Exception as e:
            write_log(f"모니터링 루프 중 시스템 예외 발생: {e}", "ERROR")
        
        # 10초 대기 후 다음 주기 실행
        time.sleep(10)
