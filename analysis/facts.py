#!/usr/bin/env python3
"""Render the factual tables for METHODS_FACTS.md from the results (stdlib only) -> results/facts.md.

Every number is read from results/ and the repository; nothing is typed by hand.
"""
import argparse
import csv
import glob
import json
import os
import statistics
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "harness"))
import scenario  # noqa: E402

MODES = ("none", "min", "max")


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def num(value):
    return float(value) if value not in (None, "") else None


def fmt(value, digits=1):
    return "–" if value in (None, "") else f"{float(value):.{digits}f}"


def mb(value):
    return "–" if value in (None, "") else f"{float(value) / 1e6:.1f}"


def pvalue(value):
    if value in (None, ""):
        return "–"
    value = float(value)
    return f"{value:.2e}" if value < 0.001 else f"{value:.4f}"


def table(header, rows):
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def counts(values):
    return ", ".join(f"{value} ({count})" for value, count in Counter(values).most_common())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default=os.path.join(ROOT, "results"))
    args = parser.parse_args()
    rows = read_csv(os.path.join(args.results, "results.csv"))
    summary = read_csv(os.path.join(args.results, "summary_by_cell.csv"))
    tests = read_csv(os.path.join(args.results, "tests.csv"))
    raw = []
    for path in sorted(glob.glob(os.path.join(args.results, "raw", "*.jsonl"))):
        with open(path, encoding="utf-8") as fh:
            raw += [json.loads(line) for line in fh if line.strip()]
    with open(os.path.join(ROOT, "pins.json"), encoding="utf-8") as fh:
        pins = json.load(fh)
    out = []

    out.append("## Runs\n")
    runs = defaultdict(list)
    for row in rows:
        runs[(row["run_id"], row["run_attempt"], row["harness_commit"])].append(row["utc_start"])
    out.append(table(["run_id", "attempt", "harness commit", "builds", "first build (UTC)", "last build (UTC)"],
                     [(r, a, c, len(t), min(x for x in t if x), max(x for x in t if x))
                      for (r, a, c), t in sorted(runs.items())]))

    out.append("\n## Versions\n")
    out.append(table(["item", "value (count of builds)"], [
        ("Buildx", counts(r.get("buildx_version") for r in rows)),
        ("BuildKit (builder inspect)", counts(r.get("buildkit_version") for r in rows)),
        ("BuildKit image", counts(r.get("buildkit_image") for r in rows)),
        ("Runner image (ImageOS / ImageVersion)", counts(f"{r['image_os']} / {r['image_version']}" for r in rows)),
        ("CPU model", counts(r.get("cpu_model") for r in rows)),
        ("vCPUs", counts(r.get("vcpus") for r in rows)),
        ("RAM bytes", counts(r.get("ram_bytes") for r in rows)),
        ("Kernel", counts(r.get("kernel") for r in rows)),
        ("Docker Engine / storage driver", counts(f"{r['docker_server_version']} / {r['docker_storage_driver']}"
                                                  for r in rows)),
        ("Cache export options", counts(r.get("cache_to_options").split(",", 2)[0] + ",mode=" + r.get("mode")
                                        for r in rows if r.get("cache_to_options"))),
        ("Cache manifest media type", counts(r.get("cache_manifest_media_type") for r in rows
                                             if r.get("cache_manifest_media_type"))),
    ]))
    out.append("\nPinned images (linux/amd64 manifest digests, mirrored byte-for-byte to ghcr.io):\n")
    out.append(table(["mirror name", "upstream", "tag", "digest"],
                     [(n, i["source"], i["tag"], f"`{i['digest']}`") for n, i in sorted(pins["images"].items())]))
    out.append(f"\nBuildx binary {pins['buildx']['version']} sha256 `{pins['buildx']['binary_sha256']}`.")

    out.append("\n## Projects and expected vs observed reusable steps\n")
    observed = defaultdict(list)
    for row in rows:
        if row["phase"] == "measured" and row["exit_code"] == "0":
            observed[(row["project"], row["variant"], row["scenario"], row["mode"])].append(
                (int(float(row["n_cached"])), int(float(row["expected_n_cached"]))))
    for project in sorted({r["project"] for r in rows}):
        with open(os.path.join(ROOT, "projects", project, "project.json"), encoding="utf-8") as fh:
            config = json.load(fh)
        with open(os.path.join(ROOT, "projects", project, config["dockerfile"]), encoding="utf-8") as fh:
            steps = scenario.steps(fh.read())
        source = config["source"]
        out.append(f"\n### {project} ({config['ecosystem']})\n")
        if "git" in source:
            out.append(f"Source: {source['git']} tag `{source['tag']}` commit `{source['commit']}`.\n")
        invalidated = config["expect"]["invalidated_from"]
        out.append(table(["stage", "step", "instruction", "first invalidated by"], [
            (s["stage"], f"{s['index']}/{s['count']}", f"`{s['text'][:90]}`",
             ", ".join(sc for sc, i in sorted(invalidated.items())
                       if s["stage"] == config["expect"]["builder_stage"] and i == s["index"])
             or ", ".join(sc for sc, i in sorted(config["expect"]["other_stages"].get(s["stage"], {}).items())
                          if i == s["index"]))
            for s in steps]))
        out.append("\nReusable (CACHED) steps, FROM excluded — expected / observed (min–max over valid builds):\n")
        variants = sorted({r["variant"] for r in rows if r["project"] == project})
        body = []
        for variant in variants:
            for scen in ("S0", "S1", "S2", "S3"):
                cells = []
                for mode in MODES:
                    data = observed.get((project, variant, scen, mode))
                    if not data:
                        cells.append("–")
                        continue
                    exp = sorted({e for _, e in data})
                    obs = [o for o, _ in data]
                    cells.append(f"{'/'.join(map(str, exp))} / {min(obs)}–{max(obs)}")
                body.append((variant, scen, *cells))
        out.append(table(["variant", "scenario", "none", "min", "max"], body))

    out.append("\n## Synthetic variants\n")
    with open(os.path.join(ROOT, "projects", "synthetic", "project.json"), encoding="utf-8") as fh:
        synthetic = json.load(fh)
    cpu = defaultdict(list)
    for record in raw:
        for step in record.get("synthetic_steps") or []:
            cpu[record["variant"]].append(step["cpu_s"])
    out.append(table(["variant", "bytes per step", "SHA-256 iterations per step", "work steps",
                      "observed CPU s per step (median, min–max)"],
                     [(v, p["build_args"]["LAYER_BYTES"], p["build_args"]["CPU_ITERS"], 4,
                       f"{statistics.median(cpu[v]):.2f} ({min(cpu[v]):.2f}–{max(cpu[v]):.2f})" if cpu[v] else "–")
                      for v, p in synthetic["variants"].items()]))

    out.append("\n## Executed plan\n")
    measured = [r for r in rows if r["phase"] == "measured"]
    jobs = {(r["run_id"], r["run_attempt"], r["project"], r["variant"], r["scenario"], r["shard"]) for r in rows}
    out.append(f"- jobs with results: {len(jobs)}; builds: {len(rows)} "
               f"({sum(r['phase'] == 'seed' for r in rows)} seed, {len(measured)} measured)")
    out.append(f"- trials per job: {counts(r['trials_per_job'] for r in rows)}")
    per_cell = Counter((r["project"], r["variant"], r["scenario"], r["mode"]) for r in measured)
    out.append(f"- measured builds per cell (project × variant × scenario × mode): {counts(per_cell.values())}")
    flags = Counter(f for r in rows for f in json.loads(r["flags"] or "[]"))
    out.append(f"- failed builds (exit ≠ 0): {sum(r['exit_code'] != '0' for r in rows)}; "
               f"flagged builds: {sum(bool(json.loads(r['flags'] or '[]')) for r in rows)}; flags: {dict(flags)}")
    out.append(f"- empty-cache check passed: {sum(r['empty_check'] == 'True' for r in rows)} of {len(rows)}; "
               f"builder removed: {sum(r['builder_removed'] == 'True' for r in rows)} of {len(rows)}")
    bad = [r for r in rows if r["valid"] != "True"]
    if bad:
        out.append("\nFailed or flagged builds:\n")
        out.append(table(["run", "project/variant", "scenario", "shard", "phase", "trial", "mode", "exit", "flags",
                          "detail"],
                         [(r["run_id"], f"{r['project']}/{r['variant']}", r["scenario"], r["shard"], r["phase"],
                           r["trial"], r["mode"], r["exit_code"], r["flags"],
                           (r.get("cache_behaviour_diff") or r["error_text"] or "")[:160].replace("|", "/")
                           .replace("\n", " ")) for r in bad]))

    out.append("\n## Per cell (valid measured builds)\n")
    by = {(s["phase"], s["project"], s["variant"], s["scenario"], s["mode"]): s for s in summary}
    body = []
    for key in sorted({k[1:4] for k in by if k[0] == "measured"}):
        for mode in MODES:
            s = by.get(("measured",) + key + (mode,))
            if not s:
                continue
            body.append((*key, mode, s["n_valid"], fmt(s["wall_s_median"]),
                         f"{fmt(s['wall_s_q1'])}–{fmt(s['wall_s_q3'])}", fmt(s["import_s_median"], 2),
                         fmt(s["export_cache_s_median"], 2), mb(s["cache_bytes_median"]),
                         mb(s["cache_bytes_excl_base_median"]), mb(s["net_rx_bytes_median"]),
                         mb(s["net_tx_bytes_median"]), mb(s["pull_other_bytes_median"])))
    out.append(table(["project", "variant", "scenario", "mode", "n", "wall_s median", "wall_s IQR (q1–q3)",
                      "import_s", "export_cache_s", "cache MB", "cache MB excl. base", "rx MB", "tx MB",
                      "cache blobs pulled MB"], body))
    seeds = []
    for key in sorted({k[1:4] for k in by if k[0] == "seed"}):
        for mode in ("min", "max"):
            s = by.get(("seed",) + key + (mode,))
            if s:
                seeds.append((*key, mode, s["n_valid"], fmt(s["wall_s_median"]), fmt(s["export_cache_s_median"], 2),
                              mb(s["cache_bytes_median"]), mb(s["net_tx_bytes_median"])))
    out.append("\nSeed builds (cold build + cache export):\n")
    out.append(table(["project", "variant", "job scenario", "mode", "n", "wall_s median", "export_cache_s",
                      "cache MB", "tx MB"], seeds))

    out.append("\n## Tests\n")
    out.append("d = wall_s(mode) − wall_s(none) per trial; CI = percentile bootstrap 95% of the median; "
               "r = matched-pairs rank-biserial (positive: cache slower); p_holm within the family.\n")
    out.append(table(["family", "alt.", "project", "variant", "scenario", "mode", "n", "median d (s)", "95% CI",
                      "rel. saving", "W / rho", "p", "p_holm", "r"],
                     [(t["family"], t["alternative"], t["project"], t["variant"], t["scenario"], t["mode"],
                       t["n_pairs"], fmt(t["median_diff_s"], 2),
                       f"[{fmt(t['ci95_low_s'], 2)}, {fmt(t['ci95_high_s'], 2)}]" if t["ci95_low_s"] else "–",
                       fmt(t["median_rel_saving"], 3), fmt(t["statistic"], 3), pvalue(t["p_value"]),
                       pvalue(t["p_holm"]), fmt(t["effect_rank_biserial"], 3)) for t in tests]))

    path = os.path.join(args.results, "facts.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")
    print(f"-> {path}")


if __name__ == "__main__":
    main()
