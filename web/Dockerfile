FROM node:26-slim AS deps
WORKDIR /app
# 락파일까지 복사하고 npm ci를 쓴다. package.json만 넣고 npm install을 돌리면
# 빌드할 때마다 의존성 트리가 달라져, 로컬에서 되던 게 CI에서 깨진다.
COPY package.json package-lock.json* ./
# --omit=dev 를 쓰면 안 된다. TypeScript 프로젝트라 next build에 typescript와
# @types/* 가 필요하고, 없으면 Next가 빌드 도중 스스로 설치를 시도하다
# 네트워크가 막힌 빌더에서 그대로 실패한다.
RUN if [ -f package-lock.json ]; then npm ci --no-audit --no-fund; \
    else npm install --no-audit --no-fund; fi

FROM node:26-slim AS builder
WORKDIR /app
ARG NEXT_PUBLIC_API_URL=http://localhost:8080
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_API_KEY=
ENV NEXT_PUBLIC_API_KEY=$NEXT_PUBLIC_API_KEY
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:26-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
# standalone 서버는 $HOSTNAME에 바인딩한다. 도커는 여기에 컨테이너 ID를 넣는다.
ENV HOSTNAME=0.0.0.0
# standalone 출력은 실행에 필요한 것만 담고 있어 dev 의존성이 딸려오지 않는다.
# 베이스 이미지에 있는 node 사용자(uid 1000)로 돈다 — root일 이유가 없다.
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static
COPY --from=builder --chown=node:node /app/public ./public
USER node
EXPOSE 3000
CMD ["node", "server.js"]
