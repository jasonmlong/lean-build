---
name: lean-build
description: How to take a multi-ticket software build from a ticket or an epic to a deploy with fewer review rounds and less test time. Uses a helper script (lbo) that picks the review level, picks the tests, runs them without polling, logs review findings and clears finished worktrees. Use when orchestrating tickets, lanes, subagents, adversarial reviews, tests or merges, or when the project has a .lbo folder.
version: 2026-11-19
---
# Lean build orchestration

You are the conductor of a build that spans several tickets. This process is built on a measured baseline of two production projects, about three weeks of AI-driven work each (see `docs/baseline.md`). What it found decides the order of everything below:

- **84 to 86% of review findings are semantic** (races, lock order, tenant scoping, state, migrations). Lint-catchable findings are 4 to 8%. Quality is won before coding and in the design, not in the linter.
- **A quarter to a third of lanes run nine or more review rounds.** That tail is the main cost of review. The wait for a reviewer is not (a median of four minutes per call).
- **Tests take 20 to 24% of agent time.** Most of it is focused runs, polling logs, and queueing behind shared resources, not the full suite.

`LBO` below means `python <this skill's folder>/scripts/lbo.py`, run from inside the project checkout or worktree. Prompts and the ticket template are in `templates/prompts.md`. If the project has no `.lbo/config.json`, run `LBO init`, fill the config with the user, and commit `.lbo/`.

## 1. Intake: get the ticket right before any code

Work arrives two ways: a lightweight inbox of small items (a kanban or bug-capture tool) and a tracker for larger work (Jira or similar). Both end at the same place: acceptance criteria and checked assumptions.

- **Inbox item** (front-end fixes, improvements, small features). Give it one acceptance line and a label. Batch small items into one lane. If it would touch three or more modules, the schema or a sensitive path, promote it to a tracker ticket.
- **Tracker epic** (anything complicated). Write tickets from the template (prompt 1). Then, in order:
  1. **Epic review** by a different model from the writer (prompt 2). Recommendations go to the user.
  2. **Assumption and data check**, read-only (prompt 3), against the repository and a snapshot of the schema with sample rows. Refuted goes back to the writer with the evidence. Unknown goes to the user. Never let a model guess here.
  3. The user approves the batch.

For any ticket that writes data, the **State and concurrency** block of the template is required. It is where most later findings come from: name the one writer of each field, answer "what if two requests do this at once", state the tenant scoping, and list what must stay true. Put those invariants in `.lbo/invariants.md` with the test that proves each.

## 2. Build in lanes, with bulk kept out of your context

- **One worktree per lane.** Independent lanes run at the same time, each with its own agent. Launch independent agents together, in one turn.
- **Isolate, do not queue.** Each lane gets its own test database and its own ports, named in its brief. A shared lock that every lane waits on cost one project half its test time. Serialize only what cannot be isolated, such as a reviewer that allows one call at a time.
- **Narrow briefs, capped reports** (prompt 4). Each agent gets one lane, the exact files or findings file, the test commands, the environment traps, what it must not touch, and a 150-word report cap. Longer material goes in a file and the report gives the path.
- **Never read an agent's transcript or poll its output.** Wait for the completion notice.
- **Findings travel as files.** A reviewer's output is saved to a file; the fix agent's brief names the file. You do not retype findings.
- **Cheaper model for mechanical work**: fixes to a decided design, merge preparation, test runs, classifying findings. Keep the strongest model for tickets, design and orchestration.
- **Comments.** No comment unless it records why. No commented-out code.
- **Never use git stash across worktrees.** To prove a test fails without its fix, copy the file aside or use `git diff > patch` and `git apply -R`.
- **Push every lane's branch at each step.** The `.lbo` ledger merges cleanly across branches and machines, so commit it with the work.

## 3. Tests: the script chooses, and nobody polls

Ask the script what to run. Do not decide by judgment and do not start a full suite in a feature lane.

```
LBO tests --tier N        # prints the commands for this diff
LBO run --name NAME --scope focused|full --tier N [--cwd DIR] [--timeout MIN] -- COMMAND
```

`LBO run` blocks until the command ends, writes the whole output to `.lbo/runs/`, prints the last lines and the result, and records the duration. Start it as a background task and wait for the notice. **Never write a sleep-and-grep loop on a log.**

| Tier | When | What runs |
| --- | --- | --- |
| 0 | Inside a coding agent's loop | Lint on changed files, the tests it touched, tests matched to changed files |
| 1 | The lane is ready for review | Tier 0 on the whole lane diff, plus the suite's related-tests command if configured |
| 2 | Lanes merged onto the integration branch | The same against production's branch, plus the always-run list |
| 3 | Release candidate | Every suite in full, the page walk and the project's quality gate. Once, in the integration lane |

