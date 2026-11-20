# The baseline behind the process

Before this process was written, the records of two production projects were measured: session transcripts, reviewer outputs and git history covering about three weeks of AI-driven work on each. Project A is a Python API with a Next.js frontend. Project B is a TypeScript monorepo. Both used an orchestrating agent, subagents in git worktrees, and iterative adversarial review by two outside models.

These are measurements from two codebases and one way of working. Treat them as a starting point for your own numbers, which `lbo.py report` collects.

## Review

| Measure | Project A | Project B |
| --- | --- | --- |
| Lanes measured | 75 | 65 |
| Review rounds per lane, median | 4 | 6 |
| Review rounds per lane, maximum | 27 | 27 |
| Lanes that needed nine or more rounds | 24% | 38% |
| Findings parsed | 2,190 | 3,027 |
| Findings per reviewer output, rounds 1 to 3 | 5.4 | 4.5 |
| Findings per reviewer output, rounds 9 and later | 1.7 | 3.1 |
| Reviewer run time per call, median | 3.9 min | 4.2 min |

A stratified sample of findings was classified by hand (196 on A, 152 on B):

| Class | Project A | Project B |
| --- | --- | --- |
| Semantic: needs an understanding of behaviour | 84% | 86% |
| Test gap: a missing or vacuous test | 8% | 10% |
| Pattern: a lint or AST rule could catch it | 7% | 3% |
| Convention: breaks a written project rule | 1% | 1% |

On Project A, 11.5% of all findings mentioned a race, a lock, concurrency or stale state. In rounds nine and later, 94% of findings were semantic.

The two reviewers differed. One produced most of the high-severity findings, reproduced the failure in about 15% of them, and had almost none recorded as wrong. The other produced mostly low-severity findings and nearly all of the findings recorded as wrong; some of those came from test files being left out of its prompt.

## Tests

| Measure | Project A | Project B |
| --- | --- | --- |
| Share of agent thread time spent on tests | 24% | 20% |
| Share spent waiting on reviewers | 3% | 11% |
| Machine time, focused runs against full runs | 2 to 1 | 6 to 1 |
| Time spent polling test logs | 12.4 h | 16.0 h |
| Full suite | 83 min, serial, grown fourfold in three weeks | Package suites of 19 to 163 s |

Project A specifics: of 68 full backend runs started, 31 completed and 22 were stopped part-way. For two weeks every completed full run on the host failed on the same tests across unrelated lanes, which pointed at the environment, not the code. A pre-commit hook that ran test suites cost 19.5 hours over 634 commits.

Project B specifics: a machine-wide test lock, added so parallel lanes would not collide, became the bottleneck. Calls through the lock added up to 42.9 hours while a call was in flight for only 20.8, so about half the time was queueing.

## What the process takes from this

- **Linting is worth having and is not the answer.** It covers a small share of findings.
- **Most review cost is the long tail of rounds on semantic findings.** Concurrency, scoping and state belong in the ticket and the design. When the same kind of finding repeats, ask the reviewer for the design.
- **Verify findings before acting**, and record the outcome, so reviewers can be compared.
- **Isolate lanes; do not queue them.** Give each lane its own database and ports.
- **Never poll a log.** Run tests through a command that returns when they finish.
- **A full suite that fails for environmental reasons is not a gate.** Make it clean and fast first.
- **Choose tests from the diff.** Focused runs are where most of the time goes.

## Limits

The classification was done by one reader from short excerpts. Counts of wrong findings are a lower bound, because outcomes were not recorded consistently at the time. The time shares are estimates: parallel threads overlap, and idle time was capped. Some days of work happened on a second machine and are not in the records.
