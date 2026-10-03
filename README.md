# BuildKit registry cache in ephemeral CI — replication package

Measurement harness, raw data and analysis scripts for the BSc thesis
experiment (Corvinus University of Budapest, Business Informatics):

> When does it pay off to download earlier BuildKit results from a remote cache
> (registry backend) instead of rebuilding them, in an ephemeral CI environment,
> considering both build time and money?

- **H1** With unchanged inputs, a build using the registry cache is significantly shorter than a build without cache.
- **H2** The time saved is smaller the earlier the modification invalidates the cache (the fewer steps are reusable).
- **H3** For at least one modification pattern, the build with registry cache is significantly *longer* than without cache, because cache import + export overhead exceeds the avoided work.
- **H4** In a parametric cost model (runner minutes + registry storage + data transfer) there is a break-even ratio of storage/transfer prices to the runner per-minute price above which the cache costs more despite the shorter build, and this point lies within the range of public price lists.

The facts of the measured runs (versions, digests, run IDs, results) are in
[`METHODS_FACTS.md`](METHODS_FACTS.md).

## Environment

- GitHub-hosted `ubuntu-24.04` standard runners of this public repository; registry: ghcr.io only.
- *Ephemeral* means: when a build starts, no local BuildKit state from an earlier build is available.
  Every measured build therefore runs in a newly created `docker-container` builder, started with
  `--bootstrap` before the clock starts (its start-up time is recorded as `builder_create_s`); the runner checks
  that `docker buildx du` reports no records and `Total: 0B` (`empty_check`) and removes the builder
  with its state afterwards (`builder_removed`).
- Pinned: Buildx (binary checksum), the BuildKit image and every base image by digest
  ([`pins.json`](pins.json)). The `mirror` job copies them once into `ghcr.io/<owner>/<repo>/mirror/...`
  (byte-identical manifests, so mirror digest = upstream digest) and all builds use the mirrors.

## Design

| Factor | Levels |
|---|---|
| Cache mode M | `none` (no cache flags), `min` and `max` (`--cache-from type=registry,ref=<seed>` + `--cache-to type=registry,ref=<out>,mode=min\|max`) |
| Scenario S | S0 no change; S1 late change (comment appended to a source file copied after the dependency install); S2 dependency manifest checksum change (same resolved dependencies); S3 early change (first `RUN` of the builder stage) |
| Project P | Uptime Kuma 1.23.17 (Node.js/npm), NetBox v4.7.2 (Python/pip), Caddy v2.11.7 (Go modules), synthetic (4 variants) |

All Dockerfiles ([`projects/`](projects)) are multi-stage in the canonical cache-friendly order
(builder: OS packages → manifests → dependency install → source → build; runtime: base → artifacts).
The synthetic project chains four work steps that each burn a fixed number of SHA-256 iterations and write
a fixed amount of seeded incompressible data, so compute time and layer size vary independently
(`projects/synthetic/project.json`).

Each job (one fresh VM per project × variant × scenario × shard) runs [`harness/run_job.py`](harness/run_job.py):

1. clone the pinned release tag and verify the commit;
2. **seed**: build the unmodified tree once per cache mode (`min`, `max`, random order) in a fresh builder,
   exporting to job-unique seed refs `ghcr.io/<owner>/<repo>/cache:<project>-<variant>-<scenario>-<run>-<attempt>-<shard>-seed-<mode>`;
3. apply the scenario modification;
4. **K trials**: `none`, `min`, `max` in random order (seeded RNG; `order_pos` recorded), each in a fresh builder;
   cache modes import from the seed ref and export to a per-trial ref `...-t<k>-<mode>`, so the seed stays identical.

All builds use the same output, `--output type=docker` (the image is loaded into the runner's Docker
engine and then deleted, never pushed), and `--provenance=false --sbom=false`, so only cache traffic
differs between modes. Default: 4 jobs × K = 5 → N = 20 per (project, variant, scenario, mode).

Expected cache behaviour is declared per project (`expect` in `project.json`) and checked for every build
(`expected_cached_steps` vs `cached_steps`); a mismatch flags the build (`cache_behaviour_mismatch`).
Observed with BuildKit v0.33.1 and encoded in [`harness/scenario.py`](harness/scenario.py):
`max` reuses every builder step before the invalidation point; `min` stores results only for the final
image, so builder steps are reused only in S0; runtime-stage `COPY --from` steps are content-addressed
(cached whenever the copied files are byte-identical); `FROM` vertices are never reported as cached and
are not counted.

## Running

Actions → `measure` → *Run workflow* (`workflow_dispatch`), inputs `projects`, `scenarios`, `shards`,
`trials`. Jobs: `plan` (matrix in a fixed pseudo-random order), `mirror`, `measure` (max-parallel 16,
within the 20 concurrent jobs of the free plan), `aggregate` (merge + analysis; uploads the `results`
artifact and pushes it as `ghcr.io/<owner>/<repo>/results:run-<id>-<attempt>`).

Re-running the analysis locally (Python ≥ 3.12):

```sh
python3 -m venv .venv && .venv/bin/pip install -r analysis/requirements.txt
.venv/bin/python analysis/merge.py      # results/raw/*.jsonl -> results/results.csv (stdlib)
.venv/bin/python analysis/analyze.py    # summary_by_cell.csv, pairs.csv, tests.csv
.venv/bin/python analysis/cost_model.py # cost_breakeven.csv, cost_by_price.csv, H4 (prices: analysis/prices.json)
python3 analysis/facts.py               # results/facts.md
python3 -m unittest discover -s tests   # harness unit tests (stdlib)
```

