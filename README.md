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
  Every measured build therefore runs in a newly created `docker-container` builder; the runner checks
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
.venv/bin/python analysis/cost_model.py # cost_breakeven.csv (prices: analysis/prices.json)
python3 -m unittest discover -s tests   # harness unit tests (stdlib)
```

## Outputs

| File | Content |
|---|---|
| `results/raw/*.jsonl` | one JSON object per build (all fields, including per-step durations) |
| `results/results.csv` | the same, one row per build (bulky fields dropped) |
| `results/summary_by_cell.csv` | per phase × project × variant × scenario × mode: n, failures, flags, wall_s median/IQR, medians of the diagnostics |
| `results/pairs.csv` | one row per trial: none/min/max side by side |
| `results/tests.csv` | Wilcoxon signed-rank tests, bootstrap CIs, rank-biserial effect sizes, Spearman trend, Holm-adjusted p-values |
| `results/cost_breakeven.csv` | cost model and break-even ratios per project × variant × scenario × mode × price scenario |

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
| `net_rx_bytes`, `net_tx_bytes` | rx/tx delta of the default-route interface around the build (includes package downloads and protocol overhead) |
| `pull_base_bytes`, `pull_other_bytes` | blob bytes pulled from the registry (rawjson statuses), split into base-image blobs and other (cache) blobs |
| `cache_bytes`, `cache_bytes_excl_base`, `cache_blobs` | unique blob bytes referenced by the exported cache manifest (read back from ghcr.io), without base-image blobs, blob count |
| `image_size_bytes` | size of the loaded final image (`docker image inspect`) |
| `flags` | `build_failed`, `cache_not_empty`, `cache_behaviour_mismatch`, `step_list_mismatch`, `import_vertex_missing`, `export_vertex_missing`, `seed_failed`, `builder_not_removed`, `builder_create_failed` |
| `valid` | exit code 0 and no flag; only valid builds enter the statistics |
