#!/usr/bin/env python3
"""Expand workflow inputs into the job matrix (one job per project x variant x scenario x shard).

Jobs are put in a fixed pseudo-random order (sha256 of the cell key), so that
max-parallel scheduling does not run all jobs of one project or scenario at
the same time of day. Prints `matrix=<json>` and `count=<n>` for $GITHUB_OUTPUT.
"""
import argparse
import hashlib
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENARIOS = ("S0", "S1", "S2", "S3")


def expand_projects(spec):
    """'uptime-kuma,synthetic,synthetic:large-short' -> [(project, variant)]; a bare
    project name expands to all of its variants."""
    units = []
    for item in [s.strip() for s in spec.split(",") if s.strip()]:
        project, _, variant = item.partition(":")
        with open(os.path.join(ROOT, "projects", project, "project.json"), encoding="utf-8") as fh:
            variants = list(json.load(fh)["variants"])
        if variant and variant not in variants:
            raise SystemExit(f"unknown variant {item!r}; known: {variants}")
        units += [(project, v) for v in ([variant] if variant else variants)]
    return units


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projects", required=True)
    parser.add_argument("--scenarios", required=True)
    parser.add_argument("--shards", type=int, required=True)
    args = parser.parse_args()
    scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    unknown = set(scenarios) - set(SCENARIOS)
    if unknown:
        raise SystemExit(f"unknown scenarios {sorted(unknown)}")

    jobs = [
        {"project": project, "variant": variant, "scenario": scenario, "shard": shard}
        for project, variant in expand_projects(args.projects)
        for scenario in scenarios
        for shard in range(1, args.shards + 1)
    ]
    if len(jobs) > 256:
        raise SystemExit(f"{len(jobs)} jobs exceed the 256-job matrix limit")
    jobs.sort(key=lambda j: hashlib.sha256(json.dumps(j, sort_keys=True).encode()).hexdigest())
    print("matrix=" + json.dumps({"include": jobs}, separators=(",", ":")))
    print(f"count={len(jobs)}")


if __name__ == "__main__":
    main()
