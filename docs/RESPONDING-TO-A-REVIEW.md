# Responding to a PR review

Short version: **merging `staging` into your branch is not a response to a review.**
It's a useful thing to do, but the reviewer's items stay open and GitHub will show your PR
as "updated" either way — so it looks answered when it isn't.

This page exists because that's happened several times, and because a round trip costs
about a day: you push, it sits, I re-read the whole PR, and we discover nothing changed.

---

## Before you push

Run this. It's the same four checks CI runs, and it takes a few seconds:

```bash
./scripts/pre-push-check.sh
```

If it reports blockers, the reviewer will report the same ones. Fixing them first saves a
round trip.

## Then, in the PR

Reply to the review with one line per item. Three valid answers:

| answer | example |
|---|---|
| **Fixed** | "1. Fixed — `down_revision` now `0003a`." |
| **Disagree, because** | "2. Kept `COUNT(*)`: this path is single-writer, see `worker.py:40`. Happy to change if you disagree." |
| **Not yet / need help** | "3. Not done — I don't follow why the fallback needs a thread. Can we talk?" |

The third is completely fine and always has been. What costs time is silence, because I
can't tell it apart from "done".

**Disagreeing is genuinely welcome.** Several review items this week were wrong —
`MIG-REVISION` rejected a format I'd asked for, the drift checker invented twelve missing
columns, and a PII rule flagged a correct CHECK constraint. If something looks wrong, it
might be.

## If you're blocked

Say so in the PR or the channel, the same day. Two examples from this week where someone
worked around a gap instead of raising it:

- A hardcoded timezone with a comment reading *"this project currently has no path to get a new migration approved"* — that was true, it was my fault, and it took ten minutes to fix once I knew.
- Three people independently wrote the same `keycloak_sub → users.id` lookup because it wasn't on `staging`. Two bugs came out of that.

Neither was a coding mistake. Both were someone deciding not to ask.

---

## Two things that cause most re-review rounds

### 1. Fixing the service and not the caller

If a review says "this isn't scoped to the facility", check **where the value enters the
system**. A guard in the service does nothing if the router hands it a value straight from
the request body:

```python
# service.py — correct, and irrelevant
async def search(db, *, facility_id: uuid.UUID): ...   # required, no default

# router.py — undoes it
facility_id=payload.facility_id                        # caller picks their own scope
```

For anything security-related, ask: *does this value come from the token, or from the
request?*

### 2. Building a table that isn't the one in §3

`docs/database-schema.md` §3 is the binding definition. It's long, so before writing a
migration, find your table's block and copy the column list from it:

```bash
grep -n '^\*\*your_table_name\*\*' docs/database-schema.md
```

Where you think §3 is wrong, say so — it's been wrong more than once and gets corrected.
What doesn't work is quietly building something different, because the drift checker will
find it and we'll spend a round on it.

---

## Migration chain order

Migrations merge in the order of `docs/database-schema.md` §2. Yours cannot merge until
everything below it has, no matter how finished it is.

```bash
./scripts/pr-triage.sh        # what's ahead of you
```

If you're blocked behind someone, that's worth saying out loud — the person ahead may not
know anyone is waiting.
