@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo   adpolicy-precheck
echo   ------------------------------------------------------------

where docker >nul 2>&1
if errorlevel 1 (
    echo   [x] Docker Desktop 이 없거나 PATH 에 없습니다.
    echo       https://www.docker.com/products/docker-desktop/
    goto :end
)

docker info >nul 2>&1
if errorlevel 1 (
    echo   [x] Docker Desktop 이 실행 중이 아닙니다. 먼저 켜 주세요.
    goto :end
)

if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo   [+] .env 를 만들었습니다.
)

rem  인자:  run.bat claude / none / llm / llm,vlm     (기본 llm)
rem    claude = 로컬 GPU 대신 이미 로그인해 둔 Claude Code 구독을 쓴다.
rem             다리(bridge)를 새 창에 띄우고 컨테이너는 api+web 만 올린다.
set "PROFILES=%~1"
if "%PROFILES%"=="" set "PROFILES=llm"
if /i "%PROFILES%"=="none" set "PROFILES="

set "USE_CLAUDE="
if /i "%PROFILES%"=="claude" (
    set "USE_CLAUDE=1"
    set "PROFILES="
)

if defined USE_CLAUDE (
    where claude >nul 2>&1
    if errorlevel 1 (
        echo   [x] claude 명령을 찾을 수 없습니다. Claude Code 를 설치하고
        echo       `claude --version` 이 되는지 확인하세요.
        goto :end
    )
    where python >nul 2>&1
    if errorlevel 1 (
        echo   [x] python 이 필요합니다 ^(다리를 띄우는 데만 씁니다^).
        goto :end
    )
    rem  주의: cmd 에서 set "VAR=" 는 변수를 **지운다**. 비워 두는 게 아니라서
    rem  COMPOSE_PROFILES 를 이렇게 비우면 compose 가 .env 값(llm)으로 되돌아가
    rem  GPU 컨테이너가 그대로 떠 버린다. 그래서 프로필로 끄지 않고, 올릴
    rem  서비스를 아래에서 이름으로 못박는다.
    set "SERVICES=api web"
    set "LLM_BASE_URL=http://host.docker.internal:8787/v1"
    set "LLM_MODEL=sonnet"
    set "VLM_BASE_URL=http://host.docker.internal:8787/v1"
    set "VLM_MODEL=sonnet"
    rem  --remove-orphans 는 compose 파일에 없는 컨테이너만 지운다. 앞서
    rem  run.bat llm 으로 띄워 둔 llm·vlm 은 그대로 살아서 VRAM 을 물고 있으므로
    rem  여기서 직접 내린다. 없으면 조용히 넘어간다.
    docker compose rm -s -f llm vlm >nul 2>&1
    echo   [ ] Claude Code 구독을 씁니다 - GPU·모델 다운로드 없음.
    echo   [+] 다리를 새 창에 띄웁니다 ^(포트 8787^). 창을 닫으면 LLM 이 멈춥니다.
    start "adpolicy claude bridge" cmd /k python "%~dp0bridge\claude_bridge.py"
    rem  다리가 뜰 때까지 잠깐 기다린다
    timeout /t 3 /nobreak >nul
) else (
    set "SERVICES="
    set "COMPOSE_PROFILES=%PROFILES%"
    if "%PROFILES%"=="" (
        echo   [ ] 프로필 없음 - 룰셋과 OCR 만 동작합니다.
    ) else (
        echo   [ ] 프로필: %PROFILES%
    )
)
if defined USE_CLAUDE (
    echo   [ ] 처음 실행은 빌드에 3~6분 걸립니다. 모델 로딩은 없습니다.
) else (
    echo   [ ] 처음 실행은 빌드 3~6분 + 모델 로딩 1~3분 걸립니다.
)
echo.

docker compose up --build -d --remove-orphans %SERVICES%
if errorlevel 1 (
    rem  중단된 실행이 남긴 컨테이너와 이름이 부딪히는 경우가 있다.
    rem  한 번 정리하고 다시 시도한다.
    echo.
    echo   [!] 실패했습니다. 남아 있는 컨테이너를 정리하고 다시 시도합니다...
    docker compose down --remove-orphans >nul 2>&1
    docker compose up --build -d --remove-orphans %SERVICES%
    if errorlevel 1 (
        echo.
        echo   [x] 그래도 실패했습니다. 위 메시지를 확인하세요.
        goto :end
    )
)

echo.
echo   [ ] API 가 준비될 때까지 기다립니다...
set /a TRIES=0
:wait
set /a TRIES+=1
curl -s -o nul http://localhost:8080/healthz
if not errorlevel 1 goto :ready
if %TRIES% geq 60 (
    echo   [!] 3분을 기다렸는데 응답이 없습니다.  docker compose logs api  를 확인하세요.
    goto :end
)
timeout /t 3 /nobreak >nul
goto :wait

:ready
echo   [o] 준비됐습니다.  http://localhost:3000
echo.
start "" http://localhost:3000
echo   로그를 붙입니다. 창을 닫아도 서버는 계속 돕니다. (중지: docker compose down)
echo.
docker compose logs -f

:end
endlocal
echo.
pause
