# Field report: PHP API + TypeScript SPA, six lanes, handoff between machines

## 1. Shape of the build

- **Stack:** a PHP web API (tests run in Docker on a Windows bind mount) and a TypeScript single-page app (unit tests in headless Chrome, end-to-end tests in Playwright).
- **Lanes:** six.
  - One review of earlier unreviewed commits.
  - A backend validation and aggregation feature, with a matching frontend editor lane and a frontend results lane.
  - A second backend results feature.
  - A small backend email-link fix.
  - Risk levels: the feature lanes touched rules about which data may be shown to which audience, so they ran at the two-reviewer level.
- **Handoff:** the run crossed one machine handoff, from a handover document written on the first machine, and one restart of the orchestrator session (the machine kept running). The second machine had no dependencies, containers or test databases set up.
- **Reviewers:** two flat-rate reviewers on every round of the two-reviewer lanes.

## 2. Numbers

From `lbo report` (findings ledger, backfilled from review JSON):

| Lane | Rounds |
| --- | --- |
| Frontend editor lane | 12 (including one fresh full-lane pass) |
| Merge review (where lanes meet) | 3 (frontend side), 2 (backend side) |
| Other lanes | 2 to 4 |

- **Findings recorded:** 69 for the editor lane's rounds 3 to 12 alone; 18 for the merge review.
- **Declined as not real:** 4. Each was found by checking the claim against the code before a fix agent ran.
- **Missing data:** test-run times weren't recorded through `lbo run` after the handoff (see section 4). Run data for this period is missing, not zero.

Estimates (not from the ledger):

- One review round with both reviewers in parallel took about 10 to 25 minutes. A fix agent took 5 to 30 minutes, depending on the size of the change.
- One backend test file took about 4 minutes on the Windows bind mount. The full backend suite took tens of minutes.
- One end-to-end run of the safe folders took 5.1 hours and gave 19 real passes out of 231 tests. Almost all failures came from the environment (section 3).

## 3. What cost the most time

1. **One long-pole lane: 12 rounds where the others took 2 to 4.**
   - The editor lane owned a small state machine: autosave with retries and a deadline, a route guard, back and preview buttons, browser unload, and a shared confirm dialog.
   - Every narrowed round closed its findings and surfaced a new variant in the same area. Rounds 3, 4 and 5 were all in the leave/save interplay before the reviewer was asked for a design.
   - After the design was built, the fresh full-lane pass found three highs in code the narrowed rounds had never looked at (end-user form inputs, a raw JSON editing path, number parsing). Each needed another two to three rounds.
2. **An end-to-end run that produced almost no signal.**
   - The run took 5.1 hours. Most specs needed seed accounts that didn't exist locally, some hard-coded a port nothing listened on, and some wrote helper scripts to a path the container didn't mount.
   - A two-minute preflight (sign in as each account the selected specs use, and check each hard-coded host and port answers) would have shown this before the run started.
3. **Rebuilding the environment on the new machine.**
   - The backend needed a newer language runtime than the repo's Dockerfile declared, and a test env file and database that weren't documented.
   - The frontend used a different package manager than the helper config assumed. A busy port forced a no-host-ports compose override.
   - It took about an hour of an agent's time, and two failed reviewer calls (the interpreter alias and file encoding on Windows).
4. **Serialised shared resources discovered late.**
   - The only backend test container mounted the same checkout that the end-to-end stack served. Backend fixes therefore had to wait for, or work around, a five-hour browser run.
   - A second checkout with a throwaway container fixed it, but only after the conflict had cost time.
5. **Orchestrator wake-ups from agents that left background tasks open.**
   - Several fix agents finished their work and kept re-sending the same report, because a test runner they had started was still attached. Each repeat woke the orchestrator.
   - Once "have no background tasks open when you report" was added to every brief, it stopped.

## 4. Where the process wasn't followed

1. **`lbo run` and the ledgers were dropped after the handoff.**
   - The configs were restored, but the orchestrator ran tests and reviewers directly. Nothing in the flow forced the helper: the ledgers were optional bookkeeping, and the handoff checklist restored files without saying "every run goes through `lbo run`".
   - The report afterwards undercounted the long-pole lane (3 rounds instead of 12) until the findings were backfilled.
2. **The orchestrator designed a shared-component fix itself.**
   - To stop a confirm dialog being replaced mid-decision, it changed the app-wide confirm service to queue dialogs instead of asking the reviewer for a design.
   - That changed behaviour for every caller in the app: queued prompts could outlive their page and act on the wrong record. A whole round went to finding that, and another to reverting it to a local fix.
   - The skill's "settle design questions before coding" rule was clear; it wasn't applied because the change looked small.
