# Prompts and templates

Copy the block you need. Text in CAPITALS is filled in by the conductor.

## 1. Ticket or inbox item

```
Title: WHAT CHANGES, IN THE USER'S TERMS
Labels: ONE OR MORE OF THE level_labels IN .lbo/config.json

Why: ONE OR TWO SENTENCES.

Acceptance criteria
- Given ..., when ..., then ...
- (one per behaviour, including the failure paths and what a second device or a retry sees)

Assumptions (each names where to check it)
1. CLAIM. Check: FILE PATH, TABLE.COLUMN, OR ENDPOINT.
2. ...

State and concurrency (required for backend work)
- Who is the one writer of each field this touches:
- What happens when two requests do this at once:
- What must stay true afterwards (the invariants):
- Tenant or business scoping of every read and write:

Out of scope:
```

A small inbox item needs only the title, one acceptance line and a label.

## 2. Epic review (a different model from the one that wrote the epic)

```
Review this epic and its tickets before any code is written. Do not write code.

Return, in this order:
1. Missing or untestable acceptance criteria, per ticket.
2. Tickets to split, merge or reorder, and why.
3. Anything underspecified: name the decision that is missing and who must make it.
4. State and concurrency: for each ticket that writes data, is the one writer named,
   is the two-requests-at-once case answered, is tenant scoping stated?
5. Assumptions that are missing from the Assumptions lists.

Be specific and brief. One line per point. No praise, no summary.

EPIC AND TICKETS:
```

## 3. Assumption and data check (read-only)

```
You are checking assumptions, not reviewing design. You may read the repository and the
files in SNAPSHOT_DIR (schema and sample rows). You may not write, and you may not guess.

For each numbered assumption below return one JSON object:
{"n": 1, "verdict": "verified" | "refuted" | "unknown", "evidence": "path:line or table.column and what it shows"}

"unknown" is the right answer when the evidence is not in what you can read.
Return a JSON array and nothing else.

ASSUMPTIONS:
```

Refuted goes back to the ticket writer with the evidence. Unknown goes to the person who owns the product.

## 4. Coding brief (every build or fix agent)

```
Lane: NAME. Branch: BRANCH at HEAD. Worktree: PATH.
Do: THE TICKET, OR "the findings in FILE".
Do not touch: FILES OR AREAS.

Tests: run `python LBO tests --tier 0` and run what it prints, through
`python LBO run --name NAME --scope focused --tier 0 -- COMMAND`. That command returns
when the run ends. Never poll a log, never sleep-and-check, never start the full suite.
This lane's database is DB_NAME and its port is PORT. Do not use any other.

Code rules: no comment unless it records why. No commented-out code. Follow CLAUDE.md.
Every fix carries a test proven to fail without it (commit, revert the fix, see it fail, restore).

Environment traps: PASTE THE PROJECT'S LIST.
Stop every server and test run you start.
Report in under 150 words: commit SHAs, one line per finding or criterion, which tests ran.
Anything longer goes in a file; give the path. Message the conductor when done.
```

## 5. Adversarial review round

```
Review the diff below as a senior developer who has to maintain it. This is round N.
Check for general issues, security, code quality and maintainability, and say whether a
senior developer would be impressed with this code. It does not proceed unless they would.
PURPOSE OF THE LANE IN TWO SENTENCES.
Changed since last round: WHAT WAS FIXED. Look for regressions those fixes introduced.

Already enforced, do not report: the lint rules in LINT_CONFIG, and every invariant in
.lbo/invariants.md (read it; if you think one is false, say which and show the code).

Look hardest at: races and lock order, two requests at once, retries and partial failure,
tenant or business scoping on every read and write, migrations on real data, and tests that
would still pass with the fix removed. Read the test files as well as the source.

Return JSON and nothing else:
{"verdict": "impressed" | "indifferent" | "annoyed", "why": "one sentence",
 "findings": [{"severity": "critical|high|medium|low",
               "class": "pattern|convention|semantic|test-gap",
               "file": "path", "title": "the defect in one sentence",
               "detail": "the failing scenario: inputs or state, then the wrong result",
               "fix": "the smallest change that removes it"}]}

class: "pattern" only if a lint or AST rule could catch it; "convention" if it breaks a rule
written in CLAUDE.md; "test-gap" for a missing or vacuous test; otherwise "semantic".

DIFF AND THE TEST FILES IT TOUCHES:
```

Save the reply to a file, then: `python LBO finding import FILE --round N --reviewer NAME`.

## 6. Design question (the same kind of bug for more than two rounds in a row, or round four)

Ask the reviewer that raised the findings.

```
Rounds on this area keep finding new variants of the same problem: LIST THE FINDINGS.
Stop reviewing. How would you build this so the whole class cannot occur?
Recurring issues are usually architectural. Give the right fix, not the fastest one.
Give the design: who owns each lock or field, the order of operations, what is checked
where, and the invariants that must hold. Then list the tests that would prove it.
```

Hand the answer to the fix agent with "build exactly this". Add its invariants to
`.lbo/invariants.md`.

## 7. Fresh full pass (after a lane has taken more than about five rounds)

Use prompt 5 on the lane's whole diff from its base, in a new reviewer session, with no
earlier findings or verdicts. Give it the lane's purpose and the areas you trust least.
