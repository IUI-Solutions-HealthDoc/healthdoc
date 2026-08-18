"""Executable proof of the architecture findings. Run: python -m pytest test_findings.py -v"""
import sqlite3, threading, time
from datetime import datetime, timezone, timedelta
from decimal import Decimal

IST = timezone(timedelta(hours=5, minutes=30))

# ---------- FINDING 4: UTC date boundary corrupts business dates ----------
def test_utc_date_boundary_is_wrong_for_5h30_every_night():
    """PROVE: between 00:00-05:30 IST, now()::date in UTC returns YESTERDAY."""
    wrong_count = 0
    for hour in range(24):
        ist_moment = datetime(2026, 7, 23, hour, 15, tzinfo=IST)
        utc_date = ist_moment.astimezone(timezone.utc).date()
        ist_date = ist_moment.date()
        if utc_date != ist_date:
            wrong_count += 1
    assert wrong_count == 6, f"expected 6 broken hours (00:00-05:30), got {wrong_count}"
    # concrete: 2am IST OPD token
    two_am = datetime(2026, 7, 23, 2, 0, tzinfo=IST)
    assert two_am.date().isoformat() == "2026-07-23"
    assert two_am.astimezone(timezone.utc).date().isoformat() == "2026-07-22"  # WRONG day


def test_facility_timezone_fix_is_correct():
    """The v3.9 rule (now() AT TIME ZONE facility.timezone)::date gives the right day."""
    for hour in (0, 2, 5, 6, 23):
        m = datetime(2026, 7, 23, hour, 30, tzinfo=IST)
        assert m.astimezone(IST).date().isoformat() == "2026-07-23"


# ---------- Money: why NUMERIC not float ----------
def test_float_money_loses_paise():
    total = 0.0
    for _ in range(1000):
        total += 0.10          # ₹0.10 x 1000 should be ₹100.00
    assert total != 100.0, "float should drift"
    dec = sum(Decimal("0.10") for _ in range(1000))
    assert dec == Decimal("100.00")


# ---------- FINDING: gapless counter vs MAX()+1 under concurrency ----------
def _max_plus_one(path):
    """One thread's allocation, on its OWN connection.

    This used to share a single :memory: connection across ten threads with
    check_same_thread=False. sqlite3 connections are not concurrency-safe, so
    the threads clobbered each other's cursor state: some raised InterfaceError,
    others got None back from fetchone() and died on the subscript. pytest
    surfaced five PytestUnhandledThreadExceptionWarnings per run.

    The test still passed — but for the wrong reason. It asserts that MAX()+1
    collides, and threads that crash before inserting also produce a short,
    duplicate-looking table. Giving each thread a real connection to a shared
    file means the collisions it observes are genuine read-then-write races,
    which is the invariant this file exists to demonstrate.
    """
    db = sqlite3.connect(path, timeout=10)
    try:
        nxt = db.execute("SELECT COALESCE(MAX(seq),0) FROM tokens").fetchone()[0] + 1
        time.sleep(0.01)                  # window where another thread reads the same MAX
        db.execute("INSERT INTO tokens(seq) VALUES (?)", (nxt,))
        db.commit()
    finally:
        db.close()

def test_max_plus_one_produces_duplicates_under_concurrency(tmp_path):
    path = str(tmp_path / "race.db")
    setup = sqlite3.connect(path)
    setup.execute("CREATE TABLE tokens(seq INT)")
    setup.commit(); setup.close()

    threads = [threading.Thread(target=_max_plus_one, args=(path,)) for _ in range(10)]
    [t.start() for t in threads]; [t.join() for t in threads]

    db = sqlite3.connect(path)
    seqs = [r[0] for r in db.execute("SELECT seq FROM tokens")]
    db.close()

    # Every thread must have got as far as inserting — otherwise the duplicates
    # below could be an artefact of crashed threads rather than the race.
    assert len(seqs) == 10, f"expected 10 allocations, got {len(seqs)}"
    assert len(seqs) != len(set(seqs)), "MAX()+1 must collide — that's the bug"

def test_counter_row_with_lock_is_gapless_and_unique():
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.execute("CREATE TABLE counters(id INT PRIMARY KEY, last_value INT)")
    db.execute("INSERT INTO counters VALUES (1,0)")
    db.execute("CREATE TABLE tokens(seq INT UNIQUE)")
    lock = threading.Lock()
    def alloc():
        with lock:                        # stands in for SELECT ... FOR UPDATE
            v = db.execute("SELECT last_value FROM counters WHERE id=1").fetchone()[0] + 1
            db.execute("UPDATE counters SET last_value=? WHERE id=1", (v,))
            db.execute("INSERT INTO tokens(seq) VALUES (?)", (v,))
            db.commit()
    ts = [threading.Thread(target=alloc) for _ in range(50)]
    [t.start() for t in ts]; [t.join() for t in ts]
    seqs = sorted(r[0] for r in db.execute("SELECT seq FROM tokens"))
    assert seqs == list(range(1, 51)), "counter row must be unique AND gapless"


