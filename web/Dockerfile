FROM node:20-slim AS deps
WORKDIR /app
# 락파일까지 복사하고 npm ci를 쓴다. package.json만 넣고 npm install을 돌리면
# 빌드할 때마다 의존성 트리가 달라져, 로컬에서 되던 게 CI에서 깨진다.
COPY package.json package-lock.json* ./
# --omit=dev 를 쓰면 안 된다. TypeScript 프로젝트라 next build에 typescript와
# @types/* 가 필요하고, 없으면 Next가 빌드 도중 스스로 설치를 시도하다
# 네트워크가 막힌 빌더에서 그대로 실패한다.
RUN if [ -f package-lock.json ]; then npm ci --no-audit --no-fund; \
    else npm install --no-audit --no-fund; fi

FROM node:20-slim AS builder
WORKDIR /app
ARG NEXT_PUBLIC_API_URL=http://localhost:8080
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_API_KEY=
ENV NEXT_PUBLIC_API_KEY=$NEXT_PUBLIC_API_KEY
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:20-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
# standalone 출력은 실행에 필요한 것만 담고 있어 dev 의존성이 딸려오지 않는다.
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
