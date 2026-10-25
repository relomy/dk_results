# Delivery Workflow

## Completion and handoff

Follow the setup, enforcement, check, and completion guidance in
[`docs/TESTING.md`](TESTING.md) before handoff. Report every command run and
every failure with its exact command and a concise summary.

## Token budget

Agents read files whole, so no committed file may exceed 5,000 tokens, where
tokens = bytes / 4 (20,000 bytes; exactly at budget passes).
See [`docs/TESTING.md`](TESTING.md#git-hooks) for the check, setup, and
enforcement locations.

### Splitting an over-budget file

Split along a real seam, not at an arbitrary line count.

- **Python module**: turn it into a package of the same name laid out per
  [`CODING_STANDARDS.md`](../CODING_STANDARDS.md) (Module layout);
  `__init__.py` re-exports the original public names.
- **Python test file**: turn it into a test directory per
  [`CODING_STANDARDS.md`](../CODING_STANDARDS.md).
- **Markdown**: split by H2 into linked pages, or move content that isn't the
  doc's job to the doc that owns it. Sections that tools read stay put:
  `## Breaking changes` in `docs/SNAPSHOT_SCHEMA.md` is read by the schema
  compatibility gate and must remain in that file.
- **Anything else**: split into smaller files along its natural sections.

A split is a pure move: no behaviour change, assertions moved and never
edited. Prove it against the base before opening the PR, and include the output
in the PR's evidence. The command and its comparison rules are in
[`docs/TESTING.md`](TESTING.md#completion-checks).

#### Source splits

- **Coverage first**: before moving source, add characterization tests through
  the public interface until the file's line and branch coverage is complete or
  every gap is explained. Tests land first; for a pure move, in a separate first
  commit.
- **Pure move**: keep public entry points in the original module, leave
  patched names where tests patch them (for example `collector.load_vips`), and
  keep moved helpers' names (a rename changes
  `check-pure-move`'s key). On the move commit alone, run the pure-move check
  against the preceding commit so every moved function matches. It compares line
  coverage only; compare `--cov-branch` totals too.
- **Complexity ratchet**: `complexity-ratchet` keys functions by module path, so
  a function above complexity 10 (tests included) moved to a new module reads as
  new and fails. Keep those in the original file.
- **Over-budget class**: methods that leave the class are reported changed
  (`check-pure-move` keys `Class.method`), so this is not a pure move. Refactor
  into collaborators ([`CODING_STANDARDS.md`](../CODING_STANDARDS.md)): land a
  tests-only PR first that pins behaviour (message contents, stored values,
  loop and boundary cases), then the refactor PR, which leaves those tests
  unchanged.
- **Mutation check**: before a split that is not a pure move, run the
  pre-refactor mutation check described in [`docs/TESTING.md`](TESTING.md).
  Add assertions until every survivor is log text or explained. Paste the
  before and after `mutation score` lines into the tests PR's evidence.
- **Docs**: update `docs/MODULES.md` for any split.

#### Generated files

Files no one authors by hand (`uv.lock`, `contract/snapshot.schema.json`,
`contract/goldens/*.json`) are declared once as `linguist-generated` in
`.gitattributes`; the check skips them, as it does binaries and deletions.
Declare new codegen output the same way.

#### Grandfathered files

Files already over budget when the check was added carry a
`token-budget=<N>` attribute in `.gitattributes`, set to their size then. They
may shrink but never grow past `N`. When you split one under 5,000 tokens,
delete its `token-budget` line in the same change.

## Commit messages

- Format: `type(scope): short summary`.
- Keep `type` lowercase (`feat`, `fix`, `test`, `docs`, `chore`, etc.); make
  the summary imperative and concise.

## Branches, pull requests, and review

Follow the applicable task and repository instructions for branch, base, merge,
and pull-request requirements. When a pull request is required, open it after
the spec work is complete. Review the diff against its intended base for both
standards and spec coverage before opening the PR; include verification evidence
with it. Follow the applicable instructions for merge authorization.

## Handoff

In the final response, state:

- what changed, including files and behavior;
- what commands were run and whether they passed;
- any remaining risk or follow-up.
