#!/bin/sh
# root로 시작했을 때만: 볼륨 소유권을 맞추고 app 사용자로 내려간다.
#
# ./data는 호스트 디렉터리를 바인드 마운트한다. 도커가 없는 디렉터리를 만들면
# root 소유라 app 사용자가 이력을 못 쓰고, 이전 버전(root로 돌던)이 남긴
# history.jsonl도 root 소유다. 이력 기록 실패는 경고로만 남아 조용히
# "지난 점검과 비교"가 사라지므로, 여기서 먼저 고친다.
set -e

if [ "$(id -u)" = "0" ]; then
    data_dir="$(dirname "${CHECK_HISTORY_LOG:-/app/data/history.jsonl}")"
    mkdir -p "$data_dir"
    chown -R app:app "$data_dir" 2>/dev/null || \
        echo "경고: $data_dir 소유권을 바꾸지 못했습니다. 점검 이력이 저장되지 않을 수 있습니다." >&2
    exec setpriv --reuid=app --regid=app --init-groups -- "$@"
fi

exec "$@"
