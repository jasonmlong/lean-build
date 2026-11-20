# Config reference

`.lbo/config.json` lives in the project's main checkout. Lane worktrees without their own copy read that one. All paths are globs from the repository root: `**` crosses folders, `*` stays within one, `?` is one character. Keys starting with `_` are comments and are ignored.

## Top level

| Key | Default | Meaning |
| --- | --- | --- |
| `base_branch` | `main` | The branch a lane is compared against. `--base` overrides it per call |
| `default_level` | `2` | Review level when no label is recognised |
| `level_labels` | | Map of ticket label to starting review level (0 to 3) |
| `sensitive_paths` | `[]` | A diff touching any of these is level 3 |
| `min_level_paths` | `{}` | Map of glob to a minimum level, for example `{"backend/**": 2}` |
| `size_limit_lines` | `600` | A diff with more added plus removed lines goes up one level |
| `module_depth` | `2` | Path segments that make a "module". Three or more modules touched means at least level 2 |
| `forced_full` | `[]` | A diff touching any of these runs every suite in full (tier 1 and up) |
| `prod_hosts` | `[]` | Production hostnames. Test files that name one are never selected, and the script warns before a full run |
| `max_fraction` | `0.4` | If the selection exceeds this share of a suite's test files, run the full suite |
| `max_files` | `80` | If the selection exceeds this many test files, run the full suite |
| `lint` | `[]` | Lint commands printed for tiers 0 to 2 |
| `lint_full` | `lint` | Lint commands printed for tier 3 |
| `suites` | | Map of suite name to suite settings |

## Suite settings

| Key | Meaning |
| --- | --- |
| `cwd` | Folder the commands run in, relative to the repository root. Empty for the root |
| `files_root` | Prefix stripped from test file paths in commands. Defaults to `cwd`. Use it when the command runs from the root but expects paths relative to a subfolder |
| `paths` | Globs for the source and test files that belong to this suite |
| `test_globs` | Globs for this suite's test files |
| `match` | `contains` matches a source file's name anywhere in a test file's name (useful for CamelCase names such as `FooServiceEdgeCasesTest`). Otherwise the name must appear as a whole word between `_`, `.` or `-` |
| `forced_full` | Globs that return this suite's full run when touched |
| `always_run` | Test globs added at tier 2 whatever the diff says |
| `full` | Command for the whole suite. Read it before using it: see `prod_hosts` |
| `focused` | Command for selected test files. `{files}` is replaced by the file list |
| `file_prefix` | Text put before each file in `{files}`, for runners that need a flag per file (for example `--include `) |
| `related` | Optional command that asks the runner for tests related to changed source files, with `{files}` replaced by those source files. When set, unmatched source files are not reported as unmapped |

In any command, `{main}` is replaced by the main checkout's path. Use it for tools that a lane worktree has not installed.

## Files the script writes

| File | Contents |
| --- | --- |
| `.lbo/findings.jsonl` | One line per finding, clean round, disposition or escape. Append-only, merged with `merge=union` |
| `.lbo/runs.jsonl` | One line per `LBO run`: name, lane, tier, scope, seconds, exit code, log path |
| `.lbo/runs/*.log` | Full output of each run. Ignored by git |
| `.lbo/invariants.md` | Rules the code relies on, each with the test that proves it. Written by people and agents, read by reviewers |

## Reviewer findings format

`LBO finding import` reads a JSON array, or an object with a `findings` array:

```json
{"verdict": "impressed",
 "findings": [
   {"severity": "high", "class": "semantic", "file": "app/locks.py",
    "title": "Two requests can both pass the check before either commits"}
 ]}
```

`severity` is `critical`, `high`, `medium` or `low`. `class` is `pattern`, `convention`, `semantic` or `test-gap`. An empty list records a clean round.
