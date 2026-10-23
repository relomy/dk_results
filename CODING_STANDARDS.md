# Coding Standards

Read during review. Each rule is a judgement call; tooling-enforced rules live in tooling.

## Module layout

Related modules live in a package whose `__init__.py` exports the public names; callers import from the package (`completion_processor/` is the model).

## Compose collaborators

- A class with several jobs owns one collaborator per job, built or passed in `__init__` (`CompletionProcessor` builds `WarningScheduler`, `ContestSync`, `SoftFinishAnnouncer`).
- Stateless logic (formatting, parsing) is module-level functions.
- Values and config are dataclasses.
- External systems sit behind a `typing.Protocol` port (`LineupSolver`, `ContestResultsPort`).

## Inject time and I/O

The clock (a `now` callable) and every other side-effecting dependency are constructor arguments. Tests pass fakes rather than patching module globals.

## Tests

- Tests mirror the package: `tests/<area>/test_<behaviour>.py`, with shared fakes and builders as fixtures in that directory's `conftest.py`.
- Tests drive the public interface and replace only injected dependencies.
- Older flat splits (`tests/*_fakes.py` helpers) move to this layout when a PR next changes them.

## Assert exact outputs

Assert message text, stored values and exact log lines (`caplog.messages`). A truthiness check (`assert sender.messages`) is a finding.

## Change scope

Make the smallest safe change that solves the request, reaching for existing code and seams before new abstractions. Unrelated refactors go in their own PR.

## Domain vocabulary

Names use `GLOSSARY.md` terms. A change that contradicts an ADR says so explicitly.
