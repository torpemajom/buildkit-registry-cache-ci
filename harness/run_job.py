#!/usr/bin/env python3
"""Run one measurement job (one project x variant x scenario x shard). Stdlib only.

Protocol:
  1. prepare the pinned source tree;
  2. seed: build the unmodified tree once per cache mode (min, max) in a fresh
     builder, exporting the cache to job-unique seed refs (phase=seed);
  3. apply the scenario modification;
  4. K trials: the modes none/min/max in random order, each in a fresh builder;
     cache modes import from the seed ref and export to a per-trial "out" ref.
Every build starts in a newly created docker-container builder whose cache is
verified empty (`docker buildx du`) and is removed with its state afterwards.
One JSON object per build is appended to --out.
"""
import argparse
import hashlib
import json
import os
import platform
import random
import re
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import progress  # noqa: E402
import scenario as scen  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODES = ("none", "min", "max")
CACHE_MODES = ("min", "max")
SCHEMA = 1
MIRROR_FROM_RE = re.compile(r"\$\{MIRROR\}/(?P<name>[\w.-]+)@(?P<digest>sha256:[0-9a-f]{64})")


def run(cmd, **kwargs):
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def log(message):
    print(f"[{utc_now()}] {message}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------- environment

def read_first(path, pattern):
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                match = re.match(pattern, line)
                if match:
                    return match.group(1).strip()
    except OSError:
        pass
    return None


def primary_interface():
    """Interface of the default route (/proc/net/route destination 00000000)."""
    try:
        with open("/proc/net/route", encoding="utf-8") as fh:
            next(fh)
            for line in fh:
                fields = line.split()
                if len(fields) > 1 and fields[1] == "00000000":
                    return fields[0]
    except OSError:
        pass
    return None


def net_counters(iface):
    if not iface:
        return None
    try:
        values = []
        for name in ("rx_bytes", "tx_bytes"):
            with open(f"/sys/class/net/{iface}/statistics/{name}", encoding="utf-8") as fh:
                values.append(int(fh.read().strip()))
        return tuple(values)
    except (OSError, ValueError):
        return None


def runner_info(buildkit_image):
    nulls = {}

    def env(name):
        value = os.environ.get(name)
        if value is None:
            nulls[name.lower()] = f"environment variable {name} not set"
        return value

    mem_kb = read_first("/proc/meminfo", r"MemTotal:\s+(\d+) kB")
    cpu_model = read_first("/proc/cpuinfo", r"model name\s*:\s*(.*)")
    if cpu_model is None:
        nulls["cpu_model"] = "no 'model name' in /proc/cpuinfo"
    docker = run(["docker", "version", "--format", "{{.Server.Version}}"])
    driver = run(["docker", "info", "--format", "{{.Driver}}"])
    buildx = run(["docker", "buildx", "version"])
    return {
        "image_os": env("ImageOS"),
        "image_version": env("ImageVersion"),
        "runner_name": env("RUNNER_NAME"),
        "runner_arch": env("RUNNER_ARCH"),
        "cpu_model": cpu_model,
        "vcpus": os.cpu_count(),
        "ram_bytes": int(mem_kb) * 1024 if mem_kb else None,
        "kernel": platform.release(),
        "docker_server_version": docker.stdout.strip() or None,
        "docker_storage_driver": driver.stdout.strip() or None,
        "buildx_version": buildx.stdout.strip() or None,
        "buildkit_image": buildkit_image,
        "runner_null_reasons": nulls,
    }


# ---------------------------------------------------------------- registry

def inspect_raw(ref):
    proc = subprocess.run(["docker", "buildx", "imagetools", "inspect", "--raw", ref], capture_output=True)
    if proc.returncode != 0:
        return None, None, proc.stderr.decode("utf-8", "replace").strip()[-500:]
    return json.loads(proc.stdout), "sha256:" + hashlib.sha256(proc.stdout).hexdigest(), None


def base_blobs(dockerfile_text, mirror):
    """Layer and config digests of the (mirrored) base images used by the Dockerfile."""
    blobs = set()
    for match in sorted(set(MIRROR_FROM_RE.findall(dockerfile_text))):
        manifest, _, error = inspect_raw(f"{mirror}/{match[0]}@{match[1]}")
        if manifest is None:
            raise RuntimeError(f"cannot inspect base image {match}: {error}")
        blobs.add(manifest["config"]["digest"])
        blobs.update(layer["digest"] for layer in manifest["layers"])
    return frozenset(blobs)


def cache_size(ref, base):
    """Total bytes of the unique blobs referenced by a registry cache manifest."""
    manifest, digest, error = inspect_raw(ref)
    if manifest is None:
        return None, f"imagetools inspect failed: {error}"
    if "layers" in manifest:  # image-manifest=true: OCI image manifest with cache config
        descriptors = list(manifest["layers"]) + [manifest["config"]]
        config_type = manifest["config"].get("mediaType")
    else:  # index whose entries are the layer blobs plus the cache config blob
        descriptors = list(manifest.get("manifests", []))
        config_type = next((d.get("mediaType") for d in descriptors if "cacheconfig" in d.get("mediaType", "")), None)
    unique = {d["digest"]: int(d["size"]) for d in descriptors}
    return {
        "cache_manifest_digest": digest,
        "cache_manifest_media_type": manifest.get("mediaType"),
        "cache_config_media_type": config_type,
        "cache_blobs": len(unique),
        "cache_descriptors": len(descriptors),
        "cache_bytes": sum(unique.values()),
        "cache_bytes_excl_base": sum(size for d, size in unique.items() if d not in base),
    }, None


# ---------------------------------------------------------------- builders

def du_check(builder):
    as_json = run(["docker", "buildx", "du", "--builder", builder, "--format", "json"])
    table = run(["docker", "buildx", "du", "--builder", builder])
    text = as_json.stdout.strip()
    if not text:
        records = 0
    else:
        try:
            parsed = json.loads(text)
            records = len(parsed) if isinstance(parsed, list) else 1
        except json.JSONDecodeError:
            records = len([line for line in text.splitlines() if line.strip()])
    total = re.search(r"^Total:\s*(\S+)", table.stdout, re.MULTILINE)
    total = total.group(1) if total else None
    ok = as_json.returncode == 0 and table.returncode == 0
    return {
        "empty_check": ok and records == 0 and total in ("0B", "0"),
        "du_records": records if ok else None,
        "du_total": total,
        "du_output": table.stdout.strip()[-400:] or table.stderr.strip()[-400:],
    }


def create_builder(name, args):
    cmd = ["docker", "buildx", "create", "--name", name, "--driver", "docker-container",
           "--driver-opt", f"image={args.buildkit_image}"]
    for opt in args.driver_opt:
        cmd += ["--driver-opt", opt]
    if args.buildkitd_config:
        cmd += ["--buildkitd-config", args.buildkitd_config]
    cmd.append("--bootstrap")
    started = time.monotonic()
    proc = run(cmd)
    return proc, time.monotonic() - started


def remove_builder(name):
    proc = run(["docker", "buildx", "rm", name])
    volumes = run(["docker", "volume", "ls", "-q", "--filter", f"name=buildx_buildkit_{name}"]).stdout.split()
    containers = run(["docker", "ps", "-aq", "--filter", f"name=buildx_buildkit_{name}"]).stdout.split()
    return proc.returncode == 0 and not volumes and not containers


# ---------------------------------------------------------------- one build

def measure(ctx, phase, mode, trial, order_pos, scenario_name):
    """Run one build in a fresh builder and return its result record."""
    args, job = ctx["args"], ctx["job"]
    builder = "bk" + uuid.uuid4().hex[:12]
    image_tag = f"replication-{job['project']}:{builder}"
    work = os.path.join(args.workdir, "builds", f"{phase}-t{trial}-{mode}-{builder}")
    os.makedirs(work, exist_ok=True)
    rawjson = os.path.join(work, "progress.rawjson")
    nulls = {}
    flags = []

    cache_from = cache_to = None
    if mode in CACHE_MODES:
        cache_to = f"{ctx['ref_prefix']}-{'seed' if phase == 'seed' else 't' + str(trial)}-{mode}"
        if phase == "measured":
            cache_from = ctx["seed_refs"][mode]
    cache_to_opts = f"type=registry,ref={cache_to},mode={mode}" if cache_to else None

    record = {
        "schema": SCHEMA,
        **job,
        **ctx["runner"],
        "phase": phase,
        "scenario": scenario_name,
        "mode": mode,
        "trial": trial,
        "order_pos": order_pos,
        "builder": builder,
        "cache_from_ref": cache_from,
        "cache_to_ref": cache_to,
        "cache_to_options": cache_to_opts,
    }

    created, record["builder_create_s"] = create_builder(builder, args)
    if created.returncode != 0:
        record.update({"exit_code": None, "error_text": "builder create failed: " + created.stderr.strip()[-1000:],
                       "flags": ["builder_create_failed"]})
        remove_builder(builder)
        return record
    inspect = run(["docker", "buildx", "inspect", builder]).stdout
    version = re.search(r"^BuildKit version:\s*(\S+)", inspect, re.MULTILINE)
    record["buildkit_version"] = version.group(1) if version else None
    if not version:
        nulls["buildkit_version"] = "no 'BuildKit version' in docker buildx inspect output"
    record.update(du_check(builder))
    if not record["empty_check"]:
        flags.append("cache_not_empty")

    cmd = ["docker", "buildx", "build", "--builder", builder, "--progress=rawjson",
           "--provenance=false", "--sbom=false", "--file", ctx["dockerfile"],
           "--output", f"type=docker,name={image_tag}",
           "--metadata-file", os.path.join(work, "metadata.json")]
    for key, value in sorted(ctx["build_args"].items()):
        cmd += ["--build-arg", f"{key}={value}"]
    if cache_from:
        cmd += ["--cache-from", f"type=registry,ref={cache_from}"]
    if cache_to:
        cmd += ["--cache-to", cache_to_opts]
    cmd.append(ctx["source_dir"])
    record["build_command"] = " ".join(cmd)

    # The builder is already running (--bootstrap) and checked empty, so its start-up
    # time (builder_create_s) is not part of wall_s.
    before = net_counters(ctx["iface"])
    record["utc_start"] = utc_now()
    started = time.monotonic()
    with open(rawjson, "w", encoding="utf-8") as err:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=err, text=True)
    record["wall_s"] = time.monotonic() - started
    after = net_counters(ctx["iface"])
    record["exit_code"] = proc.returncode

    if before and after:
        record["net_rx_bytes"], record["net_tx_bytes"] = after[0] - before[0], after[1] - before[1]
    else:
        record["net_rx_bytes"] = record["net_tx_bytes"] = None
        nulls["net_rx_bytes"] = nulls["net_tx_bytes"] = f"no counters for interface {ctx['iface']!r}"

    summary = progress.summarize(rawjson, ctx["base_blobs"])
    steps = summary.pop("_steps")
    record.update(summary)
    record["steps"] = [{"label": progress.label(s), "cached": s["cached"], "duration_s": s["duration_s"]} for s in steps]
    record["cache_hit_ratio"] = summary["n_cached"] / summary["n_vertices"] if summary["n_vertices"] else None
    if not summary["n_vertices"]:
        nulls["cache_hit_ratio"] = "no build-step vertices in rawjson"

    with open(rawjson, encoding="utf-8", errors="replace") as fh:
        tail = [line.rstrip() for line in fh if not line.lstrip().startswith("{")]
    record["error_text"] = "\n".join(tail[-30:]) if proc.returncode != 0 else None
    if proc.returncode != 0:
        flags.append("build_failed")

    # Expected vs observed reusable steps.
    # Seed builds start without --cache-from, so nothing is expected to be cached.
    expected = scen.expected_cached(ctx["steps"], ctx["expect"], scenario_name, mode) if phase == "measured" else []
    record["expected_cached_steps"] = expected
    record["expected_n_cached"] = len(expected)
    observed_labels = {lbl for lbl in summary["step_labels"] if not lbl.endswith(" FROM")}
    declared_labels = {f"{s['stage']} {s['index']}/{s['count']} {s['instruction']}" for s in ctx["steps"]
                       if s["instruction"] != "FROM"}
    if proc.returncode == 0:
        if observed_labels != declared_labels:
            flags.append("step_list_mismatch")
            record["step_list_diff"] = {"missing": sorted(declared_labels - observed_labels),
                                        "unexpected": sorted(observed_labels - declared_labels)}
        if set(summary["cached_steps"]) != set(expected):
            flags.append("cache_behaviour_mismatch")
            record["cache_behaviour_diff"] = {
                "expected_not_cached": sorted(set(expected) - set(summary["cached_steps"])),
                "cached_not_expected": sorted(set(summary["cached_steps"]) - set(expected)),
            }
    if mode in CACHE_MODES and phase == "measured" and not summary["import_refs"]:
        flags.append("import_vertex_missing")
    if mode in CACHE_MODES and summary["export_cache_s"] is None:
        flags.append("export_vertex_missing")
    if mode in CACHE_MODES and phase == "measured" and not ctx["seed_ok"][mode]:
        flags.append("seed_failed")

    # Null reasons for diagnostic phase times.
    if mode == "none":
        for key in ("import_s", "export_cache_s", "export_prepare_s", "export_write_layers_s", "export_write_manifest_s"):
            nulls[key] = "mode=none: no cache import/export"
    else:
        if phase == "seed":
            nulls["import_s"] = "seed build: no --cache-from"
        elif summary["import_s"] is None:
            nulls["import_s"] = "no 'importing cache manifest' vertex in rawjson"
        for key in ("export_cache_s", "export_prepare_s", "export_write_layers_s", "export_write_manifest_s"):
            if summary[key] is None:
                nulls[key] = "no matching cache-export vertex/status in rawjson"
    if summary["export_image_s"] is None:
        nulls["export_image_s"] = "no image-export vertex in rawjson"
    if summary["buildkit_span_s"] is None:
        nulls["buildkit_span_s"] = "no timestamps in rawjson"

    # Cache size in the registry after export.
    cache_keys = ("cache_manifest_digest", "cache_manifest_media_type", "cache_config_media_type",
                  "cache_blobs", "cache_descriptors", "cache_bytes", "cache_bytes_excl_base")
    if cache_to and proc.returncode == 0:
        size, error = cache_size(cache_to, ctx["base_blobs"])
        if size:
            record.update(size)
        else:
            record.update({k: None for k in cache_keys})
            nulls.update({k: error for k in cache_keys})
    else:
        record.update({k: None for k in cache_keys})
        reason = "mode=none: no cache exported" if not cache_to else "build failed: no cache exported"
        nulls.update({k: reason for k in cache_keys})

    # Final image size (loaded into the docker image store, never pushed).
    if proc.returncode == 0:
        size = run(["docker", "image", "inspect", image_tag, "--format", "{{.Size}}"])
        record["image_size_bytes"] = int(size.stdout.strip()) if size.returncode == 0 else None
        if size.returncode != 0:
            nulls["image_size_bytes"] = "docker image inspect failed: " + size.stderr.strip()[-200:]
        run(["docker", "image", "rm", "-f", image_tag])
    else:
        record["image_size_bytes"] = None
        nulls["image_size_bytes"] = "build failed"

    record["builder_removed"] = remove_builder(builder)
    if not record["builder_removed"]:
        flags.append("builder_not_removed")
    record["flags"] = flags
    record["null_reasons"] = nulls
    if not args.keep_rawjson:
        shutil.rmtree(work, ignore_errors=True)
    return record


