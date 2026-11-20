"""Tests for scripts/lbo.py. Each test builds a throwaway git repository."""
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

LBO = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "lbo.py"


def run(args, cwd, check=True):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if check and r.returncode:
        raise AssertionError(f"{args} failed:\n{r.stdout}\n{r.stderr}")
    return r


def lbo(cwd, *args, check=True):
    return run([sys.executable, str(LBO), *args], cwd, check=check)


def write(root, rel, text="x\n"):
    p = pathlib.Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


CONFIG = {
    "base_branch": "main",
    "default_level": 2,
    "size_limit_lines": 50,
    "module_depth": 2,
    "min_level_paths": {"backend/**": 2},
    "level_labels": {"chore": 0, "ui": 1, "backend": 2, "security": 3},
    "sensitive_paths": ["backend/app/auth/**"],
    "prod_hosts": ["live.example.com"],
    "forced_full": [],
    "suites": {
        "backend": {
            "cwd": "backend", "paths": ["backend/**"],
            "test_globs": ["backend/tests/test_*.py"],
            "forced_full": ["backend/conftest.py"],
            "always_run": ["backend/tests/test_auth.py"],
            "full": "pytest -q", "focused": "pytest -q {files}", "related": None,
        },
        "web": {
            "cwd": "web", "paths": ["web/src/**"],
            "test_globs": ["web/src/**/*.test.ts"],
            "forced_full": [], "always_run": [], "file_prefix": "--include ",
            "full": "vitest run", "focused": "vitest run {files}",
            "related": "vitest related {files}",
        },
    },
}


class LboTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="lbo-test-")
        self.repo = pathlib.Path(self.dir) / "repo"
        self.repo.mkdir()
        r = self.repo
        run(["git", "init", "-q", "-b", "main", "."], r)
        run(["git", "config", "user.email", "test@example.com"], r)
        run(["git", "config", "user.name", "test"], r)
        run(["git", "config", "core.autocrlf", "false"], r)
        write(r, "backend/app/services/billing_calc.py")
        write(r, "backend/app/auth/session.py")
        write(r, "backend/conftest.py")
        for name in ("billing_calc", "auth", "other", "third", "fourth", "fifth"):
            write(r, f"backend/tests/test_{name}.py", "def test_x(): pass\n")
        write(r, "backend/tests/test_live_site.py", "URL = 'https://live.example.com'\n")
        write(r, "web/src/(app)/card.ts")
        for name in ("card", "b", "c", "d"):
            write(r, f"web/src/(app)/{name}.test.ts")
        write(r, ".lbo/config.json", json.dumps(CONFIG))
        run(["git", "add", "-A"], r)
        run(["git", "commit", "-q", "-m", "base"], r)
        run(["git", "checkout", "-q", "-b", "lane"], r)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def level(self, *args):
        return json.loads(lbo(self.repo, "level", *args).stdout)

    def plan_for(self, tier):
        return json.loads(lbo(self.repo, "tests", "--tier", str(tier)).stdout)

    def suite(self, plan, name):
        return next(p for p in plan["plan"] if p["suite"] == name)

    def test_label_sets_the_level(self):
        write(self.repo, "web/src/(app)/card.ts", "y\n")
        self.assertEqual(self.level("--labels", "ui")["level"], 1)

    def test_backend_path_raises_a_ui_label(self):
        write(self.repo, "backend/app/services/billing_calc.py", "y\n")
        self.assertEqual(self.level("--labels", "ui")["level"], 2)

    def test_sensitive_path_forces_level_three(self):
        write(self.repo, "backend/app/auth/session.py", "y\n")
        out = self.level("--labels", "chore")
        self.assertEqual(out["level"], 3)
        self.assertTrue(any("sensitive" in r for r in out["reasons"]))

    def test_large_diff_and_refuted_assumption_each_add_one(self):
        write(self.repo, "web/src/(app)/card.ts", "\n".join(str(i) for i in range(80)) + "\n")
        self.assertEqual(self.level("--labels", "chore")["level"], 1)
        self.assertEqual(self.level("--labels", "chore", "--refuted")["level"], 2)

    def test_focused_selection_matches_by_name_and_quotes_odd_paths(self):
        write(self.repo, "backend/app/services/billing_calc.py", "y\n")
        write(self.repo, "web/src/(app)/card.ts", "y\n")
        plan = self.plan_for(1)
        be = self.suite(plan, "backend")
        self.assertEqual(be["scope"], "focused")
        self.assertEqual(be["commands"], ["pytest -q tests/test_billing_calc.py"])
        web = self.suite(plan, "web")
        self.assertIn('--include "src/(app)/card.test.ts"', web["commands"][0])
        self.assertTrue(web["commands"][1].startswith("vitest related"))

    def test_forced_full_path_returns_the_full_suite(self):
        write(self.repo, "backend/conftest.py", "y\n")
        be = self.suite(self.plan_for(1), "backend")
        self.assertEqual((be["scope"], be["commands"]), ("full", ["pytest -q"]))

    def test_tier_two_adds_always_run_and_tier_three_runs_everything(self):
        write(self.repo, "backend/app/services/billing_calc.py", "y\n")
        be = self.suite(self.plan_for(2), "backend")
        self.assertIn("tests/test_auth.py", be["commands"][0])
        self.assertTrue(all(p["scope"] == "full" for p in self.plan_for(3)["plan"]))

    def test_test_files_naming_a_production_host_are_never_selected(self):
        write(self.repo, "backend/tests/test_live_site.py", "URL = 'https://live.example.com/x'\n")
        plan = self.plan_for(1)
        cmds = " ".join(c for p in plan["plan"] for c in p["commands"])
        self.assertNotIn("test_live_site", cmds)
        self.assertTrue(any("production host" in n for n in plan["notes"]))

    def test_unmapped_source_files_are_reported(self):
        write(self.repo, "backend/app/services/brand_new_thing.py")
        be = self.suite(self.plan_for(1), "backend")
        self.assertIn("backend/app/services/brand_new_thing.py", be["unmapped"])

    def test_run_records_pass_fail_and_proof_runs(self):
        py = sys.executable
        ok = lbo(self.repo, "run", "--name", "ok", "--", f'"{py}" -c "print(42)"')
        self.assertIn("PASSED", ok.stdout)
        bad = lbo(self.repo, "run", "--name", "bad", "--", f'"{py}" -c "raise SystemExit(2)"',
                  check=False)
        self.assertEqual(bad.returncode, 1)
        proof = lbo(self.repo, "run", "--name", "proof", "--expect-fail", "--",
                    f'"{py}" -c "raise SystemExit(1)"')
        self.assertIn("FAILED AS EXPECTED", proof.stdout)
        vacuous = lbo(self.repo, "run", "--name", "vac", "--expect-fail", "--",
                      f'"{py}" -c "print(1)"', check=False)
        self.assertEqual(vacuous.returncode, 1)
        rows = [json.loads(x) for x in
                (self.repo / ".lbo" / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["ok"] for r in rows], [True, False, True, False])

    def test_findings_dispositions_and_report(self):
        f = self.repo / "round1.json"
        f.write_text(json.dumps({"findings": [
            {"severity": "High", "class": "semantic", "file": "a.py", "title": "race on insert"},
            {"severity": "low", "class": "pattern", "file": "b.py", "title": "naive utcnow"}]}),
            encoding="utf-8")
        out = lbo(self.repo, "finding", "import", str(f), "--round", "1", "--reviewer", "rev-a")
        fid = out.stdout.splitlines()[1].split()[0]
        lbo(self.repo, "finding", "dispose", "--id", fid, "--real", "no", "--became", "declined")
        empty = self.repo / "round2.json"
        empty.write_text("[]", encoding="utf-8")
        lbo(self.repo, "finding", "import", str(empty), "--round", "2", "--reviewer", "rev-a")
        lbo(self.repo, "escape", "--test", "tests/test_x.py", "--reason", "template change")
        report = lbo(self.repo, "report").stdout
        self.assertIn("median 2, max 2", report)
        self.assertIn("rev-a         2 /   1 /   1", report)
        self.assertIn("Test selection escapes: 1", report)

    def test_worktrees_removes_only_merged_and_clean(self):
        run(["git", "checkout", "-q", "main"], self.repo)
        base = pathlib.Path(self.dir)
        run(["git", "worktree", "add", "-q", "-b", "done", str(base / "wt-done")], self.repo)
        run(["git", "worktree", "add", "-q", "-b", "open", str(base / "wt-open")], self.repo)
        run(["git", "worktree", "add", "-q", "-b", "dirty", str(base / "wt-dirty")], self.repo)
        write(base / "wt-open", "new.txt")
        run(["git", "add", "-A"], base / "wt-open")
        run(["git", "commit", "-q", "-m", "unmerged work"], base / "wt-open")
        write(base / "wt-dirty", "scratch.txt")
        listing = lbo(self.repo, "worktrees").stdout
        self.assertIn("1 safe to remove, 2 kept", listing)
        self.assertIn("Nothing was removed", listing)
        lbo(self.repo, "worktrees", "--remove")
        self.assertFalse((base / "wt-done").exists())
        self.assertTrue((base / "wt-open").exists())
        self.assertTrue((base / "wt-dirty" / "scratch.txt").exists())

    def test_lane_worktree_reads_the_main_checkout_config(self):
        run(["git", "checkout", "-q", "main"], self.repo)
        run(["git", "rm", "-q", "--cached", ".lbo/config.json"], self.repo)
        run(["git", "commit", "-q", "-m", "untrack config"], self.repo)
        wt = pathlib.Path(self.dir) / "wt-lane"
        run(["git", "worktree", "add", "-q", "-b", "lane2", str(wt)], self.repo)
        self.assertFalse((wt / ".lbo" / "config.json").exists())
        write(wt, "web/src/(app)/card.ts", "y\n")
        out = json.loads(lbo(wt, "level", "--labels", "ui").stdout)
        self.assertEqual(out["level"], 1)


if __name__ == "__main__":
    unittest.main()
