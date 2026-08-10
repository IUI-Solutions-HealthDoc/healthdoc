"""
Standard action names for audit_logs.action.

Repo path: backend/app/audit/actions.py

NOT a database change. audit_logs.action is already a plain text column
(schema doc §3 0003: "action text NOT NULL -- create | update | merge |
login | ..."), not a CHECK-constrained enum — the doc itself shows it as
an open, growing list of example values, not a closed set. So this file
is just a shared list of spellings, so every module writes "login" the
same way instead of "Login"/"LOGIN"/"user_login" scattered across the
codebase. No migration needed, nothing for Postgres to know about.

Covers every item in the compliance list (26.1 Audit Events):
  Login/logout, Patient create/update/view, UHID merge, THID
  merge/unmerge, Diagnosis update, Prescription create/change, Lab
  result entry/update/approval, Radiology report update/approval,
  Pharmacy dispense/return, Payment/refund, Inventory adjustment, User
  role change, Data export/print, Break-glass emergency access.
"""


class AuditAction:
    # Generic row changes -- listeners.py uses these automatically for
    # any model that opts in (see that file's docstring).
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"

    # Auth -- NOT a row change, must be called manually (see events.py)
    LOGIN = "login"
    LOGOUT = "logout"

    # Reads -- NOT row changes, must be called manually
    VIEW = "view"
    EXPORT = "export"
    PRINT = "print"
    BREAK_GLASS_ACCESS = "break_glass_access"

    # Patient identity actions -- more specific than plain "update", so
    # the audit trail reads clearly instead of just saying "update"
    UHID_MERGE = "uhid_merge"
    THID_MERGE = "thid_merge"
    THID_UNMERGE = "thid_unmerge"

    # Clinical workflow actions -- more specific than plain "update"
    APPROVE = "approve"
    DISPENSE = "dispense"
    RETURN = "return"

    # Account governance -- roles live in Keycloak (schema doc: "role
    # lives in Keycloak"), not as a column in `users`, so this can never
    # be picked up by listeners.py watching database rows
    ROLE_CHANGE = "role_change"
