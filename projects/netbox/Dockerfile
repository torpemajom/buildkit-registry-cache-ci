# NetBox v4.7.2 (Python / pip), canonical cache-friendly multi-stage build.
ARG MIRROR=ghcr.io/torpemajom/buildkit-registry-cache-ci/mirror
FROM ${MIRROR}/python@sha256:6b1f85a08c199d29d5b6d71ab9c27bd5b3b393492e01216a15758ff69c4be8b8 AS builder
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libpq-dev && rm -rf /var/lib/apt/lists/* && python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /opt/netbox
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN zensical build && NETBOX_CONFIGURATION=netbox.configuration_testing python netbox/manage.py collectstatic --no-input

FROM ${MIRROR}/python@sha256:6b1f85a08c199d29d5b6d71ab9c27bd5b3b393492e01216a15758ff69c4be8b8 AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 && rm -rf /var/lib/apt/lists/*
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /opt/netbox
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /opt/netbox /opt/netbox
CMD ["gunicorn", "--chdir", "/opt/netbox/netbox", "netbox.wsgi"]