- **A full command is dangerous until it has been read.** On one project a bare end-to-end "run everything" command ran 21 specs that were hard-coded to the production site, signed in there and acted on it for two hours. Before the first full run of any suite on a project: search its test files for production hostnames, list those hosts in `prod_hosts` in the config (the script then refuses to select such files and warns about the full command), and make the full command name the folders it may run. Never run a bare "all tests" command for a browser or API suite you have not checked.
- **Proof runs use `--expect-fail`.** When proving a test fails without its fix, run it with `LBO run --expect-fail ...`. It reports "failed as expected", or flags a vacuous test if the run passes, and the report counts proofs apart from real failures.
- The script returns the full suite by itself when the diff touches a forced-full path (fixtures, migrations, models, lockfiles, config) or when the selection is a large share of the suite.
- If it lists **unmapped** files, pick their tests by hand and say so in the report.
- **Escapes.** When a tier 3 run fails a test that tiers 1 and 2 skipped, log it: `LBO escape --test X --reason Y`, then add the path to `forced_full` or the test to `always_run`. Selection is trusted only while escapes stay near zero.
- A full suite that fails for environmental reasons is not a gate. If the full run is not clean on the main branch, fix that first (run it in the project's container, in parallel) before relying on it.

## 4. Review: the level is computed, the bar is fixed

```
LBO level --labels LABELS [--refuted]
```

| Level | Applies to | Review |
| --- | --- | --- |
| 0 | Copy, layout, config, small inbox items | Gates only |
| 1 | Isolated UI, bounded single-module changes | One reviewer, one round plus one confirming round |
| 2 | Standard backend, three or more modules | One reviewer, iterated to a clean verdict |
| 3 | Auth, tenant isolation, money, concurrency, migrations, data deletion | Two vendors, iterated until both are clean, then a fresh full pass |

The diff can only raise the level: sensitive paths force level 3, a large diff or a refuted assumption adds one. Every epic with two or more lanes also gets a review of the merge itself.

**The standing rule, which the levels serve and never weaken:** after each epic, run an iterative adversarial review with two independent reviewers (Codex, and z.ai when it has credits; see section 6) that checks for general issues, security, code quality and maintainability, and whether a senior developer would be impressed with the code. Do not proceed unless a senior developer would be impressed. If the same bug or the same kind of bug comes back for more than two rounds in a row, ask the reviewer that raised it how to fix it. Recurring issues are usually architectural, so do things the right way, not just the fast way, unless told to do it the fast way.

So: every epic gets the review with both reviewers on its merged diff, whatever the levels of its lanes. The level decides how much review a lane gets on the way there.

Rules for every round:

- **Gates first.** No reviewer sees a lane until tier 1 is green.
- **A different vendor from the coder.** The stronger reviewer is the default lane reviewer (in the baseline that was Codex: it reproduced failures and had the fewest findings recorded as wrong). The second reviewer joins at level 3 and on every epic review.
- **Right over fast.** When a finding points at the structure (who owns a lock, where a check lives, two copies of one rule), fix the structure. Do not add a patch per symptom to save a round.
- **Use prompt 5.** It names what is already enforced, points at `.lbo/invariants.md`, includes the test files, and asks for JSON. Give a focused diff or named files, never the whole epic.
- **Log the round**: `LBO finding import FILE --round N --reviewer NAME`. A clean round is logged the same way with an empty list.
- **Verify every finding before acting**, then record it: `LBO finding dispose --id ID --real yes|no --became fix|rule|test|invariant|declined`. Reviewers are confidently wrong sometimes, and an unrecorded disposition cannot be measured later.
- **Every fix carries a test proven to fail without it.** Commit, revert the fix in a way that reproduces the bug, see the test fail, restore. Check the reverted line is present before trusting a failure.
- **Done** means a round with nothing critical, high or medium, and the verdict "impressed". Fix that round's lows and stop.
- **Narrow the confirming rounds** to the fixes and the new diff once a lane is down to one or two findings. Tell each round what changed and ask for regressions in the fixes.
- **When the same bug or the same kind of bug has come back for more than two rounds in a row, stop patching.** Ask the reviewer that raised it how it would fix it (prompt 6), give that design to the fix agent with "build exactly this", and add its invariants to the invariants file. Do the same at round four if a lane is still not clean, even when the findings differ. Do not wait for round ten.
- **After more than about five rounds, close with one fresh full pass** (prompt 7).

What each kind of finding becomes:

| Class | Becomes |
| --- | --- |
| Semantic | A fix with its test, and a line in `.lbo/invariants.md` when it states a rule the code relies on |
| Test gap | A test, proven to fail without the code |
| Pattern or convention | A lint rule, if it has occurred more than once. Use the linter's built-in rules first. A custom rule is admitted only if it flags the original code, passes the fixed code, has few false hits across the repo, and ships with a passing and a failing example |

## 5. Merge and ship

- **Prepare the merge while lanes are still in review.** Build the integration branch from what production runs as soon as the first lanes are clean, re-chain migrations, and run tier 2 there.
- **Ship in batches when one lane is the long pole.** Clean lanes do not wait for the slowest one.
- **Tier 3 once per release candidate.** Merges to the production branch and deploys follow the project's own approval rules. This skill does not grant them.

## 6. Vendors

| Role | Default | Notes |
| --- | --- | --- |
| Conductor, tickets, design | Claude, strongest model, interactive | |
| Hard coding: security, money, concurrency, migrations, cross-cutting | Claude subagent | |
| Bounded coding with tests given | The project's bulk coder if one is configured, else a cheaper Claude model | A vendor never reviews its own code |
| Assumption check, review | Codex | Its quota is the one to protect |
| Second reviewer at level 3 and on every epic review | z.ai, when it has credits | Include test files in its prompt. Without z.ai credits, Codex reviews alone, and the epic review closes with a fresh full Codex pass (prompt 7) |
| Cheap single-reviewer round at level 1 | Codex | Still a different vendor from the coder |

**Never use Gemini** (Jason, 22 November 2026: too expensive). It briefly replaced z.ai that day; that is reversed. The key folder `C:\Users\jason\Documents\GitHub\gemini-key\` stays on disk, unused.

Use the reviewer commands recorded in the project's CLAUDE.md. Treat a quota error as "pause this lane, continue the others" and say which plan stalled.

### Calling Codex

- **The CLI, read-only, from the worktree:** `codex exec -s read-only -o <answer file> - < <prompt file>`. Prompt 5 works with it as it is, since it asks for JSON.
- **Not the Codex MCP server:** it has failed to connect in Claude Code sessions. Use the CLI.
- **Log the round** with `LBO finding import <answer file> --round N --reviewer codex`.
- **Ask for the senior-developer verdict outright** (impressed, indifferent or annoyed, and why) and treat "annoyed" as a finding.

## 7. Survive resets, and close out

- **`.lbo/` is the record**: `findings.jsonl`, `runs.jsonl`, `invariants.md`. Keep a short state file per build with each lane's status, level, round and what is waiting on whom. Record decisions and authorizations in memory files when they are made.
- **Do not re-litigate settled decisions or re-run checks whose results are recorded.**
- **Wake-ups cost the conductor.** Prefer one agent working through a sequence and reporting once. Batch related lanes so their reports arrive together.
- **Clear out finished worktrees.** Old lane folders have filled tens of gigabytes on one project. When a lane is merged, and again at the end of every build, run `LBO worktrees` (add `--sizes` to see the space). It lists each lane worktree as safe to remove (merged into the base branch, nothing uncommitted) or kept, with the reason. Run `LBO worktrees --remove` to remove the safe ones; it never touches a worktree with uncommitted files or unmerged commits. Tell the user what was removed and what was kept and why. Anything kept for more than a few days needs a decision from the user, not silence. Never delete a worktree folder by hand.
- **At a pause or the end:** stop every agent with background work, check for leftover servers and test runs by port and process, push every branch, update the state file, and run `LBO report`. Give the user its numbers: rounds per lane, findings by class, findings recorded as wrong per reviewer, test hours, escapes.

## 8. Environment traps go in every brief

Each agent starts with none of your knowledge of the machine. Keep the project's list in its notes and paste it into every brief. The standing ones:

- Do not edit files or run logic with inline interpreter commands (`node -e`, `python -c`). Use the editor tool or a script file.
- Never pipe a heredoc or empty stdin to a bare interpreter.
- After restoring a file from git, line endings may change. Check that an edit landed.
- On Windows, killing a background task can leave its child server running. Stop servers by the port's process ID.
- Keep worktrees out of temp folders the system may clean.

## What not to save on

Do not skip a review the level requires, run fewer tests than the tier requires, or deploy without the project's live checks to save tokens. A production defect costs more than the review that would have caught it.
