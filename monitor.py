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

def find_process_by_port(port):
    """지정된 포트(8502)를 사용 중인 모든 프로세스를 탐색"""
    target_processes = []
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            try:
                connections = proc.net_connections(kind='inet')
            except AttributeError:
                connections = proc.connections(kind='inet')
            for conn in connections:
                if conn.laddr.port == port:
                    target_processes.append(proc)
                    break
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return target_processes

def kill_server():
    """포트 8502를 점유 중인 기존 프로세스를 안전하게 종료"""
    processes = find_process_by_port(TARGET_PORT)
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
    except Exception as e:
        write_log(f"HTTP 서버 기동 실패: {e}", "ERROR")

def check_and_restart():
    # 1) /health 엔드포인트로 실제 앱 응답 여부 확인
    health = check_health()
    
    # 2) 서버가 응답하지 않는 경우 -> 기존 프로세스 정리 후 재시작
    if not health["healthy"]:
        write_log("서버가 응답하지 않습니다. 기존 프로세스 정리 후 재시작합니다.", "WARNING")
        kill_server()
        start_server()
        return

    # 3) 메모리가 2GB 임계값을 넘을 때 강제 재시작
    mem_mb = health["memory_mb"]
    if mem_mb > MEMORY_LIMIT_MB:
        write_log(
            f"메모리 점유량({mem_mb:.2f} MB)이 임계값({MEMORY_LIMIT_MB} MB)을 초과하였습니다.",
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