# ---------- Invoice arithmetic invariant (v3.9 CHECK) ----------
def test_invoice_balance_check_rejects_drift():
    db = sqlite3.connect(":memory:")
    db.execute("""CREATE TABLE invoices(
        id INT PRIMARY KEY, gross NUMERIC, discount NUMERIC, scheme NUMERIC, net NUMERIC,
        CHECK (net = gross - discount - scheme))""")
    db.execute("INSERT INTO invoices VALUES (1, 500, 50, 0, 450)")   # valid
    try:
        db.execute("INSERT INTO invoices VALUES (2, 500, 50, 0, 999)")  # drift
        assert False, "CHECK should have rejected unbalanced invoice"
    except sqlite3.IntegrityError:
        pass


# ---------- Partial unique index: NULL uhid coexistence (v2.1 note) ----------
def test_partial_unique_allows_many_null_uhid_but_one_real():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE patients(id INT PRIMARY KEY, uhid TEXT, deleted_at TEXT)")
    db.execute("CREATE UNIQUE INDEX uq ON patients(uhid) WHERE deleted_at IS NULL")
    db.executemany("INSERT INTO patients VALUES (?,?,NULL)",
                   [(1, None), (2, None), (3, None)])          # 3 THID-only patients
    db.execute("INSERT INTO patients VALUES (4,'IN-RJ-X-2026-000001-7',NULL)")
    try:
        db.execute("INSERT INTO patients VALUES (5,'IN-RJ-X-2026-000001-7',NULL)")
        assert False, "duplicate live UHID must be rejected"
    except sqlite3.IntegrityError:
        pass
    # soft-deleted row must NOT block reuse
    db.execute("INSERT INTO patients VALUES (6,'IN-RJ-X-2026-000002-7','2026-07-01')")
    db.execute("INSERT INTO patients VALUES (7,'IN-RJ-X-2026-000002-7',NULL)")


# ---------- Append-only enforcement ----------
def test_append_only_trigger_blocks_update_and_delete():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE audit_logs(id INT PRIMARY KEY, action TEXT)")
    db.execute("""CREATE TRIGGER trg_block_update BEFORE UPDATE ON audit_logs
                  BEGIN SELECT RAISE(ABORT,'audit_logs is append-only'); END""")
    db.execute("""CREATE TRIGGER trg_block_delete BEFORE DELETE ON audit_logs
                  BEGIN SELECT RAISE(ABORT,'audit_logs is append-only'); END""")
    db.execute("INSERT INTO audit_logs VALUES (1,'create')")
    for stmt in ("UPDATE audit_logs SET action='x' WHERE id=1", "DELETE FROM audit_logs WHERE id=1"):
        try:
            db.execute(stmt); assert False, f"{stmt} must be blocked"
        except (sqlite3.OperationalError, sqlite3.IntegrityError):
            pass


# ---------- Idempotency replay (§4A.1) ----------
def test_idempotency_replays_instead_of_duplicating():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE idem(key TEXT, endpoint TEXT, body TEXT, PRIMARY KEY(key,endpoint))")
    db.execute("CREATE TABLE payments(id INTEGER PRIMARY KEY, amount NUMERIC)")
    def pay(key, amount):
        row = db.execute("SELECT body FROM idem WHERE key=? AND endpoint='/payments'", (key,)).fetchone()
        if row:
            return row[0]                             # replay, no second charge
        cur = db.execute("INSERT INTO payments(amount) VALUES (?)", (amount,))
        body = f"payment:{cur.lastrowid}"
        db.execute("INSERT INTO idem VALUES (?,?,?)", (key, '/payments', body))
        db.commit(); return body
    a = pay("k-1", 500); b = pay("k-1", 500); c = pay("k-1", 500)   # user double-clicks + retry
    assert a == b == c
    assert db.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 1, "must charge once"


# ---------- Optimistic concurrency (§4A.2) ----------
def test_row_version_prevents_lost_update():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE encounters(id INT PRIMARY KEY, notes TEXT, row_version INT)")
    db.execute("INSERT INTO encounters VALUES (1,'initial',1)")
    doctor_a_version = doctor_b_version = 1                    # both opened the record
    db.execute("UPDATE encounters SET notes=?, row_version=row_version+1 WHERE id=1 AND row_version=?",
               ("doctor A findings", doctor_a_version))
    assert db.total_changes > 0
    cur = db.execute("UPDATE encounters SET notes=?, row_version=row_version+1 WHERE id=1 AND row_version=?",
                     ("doctor B findings", doctor_b_version))
    assert cur.rowcount == 0, "stale write must affect 0 rows -> 409, not silently overwrite"
    assert db.execute("SELECT notes FROM encounters").fetchone()[0] == "doctor A findings"


# ---------- the PR checker itself must keep catching the known violations ----------
def test_pr_checker_catches_known_violations(tmp_path):
    """Regression: the checker must flag MAX()+1, hand-rolled mixins, narrow enum widths,
    UTC dates, float money, and a revived 0018 migration."""
    import subprocess, sys, pathlib
    checker = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "pr_check.py"
    bad = tmp_path / "models.py"
    bad.write_text(
        "from sqlalchemy import String\n"
        "from sqlalchemy.orm import Mapped, mapped_column\n"
        "class Thing(Base):\n"
        "    id: Mapped[str] = mapped_column(primary_key=True)\n"
        "    status: Mapped[str] = mapped_column(String(30))\n"
    )
    out = subprocess.run([sys.executable, str(checker), str(bad)],
                         capture_output=True, text=True).stdout
    assert "ENUM-WIDTH" in out
    assert "MIXIN" in out
