#!/usr/bin/env python3
"""Parametric cost model, break-even ratios and the H4 decision.

Cost of one build (thesis, eq. 1):
    K = t * p_v + D * p_a + M * p_t / n
  t    build time in minutes (wall_s / 60)
  D    cache data downloaded at import, GB: blob bytes of cache layers pulled during the
       build (rawjson layer downloads; base-image layers excluded, they are pulled in every mode)
  M    cache size, GB: unique blob bytes referenced by the exported cache manifest
  p_v  runner price per minute, p_a download price per GB, p_t storage price per GB-month,
  n    builds per month that use the same cache.
Uploads are not priced (the registries in prices.json do not charge ingress). For the
no-cache build D = M = 0, so the cache is cheaper iff (eq. 2)
    (t0 - tg) * p_v > Dg * p_a + Mg * p_t / n.
Dividing by p_v leaves the price ratios r_a = p_a / p_v (runner minutes per GB downloaded)
and r_t = p_t / p_v (runner minutes per GB-month stored). Per cell (project x variant x
scenario x cache mode), with dt = median over the trials of (t0 - tg), Dg and Mg medians:
    ra_star       = dt / Dg         break-even download ratio, storage cost neglected
    rt_star_n<n>  = dt * n / Mg     break-even storage ratio, download cost neglected
Above the ratio the cache costs more. If dt <= 0 the cache build is not shorter and there is
no break-even point (the cache is more expensive at any price); if Dg = 0 (Mg = 0) the
download (storage) price cannot make the cache more expensive.

H4 (thesis, table 4): among the cells where the cache build is shorter (dt > 0), at least one
ra_star lies within [min, max] of the r_a ratios of the price lists (registries in
prices.json) at the base runner price. The same check is also reported for the paid
registries only and over all runner prices (sensitivity).

Outputs: results/cost_breakeven.csv (per cell), results/cost_by_price.csv (per cell x
registry x runner price x n), and the H4 row of results/hypotheses.csv.
"""
import argparse
import csv
import json
import os
from collections import defaultdict

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CELL = ("project", "variant", "scenario")
CACHE_MODES = ("min", "max")


def number(value):
    return float(value) if value not in (None, "") else None


def median(items):
    items = [i for i in items if i is not None]
    return float(np.median(items)) if items else None


def write(path, rows):
    columns = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: "" if row.get(k) is None else row[k] for k in columns})
    print(f"{len(rows)} rows -> {path}")


def per_gb(price, unit, gb_bytes):
    """Convert a price per `unit` (GB or GiB) into a price per GB of gb_bytes bytes."""
    return price * gb_bytes / {"GB": 1e9, "GiB": 2 ** 30}[unit]


def ratio_range(values):
    return (min(values), max(values)) if values else (None, None)


