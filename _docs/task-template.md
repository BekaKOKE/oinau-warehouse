# Issue template

Every issue is groomed into this shape by the PM before implementation.

```markdown
## Goal

One or two sentences: what works after this issue that did not work before.

## Description

What to build and where (modules, files, endpoints). Reference the design sections.

## Acceptance criteria

- [ ] Checkable statement 1 (behaviour, error code, constraint)
- [ ] Checkable statement 2
- [ ] Tests listed in the design for this part exist and pass
- [ ] ruff and mypy (or lint and typecheck) are clean for the touched code

## Out of scope

- Things that belong to other issues (name the issue number)

## Constraints

- Safety rules from AGENTS.md that matter here (additive migration, no prices for WAREHOUSE role, ...)
- Dependencies: issues that must be closed first

## References

- `_docs/warehouse-design.md` §x.y
- `_docs/decisions.md` Tx
```

Comments added later in the issue:

- Engineer: `## Implementation` — summary, files, commands run.
- QA: `## QA: PASS` or `## QA: FAIL` — one line per acceptance criterion, commands run.
- Orchestrator: `## Done` — commit hash, then the issue is closed.
