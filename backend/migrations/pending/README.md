# Parked migrations

Migrations here are **finished and reviewed** but chain off a `down_revision` that has
not merged yet. They are not dead code and not drafts.

## Why they can't just sit in `versions/`

Alembic builds the entire revision map before it executes anything. One unresolvable
`down_revision` therefore breaks *every* command, not just the one that would run the
broken file — including `alembic upgrade 0003` on a database that never had 0032 in the
first place.

The failure looks like this, for everyone, on every branch:

```
KeyError: '0031'
```

That is what a developer sees after `git pull && make migrate`. Nothing in the message
points at the parked file, and the natural reading is "my database is broken," so the
cost lands on whoever pulls rather than on whoever parked. Hence: out of the path.

## Current contents

**Empty.** First time since 4 August.

The pile peaked at six: 0009, 0019, 0020, and 0032–0034. It drained as the chain
below it merged, and none of the three that came out last needed a single edit —
they were written against the numbers §2 assigned them, those numbers became
real, and the files resolved untouched.

That is the argument for pointing `down_revision` at the number the map gives you
even when that revision doesn't exist yet. The alternative — chaining off whatever
happens to be in your `versions/` folder today — is what produced the 0002 fork in
#264 and the collision in #297, and those cost days each.

## Moving one back

```bash
git mv backend/migrations/pending/0032_allergies.py backend/migrations/versions/
cd backend && alembic upgrade head        # must reach 0032 with no KeyError
pytest tests/test_v314_invariants.py      # constraints must still hold
```

`tests/test_v314_invariants.py` searches `versions/` and `pending/` both, so the
constraint tests keep running while a migration is parked and need no edit when it
returns. A parked migration whose tests are skipped is a migration that quietly rots.

## Check what imports it before you park it

```bash
grep -rn "0019_files" backend/tests backend/scripts
```

This directory is deliberately **not** a package — no `__init__.py`, so alembic
never sees these files. That also means any test doing
`importlib.import_module("migrations.versions.0019_files")` raises
`ModuleNotFoundError` the moment the file moves here, and pytest fails at
**collection**, which takes down the whole backend suite — on staging and on
every open PR at once, with an error naming a file most authors have never
touched.

That happened when 0019 was parked. The fix in `tests/files/conftest.py` is to
load by file path and look in `versions/` first, then `pending/`:

```python
spec = importlib.util.spec_from_file_location("migration_0019", path)
```

Tests that apply a migration through an isolated `MigrationContext` don't need
it to be in the chain at all — only the module object. Write them that way and
parking costs nothing.

## Before parking anything else

Parking is for a revision that cannot resolve. It is not a way to defer a migration
that merely fails or is unfinished — that belongs on a branch, not on staging.
