# lean-build

A Claude Code skill and a small helper script for running multi-ticket software builds with AI agents: fewer review rounds, less time spent on tests, and a record of what each build cost.

It is a process (`SKILL.md`) plus a tool (`scripts/lbo.py`) that takes the judgment calls an orchestrating agent tends to get wrong and makes them mechanical:

- how much review a change needs;
- which tests to run for a given diff;
- waiting for a test run without polling its log;
- recording every review finding and what happened to it;
- clearing out finished git worktrees.

The script is plain Python with no dependencies. It works on Windows, macOS and Linux.

## Why it exists

The process was shaped by measuring about three weeks of AI-driven work on each of two production codebases. The short version (details in [docs/baseline.md](docs/baseline.md)):

- **84 to 86% of adversarial review findings were semantic**: races, lock order, tenant scoping, state, migrations. Lint-catchable findings were 4 to 8%. Better linting does not replace review.
- **A quarter to a third of lanes needed nine or more review rounds.** That tail is the main cost of review. Waiting on the reviewer was 2 to 11% of agent time.
- **Tests took 20 to 24% of agent time**, mostly in focused runs, log polling and queueing behind shared resources, not in the full suite.

So the process puts its effort into the ticket and the design before coding, into asking the reviewer for a design when findings repeat, and into running fewer and better-chosen tests.

## Install

The repository root is the skill folder. Clone it into your Claude Code skills directory:

```bash
git clone <this repo's URL> ~/.claude/skills/lean-build
```

On Windows the folder is `%USERPROFILE%\.claude\skills\lean-build`.

Requirements: Python 3.9 or newer, and git.

## Set up a project

From inside the project's git checkout:

```bash
python ~/.claude/skills/lean-build/scripts/lbo.py init
```

This creates a `.lbo/` folder with a `config.json` to fill in. The config describes your test suites and how to run them, which paths are sensitive, which tests always run, and which hostnames are production. See [docs/config.md](docs/config.md).

**Fill in `prod_hosts` and read every `full` command before the first full run.** See "Safety" below.

Commit `.lbo/` (the config, `invariants.md`, `findings.jsonl` and `runs.jsonl`). Run logs under `.lbo/runs/` are ignored. Lane worktrees without their own config read the main checkout's copy.

Then ask Claude Code to run the build with the lean-build skill.

## Commands

Run from anywhere inside a project checkout or worktree. `LBO` is `python <skill folder>/scripts/lbo.py`.

| Command | What it does |
| --- | --- |
| `LBO init` | Create `.lbo/` with a config template |
| `LBO level --labels ui,bounded` | Review level (0 to 3) for the current diff, with the reasons |
| `LBO tests --tier 1` | The test commands to run for the current diff at a tier (0 to 3) |
| `LBO run --name N --scope focused --tier 1 -- CMD` | Run CMD to completion, log it, print the tail, record the time |
| `LBO run --expect-fail ...` | A proof run: the command is meant to fail (a test without its fix) |
| `LBO finding import FILE --round 2 --reviewer codex` | Log a reviewer's findings from JSON |
| `LBO finding dispose --id ID --real no --became declined` | Record what happened to a finding |
| `LBO escape --test T --reason R` | Log a test the selection wrongly skipped |
| `LBO report` | Rounds per lane, findings by class, wrong findings per reviewer, test hours |
| `LBO worktrees [--sizes] [--remove]` | List lane worktrees that are merged and clean, and optionally remove them |

### Review levels

| Level | Applies to | Review |
| --- | --- | --- |
| 0 | Copy, layout, config, small items | Gates only |
| 1 | Isolated UI, bounded single-module changes | One reviewer, one round plus a confirming round |
| 2 | Standard backend work, three or more modules | One reviewer, iterated to a clean verdict |
| 3 | Auth, tenant isolation, money, concurrency, migrations | Two reviewers, iterated until both are clean, then a fresh full pass |

The level starts from the ticket's labels. The diff can only raise it: sensitive paths force level 3, and a large diff or a refuted assumption adds one.

### Test tiers

| Tier | When | What runs |
| --- | --- | --- |
| 0 | Inside a coding agent's loop | Lint on changed files and the tests matched to them |
| 1 | A lane is ready for review | The same over the whole lane diff |
| 2 | Lanes merged onto the integration branch | The same against the base branch, plus the always-run list |
| 3 | Release candidate | Every suite in full, once |

Tests are matched to changed source files by file name, unless a suite configures a "related tests" command (for example `vitest related`). Files it cannot match are listed as unmapped for the agent to handle. Changes to configured paths (fixtures, lockfiles, shared setup) return the full suite.

## Safety

- **A "full" test command is dangerous until you have read it.** On first use of this tool, a bare end-to-end "run everything" command executed specs that were hard-coded to a production site. List production hostnames in `prod_hosts`: the script then refuses to select any test file that names one and warns before a full run. Make each `full` command name the folders it may run.
- `LBO worktrees --remove` only removes worktrees that are merged into the base branch and have no uncommitted or untracked files. It never forces.
- The script never pushes, merges, deploys or calls a network service. It reads git, runs the commands you configure, and writes under `.lbo/`.
- The process grants no deploys and no merges to a production branch. Your project's own approval rules apply.

## What is in the repository

```
SKILL.md                    the process, loaded by Claude Code
scripts/lbo.py              the helper
templates/lbo.config.json   the config that `init` copies into a project
templates/prompts.md        ticket template and prompts: epic review, assumption check,
                            coding brief, review round, design question
docs/config.md              every config key
docs/baseline.md            the measurements the process is based on
tests/test_lbo.py           tests for the helper
```

## Tests

```bash
python -m unittest discover -s tests -v
```

The tests build throwaway git repositories in a temp folder.

## Status

Early. The process has been used on a handful of real builds. The name-based test matching is deliberately simple, and the thresholds in the config template are starting points, not findings. Expect to tune the config per project.

## License

MIT. See [LICENSE](LICENSE).
