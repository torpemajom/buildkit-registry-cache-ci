# Caddy v2.11.7 (Go modules), canonical cache-friendly multi-stage build.
ARG MIRROR=ghcr.io/torpemajom/buildkit-registry-cache-ci/mirror
FROM ${MIRROR}/golang@sha256:af00f232205a01baf323bddc5bb4a4ea2e4cbf49e8ccc988beb2558d0f9c882a AS builder
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates git && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/caddy ./cmd/caddy

FROM ${MIRROR}/debian@sha256:7792b1f7702a86946cd518db72b6a407302c3e9bc1635634368b878189e8221c AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates mailcap && rm -rf /var/lib/apt/lists/*
COPY --from=builder /out/caddy /usr/bin/caddy
CMD ["caddy", "version"]
