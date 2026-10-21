# Code Conventions

## Change philosophy

- Make the smallest safe change that solves the request.
- Prefer existing code and seams before adding abstractions.
- Keep unrelated refactors out of the change.

## Boundaries

- Keep edits in this repository.
- Ask before changing public outputs or integrations.
- Ask before changing `../dfs_common` or any other repository.

## Token budget

Agents read files whole, so no committed file may exceed 5,000 tokens, where
tokens = bytes / 4 (20,000 bytes; exactly at budget passes).
`scripts/check-token-budget.sh` enforces it on staged files as a pre-commit
hook (enable it as in `docs/TESTING.md`, "Git hooks") and on a PR's changed
files in CI (the `token-budget` job in `.github/workflows/ci.yml`), so
`--no-verify` does not bypass it. relomy/dk_dashboard carries
a port of the script; keep their behaviour in sync.

### Splitting an over-budget file

Split along a real seam, not at an arbitrary line count.

- **Python module**: turn it into a package, or sibling modules, and re-export
  the public names from the original import path so callers don't change.
  Names that tests monkeypatch (for example `collector.load_vips`) must stay in
  the module the tests patch.
- **Python test file**: split by behaviour under test into several `test_*.py`
  files. Move shared fakes and builders into a helper module whose name does
  not start with `test_`, so pytest doesn't collect it.
- **Markdown**: split by H2 into linked pages, or move content that isn't the
  doc's job to the doc that owns it. Sections that tools read stay put:
  `## Breaking changes` in `docs/SNAPSHOT_SCHEMA.md` is read by the schema
  compatibility gate and must remain in that file.
- **Anything else**: split into smaller files along its natural sections.

A split is a pure move: no behaviour change, assertions moved and never
edited. Prove it with the working tree against the base before opening the PR,
and paste the output into the PR's evidence:

```bash
uv run scripts/check-pure-move.py              # --base REF; default origin/main
```

It runs pytest on both trees (the base from `git archive`, on this venv) and
exits 1 when the head collects fewer tests, when a base assertion in `tests/`
is missing from the head, when a `src/` function changed or lost covered
lines, or when a test fails in either tree. Assertions (`assert`,
`pytest.raises`/`warns`/`approx`, mock `assert_*` calls) are compared as
`ast.unparse` text, so reformatting passes and edits don't. Functions are matched by qualified name plus a hash of their
AST, so they may move between files; module-level lines such as imports are
not compared. Exit 2 means it could not run, for example an unknown ref or a
collection error.

#### Source splits

- **Coverage first**: before moving source, add characterization tests through
  the public interface until the file's line and branch coverage is complete or
  every gap is explained. Tests land first; for a pure move, in a separate first
  commit.
- **Pure move**: keep public entry points in the original module, re-export
  public names (`from .x import Y as Y`), leave monkeypatched names where tests
  patch them, and keep moved helpers' names (a rename changes
  `check-pure-move`'s key). Run
  `uv run scripts/check-pure-move.py --base HEAD~1` on the move commit alone so
  every moved function matches. It compares line coverage only; compare
  `--cov-branch` totals too.
- **Complexity ratchet**: `complexity-ratchet` keys functions by module path, so
  a function above complexity 10 (tests included) moved to a new module reads as
  new and fails. Keep those in the original file.
- **Over-budget class**: methods that leave the class are reported changed
  (`check-pure-move` keys `Class.method`), so this is not a pure move. Refactor
  into collaborator classes: land a tests-only PR first that pins behaviour
  (message contents, stored values, loop and boundary cases), then the refactor
  PR, which leaves those tests unchanged.
- **Mutation check**: before any split that is not a pure move, run
  `uv run --group quality scripts/mutate-file.sh <src-file> <test paths...>`
  (about 10 s for a small module). Add assertions until every survivor is log
  text or explained. Paste the before and after `mutation score` lines into the
  tests PR's evidence.
- **Docs**: update `docs/MODULES.md` for any split.

### Generated files

Files no one authors by hand (`uv.lock`, `contract/snapshot.schema.json`,
`contract/goldens/*.json`) are declared once as `linguist-generated` in
`.gitattributes`; the check skips them, as it does binaries and deletions.
Declare new codegen output the same way.

### Grandfathered files

Files already over budget when the check was added carry a
`token-budget=<N>` attribute in `.gitattributes`, set to their size then. They
may shrink but never grow past `N`. When you split one under 5,000 tokens,
delete its `token-budget` line in the same change.
