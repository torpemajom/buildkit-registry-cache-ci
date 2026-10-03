"""Parse `docker buildx build --progress=rawjson` output (one SolveStatus JSON per line).

All phase times are diagnostic: BuildKit runs vertices concurrently, so the
phases overlap and do not add up to the wall-clock duration of the build.
"""
import base64
import binascii
import json
import re
from datetime import datetime

# "[builder 2/8] RUN ...", "[runtime 3/3] COPY --from=builder ...", "[2/5] RUN ..."
STEP_RE = re.compile(r"^\[(?:(?P<stage>[^\]\s]+) )?(?P<index>\d+)/(?P<count>\d+)\] (?P<instruction>[A-Z]+)\b")
BLOB_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
IMPORT_PREFIX = "importing cache manifest from "
CACHE_EXPORT_NAMES = ("exporting cache to registry", "exporting cache")
IMAGE_EXPORT_PREFIXES = ("exporting to ", "importing to docker", "sending tarball")
# Printed by projects/synthetic/context/work.py
SYNTHETIC_RE = re.compile(r"step=(?P<step>\S+) cpu_iters=(?P<iters>\d+) cpu_s=(?P<cpu_s>[0-9.]+) bytes=(?P<bytes>\d+)")


def _time(value):
    if not value:
        return None
    # BuildKit emits RFC 3339 with nanoseconds; datetime accepts at most microseconds.
    match = re.match(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(\.\d+)?(Z|[+-]\d\d:\d\d)$", value)
    if not match:
        return None
    base, fraction, zone = match.groups()
    fraction = (fraction or ".0")[:7]
    zone = "+00:00" if zone == "Z" else zone
    return datetime.fromisoformat(base + fraction + zone)


def _text(value):
    """Warning texts are []byte in Go, i.e. base64 in JSON."""
    if not value:
        return None
    try:
        return base64.b64decode(value, validate=True).decode("utf-8", "replace")
    except (binascii.Error, ValueError):
        return value


def _duration(item):
    started, completed = _time(item.get("started")), _time(item.get("completed"))
    if started is None or completed is None:
        return None
    return (completed - started).total_seconds()


def _span(items):
    starts = [_time(i.get("started")) for i in items]
    ends = [_time(i.get("completed")) for i in items]
    starts = [s for s in starts if s is not None]
    ends = [e for e in ends if e is not None]
    if not starts or not ends:
        return None
    return (max(ends) - min(starts)).total_seconds()


def load(path):
    """Merge the incremental updates into final vertex and status records."""
    vertices, statuses, warnings, logs, unparsed = {}, {}, [], [], 0
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line.startswith("{"):
                if line:
                    unparsed += 1
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                unparsed += 1
                continue
            for vertex in record.get("vertexes") or []:
                merged = vertices.setdefault(vertex["digest"], {})
                merged.update({k: v for k, v in vertex.items() if v is not None})
            for status in record.get("statuses") or []:
                merged = statuses.setdefault((status.get("vertex"), status.get("id")), {})
                merged.update({k: v for k, v in status.items() if v is not None})
            for warning in record.get("warnings") or []:
                warnings.append(_text(warning.get("short")))
            for log in record.get("logs") or []:
                logs.append(_text(log.get("data")) or "")
    return vertices, statuses, warnings, logs, unparsed


def steps_of(vertices):
    """Dockerfile step vertices in label order: dicts with stage, index, count, instruction, cached."""
    steps = []
    for digest, vertex in vertices.items():
        match = STEP_RE.match(vertex.get("name", ""))
        if not match:
            continue
        steps.append({
            "digest": digest,
            "stage": match.group("stage") or "",
            "index": int(match.group("index")),
            "count": int(match.group("count")),
            "instruction": match.group("instruction"),
            "name": vertex["name"],
            "cached": bool(vertex.get("cached")),
            "duration_s": _duration(vertex),
            "error": vertex.get("error"),
        })
    steps.sort(key=lambda s: (s["stage"], s["index"]))
    return steps


def label(step):
    return f"{step['stage']} {step['index']}/{step['count']} {step['instruction']}".strip()


def summarize(path, base_blobs=frozenset()):
    """Summary metrics of one build. `base_blobs` are layer digests of the base images."""
    vertices, statuses, warnings, logs, unparsed = load(path)
    steps = steps_of(vertices)
    synthetic = [
        {"step": m.group("step"), "cpu_iters": int(m.group("iters")), "cpu_s": float(m.group("cpu_s")), "bytes": int(m.group("bytes"))}
        for m in SYNTHETIC_RE.finditer("".join(logs))
    ]
    # FROM vertices are image sources: BuildKit never reports them as cached,
    # so they are excluded from the reusable-step counts.
    counted = [s for s in steps if s["instruction"] != "FROM"]
    by_name = lambda pred: [v for v in vertices.values() if pred(v.get("name", ""))]

    imports = by_name(lambda n: n.startswith(IMPORT_PREFIX))
    cache_exports = by_name(lambda n: n in CACHE_EXPORT_NAMES)
    image_exports = by_name(lambda n: n.startswith(IMAGE_EXPORT_PREFIXES))
    export_digests = {v["digest"] for v in cache_exports}
    export_statuses = [s for (vertex, _), s in statuses.items() if vertex in export_digests]

    def export_part(prefix):
        items = [s for s in export_statuses if (s.get("id") or "").startswith(prefix)]
        return _span(items) if items else None

    run_steps = [s for s in counted if s["instruction"] == "RUN" and not s["cached"]]
    run_durations = [s["duration_s"] for s in run_steps if s["duration_s"] is not None]

    # Blob downloads appear as statuses whose id is the blob digest (with byte totals).
    pulled = {}
    for (_, status_id), status in statuses.items():
        if status_id and BLOB_RE.match(status_id) and status.get("total"):
            pulled[status_id] = max(pulled.get(status_id, 0), int(status["total"]))
    base_pull = sum(size for digest, size in pulled.items() if digest in base_blobs)
    other_pull = sum(size for digest, size in pulled.items() if digest not in base_blobs)

    errors = [v["error"] for v in vertices.values() if v.get("error")]
    return {
        "n_vertices_total": len(vertices),
        "n_vertices": len(counted),
        "n_cached": sum(1 for s in counted if s["cached"]),
        "cached_steps": [label(s) for s in counted if s["cached"]],
        "executed_steps": [label(s) for s in counted if not s["cached"]],
        "step_labels": [label(s) for s in steps],
        "import_s": sum(_duration(v) or 0.0 for v in imports) if imports else None,
        "import_refs": [v["name"][len(IMPORT_PREFIX):] for v in imports],
        "export_cache_s": sum(_duration(v) or 0.0 for v in cache_exports) if cache_exports else None,
        "export_prepare_s": export_part("preparing build cache for export"),
        "export_write_layers_s": export_part("writing layer "),
        "export_write_manifest_s": export_part("writing cache"),
        "export_image_s": _span(image_exports) if image_exports else None,
        "exec_run_s": sum(run_durations) if run_steps else 0.0,
        "n_run_executed": len(run_steps),
        "buildkit_span_s": _span(list(vertices.values())),
        "pulled_blobs": len(pulled),
        "pull_base_bytes": base_pull,
        "pull_other_bytes": other_pull,
        "vertex_errors": errors,
        "synthetic_steps": synthetic or None,
        "warnings": [w for w in warnings if w],
        "rawjson_unparsed_lines": unparsed,
        "_steps": steps,
    }
