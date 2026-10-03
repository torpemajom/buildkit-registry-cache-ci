#!/usr/bin/env python3
"""Tidy statistical outputs from results/results.csv (no figures).

  results/summary_by_cell.csv  descriptives per phase x project x variant x scenario x mode
  results/pairs.csv            one row per trial: none/min/max builds of the same trial side by side
  results/tests.csv            hypothesis tests
  results/hypotheses.csv       decisions for H1-H3 by the pre-registered rules (H4: cost_model.py)

Only valid builds enter the statistics (exit code 0 and no flag); flagged and
failed builds are counted in summary_by_cell.csv. A trial contributes a pair
(mode - none) only if both builds are valid.

Per project x variant x scenario and cache mode, on d = wall_s(mode) - wall_s(none):
median of d with a percentile bootstrap 95% CI (10,000 resamples of the pairs,
fixed seed) and the matched-pairs rank-biserial correlation r = (T+ - T-) / (T+ + T-)
(Kerby 2014; positive: cache slower). Wilcoxon signed-rank tests are exact when
n <= 50 without zeros/ties, otherwise the normal approximation; `statistic`
follows scipy: min(T+, T-) for two-sided tests, T+ for one-sided tests.

Test families (Holm-corrected separately) and decision rules (thesis, table 4):
  H1  S0 cells, Wilcoxon two-sided. Supported if in both cache modes and in every
      real project the median difference is negative with p_holm < 0.05.
  H2  per project x variant x mode, Spearman rho between the cache hit ratio and the
      relative time saving (none - mode) / none over the trials of S0-S3, one-sided
      (rho > 0). Supported if in max mode rho > 0 with p_holm < 0.05 in every real project.
  H3  all cells, Wilcoxon one-sided "greater" (cache build longer). Supported if at
      least one cell has a positive median difference with p_holm < 0.05.
  S1-S3 (supplementary, no decision): S1-S3 cells, Wilcoxon two-sided.
Real projects are those whose ecosystem is not "synthetic".
"""
import argparse
import csv
import json
import os
from collections import Counter, defaultdict

import numpy as np
from scipy import stats

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOTSTRAP = 10_000
SEED = 20261003
MODES = ("none", "min", "max")
CACHE_MODES = ("min", "max")
CELL = ("project", "variant", "scenario")
PAIR_KEY = ("run_id", "run_attempt", "project", "variant", "scenario", "shard", "trial")
NUMERIC = (
    "wall_s", "import_s", "export_cache_s", "export_prepare_s", "export_write_layers_s", "export_write_manifest_s",
    "export_image_s", "exec_run_s", "buildkit_span_s", "builder_create_s", "n_vertices", "n_cached",
    "expected_n_cached", "cache_hit_ratio", "net_rx_bytes", "net_tx_bytes", "pull_base_bytes",
    "pull_cache_bytes", "cache_bytes", "cache_bytes_excl_base", "cache_blobs", "image_size_bytes",
    "exit_code", "order_pos",
)
MEDIANS = (
    "import_s", "export_cache_s", "export_image_s", "exec_run_s", "buildkit_span_s", "builder_create_s",
    "n_cached", "cache_hit_ratio", "net_rx_bytes", "net_tx_bytes", "pull_base_bytes", "pull_cache_bytes",
    "cache_bytes", "cache_bytes_excl_base", "image_size_bytes",
)
PAIR_FIELDS = ("wall_s", "n_cached", "cache_hit_ratio", "net_rx_bytes", "net_tx_bytes", "pull_base_bytes",
               "pull_cache_bytes", "cache_bytes", "cache_bytes_excl_base", "import_s", "export_cache_s",
               "order_pos", "utc_start")
ALPHA = 0.05


def load(path):
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        for key in NUMERIC:
            row[key] = float(row[key]) if row.get(key, "") != "" else None
        for key in ("shard", "trial"):
            row[key] = int(row[key])
        row["valid"] = row["valid"] == "True"
        row["flags"] = json.loads(row["flags"]) if row.get("flags") else []
    return rows


def write(path, rows, columns=None):
    columns = columns or list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("" if row.get(k) is None or (isinstance(row.get(k), float) and np.isnan(row[k]))
                                 else row[k]) for k in columns})
    print(f"{len(rows)} rows -> {path}")


def values(rows, key):
    return np.array([r[key] for r in rows if r[key] is not None], dtype=float)


