#!/usr/bin/env python3
"""One deterministic synthetic build step.

Burns a fixed amount of CPU work (chained SHA-256 iterations) and writes a
fixed amount of seeded, incompressible data. The seed is derived from the
step name and the content of the given input files, so the output changes
exactly when an input changes, like a real compiler or package manager.

Writes <out> (the data) and <out>.seed (hex seed, for chaining steps).
"""
import argparse
import hashlib
import sys
import time

CHUNK = 1 << 20


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--cpu-iters", type=int, required=True)
    parser.add_argument("--bytes", type=int, required=True)
    parser.add_argument("--input", action="append", default=[])
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    seed = hashlib.sha256(args.name.encode())
    for path in args.input:
        with open(path, "rb") as fh:
            seed.update(hashlib.sha256(fh.read()).digest())
    seed_bytes = seed.digest()

    started = time.process_time()
    state = seed_bytes
    for _ in range(args.cpu_iters):
        state = hashlib.sha256(state).digest()
    cpu_s = time.process_time() - started

    remaining = args.bytes
    counter = 0
    with open(args.out, "wb") as fh:
        while remaining > 0:
            size = min(CHUNK, remaining)
            fh.write(hashlib.shake_256(state + counter.to_bytes(8, "big")).digest(size))
            remaining -= size
            counter += 1
    with open(args.out + ".seed", "w") as fh:
        fh.write(state.hex() + "\n")

    print(f"step={args.name} cpu_iters={args.cpu_iters} cpu_s={cpu_s:.3f} bytes={args.bytes}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
