"""Unit tests for the stdlib harness modules: python3 -m unittest discover -s tests"""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "harness"))
import progress  # noqa: E402
import scenario  # noqa: E402

FIXTURES = os.path.join(ROOT, "tests", "fixtures")


def project(name):
    with open(os.path.join(ROOT, "projects", name, "project.json"), encoding="utf-8") as fh:
        config = json.load(fh)
    with open(os.path.join(ROOT, "projects", name, config["dockerfile"]), encoding="utf-8") as fh:
        return config, fh.read()


class DockerfileTest(unittest.TestCase):
    def test_step_labels_match_buildkit(self):
        _, dockerfile = project("synthetic")
        labels = [f"{s['stage']} {s['index']}/{s['count']} {s['instruction']}" for s in scenario.steps(dockerfile)]
        observed = progress.summarize(os.path.join(FIXTURES, "synthetic-s1-max.rawjson"))["step_labels"]
        # the runtime FROM uses the same image as the builder FROM, so BuildKit shows one FROM vertex
        self.assertEqual(sorted(set(labels) - {"runtime 1/3 FROM"}), sorted(observed))

    def test_first_run_patch_changes_only_first_builder_run(self):
        for name in ("synthetic", "uptime-kuma", "netbox", "caddy"):
            config, dockerfile = project(name)
            patched, where = scenario.patch_first_run(dockerfile, "builder", " && true")
            before, after = scenario.steps(dockerfile), scenario.steps(patched)
            changed = [a for b, a in zip(before, after) if a["text"] != b["text"]]
            self.assertEqual(len(changed), 1, name)
            self.assertEqual((changed[0]["stage"], changed[0]["index"], changed[0]["instruction"]),
                             ("builder", config["expect"]["invalidated_from"]["S3"], "RUN"), name)

    def test_invalidation_points_name_the_modified_inputs(self):
        for name in ("synthetic", "uptime-kuma", "netbox", "caddy"):
            config, dockerfile = project(name)
            steps = {s["index"]: s for s in scenario.steps(dockerfile) if s["stage"] == "builder"}
            for scen in ("S1", "S2"):
                step = steps[config["expect"]["invalidated_from"][scen]]
                self.assertEqual(step["instruction"], "COPY", f"{name} {scen}")
                target = config["scenarios"][scen]["path"]
                sources = step["text"].split()[1:-1]
                self.assertTrue(any(s in (".", target) or target.startswith(s.rstrip("/") + "/") for s in sources),
                                f"{name} {scen}: {step['text']}")


class ExpectationTest(unittest.TestCase):
    def test_matches_observed_synthetic_builds(self):
        config, dockerfile = project("synthetic")
        steps = scenario.steps(dockerfile)
        for fixture, scen, mode in (("synthetic-s1-max.rawjson", "S1", "max"), ("synthetic-s3-min.rawjson", "S3", "min")):
            observed = progress.summarize(os.path.join(FIXTURES, fixture))["cached_steps"]
            self.assertEqual(sorted(observed), sorted(scenario.expected_cached(steps, config["expect"], scen, mode)))

    def test_none_and_s0(self):
        config, dockerfile = project("netbox")
        steps = scenario.steps(dockerfile)
        self.assertEqual(scenario.expected_cached(steps, config["expect"], "S2", "none"), [])
        non_from = [s for s in steps if s["instruction"] != "FROM"]
        for mode in ("min", "max"):
            self.assertEqual(len(scenario.expected_cached(steps, config["expect"], "S0", mode)), len(non_from))


class ProgressTest(unittest.TestCase):
    def test_summary(self):
        summary = progress.summarize(os.path.join(FIXTURES, "synthetic-s1-max.rawjson"))
        self.assertEqual((summary["n_vertices"], summary["n_cached"]), (9, 5))
        self.assertEqual(summary["n_run_executed"], 2)
        self.assertIsNotNone(summary["import_s"])
        self.assertIsNotNone(summary["export_cache_s"])
        self.assertGreater(summary["pull_cache_bytes"], 0)
        self.assertEqual(summary["rawjson_unparsed_lines"], 0)


class ApplyTest(unittest.TestCase):
    def test_apply_changes_checksum(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "package.json")
            with open(path, "w") as fh:
                fh.write('{\n    "name": "x"\n}\n')
            result = scenario.apply({"kind": "replace_once", "path": "package.json", "old": "{\n",
                                     "new": '{\n    "x-replication-scenario": "S2",\n'}, tmp, None)
            self.assertNotEqual(result["sha256_before"], result["sha256_after"])
            with open(path) as fh:
                self.assertEqual(json.load(fh)["x-replication-scenario"], "S2")


if __name__ == "__main__":
    unittest.main()
