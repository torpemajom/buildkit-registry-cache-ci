# Uptime Kuma 1.23.17 (Node.js / npm), canonical cache-friendly multi-stage build.
ARG MIRROR=ghcr.io/torpemajom/buildkit-registry-cache-ci/mirror
FROM ${MIRROR}/node@sha256:1694ccde5ea9efb3060bb8612b1f287256061ff2a04d75dc1b71f57cb7239520 AS builder
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates python3 make g++ && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV CYPRESS_INSTALL_BINARY=0 PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=1
COPY package.json package-lock.json .npmrc ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build && npm prune --omit=dev --no-audit --no-fund

FROM ${MIRROR}/node@sha256:1694ccde5ea9efb3060bb8612b1f287256061ff2a04d75dc1b71f57cb7239520 AS runtime
WORKDIR /app
ENV UPTIME_KUMA_IS_CONTAINER=1
COPY --from=builder /app /app
EXPOSE 3001
CMD ["node", "server/server.js"]
