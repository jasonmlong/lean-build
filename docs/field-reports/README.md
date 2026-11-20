# Field reports

Each file here is one project's account of a lean-build run: what slowed it down, where the process or `lbo.py` didn't help, and what to change centrally. Reports leave out project names, clients, people, paths and branch names, so the lessons can be compared across projects and the process improved in one place.

This repo is public: leave out anything that identifies a project, client, person, machine or date (no names, domains, paths, branch names, ticket ids or product terms). Name files `NNN-<short-stack-or-shape>.md` with the next free number, and use these sections so reports can be compared:

1. **Shape of the build**: stack in generic terms, lane count, risk levels, machine/OS, and whether the run crossed a context or machine handoff.
2. **Numbers**: rounds per lane, findings per lane, findings declined as not real, wall-clock and test hours where known. Say which numbers came from `lbo report` and which are estimates.
3. **What cost the most time**: in order, with the cause.
4. **Where the process wasn't followed**: and why (the rule was unclear, the tool didn't enforce it, or a judgement call went wrong).
5. **What worked**: so it isn't removed by accident.
6. **Proposed central changes**: to SKILL.md, `lbo.py`, the templates or the config, each one concrete enough to build.
