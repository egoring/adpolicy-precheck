#!/usr/bin/env bash
# 한 번에 실행 — 인자로 프로필 지정 (none / llm / llm,vlm). 기본 llm.
set -euo pipefail
cd "$(dirname "$0")"

echo
echo "  adpolicy-precheck"
echo "  ------------------------------------------------------------"

command -v docker >/dev/null || { echo "  [x] Docker 가 없습니다."; exit 1; }
docker info >/dev/null 2>&1 || { echo "  [x] Docker 데몬이 실행 중이 아닙니다."; exit 1; }

[ -f .env ] || { cp .env.example .env; echo "  [+] .env 를 만들었습니다."; }

profiles="${1:-llm}"
[ "$profiles" = "none" ] && profiles=""

if [ "$profiles" = "claude" ]; then
    # 로컬 GPU 대신 이미 로그인해 둔 Claude Code 구독을 쓴다.
    command -v claude >/dev/null || {
        echo "  [x] claude 명령이 없습니다. Claude Code 를 설치하세요."; exit 1; }
    profiles=""
    # COMPOSE_PROFILES 를 비우는 것에 기대지 않는다 — 빈 값을 "설정 안 됨"으로
    # 보고 .env 값(llm)으로 되돌아가는 구현이 있다. 올릴 서비스를 이름으로 못박는다.
    services="api web"
    # --remove-orphans 는 compose 파일에 없는 컨테이너만 지운다. 앞서 띄워 둔
    # llm·vlm 은 그대로 살아 VRAM 을 물고 있으므로 여기서 직접 내린다.
    docker compose rm -s -f llm vlm >/dev/null 2>&1 || true
    export LLM_BASE_URL="http://host.docker.internal:8787/v1" LLM_MODEL="sonnet"
    export VLM_BASE_URL="http://host.docker.internal:8787/v1" VLM_MODEL="sonnet"
    echo "  [ ] Claude Code 구독을 씁니다 — GPU·모델 다운로드 없음."
    python3 bridge/claude_bridge.py &
    bridge_pid=$!
    trap 'kill "$bridge_pid" 2>/dev/null || true' EXIT
    sleep 2
    echo "  [+] 다리 실행 중 (pid $bridge_pid, 포트 8787)"
fi

services="${services:-}"
export COMPOSE_PROFILES="$profiles"

[ -n "$profiles" ] && echo "  [ ] 프로필: $profiles" || echo "  [ ] 프로필 없음 — 룰셋과 OCR 만 동작합니다."
echo "  [ ] 처음 실행은 빌드 3~6분 + 모델 로딩 1~3분 걸립니다."
echo

# 중단된 실행이 남긴 컨테이너와 이름이 부딪히면 한 번 정리하고 다시 시도한다.
if ! docker compose up --build -d --remove-orphans $services; then
    echo "  [!] 실패했습니다. 남아 있는 컨테이너를 정리하고 다시 시도합니다..."
    docker compose down --remove-orphans >/dev/null 2>&1 || true
    docker compose up --build -d --remove-orphans $services
fi

echo
echo "  [ ] API 가 준비될 때까지 기다립니다..."
for i in $(seq 1 60); do
    if curl -sf -o /dev/null http://localhost:8080/healthz; then
        echo "  [o] 준비됐습니다.  http://localhost:3000"
        echo
        command -v xdg-open >/dev/null && xdg-open http://localhost:3000 >/dev/null 2>&1 || true
        command -v open >/dev/null && open http://localhost:3000 >/dev/null 2>&1 || true
        exec docker compose logs -f
    fi
    sleep 3
done

echo "  [!] 3분을 기다렸는데 응답이 없습니다.  docker compose logs api  를 확인하세요."
exit 1