def within(value, bounds):
    low, high = bounds
    return None if value is None or low is None else low <= value <= high


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results", default=os.path.join(ROOT, "results"))
    parser.add_argument("--prices", default=os.path.join(ROOT, "analysis", "prices.json"))
    args = parser.parse_args()
    with open(args.prices, encoding="utf-8") as fh:
        prices = json.load(fh)
    gb = float(prices["gb_bytes"])
    runners = prices["runner_per_minute"]
    base_runner = prices["base_runner"]
    ns = prices["builds_per_month"]
    registries = [{**r, "download_per_gb": per_gb(r["download"], r["unit"], gb),
                   "storage_per_gb_month": per_gb(r["storage_per_month"], r["unit"], gb)}
                  for r in prices["registries"]]
    ra_base = ratio_range([r["download_per_gb"] / runners[base_runner] for r in registries])
    ra_paid = ratio_range([r["download_per_gb"] / runners[base_runner] for r in registries if r["download_per_gb"]])
    ra_all = ratio_range([r["download_per_gb"] / pv for r in registries for pv in runners.values()])

    with open(os.path.join(args.results, "pairs.csv"), newline="", encoding="utf-8") as fh:
        pair_rows = list(csv.DictReader(fh))
    cells = defaultdict(list)
    for row in pair_rows:
        cells[tuple(row[k] for k in CELL)].append(row)

    breakeven, by_price = [], []
    for cell, group in sorted(cells.items()):
        for mode in CACHE_MODES:
            complete = [r for r in group if r[f"wall_s_{mode}"] not in (None, "")]
            if not complete:
                continue
            dt = median([(number(r["wall_s_none"]) - number(r[f"wall_s_{mode}"])) / 60 for r in complete])
            t0 = median([number(r["wall_s_none"]) / 60 for r in complete])
            tg = median([number(r[f"wall_s_{mode}"]) / 60 for r in complete])
            downloaded = median([number(r[f"pull_cache_bytes_{mode}"]) for r in complete])
            stored = median([number(r[f"{prices['storage_basis']}_{mode}"]) for r in complete])
            d_gb = downloaded / gb if downloaded is not None else None
            m_gb = stored / gb if stored is not None else None
            shorter = dt > 0
            notes = []
            if not shorter:
                notes.append("cache build not shorter (dt <= 0): no break-even, the cache is dearer at any price")
            elif not d_gb:
                notes.append("no cache download (Dg = 0): the download price cannot make the cache dearer")
            ra_star = dt / d_gb if shorter and d_gb else None
            row = {
                **dict(zip(CELL, cell)), "mode": mode, "n_pairs": len(complete),
                "t0_min": t0, "tg_min": tg, "dt_min": dt, "cache_shorter": shorter,
                "download_gb": d_gb, "cache_gb": m_gb, "storage_basis": prices["storage_basis"],
                "ra_star": ra_star,
            }
            for n in ns:
                row[f"rt_star_n{n}"] = dt * n / m_gb if shorter and m_gb else None
            row.update({
                "ra_range_base_low": ra_base[0], "ra_range_base_high": ra_base[1],
                "ra_star_within_base": within(ra_star, ra_base) if shorter else None,
                "ra_star_within_paid": within(ra_star, ra_paid) if shorter else None,
                "ra_star_within_all_runner_prices": within(ra_star, ra_all) if shorter else None,
                "note": "; ".join(notes) or None,
            })
            breakeven.append(row)

            for registry in registries:
                pa, pt = registry["download_per_gb"], registry["storage_per_gb_month"]
                for runner, pv in runners.items():
                    for n in ns:
                        saved = dt * pv
                        added = (d_gb or 0) * pa + (m_gb or 0) * pt / n
                        by_price.append({
                            **dict(zip(CELL, cell)), "mode": mode, "registry": registry["name"],
                            "runner": runner, "base_runner": runner == base_runner, "builds_per_month": n,
                            "p_v": pv, "p_a_per_gb": pa, "p_t_per_gb_month": pt, "r_a": pa / pv, "r_t": pt / pv,
                            "cost_none": t0 * pv, "cost_cache": tg * pv + added,
                            "saved_runner_cost": saved, "added_cache_cost": added, "cache_cheaper": saved > added,
                            # download break-even with this registry's storage cost included
                            "ra_star_with_storage": (dt - (m_gb or 0) * (pt / pv) / n) / d_gb
                            if shorter and d_gb else None,
                        })

    write(os.path.join(args.results, "cost_breakeven.csv"), breakeven)
    write(os.path.join(args.results, "cost_by_price.csv"), by_price)

    candidates = [r for r in breakeven if r["cache_shorter"]]
    hits = [r for r in candidates if r["ra_star_within_base"]]
    decision = {
        "hypothesis": "H4",
        "rule": f"among cells with a shorter cache build, at least one ra_star = dt / Dg within the r_a range of "
                f"the price lists at the base runner price ({base_runner}): [{ra_base[0]:.4g}, {ra_base[1]:.4g}] "
                f"runner minutes per GB",
        "tests_evaluated": len(candidates), "tests_missing": 0, "tests_meeting_rule": len(hits),
        "supported": bool(hits) if candidates else None,
        "evidence": json.dumps([{k: r[k] for k in (*CELL, "mode", "dt_min", "download_gb", "ra_star",
                                                   "ra_star_within_paid", "ra_star_within_all_runner_prices")}
                                for r in hits]),
    }
    path = os.path.join(args.results, "hypotheses.csv")
    rows = []
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as fh:
            rows = [r for r in csv.DictReader(fh) if r["hypothesis"] != "H4"]
    write(path, rows + [decision])


if __name__ == "__main__":
    main()
