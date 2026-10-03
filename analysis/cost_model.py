#!/usr/bin/env python3
"""Parametric cost model and break-even ratios -> results/cost_breakeven.csv.

Cost of one build (prices from analysis/prices.json, supplied and dated by the author):
  cost = runner_minutes * runner_per_minute
       + cache_GB * storage_per_gb_month / builds_per_month     (storage share of one build)
       + download_GB * download_per_gb + upload_GB * upload_per_gb
Runner minutes are wall_s / 60 (no per-job rounding). The no-cache build has no
storage. With the paired medians of one cell
  dt  = median(wall_none - wall_mode) / 60          runner minutes saved (negative: cache slower)
  S   = median cache size of the mode's exported cache (GB)
  dD  = median(download_mode - download_none) (GB), dU likewise for upload,
the cache is more expensive iff
  (p_s/p_min) * S / builds_per_month + (p_d/p_min) * dD + (p_u/p_min) * dU > dt.
Price-free break-even ratios (each with the other storage/transfer prices at 0):
  breakeven_storage_ratio  = dt * builds_per_month / S     [(price per GB-month) / (price per minute)]
  breakeven_download_ratio = dt / dD                       [(price per GB) / (price per minute)]
  breakeven_upload_ratio   = dt / dU
Above the ratio the cache costs more. A ratio is left empty when it is not a
break-even point (dt <= 0: the cache is never cheaper while it adds storage or
transfer; dD <= 0: downloads do not grow with the cache); `ratio_note` says which.
For every price scenario, lambda_star = saved runner cost / added storage+transfer
cost is the factor by which the storage and transfer prices (relative to the
runner price) would have to change to reach break-even; < 1 means the cache is
already more expensive at those prices.

Download/upload bytes ("transfer_basis" in prices.json):
  registry  : download = blob bytes pulled from the registry (rawjson statuses:
              base-image and cache blobs), upload = interface tx bytes
  interface : download = interface rx bytes, upload = interface tx bytes
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


def transfer(row, mode, basis):
    if basis == "registry":
        pulled = [number(row[f"pull_base_bytes_{mode}"]), number(row[f"pull_other_bytes_{mode}"])]
        down = None if None in pulled else sum(pulled)
    elif basis == "interface":
        down = number(row[f"net_rx_bytes_{mode}"])
    else:
        raise SystemExit(f"unknown transfer_basis {basis!r}")
    return down, number(row[f"net_tx_bytes_{mode}"])


def median(items):
    items = [i for i in items if i is not None]
    return float(np.median(items)) if items else None


def ratio(numerator, denominator):
    return numerator / denominator if numerator is not None and denominator else None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results", default=os.path.join(ROOT, "results"))
    parser.add_argument("--prices", default=os.path.join(ROOT, "analysis", "prices.json"))
    args = parser.parse_args()
    with open(args.prices, encoding="utf-8") as fh:
        prices = json.load(fh)
    gb = float(prices["gb_bytes"])
    basis, storage_basis = prices["transfer_basis"], prices["storage_basis"]
    with open(os.path.join(args.results, "pairs.csv"), newline="", encoding="utf-8") as fh:
        pair_rows = list(csv.DictReader(fh))

    cells = defaultdict(list)
    for row in pair_rows:
        cells[tuple(row[k] for k in CELL)].append(row)

    out = []
    for cell, group in sorted(cells.items()):
        for mode in CACHE_MODES:
            complete = [r for r in group if r[f"wall_s_{mode}"] not in (None, "")]
            if not complete:
                continue
            dt = median([(number(r["wall_s_none"]) - number(r[f"wall_s_{mode}"])) / 60 for r in complete])
            t_none = median([number(r["wall_s_none"]) / 60 for r in complete])
            t_mode = median([number(r[f"wall_s_{mode}"]) / 60 for r in complete])
            storage = median([number(r[f"{storage_basis}_{mode}"]) for r in complete])
            storage_gb = storage / gb if storage is not None else None
            moved = [(transfer(r, "none", basis), transfer(r, mode, basis)) for r in complete]
            down_none = median([n[0] for n, _ in moved])
            up_none = median([n[1] for n, _ in moved])
            down_mode = median([m[0] for _, m in moved])
            up_mode = median([m[1] for _, m in moved])
            d_down = median([(m[0] - n[0]) / gb for n, m in moved if None not in (m[0], n[0])])
            d_up = median([(m[1] - n[1]) / gb for n, m in moved if None not in (m[1], n[1])])

            base = {
                **dict(zip(CELL, cell)), "mode": mode, "n_pairs": len(complete),
                "transfer_basis": basis, "storage_basis": storage_basis,
                "runner_min_none": t_none, "runner_min_mode": t_mode, "saved_runner_min": dt,
                "cache_gb": storage_gb,
                "download_gb_none": down_none / gb if down_none is not None else None,
                "download_gb_mode": down_mode / gb if down_mode is not None else None,
                "upload_gb_none": up_none / gb if up_none is not None else None,
                "upload_gb_mode": up_mode / gb if up_mode is not None else None,
                "extra_download_gb": d_down, "extra_upload_gb": d_up,
            }
            notes = []
            if dt is not None and dt <= 0:
                notes.append("cache not faster (saved_runner_min <= 0): never cheaper while it adds cost")
            if d_down is not None and d_down <= 0:
                notes.append("download does not grow with the cache: no download break-even")
            if d_up is not None and d_up <= 0:
                notes.append("upload does not grow with the cache: no upload break-even")
            positive = dt is not None and dt > 0
            base["breakeven_download_ratio"] = ratio(dt, d_down) if positive and d_down and d_down > 0 else None
            base["breakeven_upload_ratio"] = ratio(dt, d_up) if positive and d_up and d_up > 0 else None
            base["ratio_note"] = "; ".join(notes) or None

            for scenario in prices["scenarios"]:
                row = dict(base)
                row.update({"price_scenario": scenario["name"], "price_as_of": scenario.get("as_of"),
                            "currency": scenario.get("currency")})
                bpm = scenario.get("builds_per_month")
                row["builds_per_month"] = bpm
                row["breakeven_storage_ratio"] = (dt * bpm / storage_gb
                                                  if positive and bpm and storage_gb else None)
                p = {k: scenario.get(k) for k in ("runner_per_minute", "storage_per_gb_month",
                                                  "download_per_gb", "upload_per_gb")}
                inputs = [p["runner_per_minute"], p["storage_per_gb_month"], p["download_per_gb"],
                          p["upload_per_gb"], bpm, t_none, t_mode, storage_gb, down_none, down_mode, up_none, up_mode]
                if None in inputs:
                    row["price_note"] = "prices or measurements missing: price-dependent columns left empty"
                else:
                    cost_none = t_none * p["runner_per_minute"] + down_none / gb * p["download_per_gb"] \
                        + up_none / gb * p["upload_per_gb"]
                    storage_cost = storage_gb * p["storage_per_gb_month"] / bpm
                    cost_mode = t_mode * p["runner_per_minute"] + storage_cost \
                        + down_mode / gb * p["download_per_gb"] + up_mode / gb * p["upload_per_gb"]
                    added = storage_cost + (d_down or 0) * p["download_per_gb"] + (d_up or 0) * p["upload_per_gb"]
                    saved = dt * p["runner_per_minute"]
                    row.update({
                        "ref_storage_ratio": p["storage_per_gb_month"] / p["runner_per_minute"],
                        "ref_download_ratio": p["download_per_gb"] / p["runner_per_minute"],
                        "ref_upload_ratio": p["upload_per_gb"] / p["runner_per_minute"],
                        "cost_none": cost_none, "cost_mode": cost_mode,
                        "cost_difference": cost_mode - cost_none,
                        "saved_runner_cost": saved, "added_storage_transfer_cost": added,
                        "lambda_star": saved / added if added > 0 else None,
                        "cache_cheaper": cost_mode < cost_none,
                    })
                out.append(row)

    columns = list(dict.fromkeys(k for r in out for k in r))
    path = os.path.join(args.results, "cost_breakeven.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for row in out:
            writer.writerow({k: "" if row.get(k) is None else row[k] for k in columns})
    print(f"{len(out)} rows -> {path}")


if __name__ == "__main__":
    main()
