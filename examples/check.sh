#!/usr/bin/env bash
# API 직접 호출 예시. 서버가 http://localhost:8080 에 떠 있어야 합니다.
set -euo pipefail

API="${API:-http://localhost:8080}"
URL="${1:-https://example.com}"
COPY="${2:-}"

echo "▶ 점검 대상: $URL"
echo

curl -sS -X POST "$API/v1/check" \
  -H 'Content-Type: application/json' \
  -d "$(cat <<JSON
{
  "platform": "google_ads",
  "url": "$URL",
  "ad_copy": "$COPY",
  "use_llm": true
}
JSON
)" | python3 -m json.tool

echo
echo "▶ LLM 없이 룰셋만 실행하려면 use_llm 을 false 로 바꾸세요."
