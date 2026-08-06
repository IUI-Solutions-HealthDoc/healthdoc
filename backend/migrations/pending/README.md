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

| file | chains off | unblocked when |
|---|---|---|
| `0032_allergies.py` | 0031 | 0031 merges |
| `0033_charge_master.py` | 0032 | with 0032 |
| `0034_ipd_bed_integrity.py` | 0033 | with 0033 |

## Moving one back

```bash
git mv backend/migrations/pending/0032_allergies.py backend/migrations/versions/
cd backend && alembic upgrade head        # must reach 0032 with no KeyError
pytest tests/test_v314_invariants.py      # constraints must still hold
```

`tests/test_v314_invariants.py` searches `versions/` and `pending/` both, so the
constraint tests keep running while a migration is parked and need no edit when it
returns. A parked migration whose tests are skipped is a migration that quietly rots.

## Before parking anything else

Parking is for a revision that cannot resolve. It is not a way to defer a migration
that merely fails or is unfinished — that belongs on a branch, not on staging.
