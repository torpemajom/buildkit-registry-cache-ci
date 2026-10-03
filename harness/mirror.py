#!/usr/bin/env python3
"""Mirror every pinned image (pins.json) into <mirror>/<name>:<tag>. Stdlib only.

Each linux/amd64 manifest is copied byte-for-byte (`--prefer-index=false`),
so the mirror digest equals the pinned upstream digest; this is verified.
Already mirrored images are left untouched. Writes a JSON report.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def raw_digest(ref):
    proc = subprocess.run(["docker", "buildx", "imagetools", "inspect", "--raw", ref], capture_output=True)
    if proc.returncode != 0:
        return None
    return "sha256:" + hashlib.sha256(proc.stdout).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mirror", required=True, help="e.g. ghcr.io/<owner>/<repo>/mirror")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    with open(os.path.join(ROOT, "pins.json"), encoding="utf-8") as fh:
        pins = json.load(fh)

    report, failed = [], False
    for name, image in sorted(pins["images"].items()):
        source = f"{image['source']}@{image['digest']}"
        target = f"{args.mirror}/{name}:{image['tag']}"
        entry = {"name": name, "source": source, "target": target, "pinned_digest": image["digest"]}
        if raw_digest(target) == image["digest"]:
            entry["action"] = "already mirrored"
        else:
            # Docker Hub answers 429 when its anonymous pull limit is hit: back off and retry.
            for wait in (30, 60, 120, None):
                proc = subprocess.run(["docker", "buildx", "imagetools", "create", "--prefer-index=false",
                                       "--tag", target, source], capture_output=True, text=True)
                if proc.returncode == 0 or wait is None:
                    break
                print(f"{name}: copy failed, retrying in {wait}s: {proc.stderr.strip()[-200:]}", flush=True)
                time.sleep(wait)
            entry["action"] = "copied" if proc.returncode == 0 else "copy failed: " + proc.stderr.strip()[-500:]
        entry["mirror_digest"] = raw_digest(target)
        entry["verified"] = entry["mirror_digest"] == image["digest"]
        failed |= not entry["verified"]
        report.append(entry)
        print(json.dumps(entry), flush=True)

    with open(args.report, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