3. **The design question was asked one round too late.** The rule says to ask when rounds go in circles. The circle was visible at round 4 (the second variant in one area), and the ask came at round 5.
4. **The cost wasn't raised with the user until round 9.** Nothing in the skill says when to surface a long-pole lane to the person paying for it, or to offer "ship with the remaining lows ticketed".

## 5. What worked

- **Verifying each finding against the code before a fix agent ran.** It took a grep or a 20-line read each time. It caught four wrong findings, including one that would have rewired service lifetime for no reason.
- **Asking the reviewer for a design and building it with "build exactly this".** It ended the first loop. The later loops were in new areas, not the same one.
- **The fresh full-lane pass with no earlier findings given.** It found real highs the narrowed rounds were structurally blind to.
- **The second reviewer.** On several rounds one reviewer said "impressed" while the other found a real high. Neither reviewer was consistently the stricter one.
- **Merge prep while reviews ran.** The integration branches were built and green before the last lane closed, so the final top-up was a fast-forward.
- **The merge review.** It found a data-exposure bug that only existed where two lanes' outputs met, and several cases where the two sides of the API disagreed on one validation or rounding rule. No lane review could have seen these.
- **A state file kept current after every step.** Recovery after the orchestrator restart took one read: every branch was pushed, and the five-hour browser run had kept going on its own.
- **Report caps and findings-in-files.** The orchestrator's context stayed at decisions and verdicts through about 30 agent runs.

## 6. Proposed central changes

### `lbo.py`

1. **`lbo review`** should run a round end to end: build the prompt from a head template, a base..head range, the fix list and invariants. Then:
   - run each configured reviewer in parallel (retry once on a dropped connection, force UTF-8);
   - extract the JSON;
   - import the findings with `--lane` and `--round`;
   - print a one-line verdict per reviewer.

   This removes the hand-rolled shell per round, which is where encoding failures, interpreter-alias problems and lost rounds came from. It also makes the ledger complete by construction.
2. **`lbo preflight e2e`** should run before any end-to-end gate:
   - refuse any selected spec that names a production host;
   - sign in as each account the selected specs reference (found by grep) and fail fast if one is missing;
   - check each hard-coded host:port answers;
   - estimate run time from the last run.

   Fail in minutes, not after five hours.
3. **`lbo env check`**: each project declares its runtime versions, package manager, test DB and env files in config. On a new machine this prints what's missing, which makes rebuilding the environment a checklist instead of a discovery.
4. **`lbo status` at session start**: shows lanes with reviews newer than their last ledger entry, and lanes whose last round had no recorded run. A dropped ledger becomes visible in the first minute after a handoff.
5. **Shared-file warning:** `lbo review` flags a fix diff that touches files outside the lane's mapped area (shared services, global components), so the orchestrator stops and asks for a design instead of patching shared code itself.
6. **Long-pole flag:** `lbo report` marks a lane at twice the median rounds, and suggests the escalation wording in SKILL.md (below).
7. **`--expect-fail`** for `lbo run`: revert-and-fail proofs shouldn't count as failed runs (also noted in an earlier report).

### SKILL.md

1. **Ask for the design at the second recurrence in the same area,** not the third, and always before changing a shared module. A "shared module" is any file outside the lane's own area that other features import.
2. **Run the fresh full-lane pass when a design rewrite lands,** or at round 5, whichever comes first, not only after "more than about five rounds". The narrowed rounds are blind to the code they don't look at, and a rewrite is exactly when the rest of the lane goes unreviewed.
3. **Name state-machine UI work as high risk at level time.** Navigation guards, autosave with retries, dialogs and unload handlers behave like concurrency code. Give them the data-and-design pass before coding, as money and concurrency already get.
4. **Escalate a long-pole lane to the user** at twice the median rounds, with three options: keep going; ship with the remaining lows ticketed; or pull the lane from this deploy.
5. **One checkout per role from the start:**
   - one checkout that the test runner mounts;
   - one that any manual or end-to-end stack serves;
   - one per lane for edits.

   Never let a long-running stack and the test runner share a checkout.
6. **The brief checklist gains:**
   - "have no background tasks open when you report";
   - "don't kill processes you didn't start";
   - the second checkout's test command, when one exists.
7. **The handoff checklist gains:**
   - every test run and review goes through `lbo`;
   - run `lbo status` first;
   - run `lbo env check` on a new machine.
8. **Treat an agent's environment claims like reviewer findings: verify before acting.** In this run an agent reported a production host in a "safe" spec folder, and a grep showed it wasn't there.

### Templates

- A review head template for each kind of round (first, narrowed confirming, fresh full pass, merge review, design ask), so the orchestrator fills in a range and a fix list instead of writing a new prompt each round.
- A fix-list template with a "declined, and why" section and a proofs section, matching what the ledger expects.
