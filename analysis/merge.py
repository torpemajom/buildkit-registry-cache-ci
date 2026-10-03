#!/usr/bin/env python3
"""Merge results/raw/*.jsonl (one JSON object per build) into results/results.csv. Stdlib only.

Missing values are written as empty cells; the reason for every null metric is
in the `null_reasons` column. List and object fields are JSON-encoded.
"""
import argparse
import csv
import glob
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY = ("run_id", "run_attempt", "project", "variant", "scenario", "shard", "phase", "trial", "mode")
FIRST = KEY + (
    "order_pos", "utc_start", "valid", "flags", "exit_code", "wall_s",
    "n_vertices", "n_cached", "expected_n_cached", "cache_hit_ratio",
    "import_s", "export_cache_s", "export_prepare_s", "export_write_layers_s", "export_write_manifest_s",
    "export_image_s", "exec_run_s", "buildkit_span_s",
    "net_rx_bytes", "net_tx_bytes", "pull_base_bytes", "pull_other_bytes",
    "cache_bytes", "cache_bytes_excl_base", "cache_blobs", "image_size_bytes",
    "empty_check", "du_records", "du_total", "builder_create_s", "builder_removed",
    "image_os", "image_version", "cpu_model", "vcpus", "ram_bytes", "net_iface",
    "error_text", "null_reasons",
)
# Bulky per-build detail kept only in the JSONL files.
DROP = ("steps", "build_command", "du_output")


def cell(value):
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", default=os.path.join(ROOT, "results", "raw"))
    parser.add_argument("--out", default=os.path.join(ROOT, "results", "results.csv"))
    args = parser.parse_args()

    rows, seen = [], set()
    for path in sorted(glob.glob(os.path.join(args.raw, "*.jsonl"))):
        with open(path, encoding="utf-8") as fh:
            for number, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                record = json.loads(line)
                key = tuple(str(record.get(k)) for k in KEY)
                if key in seen:
                    raise SystemExit(f"duplicate build {key} in {path}:{number}")
                seen.add(key)
                record["valid"] = record.get("exit_code") == 0 and not record.get("flags")
                for name in DROP:
                    record.pop(name, None)
                rows.append(record)
    if not rows:
        raise SystemExit(f"no records in {args.raw}")

    columns = list(FIRST) + sorted({k for r in rows for k in r} - set(FIRST))
    rows.sort(key=lambda r: tuple(str(r.get(k)) for k in KEY))
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for record in rows:
            writer.writerow({c: cell(record.get(c)) for c in columns})
    print(f"{len(rows)} builds -> {args.out}")


if __name__ == "__main__":
    main()
