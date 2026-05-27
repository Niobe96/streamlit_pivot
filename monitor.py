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

def find_process_by_port(port):
    """지정된 포트(8502)를 사용 중인 모든 프로세스를 탐색"""
    target_processes = []
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            connections = proc.connections(kind='inet')
            for conn in connections:
                if conn.laddr.port == port:
                    target_processes.append(proc)
                    break
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return target_processes

def start_server():
    """Uvicorn 서버를 8502 포트로 백그라운드(Headless) 기동"""
    write_log(f"Uvicorn 서버를 포트 {TARGET_PORT}로 기동합니다...", "INFO")
    
    cmd = [
        "uvicorn", "asgi:app",
        "--host", "0.0.0.0",
        "--port", str(TARGET_PORT),
        "--log-level", "info"
    ]
    
    # 윈도우 스케줄러/모니터 프로세스 종료 시 서버가 같이 꺼지지 않도록 데몬 분리 기동
    creation_flags = 0x00000008 | 0x00000200
    
    try:
        subprocess.Popen(
            cmd,
            cwd=ASGI_APP_DIR,
            creationflags=creation_flags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        write_log("Uvicorn 서버 백그라운드 분리 기동 완료", "INFO")
    except Exception as e:
        write_log(f"서버 기동 중 오류 발생: {e}", "ERROR")

def check_and_restart():
    processes = find_process_by_port(TARGET_PORT)
    
    # 1) 포트 8502가 열려있지 않은 경우 -> 서버 자동 복구 가동
    if not processes:
        write_log(f"포트 {TARGET_PORT}를 점유 중인 서버 프로세스가 없습니다! (자동 복구 가동)", "WARNING")
        start_server()
        return

    # 2) 점유 중인 프로세스 메모리 검사
    for proc in processes:
        try:
            pid = proc.pid
            name = proc.name()
            mem_info = proc.memory_info()
            rss_mb = mem_info.rss / (1024 * 1024)
            
            write_log(f"실행 중 - PID: {pid}, 프로세스명: {name}, 메모리 점유: {rss_mb:.2f} MB", "INFO")
            
            # 메모리가 2GB 임계값을 넘을 때 강제 재시작
            if mem_info.rss > LIMIT_BYTES:
                write_log(f"메모리 점유량({rss_mb:.2f} MB)이 임계값({MEMORY_LIMIT_MB} MB)을 초과하였습니다.", "WARNING")
                write_log(f"기존 프로세스(PID: {pid}) 종료 및 서버 재기동을 시도합니다...", "ALERT")
                
                # 프로세스 정상 종료 시도 -> 대기 -> 강제 종료
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except psutil.TimeoutExpired:
                    proc.kill()
                
                # 포트 반환 대기 후 재시작
                time.sleep(3)
                start_server()
                break
                
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

if __name__ == "__main__":
    write_log("=== KCDW 모니터링 시스템 기동 ===", "INFO")
    while True:
        try:
            check_and_restart()
        except Exception as e:
            write_log(f"모니터링 루프 중 시스템 예외 발생: {e}", "ERROR")
        
        # 10초 대기 후 다음 주기 실행
        time.sleep(10)