# ---------------------------------------------------------------- job

def prepare_source(project_dir, config, workdir):
    source_dir = os.path.join(workdir, "src")
    shutil.rmtree(source_dir, ignore_errors=True)
    source = config["source"]
    if "git" in source:
        clone = run(["git", "-c", "advice.detachedHead=false", "clone", "--quiet", "--depth", "1",
                     "--branch", source["tag"], source["git"], source_dir])
        if clone.returncode != 0:
            raise RuntimeError("git clone failed: " + clone.stderr)
        head = run(["git", "-C", source_dir, "rev-parse", "HEAD"]).stdout.strip()
        if head != source["commit"]:
            raise RuntimeError(f"{source['tag']} resolves to {head}, expected {source['commit']}")
        commit = head
    else:
        shutil.copytree(os.path.join(project_dir, source["local"]), source_dir)
        commit = None
    build_dir = os.path.join(workdir, "dockerfile")
    shutil.rmtree(build_dir, ignore_errors=True)
    os.makedirs(build_dir)
    for name in (config["dockerfile"], config["dockerfile"] + ".dockerignore"):
        shutil.copy2(os.path.join(project_dir, name), os.path.join(build_dir, os.path.basename(name)))
    return source_dir, os.path.join(build_dir, os.path.basename(config["dockerfile"])), commit


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", required=True)
    parser.add_argument("--variant", default="default")
    parser.add_argument("--scenario", required=True, choices=["S0", "S1", "S2", "S3"])
    parser.add_argument("--shard", type=int, required=True)
    parser.add_argument("--trials", type=int, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", default="1")
    parser.add_argument("--cache-repo", required=True, help="e.g. ghcr.io/<owner>/<repo>/cache")
    parser.add_argument("--mirror", required=True, help="e.g. ghcr.io/<owner>/<repo>/mirror")
    parser.add_argument("--buildkit-image", required=True, help="BuildKit image ref pinned by digest")
    parser.add_argument("--buildkitd-config", default=None)
    parser.add_argument("--driver-opt", action="append", default=[], help="extra driver opts (local tests)")
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--keep-rawjson", action="store_true")
    args = parser.parse_args()

    project_dir = os.path.join(ROOT, "projects", args.project)
    with open(os.path.join(project_dir, "project.json"), encoding="utf-8") as fh:
        config = json.load(fh)
    variant = config["variants"][args.variant]
    os.makedirs(args.workdir, exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)

    pulled = run(["docker", "pull", "--quiet", args.buildkit_image])
    if pulled.returncode != 0:
        raise SystemExit("cannot pull BuildKit image: " + pulled.stderr)

    source_dir, dockerfile, commit = prepare_source(project_dir, config, args.workdir)
    with open(dockerfile, encoding="utf-8") as fh:
        original_dockerfile = fh.read()
    job = {
        "run_id": args.run_id,
        "run_attempt": args.run_attempt,
        "job": os.environ.get("GITHUB_JOB"),
        "shard": args.shard,
        "project": args.project,
        "variant": args.variant,
        "ecosystem": config["ecosystem"],
        "source_tag": config["source"].get("tag"),
        "source_commit": commit,
        "job_name": f"{args.project}/{args.variant} {args.scenario} shard {args.shard}",
        "trials_per_job": args.trials,
        "harness_commit": os.environ.get("GITHUB_SHA"),
        "modification": None,
    }
    ref_prefix = f"{args.cache_repo}:{args.project}-{args.variant}-{args.scenario}-{args.run_id}-{args.run_attempt}-{args.shard}"
    ctx = {
        "args": args,
        "job": job,
        "runner": runner_info(args.buildkit_image),
        "iface": primary_interface(),
        "base_blobs": base_blobs(original_dockerfile, args.mirror),
        "build_args": {"MIRROR": args.mirror, **variant["build_args"]},
        "source_dir": source_dir,
        "dockerfile": dockerfile,
        "expect": config["expect"],
        "steps": scen.steps(original_dockerfile),
        "ref_prefix": ref_prefix,
        "seed_refs": {},
        "seed_ok": {},
    }
    ctx["runner"]["net_iface"] = ctx["iface"]
    rng = random.Random(f"{args.run_id}:{args.run_attempt}:{args.project}:{args.variant}:{args.scenario}:{args.shard}")

    with open(args.out, "a", encoding="utf-8") as out:
        def emit(record):
            out.write(json.dumps(record, sort_keys=True) + "\n")
            out.flush()
            log(f"{record['phase']} trial={record['trial']} mode={record['mode']} exit={record.get('exit_code')} "
                f"wall_s={record.get('wall_s')} cached={record.get('n_cached')}/{record.get('n_vertices')} "
                f"flags={record.get('flags')}")

        for pos, mode in enumerate(rng.sample(CACHE_MODES, len(CACHE_MODES)), start=1):
            record = measure(ctx, "seed", mode, 0, pos, args.scenario)
            ctx["seed_refs"][mode] = record["cache_to_ref"]
            ctx["seed_ok"][mode] = record.get("exit_code") == 0
            emit(record)

        modification = None
        if args.scenario != "S0":
            modification = scen.apply(config["scenarios"][args.scenario], source_dir, dockerfile)
            with open(dockerfile, encoding="utf-8") as fh:
                ctx["steps"] = scen.steps(fh.read())
        job["modification"] = modification

        for trial in range(1, args.trials + 1):
            for pos, mode in enumerate(rng.sample(MODES, len(MODES)), start=1):
                emit(measure(ctx, "measured", mode, trial, pos, args.scenario))


if __name__ == "__main__":
    main()