def summary(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(row["phase"],) + tuple(row[k] for k in CELL) + (row["mode"],)].append(row)
    out = []
    for key, group in sorted(groups.items()):
        valid = [r for r in group if r["valid"]]
        wall = values(valid, "wall_s")
        expected = sorted({int(r["expected_n_cached"]) for r in group if r["expected_n_cached"] is not None})
        record = dict(zip(("phase",) + CELL + ("mode",), key))
        record.update({
            "n_builds": len(group),
            "n_valid": len(valid),
            "n_failed": sum(1 for r in group if r["exit_code"] != 0),
            "n_flagged": sum(1 for r in group if r["flags"]),
            "flag_counts": json.dumps(dict(Counter(f for r in group for f in r["flags"])), sort_keys=True),
            "expected_n_cached": expected[0] if len(expected) == 1 else json.dumps(expected),
        })
        if len(wall):
            q1, median, q3 = np.percentile(wall, [25, 50, 75])
            record.update({
                "wall_s_median": median, "wall_s_q1": q1, "wall_s_q3": q3, "wall_s_iqr": q3 - q1,
                "wall_s_mean": wall.mean(), "wall_s_sd": wall.std(ddof=1) if len(wall) > 1 else None,
                "wall_s_min": wall.min(), "wall_s_max": wall.max(),
            })
        for metric in MEDIANS:
            data = values(valid, metric)
            record[f"{metric}_median"] = float(np.median(data)) if len(data) else None
        out.append(record)
    return out


def pairs(rows):
    trials = defaultdict(dict)
    for row in rows:
        if row["phase"] == "measured" and row["valid"]:
            trials[tuple(row[k] for k in PAIR_KEY)][row["mode"]] = row
    out = []
    for key, builds in sorted(trials.items()):
        if "none" not in builds:
            continue
        record = dict(zip(PAIR_KEY, key))
        for mode in MODES:
            for field in PAIR_FIELDS:
                record[f"{field}_{mode}"] = builds[mode][field] if mode in builds else None
        out.append(record)
    return out


def rank_biserial(d):
    nonzero = d[d != 0]
    if not len(nonzero):
        return None
    ranks = stats.rankdata(np.abs(nonzero))
    plus, minus = ranks[nonzero > 0].sum(), ranks[nonzero < 0].sum()
    return (plus - minus) / (plus + minus)


def bootstrap_median_ci(d, rng):
    samples = rng.choice(d, size=(BOOTSTRAP, len(d)), replace=True)
    low, high = np.percentile(np.median(samples, axis=1), [2.5, 97.5])
    return low, high


def wilcoxon(d, alternative):
    nonzero = d[d != 0]
    exact = len(d) <= 50 and len(nonzero) == len(d) and len(np.unique(np.abs(d))) == len(d)
    method = "exact" if exact else "approx"
    if not len(nonzero):
        return None, None, method, "all differences are zero"
    result = stats.wilcoxon(d, alternative=alternative, zero_method="wilcox", method=method)
    return float(result.statistic), float(result.pvalue), method, None


def holm(rows):
    """Holm step-down adjustment within each family (rows without p-value are skipped)."""
    families = defaultdict(list)
    for row in rows:
        if row["p_value"] is not None:
            families[row["family"]].append(row)
    for family in families.values():
        family.sort(key=lambda r: r["p_value"])
        m, running = len(family), 0.0
        for rank, row in enumerate(family):
            running = max(running, min(1.0, (m - rank) * row["p_value"]))
            row["p_holm"], row["family_size"] = running, m


def tests(pair_rows):
    rng = np.random.default_rng(SEED)
    out = []
    cells = defaultdict(list)
    for row in pair_rows:
        cells[tuple(row[k] for k in CELL)].append(row)
    for cell, group in sorted(cells.items()):
        scenario = cell[2]
        for mode in CACHE_MODES:
            complete = [r for r in group if r[f"wall_s_{mode}"] is not None]
            if not complete:
                continue
            none = np.array([r["wall_s_none"] for r in complete])
            cached = np.array([r[f"wall_s_{mode}"] for r in complete])
            d = cached - none
            low, high = bootstrap_median_ci(d, rng)
            base = {
                **dict(zip(CELL, cell)), "mode": mode, "n_pairs": len(d),
                "median_none_s": float(np.median(none)), "median_mode_s": float(np.median(cached)),
                "median_diff_s": float(np.median(d)), "ci95_low_s": low, "ci95_high_s": high,
                "median_rel_saving": float(np.median((none - cached) / none)),
                "effect_rank_biserial": rank_biserial(d),
            }
            families = [("H1", "H1", "two-sided")] if scenario == "S0" else [("-", "S1-S3", "two-sided")]
            families.append(("H3", "H3", "greater"))
            for hypothesis, family, alternative in families:
                statistic, p, method, note = wilcoxon(d, alternative)
                out.append({"hypothesis": hypothesis, "family": family, "test": "wilcoxon_signed_rank",
                            "alternative": alternative, **base, "statistic": statistic, "p_value": p,
                            "method": method, "note": note})

    trend = defaultdict(lambda: ([], []))
    for row in pair_rows:
        for mode in CACHE_MODES:
            if row[f"wall_s_{mode}"] is not None and row[f"cache_hit_ratio_{mode}"] is not None:
                x, y = trend[(row["project"], row["variant"], mode)]
                x.append(row[f"cache_hit_ratio_{mode}"])
                y.append((row["wall_s_none"] - row[f"wall_s_{mode}"]) / row["wall_s_none"])
    for (project, variant, mode), (x, y) in sorted(trend.items()):
        row = {"hypothesis": "H2", "family": "H2", "test": "spearman", "alternative": "greater",
               "project": project, "variant": variant, "scenario": "S0-S3", "mode": mode, "n_pairs": len(x)}
        if len(set(x)) > 1 and len(x) > 2:
            result = stats.spearmanr(x, y, alternative="greater")
            row.update({"statistic": float(result.statistic), "spearman_rho": float(result.statistic),
                        "p_value": float(result.pvalue), "method": "t-distribution approximation"})
        else:
            row.update({"statistic": None, "p_value": None, "note": "too few pairs or constant cache hit ratio"})
        out.append(row)
    for row in out:
        row.setdefault("p_holm", None)
        row.setdefault("family_size", None)
    holm(out)
    return out


