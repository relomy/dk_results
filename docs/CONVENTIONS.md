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
files in CI, so `--no-verify` does not bypass it. The script is canonical here;
relomy/dk_dashboard keeps a byte-identical copy, so change it here first.

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
