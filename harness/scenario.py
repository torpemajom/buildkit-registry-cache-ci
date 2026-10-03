"""Dockerfile step listing, scenario modifications and expected cache behaviour."""
import hashlib
import os
import re

# Instructions for which the Dockerfile frontend emits a build-step vertex.
VERTEX_INSTRUCTIONS = {"FROM", "RUN", "COPY", "ADD", "WORKDIR"}
FROM_RE = re.compile(r"^FROM\s+(?:--\S+\s+)*(?P<image>\S+)(?:\s+AS\s+(?P<name>\S+))?\s*$", re.IGNORECASE)


def logical_lines(text):
    """(first_physical_line, last_physical_line, joined_text) for each instruction."""
    lines = text.split("\n")
    out, i = [], 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        start, parts = i, []
        while True:
            line = lines[i]
            if line.rstrip().endswith("\\"):
                parts.append(line.rstrip()[:-1])
                i += 1
                # comment lines inside a continuation are dropped by the parser
                while i < len(lines) and lines[i].strip().startswith("#"):
                    i += 1
                if i >= len(lines):
                    break
                continue
            parts.append(line)
            break
        out.append((start, i, " ".join(p.strip() for p in parts)))
        i += 1
    return out


def steps(text):
    """Vertex-producing steps as BuildKit labels them: [{stage, index, count, instruction, text}]."""
    stages, current = [], None
    for _, _, instruction in logical_lines(text):
        keyword = instruction.split(None, 1)[0].upper()
        if keyword == "FROM":
            match = FROM_RE.match(instruction)
            name = match.group("name") if match and match.group("name") else f"stage-{len(stages)}"
            current = {"name": name, "steps": []}
            stages.append(current)
        if current is not None and keyword in VERTEX_INSTRUCTIONS:
            current["steps"].append((keyword, instruction))
    result = []
    for stage in stages:
        for index, (keyword, instruction) in enumerate(stage["steps"], start=1):
            result.append({
                "stage": stage["name"],
                "index": index,
                "count": len(stage["steps"]),
                "instruction": keyword,
                "text": instruction,
            })
    return result


def patch_first_run(text, stage, suffix):
    """Append `suffix` to the first RUN instruction of `stage` (end of its last physical line)."""
    lines = text.split("\n")
    in_stage = False
    for start, end, instruction in logical_lines(text):
        keyword = instruction.split(None, 1)[0].upper()
        if keyword == "FROM":
            match = FROM_RE.match(instruction)
            in_stage = bool(match and match.group("name") == stage)
        elif in_stage and keyword == "RUN":
            lines[end] = lines[end].rstrip() + suffix
            return "\n".join(lines), {"line": end + 1, "instruction": "RUN"}
    raise ValueError(f"no RUN instruction in stage {stage!r}")


def sha256_file(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def apply(spec, source_dir, dockerfile_path):
    """Apply one scenario modification in place. Returns a description for the results."""
    kind = spec["kind"]
    if kind == "first_run":
        target = dockerfile_path
        before = sha256_file(target)
        with open(target, encoding="utf-8") as fh:
            patched, where = patch_first_run(fh.read(), spec["stage"], spec["suffix"])
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(patched)
        detail = {"file": "Dockerfile", **where}
    elif kind in ("append", "replace_once"):
        target = os.path.join(source_dir, spec["path"])
        before = sha256_file(target)
        with open(target, encoding="utf-8") as fh:
            content = fh.read()
        if kind == "append":
            content += spec["text"]
        else:
            if content.count(spec["old"]) < 1:
                raise ValueError(f"{spec['path']}: pattern not found")
            content = content.replace(spec["old"], spec["new"], 1)
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(content)
        detail = {"file": spec["path"]}
    else:
        raise ValueError(f"unknown modification kind {kind!r}")
    after = sha256_file(target)
    if before == after:
        raise ValueError(f"modification did not change {target}")
    return {"kind": kind, **detail, "sha256_before": before, "sha256_after": after}


def expected_cached(dockerfile_steps, expect, scenario, mode):
    """Labels of the steps expected to be CACHED (FROM excluded; see progress.summarize).

    `expect` (from project.json):
      builder_stage: the stage the scenarios modify;
      invalidated_from: {scenario: first invalidated step index in builder_stage};
      other_stages: {stage: {scenario: first invalidated step index or null}} - for the
        stages that COPY --from the builder; content-addressed, so declared per scenario.
    Mode semantics (verified with BuildKit v0.33.1): `max` keeps every step before the
    invalidation point; `min` stores results only for the final image, so builder
    steps are reusable only when nothing changed (S0). In `min` mode S1-S3 therefore
    rebuild the whole builder stage, so a content-addressed step of a later stage is
    reused only if a full rebuild reproduces the copied files (the S3 declaration)
    and the scenario itself does not change them.
    """
    if mode == "none":
        return []
    cached = []
    for step in dockerfile_steps:
        if step["instruction"] == "FROM":
            continue
        if scenario == "S0":
            hit = True
        elif step["stage"] == expect["builder_stage"]:
            hit = mode == "max" and step["index"] < expect["invalidated_from"][scenario]
        else:
            declared = expect["other_stages"][step["stage"]]
            points = [declared[scenario]] + ([declared["S3"]] if mode == "min" else [])
            points = [p for p in points if p is not None]
            hit = not points or step["index"] < min(points)
        if hit:
            cached.append(f"{step['stage']} {step['index']}/{step['count']} {step['instruction']}")
    return cached
