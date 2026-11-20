#!/usr/bin/env python3
"""lbo: helper for lean build orchestration. Standard library only.

Run from inside a project's git checkout (any worktree):

  python lbo.py init                       create .lbo/ with a config to fill in
  python lbo.py level --labels ui,bounded  which review level this lane gets
  python lbo.py tests --tier 1             which tests to run for this diff
  python lbo.py run --name be-t1 -- CMD    run CMD to completion, log it, print the tail
  python lbo.py finding import FILE ...    log a reviewer's findings (JSON)
  python lbo.py finding add ...            log one finding
  python lbo.py finding dispose ...        record what happened to a finding
  python lbo.py escape --test X --reason Y log a test the selector wrongly skipped
  python lbo.py report                     rounds, finding classes, test hours
  python lbo.py worktrees [--sizes]        which lane worktrees are safe to remove
  python lbo.py worktrees --remove         remove the merged, clean ones
"""
import argparse
import datetime
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import sys
import time

CLASSES = ["pattern", "convention", "semantic", "test-gap", "unclassified"]
SEVERITIES = ["critical", "high", "medium", "low"]
GENERIC_STEMS = {"index", "utils", "util", "types", "main", "app", "base", "common",
                 "helpers", "config", "constants", "models", "schemas", "page", "route",
                 "layout", "__init__", "conftest", "setup"}
REVIEW = {
    0: "Gates only. No reviewer.",
    1: "One reviewer from a different vendor than the coder: one round plus one confirming round.",
    2: "One reviewer, iterated until a round has no critical, high or medium finding "
       "and the senior-developer verdict is 'impressed'.",
    3: "Two independent reviewers, iterated until both clear the bar, then one fresh full pass.",
}


def sh(args, cwd=None):
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=cwd)
    return r.returncode, r.stdout


_root = None


def root():
    global _root
    if _root is None:
        code, out = sh(["git", "rev-parse", "--show-toplevel"])
        if code:
            sys.exit("lbo: not inside a git repository")
        _root = pathlib.Path(out.strip())
    return _root


def git(*args):
    return sh(["git", *args], cwd=root())[1]


def lbo_dir():
    return root() / ".lbo"


def load_cfg():
    p = lbo_dir() / "config.json"
    if not p.exists():
        # A lane worktree without its own copy uses the main checkout's config.
        common = git("rev-parse", "--path-format=absolute", "--git-common-dir").strip()
        alt = pathlib.Path(common).parent / ".lbo" / "config.json" if common else None
        if alt and alt.exists():
            p = alt
        else:
            sys.exit("lbo: no .lbo/config.json here or in the main checkout. Run: python lbo.py init")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"lbo: .lbo/config.json is not valid JSON: {e}")


