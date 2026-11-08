# tinymigrate

A pure-Python, SQLAlchemy-based migration runner: it applies SQL migration files in its own
simple syntax and records them in its own version table.
`docs/SPEC.md` is what the package does, `docs/PLAN.md` the order it is built in.

## Scope

**Build the MVP, not the feature.** The smallest version that works end to end. No
options nobody asked for, no extension points with one implementation, no config with one
value, no abstractions with one caller.

- Work in small stacked PRs, one GitHub issue each (`docs/PLAN.md`). Each PR closes its
  issue, passes the checks on its own and leaves the tree working.
- Ideas that are not in the current PR go in `docs/FUTURE.md` (or a `followup` issue), not
  into the code. Design decisions, with the reason, go in `docs/DECISIONS.md`.
- Touch only what the change needs. Living docs describe the code that exists; if a doc
  disagrees with the tree, fix the doc in the same change.
- Process artifacts (plans, specs, review notes) stay out of the tree: `docs/superpowers/`
  is gitignored.
- Never commit, push or merge to `main` unasked. Stage files by name, never `git add -A`.

## Checks

Python 3.12, managed with `uv`. Always `uv run …`, never bare `python` or `pytest`; add
dependencies with `uv add`, and don't add one without discussion. All of these must pass
before a PR, and CI (`.github/workflows/ci.yml`) runs the same:

```bash
uv sync
uv run ruff format .        # CI runs `ruff format --check .`
uv run ruff check .
uv run ty check
uv run pytest
```

Fix failures rather than suppressing them. `# noqa` or `# ty: ignore[rule]` only for
deliberately invalid code (a negative test), always with a comment saying why.

## Tests

- Tests live in `tests/`, one `tests/test_<module>.py` per module. Plain functions with
  sentence names, annotated `-> None`: `test_a_failing_migration_leaves_no_version_row`.
- `asyncio_mode = "auto"`: async tests need no decorator.
- Simple values are module-level constants; fixtures are for setup/teardown and live in
  `tests/conftest.py`. Fakes, not mocks; no `unittest.mock`. Assert with plain `assert`,
  `pytest.raises(..., match=...)` for errors.

## Naming

- **Type names are singular**, including type aliases: name what one instance is
  (`Migration`, not `Migrations`).
- **A function name says what it does in technical terms**: the operation and what it acts
  on. No metaphor or personification. **A function that does work opens with an imperative
  verb**, never a past-tense name: `migrate_up`, `parse_migration`, `collect_migrations`,
  not `up`, `parsed` or `migrations`. Test names are the exception (sentences).
- Spell names out (`Configuration`, not `Config`). Module names are singular nouns
  (`errors.py`, `migration.py`). Private helpers and instance state take a leading `_`.
- Every module-level constant gets a comment giving its units and why it has that value.
  `DEFAULT_*` constants for parameter defaults.

## Python style

From `~/.claude/skills/style-pass/style-guide.md`; that file has the full guide.

- **Typing:** annotate every signature fully, including `-> None`, in tests too. `X | None`,
  builtin generics. `Any` only as a commented last resort; prefer a `Protocol`.
- **Data:** `@dataclass(frozen=True)` for value objects. A field gets a default only when
  the default means something.
- **Errors:** every error tinymigrate raises subclasses `tinymigrate.TinymigrateError`
  (`errors.py`, small docstring-only classes). Messages name what failed and what was
  expected, and name the migration file and line where there is one. Catch specific
  exceptions; no broad `except Exception`. `raise … from error` when translating. **No `assert` outside tests.**
- **Logging:** stdlib `logging`, never loguru. `logger = logging.getLogger(__name__)` per
  module; never configure handlers in the library. Lazy `%` arguments, not f-strings;
  lowercase plain-sentence messages (`"applied migration %s"`).
- **Imports** at module level. Keep `__init__.py` to explicit re-exports with `__all__`.
- **Idioms:** `pathlib` (never `os.path`), `encoding="utf-8"` on every file read, double
  quotes, f-strings with `!r` for user-supplied values, guard clauses, keyword-only `*`
  for options (`migrate_up(engine, directory, *, table=...)`). Leave calls on one line up
  to 180 columns rather than hand-wrapping.

### Comments

The default is no comment. A comment says what the code can't: why this and not the
obvious alternative, which invariant holds, what breaks if it changes. One or two lines;
name mechanisms, not images; never restate the code. No commented-out code.

### Docstrings

Both `"""` on their own lines, even for a one-liner (ruff D209/D213 enforce it). The
summary is one sentence on one line and says what the thing does first: a function opens
with an imperative verb ("Return the current version of the database."), a class with
what it is. Extra detail goes in prose paragraphs below a blank line, wrapped at 90
columns, covering only what the signature can't (ordering, transactions, what raises).
No `Args:`/`Returns:` sections, no roadmap or spec references, no descriptions of callers.
Single backticks for inline code. Skip docstrings on trivial helpers and modules.

```python
# Illustrative only; the real signature and behaviour are whatever SPEC.md and the code say.
def get_version(engine: Engine, *, table: str = DEFAULT_TABLE) -> int:
    """
    Return the newest applied migration version, or 0 for a fresh database.

    Creates the version table when it does not exist.
    """
```

## Commits and PRs

Squash-merged; the PR title becomes the commit subject, an outcome in plain English with
no trailing period ("Apply migrations up through SQLAlchemy"). The PR body says what
changed, why, how it was tested, what is unverified, and `Closes #<issue>`.
