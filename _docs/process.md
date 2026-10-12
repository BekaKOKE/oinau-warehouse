# Process

How we build the warehouse feature. Work is driven by GitHub issues (repo `uproxx111/oinau-pro`), one issue at a time, with three roles: PM, Engineer, QA. Role instructions are in `_docs/team/`.

## Source of truth

- The design: `_docs/plan.md`, `_docs/decisions.md`, `_docs/warehouse-design.md`.
- The backlog: GitHub issues with label `mvp` (first release) or `post-mvp` (later). `_docs/tasks.md` is the original list the issues were created from.
- Issue format: `_docs/task-template.md`.

## Life of an issue

1. **Groom (PM).** Pick the next open `mvp` issue whose dependencies are closed. Read the design sections it refers to. Rewrite the issue body with: Goal, Acceptance criteria (checkable), Out of scope, Constraints, Design references. Split the issue if it is too big for one commit.
2. **Implement (Engineer).** Work on branch `feature/warehouse`. Write the code and its tests, run the checks from `AGENTS.md` for the touched module, commit once, push. Post a comment on the issue: what was done, files touched, commands run and their result.
3. **Test (QA).** QA has not seen the implementation reasoning. QA reads the issue, checks every acceptance criterion against the code and runs the module tests, ruff and mypy (or the frontend checks). QA posts exactly one verdict comment, beginning with `## QA: PASS` or `## QA: FAIL`, followed by a checklist per criterion and the commands run.
4. **Close.** On PASS the orchestrator posts a final comment with the commit hash and closes the issue. On FAIL the engineer fixes and QA tests again. After 3 FAILs on the same issue, stop and write down the blocker in the issue for the human.

## Orchestrator rules (loop / `/goal`)

The orchestrator is the main session. It does not write code itself; it starts a PM, Engineer or QA sub-agent with a short prompt that points to the role file and the issue number, and reads the result from the issue.

- Order: lowest-numbered open `mvp` issue first, but never before the issues it depends on are closed.
- Per issue: Groom → Implement → QA → (fix loop) → close.
- Stop when: all `mvp` issues are closed, or an issue is blocked after 3 FAILs, or something would break a safety rule.
- Never close an issue without a `## QA: PASS` comment and a commit hash comment.
- After the last issue, open a pull request from `feature/warehouse` to `main` and stop. The owner reviews, merges and deploys.

## Safety rules

The rules in `AGENTS.md` apply to every role. The most important:

- only branch `feature/warehouse`; never touch `main`; no force-push;
- additive migrations only;
- no secrets, no `.env` in commits;
- no `Co-Authored-By` or AI mentions in commits, issues, comments or PRs;
- module-level tests only; the full suite runs in CI.

## Testing policy

- Backend: tests for the module in `apps/backend/tests/`, run with `uv run pytest tests/<module>`; plus `ruff` and `mypy`.
- Frontend: Vitest for the changed app, plus lint and typecheck.
- Concurrency and constraint tests are required where the design says so (design §9).
- A feature without a test for its main rule is not done.

## When something is unclear

If the design is silent or contradictory, the engineer does not guess. They write the question in the issue and mark it `blocked` in the comment; the PM resolves it by updating the design file, or the human decides.