def hypotheses(test_rows, real_projects, real_variants):
    """Decisions for H1-H3 (thesis, table 4). `supported` is empty when a required test is missing."""
    def significant(row):
        return row["p_holm"] is not None and row["p_holm"] < ALPHA

    def cell(row):
        return {k: row.get(k) for k in ("project", "variant", "scenario", "mode", "n_pairs", "median_diff_s",
                                         "spearman_rho", "p_value", "p_holm")}

    def required(family, modes):
        rows = [r for r in test_rows if r["family"] == family and r["project"] in real_projects
                and r["mode"] in modes]
        missing = len(real_variants) * len(modes) - len(rows)
        return rows, missing

    out = []
    rows, missing = required("H1", CACHE_MODES)
    ok = [r["median_diff_s"] < 0 and significant(r) for r in rows]
    out.append({"hypothesis": "H1", "rule": "S0, min and max, every real project: median difference < 0 and "
                "p_holm < 0.05 (Wilcoxon two-sided)", "tests_evaluated": len(rows), "tests_missing": missing,
                "tests_meeting_rule": sum(ok), "supported": None if missing or not rows else all(ok),
                "evidence": json.dumps([{**cell(r), "meets_rule": m} for r, m in zip(rows, ok)])})
    rows, missing = required("H2", ("max",))
    ok = [r.get("spearman_rho") is not None and r["spearman_rho"] > 0 and significant(r) for r in rows]
    out.append({"hypothesis": "H2", "rule": "max mode, every real project: Spearman rho(cache hit ratio, "
                "relative saving) > 0 and p_holm < 0.05 (one-sided)", "tests_evaluated": len(rows),
                "tests_missing": missing, "tests_meeting_rule": sum(ok), "supported": None if missing or not rows else all(ok),
                "evidence": json.dumps([{**cell(r), "meets_rule": m} for r, m in zip(rows, ok)])})
    rows = [r for r in test_rows if r["family"] == "H3"]
    ok = [r["median_diff_s"] > 0 and significant(r) for r in rows]
    out.append({"hypothesis": "H3", "rule": "at least one cell (any project, scenario, cache mode): median "
                "difference > 0 and p_holm < 0.05 (Wilcoxon one-sided greater)", "tests_evaluated": len(rows),
                "tests_missing": 0, "tests_meeting_rule": sum(ok), "supported": any(ok) if rows else None,
                "evidence": json.dumps([cell(r) for r, m in zip(rows, ok) if m])})
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results", default=os.path.join(ROOT, "results"))
    args = parser.parse_args()
    rows = load(os.path.join(args.results, "results.csv"))
    write(os.path.join(args.results, "summary_by_cell.csv"), summary(rows))
    pair_rows = pairs(rows)
    write(os.path.join(args.results, "pairs.csv"), pair_rows)
    columns = ["hypothesis", "family", "test", "alternative", "project", "variant", "scenario", "mode", "n_pairs",
               "median_none_s", "median_mode_s", "median_diff_s", "ci95_low_s", "ci95_high_s", "median_rel_saving",
               "statistic", "p_value", "p_holm", "family_size", "effect_rank_biserial", "spearman_rho", "method", "note"]
    test_rows = tests(pair_rows)
    write(os.path.join(args.results, "tests.csv"), test_rows, columns)
    real = {r["project"] for r in rows if r["ecosystem"] != "synthetic"}
    real_variants = {(r["project"], r["variant"]) for r in rows if r["project"] in real}
    write(os.path.join(args.results, "hypotheses.csv"), hypotheses(test_rows, real, real_variants))


if __name__ == "__main__":
    main()
