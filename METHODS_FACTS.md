# Methods facts

Facts of the measured runs for the thesis text. Every table in the *Generated facts* section is
produced by [`analysis/facts.py`](analysis/facts.py) from `results/`; nothing in it is typed by hand.

## Repository and runs

- Repository: https://github.com/torpemajom/buildkit-registry-cache-ci (public)
- Workflow: [`.github/workflows/measure.yml`](.github/workflows/measure.yml) (`workflow_dispatch`)

| Run | Purpose | Commit | Inputs | Started (UTC) |
|---|---|---|---|---|
| [37121673730](https://github.com/torpemajom/buildkit-registry-cache-ci/actions/runs/37121673730) | infrastructure check | `ea3c718` | synthetic:small-short, S1, 1 shard, 1 trial | 2026-10-03 12:04 |
| [37121842229](https://github.com/torpemajom/buildkit-registry-cache-ci/actions/runs/37121842229) | smoke test, N = 2 | `ea3c718` | all projects, S0–S3, 1 shard, 2 trials | 2026-10-03 12:07 |
| [37123731010](https://github.com/torpemajom/buildkit-registry-cache-ci/actions/runs/37123731010) | **measured run**, N = 20 | `6eea4e9` | all projects, S0–S3, 4 shards, 5 trials | 2026-10-03 12:42 (completed 16:03, success) |

The smoke run's raw data are kept in [`results/smoke-37121842229/`](results/smoke-37121842229) (written by
commit `ea3c718`, where `pull_cache_bytes` was still named `pull_other_bytes`). The measured run's data
are in `results/`.

## Smoke test findings

- All 224 smoke builds exited 0; the empty-cache check passed and the builder was removed in all 224.
- rawjson parsing, interface byte counters, registry cache sizes and rawjson layer-download sums were
  present for every build; the only null metrics were the structural ones (no cache in mode `none`,
  no import in seed builds).
- `min` mode exports a cache with the chosen output (`--output type=docker`): 4–9 blobs, 47–315 MB.
- No project had to be replaced: Uptime Kuma 1.23.17, NetBox v4.7.2 and Caddy v2.11.7 built in every job.
- 6 of 168 measured builds contradicted the a-priori expected cache behaviour, all on the
  content-addressed runtime `COPY --from` steps, none at an invalidation point of the builder stage:
  - Uptime Kuma S3 (min and max, 4 builds): the runtime `COPY --from=builder /app /app` was not
    cached, i.e. a full rebuild of Uptime Kuma (npm ci + vite build) is not byte-reproducible.
    The a-priori declaration (reproducible) was changed to "invalidated".
  - NetBox S1 min (2 builds): the runtime venv copy was not cached. In `min` mode no builder step is
    reusable, so S1 reruns `pip install`, whose output is not byte-identical (NetBox S3 shows the same).
    The expectation model now encodes this for all projects: in `min` mode S1–S3 rebuild the whole
    builder stage, so a runtime copy is reused only if a full rebuild reproduces it and the scenario
    does not change it (commit `6eea4e9`). With the revised model all 168 smoke builds match.

## Measured run notes

- 112 jobs (7 project/variant units × 4 scenarios × 4 shards), max-parallel 16, 5 trials per job:
  224 seed and 1680 measured builds, N = 20 per project × variant × scenario × mode. No build failed
  and no build was flagged; every measured build matched the expected cache behaviour.
- One registry read failed transiently: for caddy S1, shard 3, trial 1, mode max the export succeeded
  (exit 0, `exporting cache to registry` 24.2 s) but `imagetools inspect` of the new ref returned
  "not found" immediately afterwards, so its cache-size fields are null with that reason. Re-read after
  the run, the ref exists with 931,590,116 bytes of unique blobs (the other trials of the cell:
  ≈ 931.6 MB). The raw record is left unchanged; the cell's cache-size median uses 19 values.
- Runner hardware was heterogeneous although every VM had 4 vCPUs and ≈ 16 GB RAM: six CPU models
  (see Versions). The synthetic long-compute step took 14.3–32.6 s CPU on different VMs. Pairing within
  a trial (same VM) removes this from the paired differences; it widens the IQRs of single modes in
  some cells (e.g. uptime-kuma S0 none, netbox S3 none, synthetic small-long S3 none).
- H4 counts a cell as "cache build shorter" when the median paired saving dt is positive, without a
  significance requirement; one qualifying cell (synthetic large-short S3 min, dt = 0.020 min) has a
  95% CI of the median difference that includes 0. The r_a range used for the decision includes the
  free GitHub Container Registry (r_a = 0); `ra_star_within_paid` and `ra_star_within_all_runner_prices`
  in `results/cost_breakeven.csv` give the narrower and the wider reading.

## Deviations from the original design, with reasons

- **Repository.** The session started in a private, unrelated repository; on the author's instruction
  the harness lives in a new public repository so that the standard public-repository runner
  (4 vCPU, 16 GB) is used and the package can be published.
- **Output type.** All modes use `--output type=docker` (the image is loaded into the runner's Docker
  Engine, its size read, then deleted; never pushed). Chosen over `type=cacheonly` because a CI build
  normally needs its image and because it yields the final image size.
- **Base images.** Debian trixie variants pinned by linux/amd64 digest; Node.js 20 for Uptime Kuma
  1.23 (the release's own CI tests Node 20.5); Python 3.12 for NetBox v4.7.2 (requires ≥ 3.12);
  Go 1.26.8 for Caddy v2.11.7 (`go 1.26.0` in go.mod).
- **Project builds.** Uptime Kuma: `CYPRESS_INSTALL_BINARY=0` (dev dependency, not needed for the
  build); build = `npm run build && npm prune --omit=dev`. NetBox: build = `zensical build`
  (documentation, as in upstream `upgrade.sh`) + `collectstatic` with the upstream test configuration
  (`NETBOX_CONFIGURATION=netbox.configuration_testing`), so no source file is added.
- **Reusable-step counts exclude `FROM`.** BuildKit never reports image-source vertices as cached, and
  two stages with the same base image share one `FROM` vertex.
- **Seed builds** run in random order (min/max) and carry the scenario of their job.
- **Analysis rules.** The tests follow the thesis' pre-registered decision rules (chapter 3.6,
  table 4) rather than the initial task text: H2 is tested with a one-sided Spearman correlation
  between the cache hit ratio and the relative time saving; the two-sided Wilcoxon tests of the
  S1–S3 cells are reported as a supplementary family without a decision.
- **Cost model.** Implemented as in thesis chapter 3.5 (eq. 1–2): uploads are not priced; D is the sum
  of the rawjson layer downloads of cache blobs (base-image layers excluded); M is the unique blob bytes
  of the cache manifest (base layers included; `cache_bytes_excl_base` is recorded too); n ∈ {10, 100, 1000};
  base runner price 4-core (0.012 USD/min); Google Artifact Registry prices converted from GiB to GB.
  Interface rx/tx counters are recorded as a cross-check only.
- **Uploaded bytes.** BuildKit v0.33.1 reports no byte totals for cache uploads in rawjson, so the only
  measure of uploaded bytes is the interface tx counter (includes protocol overhead).

## Generated facts

## Runs

| run_id | attempt | harness commit | builds | first build (UTC) | last build (UTC) |
|---|---|---|---|---|---|
| 37123731010 | 1 | 6eea4e94aeb0576fcd4be074da944d1ec502de28 | 1904 | 2026-10-03T12:42:52.891Z | 2026-10-03T15:58:54.849Z |

## Versions

| item | value (count of builds) |
|---|---|
| Buildx | github.com/docker/buildx v0.37.2 2d379c0c3f22da0d2759d132a0ec81ca949098f0 (1904) |
| BuildKit (builder inspect) | v0.33.1 (1904) |
| BuildKit image | ghcr.io/torpemajom/buildkit-registry-cache-ci/mirror/buildkit@sha256:98cc6a3fc46220d00f8224ae483f3274fc874e9be8d7dd1e2e2c5481209228b5 (1904) |
| Runner image (ImageOS / ImageVersion) | ubuntu24 / 20260927.320.1 (1904) |
| CPU model | AMD EPYC 7763 64-Core Processor (1020), AMD EPYC 9V74 80-Core Processor (357), AMD EPYC 9V45 96-Core Processor (306), INTEL(R) XEON(R) PLATINUM 8573C (119), Intel(R) Xeon(R) 6973P-C (68), Intel(R) Xeon(R) Platinum 8370C CPU @ 2.80GHz (34) |
| vCPUs | 4 (1904) |
| RAM bytes | 16766414848 (1275), 16766410752 (306), 16765378560 (136), 16765374464 (68), 16770748416 (51), 16766418944 (34), 16765366272 (17), 16766406656 (17) |
| Kernel | 6.17.0-1022-azure (1904) |
| Docker Engine / storage driver | 28.0.4 / overlay2 (1904) |
| Cache export options | type=registry,mode=max (672), type=registry,mode=min (672) |
| Cache manifest media type | application/vnd.oci.image.manifest.v1+json (1343) |

Pinned images (linux/amd64 manifest digests, mirrored byte-for-byte to ghcr.io):

| mirror name | upstream | tag | digest |
|---|---|---|---|
| buildkit | docker.io/moby/buildkit | v0.33.1 | `sha256:98cc6a3fc46220d00f8224ae483f3274fc874e9be8d7dd1e2e2c5481209228b5` |
| buildx-bin | docker.io/docker/buildx-bin | 0.37.2 | `sha256:9e2e0742054896c699b509239732b91138f781845e764bb4853885f26e142ad5` |
| debian | docker.io/library/debian | trixie-20260918-slim | `sha256:7792b1f7702a86946cd518db72b6a407302c3e9bc1635634368b878189e8221c` |
| golang | docker.io/library/golang | 1.26.8-trixie | `sha256:af00f232205a01baf323bddc5bb4a4ea2e4cbf49e8ccc988beb2558d0f9c882a` |
| node | docker.io/library/node | 20.20.2-trixie-slim | `sha256:1694ccde5ea9efb3060bb8612b1f287256061ff2a04d75dc1b71f57cb7239520` |
| python | docker.io/library/python | 3.12.15-slim-trixie | `sha256:6b1f85a08c199d29d5b6d71ab9c27bd5b3b393492e01216a15758ff69c4be8b8` |

Buildx binary v0.37.2 sha256 `982ca20490b45ed1ec8d99795974d3d874a358f75938c9c237305010e6b7e548`.

## Projects and expected vs observed reusable steps


### caddy (go-modules)

Source: https://github.com/caddyserver/caddy tag `v2.11.7` commit `72dd0fb067f6d7826c7f79907670ba4a713bfe37`.

| stage | step | instruction | first invalidated by |
|---|---|---|---|
| builder | 1/7 | `FROM ${MIRROR}/golang@sha256:af00f232205a01baf323bddc5bb4a4ea2e4cbf49e8ccc988beb2558d0f9c8` |  |
| builder | 2/7 | `RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates git && rm` | S3 |
| builder | 3/7 | `WORKDIR /src` |  |
| builder | 4/7 | `COPY go.mod go.sum ./` | S2 |
| builder | 5/7 | `RUN go mod download` |  |
| builder | 6/7 | `COPY . .` | S1 |
| builder | 7/7 | `RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/caddy ./cmd/caddy` |  |
| runtime | 1/3 | `FROM ${MIRROR}/debian@sha256:7792b1f7702a86946cd518db72b6a407302c3e9bc1635634368b878189e82` |  |
| runtime | 2/3 | `RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates mailcap &` |  |
| runtime | 3/3 | `COPY --from=builder /out/caddy /usr/bin/caddy` | S1 |

Reusable (CACHED) steps, FROM excluded — expected / observed (min–max over valid builds):

| variant | scenario | none | min | max |
|---|---|---|---|---|
| default | S0 | 0 / 0–0 | 8 / 8–8 | 8 / 8–8 |
| default | S1 | 0 / 0–0 | 1 / 1–1 | 5 / 5–5 |
| default | S2 | 0 / 0–0 | 2 / 2–2 | 4 / 4–4 |
| default | S3 | 0 / 0–0 | 2 / 2–2 | 2 / 2–2 |

### netbox (python-pip)

Source: https://github.com/netbox-community/netbox tag `v4.7.2` commit `251458b89a5eb2f5fe0d20ecd1140ba08f141a9c`.

| stage | step | instruction | first invalidated by |
|---|---|---|---|
| builder | 1/7 | `FROM ${MIRROR}/python@sha256:6b1f85a08c199d29d5b6d71ab9c27bd5b3b393492e01216a15758ff69c4be` |  |
| builder | 2/7 | `RUN apt-get update && apt-get install -y --no-install-recommends build-essential libpq-dev` | S3 |
| builder | 3/7 | `WORKDIR /opt/netbox` |  |
| builder | 4/7 | `COPY requirements.txt ./` | S2 |
| builder | 5/7 | `RUN pip install --no-cache-dir -r requirements.txt` |  |
| builder | 6/7 | `COPY . .` | S1 |
| builder | 7/7 | `RUN zensical build && NETBOX_CONFIGURATION=netbox.configuration_testing python netbox/mana` |  |
| runtime | 1/5 | `FROM ${MIRROR}/python@sha256:6b1f85a08c199d29d5b6d71ab9c27bd5b3b393492e01216a15758ff69c4be` |  |
| runtime | 2/5 | `RUN apt-get update && apt-get install -y --no-install-recommends libpq5 && rm -rf /var/lib` |  |
| runtime | 3/5 | `WORKDIR /opt/netbox` |  |
| runtime | 4/5 | `COPY --from=builder /opt/venv /opt/venv` | S2, S3 |
| runtime | 5/5 | `COPY --from=builder /opt/netbox /opt/netbox` | S1 |

Reusable (CACHED) steps, FROM excluded — expected / observed (min–max over valid builds):

| variant | scenario | none | min | max |
|---|---|---|---|---|
| default | S0 | 0 / 0–0 | 10 / 10–10 | 10 / 10–10 |
| default | S1 | 0 / 0–0 | 2 / 2–2 | 7 / 7–7 |
| default | S2 | 0 / 0–0 | 2 / 2–2 | 4 / 4–4 |
| default | S3 | 0 / 0–0 | 2 / 2–2 | 2 / 2–2 |

### synthetic (synthetic)

| stage | step | instruction | first invalidated by |
|---|---|---|---|
| builder | 1/8 | `FROM ${MIRROR}/python@sha256:6b1f85a08c199d29d5b6d71ab9c27bd5b3b393492e01216a15758ff69c4be` |  |
| builder | 2/8 | `RUN --mount=type=bind,source=work.py,target=/usr/local/bin/work.py python3 /usr/local/bin/` | S3 |
| builder | 3/8 | `WORKDIR /app` |  |
| builder | 4/8 | `COPY manifest.txt ./` | S2 |
| builder | 5/8 | `RUN --mount=type=bind,source=work.py,target=/usr/local/bin/work.py python3 /usr/local/bin/` |  |
| builder | 6/8 | `COPY src/ ./src/` | S1 |
| builder | 7/8 | `RUN --mount=type=bind,source=work.py,target=/usr/local/bin/work.py python3 /usr/local/bin/` |  |
| builder | 8/8 | `RUN --mount=type=bind,source=work.py,target=/usr/local/bin/work.py python3 /usr/local/bin/` |  |
| runtime | 1/3 | `FROM ${MIRROR}/python@sha256:6b1f85a08c199d29d5b6d71ab9c27bd5b3b393492e01216a15758ff69c4be` |  |
| runtime | 2/3 | `WORKDIR /app` |  |
| runtime | 3/3 | `COPY --from=builder /app/app.bin /app/app.bin.seed ./` | S1, S2 |

Reusable (CACHED) steps, FROM excluded — expected / observed (min–max over valid builds):

| variant | scenario | none | min | max |
|---|---|---|---|---|
| large-long | S0 | 0 / 0–0 | 9 / 9–9 | 9 / 9–9 |
| large-long | S1 | 0 / 0–0 | 1 / 1–1 | 5 / 5–5 |
| large-long | S2 | 0 / 0–0 | 1 / 1–1 | 3 / 3–3 |
| large-long | S3 | 0 / 0–0 | 2 / 2–2 | 2 / 2–2 |
| large-short | S0 | 0 / 0–0 | 9 / 9–9 | 9 / 9–9 |
| large-short | S1 | 0 / 0–0 | 1 / 1–1 | 5 / 5–5 |
| large-short | S2 | 0 / 0–0 | 1 / 1–1 | 3 / 3–3 |
| large-short | S3 | 0 / 0–0 | 2 / 2–2 | 2 / 2–2 |
| small-long | S0 | 0 / 0–0 | 9 / 9–9 | 9 / 9–9 |
| small-long | S1 | 0 / 0–0 | 1 / 1–1 | 5 / 5–5 |
| small-long | S2 | 0 / 0–0 | 1 / 1–1 | 3 / 3–3 |
| small-long | S3 | 0 / 0–0 | 2 / 2–2 | 2 / 2–2 |
| small-short | S0 | 0 / 0–0 | 9 / 9–9 | 9 / 9–9 |
| small-short | S1 | 0 / 0–0 | 1 / 1–1 | 5 / 5–5 |
| small-short | S2 | 0 / 0–0 | 1 / 1–1 | 3 / 3–3 |
| small-short | S3 | 0 / 0–0 | 2 / 2–2 | 2 / 2–2 |

### uptime-kuma (nodejs-npm)

Source: https://github.com/louislam/uptime-kuma tag `1.23.17` commit `40ec7158534a28e6f8b431a628c53133c327c539`.

| stage | step | instruction | first invalidated by |
|---|---|---|---|
| builder | 1/7 | `FROM ${MIRROR}/node@sha256:1694ccde5ea9efb3060bb8612b1f287256061ff2a04d75dc1b71f57cb723952` |  |
| builder | 2/7 | `RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates python3 m` | S3 |
| builder | 3/7 | `WORKDIR /app` |  |
| builder | 4/7 | `COPY package.json package-lock.json .npmrc ./` | S2 |
| builder | 5/7 | `RUN npm ci --no-audit --no-fund` |  |
| builder | 6/7 | `COPY . .` | S1 |
| builder | 7/7 | `RUN npm run build && npm prune --omit=dev --no-audit --no-fund` |  |
| runtime | 1/3 | `FROM ${MIRROR}/node@sha256:1694ccde5ea9efb3060bb8612b1f287256061ff2a04d75dc1b71f57cb723952` |  |
| runtime | 2/3 | `WORKDIR /app` |  |
| runtime | 3/3 | `COPY --from=builder /app /app` | S1, S2, S3 |

Reusable (CACHED) steps, FROM excluded — expected / observed (min–max over valid builds):

| variant | scenario | none | min | max |
|---|---|---|---|---|
| default | S0 | 0 / 0–0 | 8 / 8–8 | 8 / 8–8 |
| default | S1 | 0 / 0–0 | 1 / 1–1 | 5 / 5–5 |
| default | S2 | 0 / 0–0 | 1 / 1–1 | 3 / 3–3 |
| default | S3 | 0 / 0–0 | 1 / 1–1 | 1 / 1–1 |

## Synthetic variants

| variant | bytes per step | SHA-256 iterations per step | work steps | observed CPU s per step (median, min–max) |
|---|---|---|---|---|
| small-short | 1048576 | 2000000 | 4 | 0.94 (0.47–1.14) |
| small-long | 1048576 | 60000000 | 4 | 28.40 (14.31–32.63) |
| large-short | 268435456 | 2000000 | 4 | 0.85 (0.47–1.06) |
| large-long | 268435456 | 60000000 | 4 | 28.26 (14.39–31.04) |

## Executed plan

- jobs with results: 112; builds: 1904 (224 seed, 1680 measured)
- trials per job: 5 (1904)
- measured builds per cell (project × variant × scenario × mode): 20 (84)
- failed builds (exit ≠ 0): 0; flagged builds: 0; flags: {}
- empty-cache check passed: 1904 of 1904; builder removed: 1904 of 1904

## Per cell (valid measured builds)

| project | variant | scenario | mode | n | wall_s median | wall_s IQR (q1–q3) | import_s | export_cache_s | cache MB | cache MB excl. base | rx MB | tx MB | cache layers pulled MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| caddy | default | S0 | none | 20 | 87.3 | 85.2–90.7 | – | – | – | – | 569.2 | 2.1 | 0.0 |
| caddy | default | S0 | min | 20 | 5.9 | 5.4–6.3 | 0.55 | 0.75 | 66.3 | 36.4 | 66.7 | 0.2 | 36.4 |
| caddy | default | S0 | max | 20 | 6.1 | 5.6–6.6 | 0.57 | 0.97 | 931.6 | 589.3 | 66.7 | 0.2 | 36.4 |
| caddy | default | S1 | none | 20 | 92.2 | 91.2–93.3 | – | – | – | – | 568.4 | 1.6 | 0.0 |
| caddy | default | S1 | min | 20 | 98.1 | 95.4–99.3 | 0.35 | 2.87 | 66.3 | 36.4 | 562.4 | 22.5 | 16.3 |
| caddy | default | S1 | max | 20 | 116.1 | 114.8–119.9 | 0.35 | 25.34 | 931.6 | 589.3 | 719.5 | 225.4 | 373.8 |
| caddy | default | S2 | none | 20 | 90.1 | 87.0–91.0 | – | – | – | – | 568.5 | 1.7 | 0.0 |
| caddy | default | S2 | min | 20 | 92.0 | 89.2–92.3 | 0.69 | 1.03 | 66.3 | 36.4 | 582.7 | 1.8 | 36.4 |
| caddy | default | S2 | max | 20 | 118.3 | 113.1–119.2 | 0.70 | 28.24 | 931.6 | 589.3 | 573.1 | 577.0 | 36.4 |
| caddy | default | S3 | none | 20 | 92.6 | 91.9–93.1 | – | – | – | – | 568.4 | 1.6 | 0.0 |
| caddy | default | S3 | min | 20 | 92.8 | 92.2–93.4 | 0.31 | 1.56 | 66.3 | 36.4 | 582.5 | 1.6 | 36.4 |
| caddy | default | S3 | max | 20 | 117.4 | 116.0–118.7 | 0.31 | 25.62 | 931.6 | 589.3 | 583.1 | 577.5 | 36.4 |
| netbox | default | S0 | none | 20 | 126.3 | 111.5–131.7 | – | – | – | – | 240.4 | 0.9 | 0.0 |
| netbox | default | S0 | min | 20 | 22.3 | 21.1–22.6 | 0.39 | 0.62 | 188.5 | 142.3 | 189.5 | 0.4 | 142.3 |
| netbox | default | S0 | max | 20 | 22.4 | 21.3–22.9 | 0.41 | 0.78 | 444.8 | 398.5 | 189.7 | 0.5 | 142.3 |
| netbox | default | S1 | none | 20 | 132.1 | 128.7–133.2 | – | – | – | – | 240.4 | 0.8 | 0.0 |
| netbox | default | S1 | min | 20 | 137.4 | 132.6–139.1 | 0.47 | 4.01 | 188.5 | 142.3 | 230.5 | 147.9 | 1.3 |
| netbox | default | S1 | max | 20 | 79.3 | 78.5–82.9 | 0.48 | 6.60 | 444.8 | 398.5 | 335.9 | 116.2 | 287.7 |
| netbox | default | S2 | none | 20 | 123.1 | 108.9–131.9 | – | – | – | – | 240.3 | 0.8 | 0.0 |
| netbox | default | S2 | min | 20 | 129.5 | 117.0–138.9 | 0.54 | 4.13 | 188.5 | 142.3 | 230.5 | 147.3 | 1.3 |
| netbox | default | S2 | max | 20 | 134.9 | 123.0–143.1 | 0.59 | 15.76 | 444.8 | 398.5 | 251.3 | 289.7 | 118.4 |
| netbox | default | S3 | none | 20 | 118.6 | 99.1–135.2 | – | – | – | – | 240.5 | 0.9 | 0.0 |
| netbox | default | S3 | min | 20 | 123.4 | 104.7–140.8 | 0.51 | 3.76 | 188.5 | 142.3 | 230.7 | 144.5 | 1.3 |
| netbox | default | S3 | max | 20 | 137.3 | 114.6–156.7 | 0.52 | 17.39 | 444.8 | 398.5 | 231.1 | 405.7 | 1.3 |
| synthetic | large-long | S0 | none | 20 | 89.4 | 80.2–107.6 | – | – | – | – | 46.6 | 0.3 | 0.0 |
| synthetic | large-long | S0 | min | 20 | 12.8 | 10.0–14.9 | 0.50 | 0.71 | 314.7 | 268.5 | 317.0 | 1.1 | 268.5 |
| synthetic | large-long | S0 | max | 20 | 11.6 | 10.6–14.3 | 0.49 | 0.84 | 1389.1 | 1342.9 | 316.8 | 0.8 | 268.5 |
| synthetic | large-long | S1 | none | 20 | 129.3 | 114.3–133.5 | – | – | – | – | 46.6 | 0.3 | 0.0 |
| synthetic | large-long | S1 | min | 20 | 138.7 | 122.6–144.5 | 0.65 | 7.64 | 314.7 | 268.5 | 46.9 | 278.9 | 0.0 |
| synthetic | large-long | S1 | max | 20 | 92.6 | 86.4–95.1 | 0.65 | 14.45 | 1389.1 | 1342.9 | 587.7 | 833.6 | 537.3 |
| synthetic | large-long | S2 | none | 20 | 132.2 | 130.8–132.7 | – | – | – | – | 46.6 | 0.3 | 0.0 |
| synthetic | large-long | S2 | min | 20 | 137.8 | 136.7–138.2 | 0.26 | 4.75 | 314.7 | 268.5 | 46.8 | 280.5 | 0.0 |
| synthetic | large-long | S2 | max | 20 | 121.3 | 120.4–122.5 | 0.26 | 14.43 | 1389.1 | 1342.9 | 317.3 | 1120.5 | 268.8 |
| synthetic | large-long | S3 | none | 20 | 133.1 | 125.2–133.9 | – | – | – | – | 46.6 | 0.2 | 0.0 |
| synthetic | large-long | S3 | min | 20 | 134.6 | 126.7–136.8 | 0.69 | 1.64 | 314.7 | 268.5 | 316.9 | 1.2 | 268.5 |
| synthetic | large-long | S3 | max | 20 | 151.4 | 142.4–155.9 | 0.68 | 19.74 | 1389.1 | 1342.9 | 318.1 | 1115.2 | 268.5 |
| synthetic | large-short | S0 | none | 20 | 22.2 | 21.6–23.9 | – | – | – | – | 46.5 | 0.2 | 0.0 |
| synthetic | large-short | S0 | min | 20 | 10.7 | 8.9–13.5 | 0.48 | 0.67 | 314.7 | 268.5 | 316.1 | 0.5 | 268.5 |
| synthetic | large-short | S0 | max | 20 | 10.8 | 9.2–13.4 | 0.49 | 0.93 | 1389.1 | 1342.9 | 316.3 | 0.5 | 268.5 |
| synthetic | large-short | S1 | none | 20 | 22.7 | 21.9–23.5 | – | – | – | – | 46.5 | 0.2 | 0.0 |
| synthetic | large-short | S1 | min | 20 | 31.1 | 29.4–32.2 | 0.46 | 5.91 | 314.7 | 268.5 | 46.7 | 280.1 | 0.0 |
| synthetic | large-short | S1 | max | 20 | 38.8 | 36.6–42.0 | 0.47 | 12.25 | 1389.1 | 1342.9 | 586.8 | 840.9 | 537.3 |
| synthetic | large-short | S2 | none | 20 | 22.3 | 21.5–23.5 | – | – | – | – | 46.5 | 0.2 | 0.0 |
| synthetic | large-short | S2 | min | 20 | 29.5 | 26.8–31.2 | 0.45 | 5.35 | 314.7 | 268.5 | 46.9 | 276.0 | 0.0 |
| synthetic | large-short | S2 | max | 20 | 40.3 | 37.4–44.7 | 0.49 | 14.90 | 1389.1 | 1342.9 | 318.2 | 1105.3 | 268.8 |
| synthetic | large-short | S3 | none | 20 | 23.3 | 22.3–25.3 | – | – | – | – | 46.5 | 0.1 | 0.0 |
| synthetic | large-short | S3 | min | 20 | 22.8 | 20.5–26.7 | 0.44 | 1.39 | 314.7 | 268.5 | 316.2 | 0.6 | 268.5 |
| synthetic | large-short | S3 | max | 20 | 39.2 | 37.5–42.4 | 0.42 | 17.78 | 1389.1 | 1342.9 | 317.1 | 1120.8 | 268.5 |
| synthetic | small-long | S0 | none | 20 | 109.6 | 99.2–113.9 | – | – | – | – | 46.6 | 0.2 | 0.0 |
| synthetic | small-long | S0 | min | 20 | 4.2 | 3.9–4.6 | 0.38 | 0.65 | 47.3 | 1.1 | 47.6 | 0.1 | 1.0 |
| synthetic | small-long | S0 | max | 20 | 4.4 | 4.2–4.7 | 0.40 | 0.76 | 50.7 | 4.5 | 47.6 | 0.2 | 1.0 |
| synthetic | small-long | S1 | none | 20 | 118.9 | 111.1–120.1 | – | – | – | – | 46.6 | 0.2 | 0.0 |
| synthetic | small-long | S1 | min | 20 | 121.6 | 114.4–123.4 | 0.46 | 2.86 | 47.3 | 1.1 | 46.6 | 1.3 | 0.0 |
| synthetic | small-long | S1 | max | 20 | 64.5 | 61.4–66.4 | 0.46 | 3.19 | 50.7 | 4.5 | 49.0 | 2.4 | 2.4 |
| synthetic | small-long | S2 | none | 20 | 119.8 | 111.1–120.4 | – | – | – | – | 46.6 | 0.2 | 0.0 |
| synthetic | small-long | S2 | min | 20 | 123.6 | 115.4–124.4 | 0.47 | 2.68 | 47.3 | 1.1 | 46.6 | 1.4 | 0.0 |
| synthetic | small-long | S2 | max | 20 | 95.6 | 88.8–96.4 | 0.40 | 3.89 | 50.7 | 4.5 | 48.0 | 3.5 | 1.3 |
| synthetic | small-long | S3 | none | 20 | 93.4 | 64.4–119.7 | – | – | – | – | 46.6 | 0.2 | 0.0 |
| synthetic | small-long | S3 | min | 20 | 96.2 | 67.0–122.9 | 0.60 | 0.99 | 47.3 | 1.1 | 47.7 | 0.3 | 1.0 |
| synthetic | small-long | S3 | max | 20 | 99.8 | 71.0–126.0 | 0.58 | 4.70 | 51.8 | 5.5 | 47.7 | 4.9 | 1.0 |
| synthetic | small-short | S0 | none | 20 | 8.5 | 8.2–8.8 | – | – | – | – | 46.5 | 0.1 | 0.0 |
| synthetic | small-short | S0 | min | 20 | 4.2 | 3.4–4.9 | 0.42 | 0.70 | 47.3 | 1.1 | 47.5 | 0.1 | 1.0 |
| synthetic | small-short | S0 | max | 20 | 4.9 | 3.5–5.1 | 0.42 | 1.05 | 50.7 | 4.5 | 47.6 | 0.1 | 1.0 |
| synthetic | small-short | S1 | none | 20 | 7.8 | 6.5–8.4 | – | – | – | – | 46.5 | 0.1 | 0.0 |
| synthetic | small-short | S1 | min | 20 | 11.4 | 10.7–11.6 | 0.46 | 2.85 | 47.3 | 1.1 | 46.6 | 1.2 | 0.0 |
| synthetic | small-short | S1 | max | 20 | 9.9 | 9.6–10.2 | 0.49 | 3.06 | 50.7 | 4.5 | 49.0 | 2.3 | 2.4 |
| synthetic | small-short | S2 | none | 20 | 8.6 | 7.8–8.9 | – | – | – | – | 46.5 | 0.1 | 0.0 |
| synthetic | small-short | S2 | min | 20 | 11.7 | 10.8–13.0 | 0.41 | 2.72 | 47.3 | 1.1 | 46.6 | 1.2 | 0.0 |
| synthetic | small-short | S2 | max | 20 | 12.4 | 11.0–13.0 | 0.46 | 3.99 | 50.7 | 4.5 | 47.9 | 3.4 | 1.3 |
| synthetic | small-short | S3 | none | 20 | 8.2 | 6.5–8.7 | – | – | – | – | 46.5 | 0.1 | 0.0 |
| synthetic | small-short | S3 | min | 20 | 9.5 | 8.7–10.3 | 0.60 | 1.02 | 47.3 | 1.1 | 47.6 | 0.2 | 1.0 |
| synthetic | small-short | S3 | max | 20 | 12.4 | 11.9–12.9 | 0.53 | 4.27 | 51.8 | 5.5 | 47.6 | 4.8 | 1.0 |
| uptime-kuma | default | S0 | none | 20 | 122.0 | 95.9–150.4 | – | – | – | – | 272.2 | 1.7 | 0.0 |
| uptime-kuma | default | S0 | min | 20 | 11.7 | 11.0–12.6 | 0.37 | 0.62 | 115.5 | 42.5 | 116.1 | 0.2 | 42.5 |
| uptime-kuma | default | S0 | max | 20 | 11.7 | 11.0–12.5 | 0.38 | 0.70 | 411.0 | 338.0 | 116.1 | 0.3 | 42.5 |
| uptime-kuma | default | S1 | none | 20 | 147.1 | 141.2–148.9 | – | – | – | – | 271.9 | 1.7 | 0.0 |
| uptime-kuma | default | S1 | min | 20 | 149.8 | 145.1–154.5 | 0.54 | 3.53 | 115.5 | 42.5 | 272.1 | 46.0 | 0.0 |
| uptime-kuma | default | S1 | max | 20 | 133.4 | 127.4–136.8 | 0.52 | 4.21 | 411.2 | 338.2 | 361.8 | 54.3 | 286.8 |
| uptime-kuma | default | S2 | none | 20 | 145.7 | 140.7–147.0 | – | – | – | – | 272.3 | 1.7 | 0.0 |
| uptime-kuma | default | S2 | min | 20 | 149.8 | 145.5–151.1 | 0.27 | 3.02 | 115.5 | 42.5 | 272.2 | 46.0 | 0.0 |
| uptime-kuma | default | S2 | max | 20 | 158.8 | 153.3–160.6 | 0.28 | 20.51 | 411.0 | 338.0 | 291.3 | 233.9 | 115.6 |
| uptime-kuma | default | S3 | none | 20 | 148.0 | 145.1–149.6 | – | – | – | – | 272.1 | 1.7 | 0.0 |
| uptime-kuma | default | S3 | min | 20 | 154.9 | 150.9–156.4 | 0.70 | 4.02 | 115.5 | 42.5 | 272.0 | 46.0 | 0.0 |
| uptime-kuma | default | S3 | max | 20 | 172.5 | 169.7–174.8 | 0.69 | 23.41 | 411.0 | 338.1 | 272.3 | 353.3 | 0.0 |

Seed builds (cold build + cache export):

| project | variant | job scenario | mode | n | wall_s median | export_cache_s | cache MB | tx MB |
|---|---|---|---|---|---|---|---|---|
| caddy | default | S0 | min | 4 | 97.2 | 3.58 | 66.3 | 39.6 |
| caddy | default | S0 | max | 4 | 118.0 | 27.18 | 931.6 | 599.6 |
| caddy | default | S1 | min | 4 | 95.6 | 3.04 | 66.3 | 39.4 |
| caddy | default | S1 | max | 4 | 119.0 | 27.42 | 931.6 | 611.7 |
| caddy | default | S2 | min | 4 | 95.5 | 3.78 | 66.3 | 39.6 |
| caddy | default | S2 | max | 4 | 120.3 | 29.17 | 931.6 | 614.0 |
| caddy | default | S3 | min | 4 | 95.8 | 2.90 | 66.3 | 39.6 |
| caddy | default | S3 | max | 4 | 118.6 | 25.24 | 931.6 | 614.7 |
| netbox | default | S0 | min | 4 | 130.7 | 3.65 | 188.5 | 147.4 |
| netbox | default | S0 | max | 4 | 147.6 | 18.05 | 444.8 | 411.4 |
| netbox | default | S1 | min | 4 | 135.3 | 3.82 | 188.5 | 149.3 |
| netbox | default | S1 | max | 4 | 151.6 | 19.14 | 444.8 | 416.0 |
| netbox | default | S2 | min | 4 | 126.9 | 4.30 | 188.5 | 147.3 |
| netbox | default | S2 | max | 4 | 144.5 | 19.03 | 444.8 | 411.9 |
| netbox | default | S3 | min | 4 | 121.4 | 4.02 | 188.5 | 145.7 |
| netbox | default | S3 | max | 4 | 136.1 | 17.98 | 444.8 | 406.9 |
| synthetic | large-long | S0 | min | 4 | 96.8 | 5.59 | 314.7 | 272.9 |
| synthetic | large-long | S0 | max | 4 | 109.9 | 19.06 | 1389.1 | 1363.6 |
| synthetic | large-long | S1 | min | 4 | 136.2 | 6.65 | 314.7 | 279.6 |
| synthetic | large-long | S1 | max | 4 | 150.5 | 21.42 | 1389.1 | 1386.6 |
| synthetic | large-long | S2 | min | 4 | 137.1 | 4.53 | 314.7 | 280.2 |
| synthetic | large-long | S2 | max | 4 | 150.4 | 17.73 | 1389.1 | 1400.6 |
| synthetic | large-long | S3 | min | 4 | 139.8 | 7.97 | 314.7 | 279.8 |
| synthetic | large-long | S3 | max | 4 | 154.9 | 24.76 | 1389.1 | 1391.2 |
| synthetic | large-short | S0 | min | 4 | 30.0 | 5.32 | 314.7 | 272.9 |
| synthetic | large-short | S0 | max | 4 | 44.5 | 19.01 | 1389.1 | 1363.8 |
| synthetic | large-short | S1 | min | 4 | 31.4 | 6.51 | 314.7 | 280.2 |
| synthetic | large-short | S1 | max | 4 | 46.1 | 20.23 | 1389.1 | 1396.8 |
| synthetic | large-short | S2 | min | 4 | 30.0 | 5.28 | 314.7 | 276.2 |
| synthetic | large-short | S2 | max | 4 | 43.7 | 19.11 | 1389.1 | 1378.0 |
| synthetic | large-short | S3 | min | 4 | 30.3 | 6.04 | 314.7 | 279.9 |
| synthetic | large-short | S3 | max | 4 | 45.7 | 20.76 | 1389.1 | 1399.4 |
| synthetic | small-long | S0 | min | 4 | 112.7 | 2.78 | 47.3 | 1.4 |
| synthetic | small-long | S0 | max | 4 | 113.5 | 4.80 | 50.7 | 4.8 |
| synthetic | small-long | S1 | min | 4 | 121.9 | 2.99 | 47.3 | 1.3 |
| synthetic | small-long | S1 | max | 4 | 124.6 | 5.26 | 50.7 | 4.9 |
| synthetic | small-long | S2 | min | 4 | 122.2 | 2.79 | 47.3 | 1.3 |
| synthetic | small-long | S2 | max | 4 | 124.0 | 4.83 | 50.7 | 4.9 |
| synthetic | small-long | S3 | min | 4 | 96.8 | 2.98 | 47.3 | 1.4 |
| synthetic | small-long | S3 | max | 4 | 99.4 | 5.46 | 50.7 | 4.9 |
| synthetic | small-short | S0 | min | 4 | 11.5 | 2.93 | 47.3 | 1.2 |
| synthetic | small-short | S0 | max | 4 | 13.8 | 5.22 | 50.7 | 4.8 |
| synthetic | small-short | S1 | min | 4 | 11.1 | 2.84 | 47.3 | 1.2 |
| synthetic | small-short | S1 | max | 4 | 13.0 | 5.23 | 50.7 | 4.7 |
| synthetic | small-short | S2 | min | 4 | 11.6 | 2.91 | 47.3 | 1.2 |
| synthetic | small-short | S2 | max | 4 | 13.1 | 4.43 | 50.7 | 4.8 |
| synthetic | small-short | S3 | min | 4 | 10.3 | 3.00 | 47.3 | 1.2 |
| synthetic | small-short | S3 | max | 4 | 12.0 | 4.45 | 50.7 | 4.8 |
| uptime-kuma | default | S0 | min | 4 | 128.6 | 3.31 | 115.5 | 45.7 |
| uptime-kuma | default | S0 | max | 4 | 144.3 | 19.72 | 411.0 | 350.9 |
| uptime-kuma | default | S1 | min | 4 | 149.1 | 3.66 | 115.5 | 46.0 |
| uptime-kuma | default | S1 | max | 4 | 169.0 | 22.66 | 411.0 | 353.9 |
| uptime-kuma | default | S2 | min | 4 | 149.4 | 2.83 | 115.5 | 46.1 |
| uptime-kuma | default | S2 | max | 4 | 168.2 | 21.73 | 411.0 | 354.5 |
| uptime-kuma | default | S3 | min | 4 | 155.1 | 4.03 | 115.5 | 46.2 |
| uptime-kuma | default | S3 | max | 4 | 173.5 | 23.51 | 411.0 | 353.8 |

## Tests

d = wall_s(mode) − wall_s(none) per trial; CI = percentile bootstrap 95% of the median; r = matched-pairs rank-biserial (positive: cache slower); p_holm within the family; W = min(T+, T−) for two-sided and T+ for one-sided tests; rho = Spearman (one-sided, H2); family S1-S3 is supplementary (no decision).

| family | alt. | project | variant | scenario | mode | n | median d (s) | 95% CI | rel. saving | W / rho | p | p_holm | r |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H1 | two-sided | caddy | default | S0 | min | 20 | -81.37 | [-83.70, -79.95] | 0.932 | 0.000 | 1.91e-06 | 2.67e-05 | -1.000 |
| H3 | greater | caddy | default | S0 | min | 20 | -81.37 | [-83.70, -79.95] | 0.932 | 0.000 | 1.0000 | 1.0000 | -1.000 |
| H1 | two-sided | caddy | default | S0 | max | 20 | -81.08 | [-83.59, -79.71] | 0.928 | 0.000 | 1.91e-06 | 2.67e-05 | -1.000 |
| H3 | greater | caddy | default | S0 | max | 20 | -81.08 | [-83.59, -79.71] | 0.928 | 0.000 | 1.0000 | 1.0000 | -1.000 |
| S1-S3 | two-sided | caddy | default | S1 | min | 20 | 5.79 | [4.84, 6.52] | -0.063 | 0.000 | 1.91e-06 | 8.01e-05 | 1.000 |
| H3 | greater | caddy | default | S1 | min | 20 | 5.79 | [4.84, 6.52] | -0.063 | 210.000 | 9.54e-07 | 5.34e-05 | 1.000 |
| S1-S3 | two-sided | caddy | default | S1 | max | 20 | 24.66 | [23.28, 26.40] | -0.272 | 0.000 | 1.91e-06 | 8.01e-05 | 1.000 |
| H3 | greater | caddy | default | S1 | max | 20 | 24.66 | [23.28, 26.40] | -0.272 | 210.000 | 9.54e-07 | 5.34e-05 | 1.000 |
| S1-S3 | two-sided | caddy | default | S2 | min | 20 | 1.40 | [0.71, 2.34] | -0.015 | 9.000 | 6.29e-05 | 4.41e-04 | 0.914 |
| H3 | greater | caddy | default | S2 | min | 20 | 1.40 | [0.71, 2.34] | -0.015 | 201.000 | 3.15e-05 | 8.50e-04 | 0.914 |
| S1-S3 | two-sided | caddy | default | S2 | max | 20 | 27.45 | [25.39, 29.33] | -0.303 | 0.000 | 1.91e-06 | 8.01e-05 | 1.000 |
| H3 | greater | caddy | default | S2 | max | 20 | 27.45 | [25.39, 29.33] | -0.303 | 210.000 | 9.54e-07 | 5.34e-05 | 1.000 |
| S1-S3 | two-sided | caddy | default | S3 | min | 20 | 0.37 | [-0.18, 0.88] | -0.004 | 57.000 | 0.0759 | 0.1517 | 0.457 |
| H3 | greater | caddy | default | S3 | min | 20 | 0.37 | [-0.18, 0.88] | -0.004 | 153.000 | 0.0379 | 0.8344 | 0.457 |
| S1-S3 | two-sided | caddy | default | S3 | max | 20 | 24.68 | [23.79, 25.87] | -0.269 | 0.000 | 1.91e-06 | 8.01e-05 | 1.000 |
| H3 | greater | caddy | default | S3 | max | 20 | 24.68 | [23.79, 25.87] | -0.269 | 210.000 | 9.54e-07 | 5.34e-05 | 1.000 |
| H1 | two-sided | netbox | default | S0 | min | 20 | -103.59 | [-109.12, -96.37] | 0.823 | 0.000 | 1.91e-06 | 2.67e-05 | -1.000 |
| H3 | greater | netbox | default | S0 | min | 20 | -103.59 | [-109.12, -96.37] | 0.823 | 0.000 | 1.0000 | 1.0000 | -1.000 |
| H1 | two-sided | netbox | default | S0 | max | 20 | -103.78 | [-108.97, -95.06] | 0.821 | 0.000 | 1.91e-06 | 2.67e-05 | -1.000 |
| H3 | greater | netbox | default | S0 | max | 20 | -103.78 | [-108.97, -95.06] | 0.821 | 0.000 | 1.0000 | 1.0000 | -1.000 |
| S1-S3 | two-sided | netbox | default | S1 | min | 20 | 4.78 | [4.00, 6.10] | -0.036 | 0.000 | 1.91e-06 | 8.01e-05 | 1.000 |
| H3 | greater | netbox | default | S1 | min | 20 | 4.78 | [4.00, 6.10] | -0.036 | 210.000 | 9.54e-07 | 5.34e-05 | 1.000 |
| S1-S3 | two-sided | netbox | default | S1 | max | 20 | -50.43 | [-53.02, -44.23] | 0.376 | 0.000 | 1.91e-06 | 8.01e-05 | -1.000 |
| H3 | greater | netbox | default | S1 | max | 20 | -50.43 | [-53.02, -44.23] | 0.376 | 0.000 | 1.0000 | 1.0000 | -1.000 |
| S1-S3 | two-sided | netbox | default | S2 | min | 20 | 6.19 | [5.62, 7.38] | -0.054 | 0.000 | 1.91e-06 | 8.01e-05 | 1.000 |
| H3 | greater | netbox | default | S2 | min | 20 | 6.19 | [5.62, 7.38] | -0.054 | 210.000 | 9.54e-07 | 5.34e-05 | 1.000 |
| S1-S3 | two-sided | netbox | default | S2 | max | 20 | 10.77 | [8.69, 12.78] | -0.093 | 0.000 | 1.91e-06 | 8.01e-05 | 1.000 |
| H3 | greater | netbox | default | S2 | max | 20 | 10.77 | [8.69, 12.78] | -0.093 | 210.000 | 9.54e-07 | 5.34e-05 | 1.000 |
| S1-S3 | two-sided | netbox | default | S3 | min | 20 | 5.46 | [5.07, 6.46] | -0.046 | 0.000 | 1.91e-06 | 8.01e-05 | 1.000 |
| H3 | greater | netbox | default | S3 | min | 20 | 5.46 | [5.07, 6.46] | -0.046 | 210.000 | 9.54e-07 | 5.34e-05 | 1.000 |
| S1-S3 | two-sided | netbox | default | S3 | max | 20 | 18.74 | [16.52, 20.88] | -0.161 | 0.000 | 1.91e-06 | 8.01e-05 | 1.000 |
| H3 | greater | netbox | default | S3 | max | 20 | 18.74 | [16.52, 20.88] | -0.161 | 210.000 | 9.54e-07 | 5.34e-05 | 1.000 |
| H1 | two-sided | synthetic | large-long | S0 | min | 20 | -76.20 | [-85.74, -67.50] | 0.871 | 0.000 | 1.91e-06 | 2.67e-05 | -1.000 |
| H3 | greater | synthetic | large-long | S0 | min | 20 | -76.20 | [-85.74, -67.50] | 0.871 | 0.000 | 1.0000 | 1.0000 | -1.000 |
| H1 | two-sided | synthetic | large-long | S0 | max | 20 | -76.82 | [-86.01, -69.41] | 0.871 | 0.000 | 1.91e-06 | 2.67e-05 | -1.000 |
| H3 | greater | synthetic | large-long | S0 | max | 20 | -76.82 | [-86.01, -69.41] | 0.871 | 0.000 | 1.0000 | 1.0000 | -1.000 |
| S1-S3 | two-sided | synthetic | large-long | S1 | min | 20 | 9.39 | [6.94, 11.75] | -0.081 | 0.000 | 1.91e-06 | 8.01e-05 | 1.000 |
| H3 | greater | synthetic | large-long | S1 | min | 20 | 9.39 | [6.94, 11.75] | -0.081 | 210.000 | 9.54e-07 | 5.34e-05 | 1.000 |
| S1-S3 | two-sided | synthetic | large-long | S1 | max | 20 | -33.87 | [-37.27, -31.10] | 0.264 | 1.000 | 3.81e-06 | 8.01e-05 | -0.990 |
| H3 | greater | synthetic | large-long | S1 | max | 20 | -33.87 | [-37.27, -31.10] | 0.264 | 1.000 | 1.0000 | 1.0000 | -0.990 |
| S1-S3 | two-sided | synthetic | large-long | S2 | min | 20 | 5.65 | [4.91, 7.94] | -0.042 | 1.000 | 3.81e-06 | 8.01e-05 | 0.990 |
| H3 | greater | synthetic | large-long | S2 | min | 20 | 5.65 | [4.91, 7.94] | -0.042 | 209.000 | 1.91e-06 | 5.72e-05 | 0.990 |
| S1-S3 | two-sided | synthetic | large-long | S2 | max | 20 | -11.07 | [-11.86, -10.08] | 0.084 | 0.000 | 1.91e-06 | 8.01e-05 | -1.000 |
| H3 | greater | synthetic | large-long | S2 | max | 20 | -11.07 | [-11.86, -10.08] | 0.084 | 0.000 | 1.0000 | 1.0000 | -1.000 |
| S1-S3 | two-sided | synthetic | large-long | S3 | min | 20 | 2.30 | [1.51, 4.73] | -0.017 | 10.000 | 8.20e-05 | 4.92e-04 | 0.905 |
| H3 | greater | synthetic | large-long | S3 | min | 20 | 2.30 | [1.51, 4.73] | -0.017 | 200.000 | 4.10e-05 | 0.0011 | 0.905 |
| S1-S3 | two-sided | synthetic | large-long | S3 | max | 20 | 21.54 | [19.48, 22.45] | -0.166 | 0.000 | 1.91e-06 | 8.01e-05 | 1.000 |
| H3 | greater | synthetic | large-long | S3 | max | 20 | 21.54 | [19.48, 22.45] | -0.166 | 210.000 | 9.54e-07 | 5.34e-05 | 1.000 |
| H1 | two-sided | synthetic | large-short | S0 | min | 20 | -12.50 | [-13.79, -11.54] | 0.544 | 0.000 | 1.91e-06 | 2.67e-05 | -1.000 |
| H3 | greater | synthetic | large-short | S0 | min | 20 | -12.50 | [-13.79, -11.54] | 0.544 | 0.000 | 1.0000 | 1.0000 | -1.000 |
| H1 | two-sided | synthetic | large-short | S0 | max | 20 | -12.39 | [-13.18, -9.78] | 0.539 | 0.000 | 1.91e-06 | 2.67e-05 | -1.000 |
| H3 | greater | synthetic | large-short | S0 | max | 20 | -12.39 | [-13.18, -9.78] | 0.539 | 0.000 | 1.0000 | 1.0000 | -1.000 |
| S1-S3 | two-sided | synthetic | large-short | S1 | min | 20 | 7.85 | [5.59, 8.57] | -0.332 | 0.000 | 1.91e-06 | 8.01e-05 | 1.000 |
| H3 | greater | synthetic | large-short | S1 | min | 20 | 7.85 | [5.59, 8.57] | -0.332 | 210.000 | 9.54e-07 | 5.34e-05 | 1.000 |
| S1-S3 | two-sided | synthetic | large-short | S1 | max | 20 | 15.10 | [13.18, 19.48] | -0.642 | 0.000 | 1.91e-06 | 8.01e-05 | 1.000 |
| H3 | greater | synthetic | large-short | S1 | max | 20 | 15.10 | [13.18, 19.48] | -0.642 | 210.000 | 9.54e-07 | 5.34e-05 | 1.000 |
| S1-S3 | two-sided | synthetic | large-short | S2 | min | 20 | 6.93 | [5.24, 7.52] | -0.293 | 1.000 | 3.81e-06 | 8.01e-05 | 0.990 |
| H3 | greater | synthetic | large-short | S2 | min | 20 | 6.93 | [5.24, 7.52] | -0.293 | 209.000 | 1.91e-06 | 5.72e-05 | 0.990 |
| S1-S3 | two-sided | synthetic | large-short | S2 | max | 20 | 16.59 | [15.73, 19.70] | -0.739 | 0.000 | 1.91e-06 | 8.01e-05 | 1.000 |
| H3 | greater | synthetic | large-short | S2 | max | 20 | 16.59 | [15.73, 19.70] | -0.739 | 210.000 | 9.54e-07 | 5.34e-05 | 1.000 |
| S1-S3 | two-sided | synthetic | large-short | S3 | min | 20 | -1.17 | [-2.28, 1.33] | 0.047 | 89.000 | 0.5706 | 0.5706 | -0.152 |
| H3 | greater | synthetic | large-short | S3 | min | 20 | -1.17 | [-2.28, 1.33] | 0.047 | 89.000 | 0.7271 | 1.0000 | -0.152 |
| S1-S3 | two-sided | synthetic | large-short | S3 | max | 20 | 15.44 | [13.98, 16.74] | -0.625 | 0.000 | 1.91e-06 | 8.01e-05 | 1.000 |
| H3 | greater | synthetic | large-short | S3 | max | 20 | 15.44 | [13.98, 16.74] | -0.625 | 210.000 | 9.54e-07 | 5.34e-05 | 1.000 |
| H1 | two-sided | synthetic | small-long | S0 | min | 20 | -105.12 | [-108.20, -98.14] | 0.958 | 0.000 | 1.91e-06 | 2.67e-05 | -1.000 |
| H3 | greater | synthetic | small-long | S0 | min | 20 | -105.12 | [-108.20, -98.14] | 0.958 | 0.000 | 1.0000 | 1.0000 | -1.000 |
| H1 | two-sided | synthetic | small-long | S0 | max | 20 | -104.97 | [-108.09, -97.93] | 0.958 | 0.000 | 1.91e-06 | 2.67e-05 | -1.000 |
| H3 | greater | synthetic | small-long | S0 | max | 20 | -104.97 | [-108.09, -97.93] | 0.958 | 0.000 | 1.0000 | 1.0000 | -1.000 |
| S1-S3 | two-sided | synthetic | small-long | S1 | min | 20 | 3.11 | [2.49, 4.15] | -0.027 | 6.000 | 2.67e-05 | 2.14e-04 | 0.943 |
| H3 | greater | synthetic | small-long | S1 | min | 20 | 3.11 | [2.49, 4.15] | -0.027 | 204.000 | 1.34e-05 | 3.74e-04 | 0.943 |
| S1-S3 | two-sided | synthetic | small-long | S1 | max | 20 | -53.61 | [-54.66, -50.69] | 0.447 | 0.000 | 1.91e-06 | 8.01e-05 | -1.000 |
| H3 | greater | synthetic | small-long | S1 | max | 20 | -53.61 | [-54.66, -50.69] | 0.447 | 0.000 | 1.0000 | 1.0000 | -1.000 |
| S1-S3 | two-sided | synthetic | small-long | S2 | min | 20 | 4.12 | [3.53, 4.61] | -0.036 | 0.000 | 1.91e-06 | 8.01e-05 | 1.000 |
| H3 | greater | synthetic | small-long | S2 | min | 20 | 4.12 | [3.53, 4.61] | -0.036 | 210.000 | 9.54e-07 | 5.34e-05 | 1.000 |
| S1-S3 | two-sided | synthetic | small-long | S2 | max | 20 | -23.78 | [-24.28, -21.60] | 0.199 | 0.000 | 1.91e-06 | 8.01e-05 | -1.000 |
| H3 | greater | synthetic | small-long | S2 | max | 20 | -23.78 | [-24.28, -21.60] | 0.199 | 0.000 | 1.0000 | 1.0000 | -1.000 |
| S1-S3 | two-sided | synthetic | small-long | S3 | min | 20 | 2.79 | [2.52, 3.40] | -0.029 | 0.000 | 1.91e-06 | 8.01e-05 | 1.000 |
| H3 | greater | synthetic | small-long | S3 | min | 20 | 2.79 | [2.52, 3.40] | -0.029 | 210.000 | 9.54e-07 | 5.34e-05 | 1.000 |
| S1-S3 | two-sided | synthetic | small-long | S3 | max | 20 | 6.00 | [5.37, 6.74] | -0.066 | 0.000 | 1.91e-06 | 8.01e-05 | 1.000 |
| H3 | greater | synthetic | small-long | S3 | max | 20 | 6.00 | [5.37, 6.74] | -0.066 | 210.000 | 9.54e-07 | 5.34e-05 | 1.000 |
| H1 | two-sided | synthetic | small-short | S0 | min | 20 | -4.36 | [-4.82, -3.96] | 0.511 | 0.000 | 1.91e-06 | 2.67e-05 | -1.000 |
| H3 | greater | synthetic | small-short | S0 | min | 20 | -4.36 | [-4.82, -3.96] | 0.511 | 0.000 | 1.0000 | 1.0000 | -1.000 |
| H1 | two-sided | synthetic | small-short | S0 | max | 20 | -3.95 | [-4.64, -3.78] | 0.444 | 0.000 | 1.91e-06 | 2.67e-05 | -1.000 |
| H3 | greater | synthetic | small-short | S0 | max | 20 | -3.95 | [-4.64, -3.78] | 0.444 | 0.000 | 1.0000 | 1.0000 | -1.000 |
| S1-S3 | two-sided | synthetic | small-short | S1 | min | 20 | 3.61 | [3.36, 3.78] | -0.471 | 0.000 | 1.91e-06 | 8.01e-05 | 1.000 |
| H3 | greater | synthetic | small-short | S1 | min | 20 | 3.61 | [3.36, 3.78] | -0.471 | 210.000 | 9.54e-07 | 5.34e-05 | 1.000 |
| S1-S3 | two-sided | synthetic | small-short | S1 | max | 20 | 2.14 | [1.71, 2.80] | -0.296 | 0.000 | 1.91e-06 | 8.01e-05 | 1.000 |
| H3 | greater | synthetic | small-short | S1 | max | 20 | 2.14 | [1.71, 2.80] | -0.296 | 210.000 | 9.54e-07 | 5.34e-05 | 1.000 |
| S1-S3 | two-sided | synthetic | small-short | S2 | min | 20 | 3.64 | [3.33, 3.98] | -0.474 | 0.000 | 1.91e-06 | 8.01e-05 | 1.000 |
| H3 | greater | synthetic | small-short | S2 | min | 20 | 3.64 | [3.33, 3.98] | -0.474 | 210.000 | 9.54e-07 | 5.34e-05 | 1.000 |
| S1-S3 | two-sided | synthetic | small-short | S2 | max | 20 | 3.96 | [3.58, 4.83] | -0.481 | 0.000 | 1.91e-06 | 8.01e-05 | 1.000 |
| H3 | greater | synthetic | small-short | S2 | max | 20 | 3.96 | [3.58, 4.83] | -0.481 | 210.000 | 9.54e-07 | 5.34e-05 | 1.000 |
| S1-S3 | two-sided | synthetic | small-short | S3 | min | 20 | 1.92 | [1.71, 2.46] | -0.276 | 20.000 | 7.08e-04 | 0.0028 | 0.810 |
| H3 | greater | synthetic | small-short | S3 | min | 20 | 1.92 | [1.71, 2.46] | -0.276 | 190.000 | 3.54e-04 | 0.0085 | 0.810 |
| S1-S3 | two-sided | synthetic | small-short | S3 | max | 20 | 5.17 | [4.51, 5.43] | -0.651 | 20.000 | 7.08e-04 | 0.0028 | 0.810 |
| H3 | greater | synthetic | small-short | S3 | max | 20 | 5.17 | [4.51, 5.43] | -0.651 | 190.000 | 3.54e-04 | 0.0085 | 0.810 |
| H1 | two-sided | uptime-kuma | default | S0 | min | 20 | -110.18 | [-137.51, -84.98] | 0.902 | 0.000 | 1.91e-06 | 2.67e-05 | -1.000 |
| H3 | greater | uptime-kuma | default | S0 | min | 20 | -110.18 | [-137.51, -84.98] | 0.902 | 0.000 | 1.0000 | 1.0000 | -1.000 |
| H1 | two-sided | uptime-kuma | default | S0 | max | 20 | -110.26 | [-137.69, -85.43] | 0.903 | 0.000 | 1.91e-06 | 2.67e-05 | -1.000 |
| H3 | greater | uptime-kuma | default | S0 | max | 20 | -110.26 | [-137.69, -85.43] | 0.903 | 0.000 | 1.0000 | 1.0000 | -1.000 |
| S1-S3 | two-sided | uptime-kuma | default | S1 | min | 20 | 4.55 | [2.91, 5.04] | -0.032 | 10.000 | 8.20e-05 | 4.92e-04 | 0.905 |
| H3 | greater | uptime-kuma | default | S1 | min | 20 | 4.55 | [2.91, 5.04] | -0.032 | 200.000 | 4.10e-05 | 0.0011 | 0.905 |
| S1-S3 | two-sided | uptime-kuma | default | S1 | max | 20 | -12.88 | [-15.11, -11.15] | 0.090 | 0.000 | 1.91e-06 | 8.01e-05 | -1.000 |
| H3 | greater | uptime-kuma | default | S1 | max | 20 | -12.88 | [-15.11, -11.15] | 0.090 | 0.000 | 1.0000 | 1.0000 | -1.000 |
| S1-S3 | two-sided | uptime-kuma | default | S2 | min | 20 | 3.46 | [3.02, 4.21] | -0.024 | 0.000 | 1.91e-06 | 8.01e-05 | 1.000 |
| H3 | greater | uptime-kuma | default | S2 | min | 20 | 3.46 | [3.02, 4.21] | -0.024 | 210.000 | 9.54e-07 | 5.34e-05 | 1.000 |
| S1-S3 | two-sided | uptime-kuma | default | S2 | max | 20 | 12.44 | [11.27, 14.15] | -0.086 | 0.000 | 1.91e-06 | 8.01e-05 | 1.000 |
| H3 | greater | uptime-kuma | default | S2 | max | 20 | 12.44 | [11.27, 14.15] | -0.086 | 210.000 | 9.54e-07 | 5.34e-05 | 1.000 |
| S1-S3 | two-sided | uptime-kuma | default | S3 | min | 20 | 5.78 | [5.03, 6.84] | -0.039 | 0.000 | 1.91e-06 | 8.01e-05 | 1.000 |
| H3 | greater | uptime-kuma | default | S3 | min | 20 | 5.78 | [5.03, 6.84] | -0.039 | 210.000 | 9.54e-07 | 5.34e-05 | 1.000 |
| S1-S3 | two-sided | uptime-kuma | default | S3 | max | 20 | 24.53 | [23.28, 25.71] | -0.165 | 0.000 | 1.91e-06 | 8.01e-05 | 1.000 |
| H3 | greater | uptime-kuma | default | S3 | max | 20 | 24.53 | [23.28, 25.71] | -0.165 | 210.000 | 9.54e-07 | 5.34e-05 | 1.000 |
| H2 | greater | caddy | default | S0-S3 | max | 80 | – | – | – | 0.567 | 2.03e-08 | 2.03e-08 | – |
| H2 | greater | caddy | default | S0-S3 | min | 80 | – | – | – | 0.907 | 2.36e-31 | 2.36e-30 | – |
| H2 | greater | netbox | default | S0-S3 | max | 80 | – | – | – | 0.959 | 1.27e-44 | 1.53e-43 | – |
| H2 | greater | netbox | default | S0-S3 | min | 80 | – | – | – | 0.750 | 5.87e-16 | 2.94e-15 | – |
| H2 | greater | synthetic | large-long | S0-S3 | max | 80 | – | – | – | 0.959 | 1.27e-44 | 1.53e-43 | – |
| H2 | greater | synthetic | large-long | S0-S3 | min | 80 | – | – | – | 0.824 | 2.81e-21 | 1.97e-20 | – |
| H2 | greater | synthetic | large-short | S0-S3 | max | 80 | – | – | – | 0.591 | 4.03e-09 | 8.05e-09 | – |
| H2 | greater | synthetic | large-short | S0-S3 | min | 80 | – | – | – | 0.905 | 5.86e-31 | 5.28e-30 | – |
| H2 | greater | synthetic | small-long | S0-S3 | max | 80 | – | – | – | 0.968 | 4.64e-49 | 6.50e-48 | – |
| H2 | greater | synthetic | small-long | S0-S3 | min | 80 | – | – | – | 0.628 | 2.16e-10 | 6.49e-10 | – |
| H2 | greater | synthetic | small-short | S0-S3 | max | 80 | – | – | – | 0.815 | 1.69e-20 | 1.02e-19 | – |
| H2 | greater | synthetic | small-short | S0-S3 | min | 80 | – | – | – | 0.836 | 2.26e-22 | 1.81e-21 | – |
| H2 | greater | uptime-kuma | default | S0-S3 | max | 80 | – | – | – | 0.968 | 4.64e-49 | 6.50e-48 | – |
| H2 | greater | uptime-kuma | default | S0-S3 | min | 80 | – | – | – | 0.750 | 5.87e-16 | 2.94e-15 | – |

## Hypothesis decisions (thesis, table 4)

| hypothesis | rule | tests evaluated | meeting rule | missing | supported |
|---|---|---|---|---|---|
| H1 | S0, min and max, every real project: median difference < 0 and p_holm < 0.05 (Wilcoxon two-sided) | 6 | 6 | 0 | True |
| H2 | max mode, every real project: Spearman rho(cache hit ratio, relative saving) > 0 and p_holm < 0.05 (one-sided) | 3 | 3 | 0 | True |
| H3 | at least one cell (any project, scenario, cache mode): median difference > 0 and p_holm < 0.05 (Wilcoxon one-sided greater) | 56 | 34 | 0 | True |
| H4 | among cells with a shorter cache build, at least one ra_star = dt / Dg within the r_a range of the price lists at the base runner price (4-core): [0, 9.313] runner minutes per GB | 21 | 9 | 0 | True |

## Cost model: break-even ratios (runner minutes per GB)

r_a range of the price lists at the base runner price: [0.000, 9.313]

| project | variant | scenario | mode | dt (min) | Dg (GB) | Mg (GB) | ra* | rt* n=10 | rt* n=100 | rt* n=1000 | ra* in range (base / paid / all) | note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| caddy | default | S0 | min | 1.356 | 0.036 | 0.066 | 37.21 | 204.6 | 2046.2 | 20462.3 | False / False / True |  |
| caddy | default | S0 | max | 1.351 | 0.036 | 0.932 | 37.08 | 14.5 | 145.1 | 1450.6 | False / False / True |  |
| caddy | default | S1 | min | -0.097 | 0.016 | 0.066 | – | – | – | – | – / – / – | cache build not shorter (dt <= 0): no break-even, the cache is dearer at any price |
| caddy | default | S1 | max | -0.411 | 0.374 | 0.932 | – | – | – | – | – / – / – | cache build not shorter (dt <= 0): no break-even, the cache is dearer at any price |
| caddy | default | S2 | min | -0.023 | 0.036 | 0.066 | – | – | – | – | – / – / – | cache build not shorter (dt <= 0): no break-even, the cache is dearer at any price |
| caddy | default | S2 | max | -0.458 | 0.036 | 0.932 | – | – | – | – | – / – / – | cache build not shorter (dt <= 0): no break-even, the cache is dearer at any price |
| caddy | default | S3 | min | -0.006 | 0.036 | 0.066 | – | – | – | – | – / – / – | cache build not shorter (dt <= 0): no break-even, the cache is dearer at any price |
| caddy | default | S3 | max | -0.411 | 0.036 | 0.932 | – | – | – | – | – / – / – | cache build not shorter (dt <= 0): no break-even, the cache is dearer at any price |
| netbox | default | S0 | min | 1.727 | 0.142 | 0.188 | 12.13 | 91.6 | 915.9 | 9159.2 | False / False / True |  |
| netbox | default | S0 | max | 1.730 | 0.142 | 0.445 | 12.16 | 38.9 | 388.9 | 3889.1 | False / False / True |  |
| netbox | default | S1 | min | -0.080 | 0.001 | 0.188 | – | – | – | – | – / – / – | cache build not shorter (dt <= 0): no break-even, the cache is dearer at any price |
| netbox | default | S1 | max | 0.841 | 0.288 | 0.445 | 2.92 | 18.9 | 189.0 | 1889.8 | True / False / True |  |
| netbox | default | S2 | min | -0.103 | 0.001 | 0.188 | – | – | – | – | – / – / – | cache build not shorter (dt <= 0): no break-even, the cache is dearer at any price |
| netbox | default | S2 | max | -0.179 | 0.118 | 0.445 | – | – | – | – | – / – / – | cache build not shorter (dt <= 0): no break-even, the cache is dearer at any price |
| netbox | default | S3 | min | -0.091 | 0.001 | 0.188 | – | – | – | – | – / – / – | cache build not shorter (dt <= 0): no break-even, the cache is dearer at any price |
| netbox | default | S3 | max | -0.312 | 0.001 | 0.445 | – | – | – | – | – / – / – | cache build not shorter (dt <= 0): no break-even, the cache is dearer at any price |
| synthetic | large-long | S0 | min | 1.270 | 0.269 | 0.315 | 4.73 | 40.3 | 403.5 | 4035.0 | True / False / True |  |
| synthetic | large-long | S0 | max | 1.280 | 0.269 | 1.389 | 4.77 | 9.2 | 92.2 | 921.7 | True / False / True |  |
| synthetic | large-long | S1 | min | -0.156 | 0.000 | 0.315 | – | – | – | – | – / – / – | cache build not shorter (dt <= 0): no break-even, the cache is dearer at any price |
| synthetic | large-long | S1 | max | 0.564 | 0.537 | 1.389 | 1.05 | 4.1 | 40.6 | 406.3 | True / False / True |  |
| synthetic | large-long | S2 | min | -0.094 | 0.000 | 0.315 | – | – | – | – | – / – / – | cache build not shorter (dt <= 0): no break-even, the cache is dearer at any price |
| synthetic | large-long | S2 | max | 0.185 | 0.269 | 1.389 | 0.69 | 1.3 | 13.3 | 132.9 | True / False / True |  |
| synthetic | large-long | S3 | min | -0.038 | 0.269 | 0.315 | – | – | – | – | – / – / – | cache build not shorter (dt <= 0): no break-even, the cache is dearer at any price |
| synthetic | large-long | S3 | max | -0.359 | 0.269 | 1.389 | – | – | – | – | – / – / – | cache build not shorter (dt <= 0): no break-even, the cache is dearer at any price |
| synthetic | large-short | S0 | min | 0.208 | 0.269 | 0.315 | 0.78 | 6.6 | 66.2 | 661.8 | True / False / True |  |
| synthetic | large-short | S0 | max | 0.207 | 0.269 | 1.389 | 0.77 | 1.5 | 14.9 | 148.7 | True / False / True |  |
| synthetic | large-short | S1 | min | -0.131 | 0.000 | 0.315 | – | – | – | – | – / – / – | cache build not shorter (dt <= 0): no break-even, the cache is dearer at any price |
| synthetic | large-short | S1 | max | -0.252 | 0.537 | 1.389 | – | – | – | – | – / – / – | cache build not shorter (dt <= 0): no break-even, the cache is dearer at any price |
| synthetic | large-short | S2 | min | -0.116 | 0.000 | 0.315 | – | – | – | – | – / – / – | cache build not shorter (dt <= 0): no break-even, the cache is dearer at any price |
| synthetic | large-short | S2 | max | -0.276 | 0.269 | 1.389 | – | – | – | – | – / – / – | cache build not shorter (dt <= 0): no break-even, the cache is dearer at any price |
| synthetic | large-short | S3 | min | 0.020 | 0.269 | 0.315 | 0.07 | 0.6 | 6.2 | 62.2 | True / False / True |  |
| synthetic | large-short | S3 | max | -0.257 | 0.269 | 1.389 | – | – | – | – | – / – / – | cache build not shorter (dt <= 0): no break-even, the cache is dearer at any price |
| synthetic | small-long | S0 | min | 1.752 | 0.001 | 0.047 | 1669.65 | 370.6 | 3706.2 | 37062.1 | False / False / False |  |
| synthetic | small-long | S0 | max | 1.749 | 0.001 | 0.051 | 1667.26 | 345.0 | 3449.6 | 34495.6 | False / False / False |  |
| synthetic | small-long | S1 | min | -0.052 | 0.000 | 0.047 | – | – | – | – | – / – / – | cache build not shorter (dt <= 0): no break-even, the cache is dearer at any price |
| synthetic | small-long | S1 | max | 0.893 | 0.002 | 0.051 | 373.24 | 176.2 | 1761.7 | 17617.1 | False / False / False |  |
| synthetic | small-long | S2 | min | -0.069 | 0.000 | 0.047 | – | – | – | – | – / – / – | cache build not shorter (dt <= 0): no break-even, the cache is dearer at any price |
| synthetic | small-long | S2 | max | 0.396 | 0.001 | 0.051 | 294.82 | 78.1 | 781.5 | 7814.8 | False / False / False |  |
| synthetic | small-long | S3 | min | -0.047 | 0.001 | 0.047 | – | – | – | – | – / – / – | cache build not shorter (dt <= 0): no break-even, the cache is dearer at any price |
| synthetic | small-long | S3 | max | -0.100 | 0.001 | 0.052 | – | – | – | – | – / – / – | cache build not shorter (dt <= 0): no break-even, the cache is dearer at any price |
| synthetic | small-short | S0 | min | 0.073 | 0.001 | 0.047 | 69.24 | 15.4 | 153.7 | 1536.9 | False / False / False |  |
| synthetic | small-short | S0 | max | 0.066 | 0.001 | 0.051 | 62.69 | 13.0 | 129.7 | 1297.1 | False / False / False |  |
| synthetic | small-short | S1 | min | -0.060 | 0.000 | 0.047 | – | – | – | – | – / – / – | cache build not shorter (dt <= 0): no break-even, the cache is dearer at any price |
| synthetic | small-short | S1 | max | -0.036 | 0.002 | 0.051 | – | – | – | – | – / – / – | cache build not shorter (dt <= 0): no break-even, the cache is dearer at any price |
| synthetic | small-short | S2 | min | -0.061 | 0.000 | 0.047 | – | – | – | – | – / – / – | cache build not shorter (dt <= 0): no break-even, the cache is dearer at any price |
| synthetic | small-short | S2 | max | -0.066 | 0.001 | 0.051 | – | – | – | – | – / – / – | cache build not shorter (dt <= 0): no break-even, the cache is dearer at any price |
| synthetic | small-short | S3 | min | -0.032 | 0.001 | 0.047 | – | – | – | – | – / – / – | cache build not shorter (dt <= 0): no break-even, the cache is dearer at any price |
| synthetic | small-short | S3 | max | -0.086 | 0.001 | 0.052 | – | – | – | – | – / – / – | cache build not shorter (dt <= 0): no break-even, the cache is dearer at any price |
| uptime-kuma | default | S0 | min | 1.836 | 0.043 | 0.115 | 43.19 | 159.0 | 1590.1 | 15901.1 | False / False / True |  |
| uptime-kuma | default | S0 | max | 1.838 | 0.043 | 0.411 | 43.23 | 44.7 | 447.1 | 4471.2 | False / False / True |  |
| uptime-kuma | default | S1 | min | -0.076 | 0.000 | 0.115 | – | – | – | – | – / – / – | cache build not shorter (dt <= 0): no break-even, the cache is dearer at any price |
| uptime-kuma | default | S1 | max | 0.215 | 0.287 | 0.411 | 0.75 | 5.2 | 52.2 | 522.1 | True / False / True |  |
| uptime-kuma | default | S2 | min | -0.058 | 0.000 | 0.115 | – | – | – | – | – / – / – | cache build not shorter (dt <= 0): no break-even, the cache is dearer at any price |
| uptime-kuma | default | S2 | max | -0.207 | 0.116 | 0.411 | – | – | – | – | – / – / – | cache build not shorter (dt <= 0): no break-even, the cache is dearer at any price |
| uptime-kuma | default | S3 | min | -0.096 | 0.000 | 0.115 | – | – | – | – | – / – / – | cache build not shorter (dt <= 0): no break-even, the cache is dearer at any price |
| uptime-kuma | default | S3 | max | -0.409 | 0.000 | 0.411 | – | – | – | – | – / – / – | cache build not shorter (dt <= 0): no break-even, the cache is dearer at any price |
