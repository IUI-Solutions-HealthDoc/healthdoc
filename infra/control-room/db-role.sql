-- The control-room server's database role: what the control-room API may
-- touch, and nothing else.
--
-- The control room runs on its own host (like BHAVYA's command-and-control
-- dashboard beside its HIMS), so a compromise there must not become a
-- compromise of patient records. The 15-minute capture therefore runs on the
-- hospital server, which already holds full access, and writes counts into
-- facility_pulse and diagnosis_daily_counts; this role only reads them. The
-- one live read is a facility's activity trail, which is audited and shows
-- patients as per-day codes, so the role reads the event tables the trail is
-- built from and staff names, and has no access at all to patients (names,
-- ABHA numbers, contacts), notes, files, consent, billing or identity
-- tables. Nothing here grants UPDATE or DELETE.
--
-- Run once on the central database as its owner, then give the role a login
-- separately so the password never sits in this file:
--
--   psql "$OWNER_URL" -v ON_ERROR_STOP=1 -f infra/control-room/db-role.sql
--   psql "$OWNER_URL" -c "ALTER ROLE healthdoc_control_room LOGIN PASSWORD '...'"
--
-- Re-running is safe. tests/monitor/test_control_room_db_role.py reruns every
-- control-room test with the officer endpoints executing as this role, and
-- fails on a missing grant or on one that reaches patients.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'healthdoc_control_room') THEN
        CREATE ROLE healthdoc_control_room NOLOGIN;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO healthdoc_control_room;

-- The board, the facility drill-down and the disease trends: snapshots the
-- hospital server's capture wrote, and the officers' areas its superadmin granted.
-- icd_codes is the public ICD reference the trends take their titles from.
GRANT SELECT ON facility_pulse, diagnosis_daily_counts, monitor_scopes, facilities, icd_codes
TO healthdoc_control_room;

-- The activity trail: who was registered, seen, dispensed to, tested, operated
-- on, admitted and discharged, by which staff. Patient ids are read only to
-- derive the masked per-day code.
GRANT SELECT ON
    visits, encounters, departments, wards, admissions, discharges,
    orders, prescription_items, lab_order_items, lab_results,
    pharmacy_dispenses, pharmacy_dispense_items, ot_schedules, ot_records
TO healthdoc_control_room;
-- Staff appear by name. The sign-in check reads the account columns so that a
-- token from anyone but an officer is refused (403), not an error; email and
-- mobile stay out of reach.
GRANT SELECT (id, keycloak_sub, username, full_name, facility_id, department_id, is_active)
ON users TO healthdoc_control_room;

-- Opening a trail is audited. audit_logs is append-only (its trigger refuses
-- UPDATE); the chain trigger runs as the inserting role and upserts the
-- per-facility counter. The insert returns the row's id and time, so those two
-- columns are readable; the log itself, every facility's history, is not.
GRANT INSERT, SELECT (id, created_at) ON audit_logs TO healthdoc_control_room;
GRANT SELECT, INSERT, UPDATE ON audit_counters TO healthdoc_control_room;
