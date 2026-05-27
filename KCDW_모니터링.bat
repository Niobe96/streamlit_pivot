@echo off
chcp 65001 >nul
title KCDW 분석기 모니터링 시스템

:: ============================================================
:: KCDW 분석기 모니터링 시스템 — 매일 재시작 배치 파일
:: 
:: 역할:
::   1. 기존 monitor.py 및 Uvicorn 서버를 모두 종료
::   2. 로그 파일 날짜별 백업
::   3. monitor.py를 백그라운드에서 새로 시작
::
:: 윈도우 작업 스케줄러 등록 방법:
::   1. Win + R → taskschd.msc 실행
::   2. [작업 만들기] 클릭
::   3. [일반] 탭:
::        - 이름: KCDW 모니터링 (매일 재시작)
::        - "사용자가 로그온하지 않아도 실행" 체크
::        - "최고 권한으로 실행" 체크
::   4. [트리거] 탭:
::        - [새로 만들기] → "매일" 선택
::        - 시작 시간: 06:00 (원하는 시간)
::   5. [동작] 탭:
::        - 프로그램/스크립트: 이 파일의 전체 경로
::          예) C:\Users\KimGeonHee\Desktop\KUH\streamlit\pivot\KCDW_모니터링.bat
::   6. [설정] 탭:
::        - "이미 실행 중이면 기존 인스턴스 중지" 선택
:: ============================================================

:: 경로 설정
set PYTHON_EXE=C:\Python313\python.exe
set SCRIPT_DIR=C:\Users\KimGeonHee\Desktop\KUH\streamlit\pivot
set SCRIPT_NAME=monitor.py
set LOG_FILE=%SCRIPT_DIR%\로그.txt

echo [%date% %time%] === KCDW 매일 재시작 시작 ===

:: ----------------------------------------------
:: STEP 1. 기존 monitor.py 프로세스 종료
:: ----------------------------------------------
echo [%date% %time%] 기존 monitor.py 프로세스를 종료합니다...
wmic process where "name='python.exe' and commandline like '%%monitor.py%%'" call terminate >nul 2>&1
timeout /t 2 /nobreak >nul

:: ----------------------------------------------
:: STEP 2. 기존 Uvicorn(asgi:app) 서버 프로세스 종료
:: ----------------------------------------------
echo [%date% %time%] 기존 Uvicorn 서버 프로세스를 종료합니다...
wmic process where "name='python.exe' and commandline like '%%uvicorn%%asgi:app%%'" call terminate >nul 2>&1
timeout /t 3 /nobreak >nul

:: ----------------------------------------------
:: STEP 3. 로그 파일 보존 및 재시작 기록 추가
:: ----------------------------------------------
echo [%date% %time%] 기존 로그 파일에 재시작 기록을 추가합니다...
echo. >> "%LOG_FILE%"
echo [%date% %time%] [INFO] === KCDW 매일 재시작 배치 실행 === >> "%LOG_FILE%"

:: ----------------------------------------------
:: STEP 4. monitor.py 새로 시작 (백그라운드)
:: ----------------------------------------------
echo [%date% %time%] monitor.py를 새로 시작합니다...
cd /d "%SCRIPT_DIR%"
start "" /B /MIN "%PYTHON_EXE%" "%SCRIPT_NAME%"
echo [%date% %time%] === KCDW 매일 재시작 완료 ===

exit /b 0
