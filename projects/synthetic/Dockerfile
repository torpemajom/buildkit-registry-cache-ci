# Synthetic multi-stage build with the same shape as the real projects:
# builder stage: "OS packages" -> manifest -> "dependencies" -> source ->
# "compile" -> "link"; runtime stage: base image -> copy artifact.
# Each work step burns CPU_ITERS chained SHA-256 iterations and writes
# LAYER_BYTES of seeded incompressible data (see work.py).
ARG MIRROR=ghcr.io/torpemajom/buildkit-registry-cache-ci/mirror
FROM ${MIRROR}/python@sha256:6b1f85a08c199d29d5b6d71ab9c27bd5b3b393492e01216a15758ff69c4be8b8 AS builder
ARG CPU_ITERS
ARG LAYER_BYTES
RUN --mount=type=bind,source=work.py,target=/usr/local/bin/work.py python3 /usr/local/bin/work.py --name os --cpu-iters "$CPU_ITERS" --bytes "$LAYER_BYTES" --out /opt/os.bin
WORKDIR /app
COPY manifest.txt ./
RUN --mount=type=bind,source=work.py,target=/usr/local/bin/work.py python3 /usr/local/bin/work.py --name deps --cpu-iters "$CPU_ITERS" --bytes "$LAYER_BYTES" --input /opt/os.bin.seed --input manifest.txt --out /app/deps.bin
COPY src/ ./src/
RUN --mount=type=bind,source=work.py,target=/usr/local/bin/work.py python3 /usr/local/bin/work.py --name compile --cpu-iters "$CPU_ITERS" --bytes "$LAYER_BYTES" --input deps.bin.seed --input src/main.txt --out /app/compile.bin
RUN --mount=type=bind,source=work.py,target=/usr/local/bin/work.py python3 /usr/local/bin/work.py --name link --cpu-iters "$CPU_ITERS" --bytes "$LAYER_BYTES" --input compile.bin.seed --out /app/app.bin

FROM ${MIRROR}/python@sha256:6b1f85a08c199d29d5b6d71ab9c27bd5b3b393492e01216a15758ff69c4be8b8 AS runtime
WORKDIR /app
COPY --from=builder /app/app.bin /app/app.bin.seed ./
CMD ["python3", "-c", "print(open('/app/app.bin.seed').read())"]