## Outputs

| File | Content |
|---|---|
| `results/raw/*.jsonl` | one JSON object per build (all fields, including per-step durations) |
| `results/results.csv` | the same, one row per build (bulky fields dropped) |
| `results/summary_by_cell.csv` | per phase × project × variant × scenario × mode: n, failures, flags, wall_s median/IQR, medians of the diagnostics |
| `results/pairs.csv` | one row per trial: none/min/max side by side |
| `results/tests.csv` | Wilcoxon signed-rank tests, bootstrap CIs, rank-biserial effect sizes, Spearman (H2), Holm-adjusted p-values |
| `results/hypotheses.csv` | decision for H1–H4 by the pre-registered rules below |
| `results/cost_breakeven.csv` | break-even ratios per project × variant × scenario × mode |
| `results/cost_by_price.csv` | cost per build for every registry price list × runner price × builds per month |
| `results/facts.md` | tables for `METHODS_FACTS.md`, generated by `analysis/facts.py` |

### Analysis and decision rules

Pairs: the none/min/max builds of the same trial; d = wall_s(mode) − wall_s(none).

| Hypothesis | Test (Holm within the family) | Supported if |
|---|---|---|
| H1 | S0 cells, Wilcoxon signed-rank, two-sided | in both cache modes and every real project: median d < 0 and p_holm < 0.05 |
| H2 | per project × variant × mode, Spearman ρ(cache hit ratio, (none − mode)/none) over the trials of S0–S3, one-sided | in max mode, every real project: ρ > 0 and p_holm < 0.05 |
| H3 | all cells, Wilcoxon signed-rank, one-sided "greater" | at least one cell: median d > 0 and p_holm < 0.05 |
| H4 | cost model, cells with a shorter cache build | at least one cell: r_a* within the range of the price lists' r_a at the base runner price |

Effect sizes: median d with a percentile-bootstrap 95% CI (10,000 resamples, fixed seed) and the
matched-pairs rank-biserial correlation. Two-sided tests of the S1–S3 cells are reported as a
supplementary family without a decision.

### Cost model

`analysis/cost_model.py`, prices in [`analysis/prices.json`](analysis/prices.json) (thesis table 3, as of 2026-10-03):

K = t·p_v + D·p_a + M·p_t / n, with t the build time in minutes, D the cache data downloaded
(rawjson layer downloads of cache blobs, base-image layers excluded), M the cache size
(`cache_bytes`), n the builds per month sharing the cache (10, 100, 1000). Uploads are not priced.
The cache is cheaper iff (t0 − tg)·p_v > Dg·p_a + Mg·p_t / n; the break-even ratios are
r_a* = (t0 − tg) / Dg (storage neglected) and r_t* = (t0 − tg)·n / Mg (download neglected), in
runner minutes per GB (per GB-month). Without a shorter cache build there is no break-even point.

Missing values are empty cells / JSON `null`, never 0; `null_reasons` says why.

### Main fields of a build record

| Field | Meaning |
|---|---|
| `wall_s` | **primary outcome**: duration of the `docker buildx build` command (monotonic clock), including cache import and export |
| `phase`, `trial`, `order_pos` | `seed`/`measured`, trial number (0 for seeds), position of the mode within the trial |
| `empty_check`, `du_records`, `du_total` | result of the empty-cache check of the fresh builder |
| `n_vertices`, `n_cached`, `cache_hit_ratio` | Dockerfile step vertices without `FROM`, those reported CACHED, ratio |
| `expected_n_cached`, `expected_cached_steps`, `cached_steps` | declared vs observed reusable steps |
| `import_s` | duration of the `importing cache manifest from …` vertex (layer downloads happen later, inside the steps) |
| `export_cache_s` (+ `export_prepare_s`, `export_write_layers_s`, `export_write_manifest_s`) | `exporting cache to registry` vertex and the spans of its sub-statuses |
| `export_image_s` | span of the image export / load into Docker |
| `exec_run_s` | summed duration of the executed (non-cached) `RUN` steps |
| `net_rx_bytes`, `net_tx_bytes` | rx/tx delta of the default-route interface around the build (includes package downloads and protocol overhead); used as a cross-check |
| `pull_base_bytes`, `pull_cache_bytes` (`pulled_base_blobs`, `pulled_cache_blobs`) | layer bytes downloaded during the build, summed from the rawjson layer-download statuses: base-image blobs vs. cache blobs (every other pulled blob comes from the imported cache) |
| `cache_bytes`, `cache_bytes_excl_base`, `cache_blobs` | unique blob bytes referenced by the exported cache manifest (read back from ghcr.io), without base-image blobs, blob count |
| `image_size_bytes` | size of the loaded final image (`docker image inspect`) |
| `flags` | `build_failed`, `cache_not_empty`, `cache_behaviour_mismatch`, `step_list_mismatch`, `import_vertex_missing`, `export_vertex_missing`, `seed_failed`, `builder_not_removed`, `builder_create_failed` |
| `valid` | exit code 0 and no flag; only valid builds enter the statistics |
