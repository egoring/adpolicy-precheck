FROM python:3.12-slim

WORKDIR /app

# PaddleOCR을 넣을지. 0으로 빌드하면 이미지가 ~1.5GB 작아지고
# OCR은 tesseract로 내려간다.
ARG WITH_PADDLE=1

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/app

# 서버는 root가 아닌 app 사용자로 돈다. 공격자가 응답을 통제하는 페이지·이미지를
# 파싱하는 서비스라, 파서 취약점 하나가 컨테이너 root로 이어지지 않게 한다.
# HOME을 먼저 옮겨 두는 이유: PaddleOCR 모델이 ~/.paddleocr에 받아지는데,
# /root 아래 두면 app 사용자가 읽지 못한다.
RUN groupadd --system --gid 1000 app \
 && useradd --system --uid 1000 --gid app --home-dir /home/app --create-home app

# 이미지 속 문구를 읽기 위한 OCR.
#  - tesseract: 폴백이자 PaddleOCR을 못 쓰는 빌드의 기본 엔진.
#    한국어 학습데이터(kor)가 있어야 국내 랜딩페이지 배너를 읽는다.
#  - libgl1/libglib/libgomp: paddleocr이 끌고 오는 opencv-python(헤드리스가
#    아닌 쪽)이 이것들 없이는 import 단계에서 죽는다.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      tesseract-ocr tesseract-ocr-kor tesseract-ocr-eng \
      libgl1 libglib2.0-0 libgomp1 \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir .

# PaddleOCR 한국어 모델(korean_PP-OCRv4_rec + Multilingual_PP-OCRv3_det)을
# **빌드할 때** 받아 둔다. 런타임에 받게 두면 첫 요청이 수십 초 멈추고,
# 오프라인·사내망에서는 아예 실패한다. 모델은 ~/.paddleocr 아래 남는다.
#
# **여기서 실패해도 빌드를 죽이지 않는다.** PaddleOCR은 더 잘 읽는 선택지이지
# 이 도구가 도는 조건이 아니다(tesseract 폴백이 있다). 모델 CDN이 막힌
# 사내망이나 일시적 네트워크 장애 때문에 도구 전체를 못 쓰게 되는 쪽이
# 훨씬 나쁘다. 실패하면 이유를 파일로 남기고, /healthz가 그걸 그대로 보여준다.
# 반드시 PaddleOCR이어야 하는 빌드라면 --build-arg PADDLE_REQUIRED=1.
ARG PADDLE_REQUIRED=0
RUN if [ "$WITH_PADDLE" = "1" ]; then \
      { pip install --no-cache-dir --retries 5 --timeout 60 ".[paddle]" \
        && timeout 900 python -c "\
from paddleocr import PaddleOCR; \
PaddleOCR(lang='korean', use_angle_cls=False, show_log=False)" \
        && test -n "$(ls -A "$HOME/.paddleocr" 2>/dev/null)"; } \
      || echo "모델을 받지 못했습니다. tesseract로 동작합니다 (빌드 로그 참조)" \
           > /app/.paddle_unavailable; \
      find "$HOME/.paddleocr" -name '*.tar' -delete 2>/dev/null || true; \
      if [ -f /app/.paddle_unavailable ]; then \
        echo "=============================================================="; \
        cat /app/.paddle_unavailable; \
        echo "=============================================================="; \
        [ "$PADDLE_REQUIRED" = "1" ] && exit 1; \
      fi; \
    fi; \
    true

# auto = PaddleOCR이 준비돼 있으면 그걸, 아니면 tesseract.
ENV OCR_ENGINE=auto

RUN mkdir -p /app/data && chown -R app:app /home/app /app/data
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod 755 /usr/local/bin/docker-entrypoint.sh

EXPOSE 8080
# 엔트리포인트가 볼륨 소유권만 맞추고 app 사용자로 내려가 CMD를 실행한다.
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "adpolicy.main:app", "--host", "0.0.0.0", "--port", "8080"]