def branch():
    return git("rev-parse", "--abbrev-ref", "HEAD").strip() or "unknown"


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def append(name, row):
    lbo_dir().mkdir(exist_ok=True)
    for aux, text in ((".gitattributes", "*.jsonl merge=union\n"), (".gitignore", "runs/\n")):
        if not (lbo_dir() / aux).exists():
            (lbo_dir() / aux).write_text(text, encoding="utf-8", newline="\n")
    with open(lbo_dir() / name, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_rows(name):
    p = lbo_dir() / name
    rows = []
    if p.exists():
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def glob_re(pat):
    out, i = "", 0
    while i < len(pat):
        if pat[i:i + 3] == "**/":
            out += "(?:.*/)?"
            i += 3
        elif pat[i:i + 2] == "**":
            out += ".*"
            i += 2
        elif pat[i] == "*":
            out += "[^/]*"
            i += 1
        elif pat[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pat[i])
            i += 1
    return re.compile("^" + out + "$")


def hit(path, pats):
    return any(glob_re(p).match(path) for p in pats)


def changed(base):
    """Files that differ from the merge base with `base`, including uncommitted and untracked."""
    mb = git("merge-base", base, "HEAD").strip()
    if not mb:
        sys.exit(f"lbo: cannot find a merge base with '{base}'. Pass --base or fix base_branch.")
    files = set()
    for args in (["diff", "--name-only", mb], ["ls-files", "--others", "--exclude-standard"]):
        files.update(x.strip() for x in git(*args).splitlines() if x.strip())
    return sorted(f for f in files if not f.startswith(".lbo/")), mb


def diff_size(mb):
    n = 0
    for line in git("diff", "--numstat", mb).splitlines():
        p = line.split("\t")
        if len(p) >= 3 and p[0].isdigit() and p[1].isdigit() and not p[2].startswith(".lbo/"):
            n += int(p[0]) + int(p[1])
    return n


# ---------------------------------------------------------------- init

def cmd_init(a):
    d = lbo_dir()
    d.mkdir(exist_ok=True)
    made = []
    cfg = d / "config.json"
    if not cfg.exists():
        tpl = pathlib.Path(__file__).resolve().parent.parent / "templates" / "lbo.config.json"
        shutil.copyfile(tpl, cfg)
        made.append("config.json (edit it: suites, sensitive paths, always-run tests)")
    for name, text in ((".gitattributes", "*.jsonl merge=union\n"), (".gitignore", "runs/\n")):
        if not (d / name).exists():
            (d / name).write_text(text, encoding="utf-8", newline="\n")
            made.append(name)
    inv = d / "invariants.md"
    if not inv.exists():
        inv.write_text("# Invariants\n\nOne line per rule the code relies on, with the test that "
                       "proves it. Reviewers are pointed here and told not to re-raise these.\n",
                       encoding="utf-8", newline="\n")
        made.append("invariants.md")
    print("Created in .lbo/: " + (", ".join(made) if made else "nothing, all present"))
    print("Commit .lbo/ (config, invariants, findings.jsonl, runs.jsonl). Run logs are ignored.")


# ---------------------------------------------------------------- level

def cmd_level(a):
    cfg = load_cfg()
    files, mb = changed(a.base or cfg.get("base_branch", "main"))
    labels = [x.strip().lower() for x in (a.labels or "").split(",") if x.strip()]
    table = {k.lower(): v for k, v in cfg.get("level_labels", {}).items()}
    known = [table[x] for x in labels if x in table]
    reasons = []
    if known:
        level = max(known)
        reasons.append(f"labels {labels} give level {level}")
    else:
        level = cfg.get("default_level", 2)
        reasons.append(f"no known label, default level {level}")
    depth = cfg.get("module_depth", 2)
    tests = [g for s in cfg.get("suites", {}).values() for g in s.get("test_globs", [])]
    modules = {"/".join(f.split("/")[:depth]) for f in files if "/" in f and not hit(f, tests)}
    if len(modules) >= 3 and level < 2:
        level = 2
        reasons.append(f"touches {len(modules)} modules, raised to 2")
    for pat, floor in cfg.get("min_level_paths", {}).items():
        if level < floor and any(hit(f, [pat]) for f in files):
            level = floor
            reasons.append(f"touches {pat}, raised to {floor}")
    size = diff_size(mb)
    limit = cfg.get("size_limit_lines", 600)
    if size > limit and level < 3:
        level += 1
        reasons.append(f"diff is {size} lines (limit {limit}), raised one level")
    if a.refuted and level < 3:
        level += 1
        reasons.append("an assumption was refuted after coding began, raised one level")
    sens = [f for f in files if hit(f, cfg.get("sensitive_paths", []))]
    if sens:
        level = 3
        reasons.append("sensitive paths touched: " + ", ".join(sens[:8]) +
                       (f" and {len(sens) - 8} more" if len(sens) > 8 else ""))
    print(json.dumps({"lane": branch(), "level": level, "review": REVIEW[level],
                      "files_changed": len(files), "diff_lines": size, "reasons": reasons},
                     indent=2))


# ---------------------------------------------------------------- tests

def stem_of(path):
    name = pathlib.PurePosixPath(path).name
    return name.split(".")[0]


def cmd_tests(a):
    cfg = load_cfg()
    tier = a.tier
    files, _ = changed(a.base or cfg.get("base_branch", "main"))
    max_fraction = cfg.get("max_fraction", 0.4)
    max_files = cfg.get("max_files", 80)
    plan, notes = [], []
    tracked = [x.strip() for x in git("ls-files").splitlines() if x.strip()]
    for name, s in cfg.get("suites", {}).items():
        cwd = s.get("cwd", "").strip("/")
        strip = s.get("files_root", cwd).strip("/")

        def rel(f, c=strip):
            f = f[len(c) + 1:] if c and f.startswith(c + "/") else f
            return f'"{f}"' if re.search(r"[^A-Za-z0-9_./\-]", f) else f
        if tier == 3:
            plan.append({"suite": name, "scope": "full", "cwd": cwd, "commands": [s["full"]],
                         "why": "release candidate"})
            continue
        mine = [f for f in files if hit(f, s.get("paths", []))]
        always = [t for t in tracked if hit(t, s.get("always_run", []))] if tier >= 2 else []
        if not mine and not always:
            continue
        forced = [f for f in files if hit(f, cfg.get("forced_full", []))] + \
                 [f for f in mine if hit(f, s.get("forced_full", []))]
        if forced and tier >= 1:
            plan.append({"suite": name, "scope": "full", "cwd": cwd, "commands": [s["full"]],
                         "why": "forced full: " + ", ".join(sorted(set(forced))[:6])})
            continue
        globs = s.get("test_globs", [])
        all_tests = [t for t in tracked if hit(t, globs)]
        picked = {f for f in mine if hit(f, globs) and (root() / f).exists()}
        src = [f for f in mine if not hit(f, globs)
               and not f.lower().endswith((".md", ".txt", ".png", ".jpg", ".svg"))]
        unmapped = []
        for f in src:
            st = stem_of(f)
            found = set()
            if len(st) >= 4 and st.lower() not in GENERIC_STEMS:
                # "contains" suits CamelCase test names such as FooServiceEdgeCasesTest.php.
                rx = re.compile(re.escape(st) if s.get("match") == "contains" else
                                r"(^|[_.\-])" + re.escape(st) + r"([_.\-]|$)", re.I)
                found = {t for t in all_tests if rx.search(pathlib.PurePosixPath(t).name)}
            if found:
                picked |= found
            else:
                unmapped.append(f)
        picked |= set(always)
        # Never select a test file that names a production host.
        hosts = cfg.get("prod_hosts", [])
        if hosts:
            def names_prod(t):
                try:
                    body = (root() / t).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    return False
                return any(h in body for h in hosts)
            blocked = sorted(t for t in picked if names_prod(t))
            picked -= set(blocked)
            prod_all = [t for t in all_tests if names_prod(t)]
            if blocked:
                notes.append(f"{name}: left out {len(blocked)} selected test files that name a "
                             "production host: " + ", ".join(blocked[:5]))
            if prod_all:
                notes.append(f"{name}: {len(prod_all)} test files in this suite name a production "
                             "host. The full command must not run them. Check it before any full run.")
        related = s.get("related") if tier >= 1 else None
        too_many = all_tests and (len(picked) / len(all_tests) > max_fraction
                                  or len(picked) > max_files)
        if too_many and tier >= 1:
            plan.append({"suite": name, "scope": "full", "cwd": cwd, "commands": [s["full"]],
                         "why": f"selection is {len(picked)} of {len(all_tests)} test files"})
            continue
        cmds = []
        pre = s.get("file_prefix", "")
        if picked:
            cmds.append(s["focused"].replace(
                "{files}", " ".join(pre + rel(t) for t in sorted(picked))))
        if related and src:
            cmds.append(related.replace("{files}", " ".join(rel(f) for f in src)))
        entry = {"suite": name, "scope": "focused", "cwd": cwd, "commands": cmds,
                 "test_files": len(picked), "why": f"tier {tier}, {len(mine)} changed files"}
        if unmapped and not related:
            entry["unmapped"] = unmapped[:20]
            notes.append(f"{name}: {len(unmapped)} changed source files have no test matched by "
                         "name. Pick their tests by hand, or set this suite's 'related' command.")
        if cmds or unmapped:
            plan.append(entry)
    # {main} in a command is the main checkout, for tools a lane worktree has not installed.
    common = git("rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    main_dir = str(pathlib.Path(common).parent).replace("\\", "/") if common else str(root())
    for entry in plan:
        entry["commands"] = [c.replace("{main}", main_dir) for c in entry["commands"]]
    lint = [c for c in cfg.get("lint", [])] if tier <= 2 else cfg.get("lint_full", cfg.get("lint", []))
    print(json.dumps({"lane": branch(), "tier": tier, "changed_files": len(files),
                      "lint": lint, "plan": plan, "notes": notes}, indent=2))


# ---------------------------------------------------------------- run

def cmd_run(a):
    cmd = a.cmd[1:] if a.cmd and a.cmd[0] == "--" else a.cmd
    if not cmd:
        sys.exit("lbo: give the command after --")
    line = cmd[0] if len(cmd) == 1 else subprocess.list2cmdline(cmd)
    logs = lbo_dir() / "runs"
    logs.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    log = logs / f"{re.sub(r'[^A-Za-z0-9_.-]', '-', a.name)}-{stamp}.log"
    cwd = str(root() / a.cwd) if a.cwd else str(root())
    t0 = time.time()
    code = None
    with open(log, "w", encoding="utf-8", errors="replace") as fh:
        p = subprocess.Popen(line, shell=True, cwd=cwd, stdout=fh, stderr=subprocess.STDOUT)
        try:
            code = p.wait(timeout=a.timeout * 60 if a.timeout else None)
        except subprocess.TimeoutExpired:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
            else:
                p.kill()
            code = 124
    secs = round(time.time() - t0, 1)
    # --expect-fail is for proving a test fails without its fix: failing is the good outcome.
    good = (code not in (0, 124)) if a.expect_fail else (code == 0)
    append("runs.jsonl", {"at": now(), "name": a.name, "lane": branch(), "tier": a.tier,
                          "scope": "proof" if a.expect_fail else a.scope, "seconds": secs,
                          "exit": code, "ok": good, "cmd": line[:500],
                          "log": str(log.relative_to(root())).replace("\\", "/")})
    tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-a.tail:]
    print("\n".join(tail))
    if code == 124:
        state = "TIMED OUT"
    elif a.expect_fail:
        state = ("FAILED AS EXPECTED, the test catches the bug" if good else
                 "PASSED BUT A FAILURE WAS EXPECTED: the test is vacuous, rewrite it")
    else:
        state = "PASSED" if good else f"FAILED (exit {code})"
    print(f"\n[lbo] {a.name}: {state} in {secs}s. Full log: {log}")
    sys.exit(0 if good else 1)


# ---------------------------------------------------------------- findings

def norm(value, allowed, default):
    v = str(value or "").strip().lower().replace("_", "-").replace(" ", "-")
    return v if v in allowed else default


def finding_row(lane, rnd, reviewer, item):
    title = str(item.get("title") or item.get("claim") or item.get("summary") or "").strip()
    fid = hashlib.sha1(f"{lane}|{rnd}|{reviewer}|{title}".encode("utf-8")).hexdigest()[:8]
    return {"type": "finding", "id": fid, "at": now(), "lane": lane, "round": rnd,
            "reviewer": reviewer, "severity": norm(item.get("severity"), SEVERITIES, "medium"),
            "class": norm(item.get("class"), CLASSES, "unclassified"),
            "file": str(item.get("file") or ""), "title": title[:300]}


def cmd_finding(a):
    lane = getattr(a, "lane", None) or branch()
    if a.action == "import":
        data = json.loads(pathlib.Path(a.file).read_text(encoding="utf-8", errors="replace"))
        items = data.get("findings", []) if isinstance(data, dict) else data
        rows = [finding_row(lane, a.round, a.reviewer, i) for i in items if isinstance(i, dict)]
        for r in rows:
            append("findings.jsonl", r)
        if not rows:
            append("findings.jsonl", {"type": "clean-round", "at": now(), "lane": lane,
                                      "round": a.round, "reviewer": a.reviewer})
        print(f"[lbo] logged {len(rows)} findings for {lane} round {a.round} ({a.reviewer})")
        for r in rows:
            print(f"  {r['id']}  {r['severity']:<8} {r['class']:<12} {r['title'][:90]}")
    elif a.action == "add":
        r = finding_row(lane, a.round, a.reviewer, {"title": a.title, "severity": a.severity,
                                                    "class": a.cls, "file": a.file})
        append("findings.jsonl", r)
        print(f"[lbo] logged {r['id']}")
    elif a.action == "dispose":
        row = {"type": "disposition", "id": a.id, "at": now(), "real": a.real,
               "became": a.became, "note": a.note or ""}
        if a.cls:
            row["class"] = norm(a.cls, CLASSES, "unclassified")
        append("findings.jsonl", row)
        print(f"[lbo] recorded disposition for {a.id}")


def cmd_escape(a):
    append("findings.jsonl", {"type": "escape", "at": now(), "lane": branch(), "test": a.test,
                              "reason": a.reason})
    print("[lbo] escape logged. Add the path to forced_full or the test to always_run.")


# ---------------------------------------------------------------- worktrees

def dir_size(path):
    total = 0
    stack = [str(path)]
    while stack:
        try:
            with __import__("os").scandir(stack.pop()) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        else:
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass
        except OSError:
            pass
    return total


def cmd_worktrees(a):
    """List lane worktrees and say which are safe to remove. Removes only with --remove."""
    entries, cur = [], {}
    for line in git("worktree", "list", "--porcelain").splitlines() + [""]:
        if not line.strip():
            if cur:
                entries.append(cur)
            cur = {}
        else:
            k, _, v = line.partition(" ")
            cur[k] = v or True
    if not entries:
        sys.exit("lbo: no worktrees found")
    main_path = entries[0]["worktree"]
    here = str(root()).replace("\\", "/").lower()
    try:
        base_cfg = load_cfg().get("base_branch", "main")
    except SystemExit:
        base_cfg = "main"
    bases = [b for b in dict.fromkeys([a.base, base_cfg, "origin/" + base_cfg, "main",
                                       "origin/main", "master", "origin/master"])
             if b and sh(["git", "rev-parse", "--verify", "-q", b], cwd=root())[0] == 0]
    rows = []
    for e in entries[1:]:
        path = e["worktree"]
        name = pathlib.PurePosixPath(path.replace("\\", "/")).name
        br = str(e.get("branch", "")).replace("refs/heads/", "") or "(detached)"
        head = e.get("HEAD", "")
        why = []
        if not pathlib.Path(path).exists():
            rows.append({"name": name, "path": path, "branch": br, "ok": False, "gone": True,
                         "why": ["folder is missing; 'git worktree prune' clears the record"]})
            continue
        if path.replace("\\", "/").lower() == here:
            why.append("you are in it")
        if e.get("locked"):
            why.append("locked")
        code, out = sh(["git", "status", "--porcelain"], cwd=path)
        dirty = [x for x in out.splitlines() if x.strip()]
        if code or dirty:
            why.append(f"{len(dirty)} uncommitted or untracked files")
        merged = next((b for b in bases if sh(["git", "merge-base", "--is-ancestor", head, b],
                                              cwd=root())[0] == 0), None)
        if not merged:
            pushed = git("branch", "-r", "--contains", head).strip()
            why.append("not merged into " + "/".join(bases[:2]) +
                       ("" if pushed else ", and not pushed anywhere"))
        days = None
        ts = git("log", "-1", "--format=%ct", head).strip()
        if ts.isdigit():
            days = int((time.time() - int(ts)) / 86400)
        if a.days and days is not None and days < a.days:
            why.append(f"last commit {days} days ago (under --days {a.days})")
        rows.append({"name": name, "path": path, "branch": br, "days": days, "ok": not why,
                     "why": why, "merged": merged})
    if a.sizes:
        for r in rows:
            if not r.get("gone"):
                r["mb"] = dir_size(r["path"]) // (1024 * 1024)
    ok = [r for r in rows if r["ok"]]
    print(f"Main checkout: {main_path}")
    print(f"{len(rows)} worktrees: {len(ok)} safe to remove, {len(rows) - len(ok)} kept\n")
    for title, group in (("SAFE TO REMOVE (merged, clean)", ok),
                         ("KEPT", [r for r in rows if not r["ok"]])):
        if group:
            print(title)
        for r in sorted(group, key=lambda x: -(x.get("mb") or 0)):
            size = f"{r['mb']:>7} MB  " if "mb" in r else ""
            age = f"{r['days']}d" if r.get("days") is not None else "?"
            print(f"  {size}{r['name']:<28} {r['branch']:<34} {age:>5}  " + "; ".join(r["why"]))
        if group:
            print()
    if a.sizes:
        print(f"Space in safe-to-remove worktrees: {sum(r.get('mb', 0) for r in ok) / 1024:.1f} GB "
              f"of {sum(r.get('mb', 0) for r in rows) / 1024:.1f} GB in all worktrees")
    if not a.remove:
        print("Nothing was removed. Add --remove to remove the safe ones.")
        return
    done = failed = 0
    for r in ok:
        code, out = sh(["git", "worktree", "remove", r["path"]], cwd=root())
        if code:
            failed += 1
            print(f"  could not remove {r['name']} (left as it is)")
            continue
        done += 1
        if r["branch"] != "(detached)":
            sh(["git", "branch", "-d", r["branch"]], cwd=root())
    sh(["git", "worktree", "prune"], cwd=root())
    print(f"Removed {done} worktrees, {failed} failed. Merged branches were deleted locally; "
          "unmerged ones were never touched.")


# ---------------------------------------------------------------- report

def cmd_report(a):
    rows = read_rows("findings.jsonl")
    finds = {r["id"]: dict(r) for r in rows if r.get("type") == "finding"}
    for r in rows:
        if r.get("type") == "disposition" and r.get("id") in finds:
            finds[r["id"]].update({k: v for k, v in r.items() if k in ("real", "became", "class")})
    rounds = {}
    for r in rows:
        if r.get("type") in ("finding", "clean-round"):
            rounds[r["lane"]] = max(rounds.get(r["lane"], 0), int(r.get("round") or 0))
    print(f"# lbo report, {now()}\n")
    print(f"## Review ({len(finds)} findings, {len(rounds)} lanes)\n")
    if rounds:
        vals = sorted(rounds.values())
        print(f"Rounds per lane: median {vals[len(vals) // 2]}, max {vals[-1]}, "
              f"lanes at 9+: {sum(v >= 9 for v in vals)}")
        for lane, n in sorted(rounds.items(), key=lambda x: -x[1])[:15]:
            print(f"  {n:>3}  {lane}")
    total = len(finds) or 1
    print("\nBy class:")
    for c in CLASSES:
        n = sum(f["class"] == c for f in finds.values())
        if n:
            print(f"  {c:<13} {n:>4}  {100 * n / total:.0f}%")
    print("\nBy reviewer (findings / high or critical / recorded as not real):")
    for rv in sorted({f["reviewer"] for f in finds.values()}):
        fs = [f for f in finds.values() if f["reviewer"] == rv]
        print(f"  {rv:<10} {len(fs):>4} / {sum(f['severity'] in ('high', 'critical') for f in fs):>3}"
              f" / {sum(f.get('real') == 'no' for f in fs):>3}")
    undisposed = sum("real" not in f for f in finds.values())
    print(f"\nFindings with no recorded disposition: {undisposed}")
    became = {}
    for f in finds.values():
        if f.get("became"):
            became[f["became"]] = became.get(f["became"], 0) + 1
    if became:
        print("Became: " + ", ".join(f"{k} {v}" for k, v in sorted(became.items())))
    escapes = [r for r in rows if r.get("type") == "escape"]
    print(f"Test selection escapes: {len(escapes)}")
    runs = read_rows("runs.jsonl")
    print(f"\n## Test runs ({len(runs)})\n")
    for scope in ("full", "focused", "proof", "other"):
        rs = [r for r in runs if (r.get("scope") or "other") == scope]
        if rs:
            hrs = sum(r.get("seconds") or 0 for r in rs) / 3600
            bad = sum(1 for r in rs if not r.get("ok", r.get("exit") == 0))
            what = "passed when they should have failed" if scope == "proof" else "failed or timed out"
            print(f"  {scope:<8} {len(rs):>4} runs  {hrs:6.1f} h  {bad} {what}")


# ---------------------------------------------------------------- cli

def main():
    # Windows consoles default to cp1252; test output often carries other characters.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="lbo", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("init").set_defaults(fn=cmd_init)

    p = sub.add_parser("level")
    p.add_argument("--labels", default="")
    p.add_argument("--base")
    p.add_argument("--refuted", action="store_true",
                   help="an assumption was refuted after coding began")
    p.set_defaults(fn=cmd_level)

    p = sub.add_parser("tests")
    p.add_argument("--tier", type=int, choices=[0, 1, 2, 3], required=True)
    p.add_argument("--base")
    p.set_defaults(fn=cmd_tests)

    p = sub.add_parser("run")
    p.add_argument("--name", required=True)
    p.add_argument("--tier", type=int)
    p.add_argument("--scope", choices=["full", "focused", "other"], default="other")
    p.add_argument("--cwd", help="folder relative to the repo root")
    p.add_argument("--timeout", type=float, help="minutes")
    p.add_argument("--tail", type=int, default=40)
    p.add_argument("--expect-fail", action="store_true",
                   help="a proof run: the command is meant to fail (test without its fix)")
    p.add_argument("cmd", nargs=argparse.REMAINDER)
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("finding")
    fs = p.add_subparsers(dest="action", required=True)
    q = fs.add_parser("import")
    q.add_argument("file")
    q.add_argument("--round", type=int, required=True)
    q.add_argument("--reviewer", required=True)
    q.add_argument("--lane")
    q = fs.add_parser("add")
    q.add_argument("--round", type=int, required=True)
    q.add_argument("--reviewer", required=True)
    q.add_argument("--severity", choices=SEVERITIES, required=True)
    q.add_argument("--class", dest="cls", choices=CLASSES, default="unclassified")
    q.add_argument("--file", default="")
    q.add_argument("--title", required=True)
    q.add_argument("--lane")
    q = fs.add_parser("dispose")
    q.add_argument("--id", required=True)
    q.add_argument("--real", choices=["yes", "no"], required=True)
    q.add_argument("--became", choices=["fix", "rule", "test", "invariant", "declined"],
                   default="fix")
    q.add_argument("--class", dest="cls", choices=CLASSES)
    q.add_argument("--note")
    p.set_defaults(fn=cmd_finding)

    p = sub.add_parser("escape")
    p.add_argument("--test", required=True)
    p.add_argument("--reason", required=True)
    p.set_defaults(fn=cmd_escape)

    sub.add_parser("report").set_defaults(fn=cmd_report)

    p = sub.add_parser("worktrees")
    p.add_argument("--base", help="extra branch to count as 'merged into'")
    p.add_argument("--sizes", action="store_true", help="measure each folder (slow)")
    p.add_argument("--days", type=int, help="keep worktrees whose last commit is newer than this")
    p.add_argument("--remove", action="store_true", help="remove the ones listed as safe")
    p.set_defaults(fn=cmd_worktrees)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
