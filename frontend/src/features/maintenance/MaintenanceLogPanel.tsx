"use client";

/**
 * Equipment service record (NABH).
 *
 * Lives on the department screen rather than a page of its own: a maintenance
 * log belongs to a machine, a machine belongs to a department, and the people
 * who record service are the technicians operating it — lab_tech and
 * radiology_tech are on the endpoint's role list alongside admin.
 */
import { useCallback, useEffect, useState } from "react";

import { listDepartments } from "@/features/admin/api/departments";
import type { Department } from "@/features/admin/api/departments";
import { ApiError } from "@/lib/api";
import { useLocale, type MessageKey } from "@/lib/i18n";

import { createMaintenanceLog, listMaintenanceLogs } from "./api";
import type { MaintenanceLog, MaintenanceType } from "./types";

const TYPE_KEYS: Record<MaintenanceType, MessageKey> = {
  preventive: "maintenance.type.preventive",
  breakdown: "maintenance.type.breakdown",
  calibration: "maintenance.type.calibration",
  qa_check: "maintenance.type.qa_check",
};

export function MaintenanceLogPanel() {
  const { t, localizeField } = useLocale();
  const [logs, setLogs] = useState<MaintenanceLog[] | null>(null);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState("");

  const [machineId, setMachineId] = useState("");
  const [departmentId, setDepartmentId] = useState("");
  const [type, setType] = useState<MaintenanceType>("preventive");
  const [performedAt, setPerformedAt] = useState("");
  const [vendor, setVendor] = useState("");
  const [downtime, setDowntime] = useState("");
  const [notes, setNotes] = useState("");

  const load = useCallback(async () => {
    try {
      const [logResult, deptResult] = await Promise.all([
        listMaintenanceLogs(filter.trim() || undefined),
        listDepartments(),
      ]);
      setLogs(logResult);
      setDepartments(deptResult.items);
      setError(null);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : t("maintenance.loadFailed"));
    }
  }, [filter, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const submit = async () => {
    setBusy(true);
    try {
      await createMaintenanceLog({
        machine_id: machineId.trim(),
        department_id: departmentId,
        maintenance_type: type,
        // datetime-local gives a naive string; the server wants an instant.
        performed_at: new Date(performedAt).toISOString(),
        performed_by_vendor: vendor.trim() || null,
        // Empty is null, not 0 — "not recorded" and "no downtime" are different
        // claims, and a QA reviewer reading a run of zeros would conclude the
        // machines never went down.
        downtime_minutes: downtime.trim() === "" ? null : Number(downtime),
        notes: notes.trim() || null,
      });
      setMachineId("");
      setPerformedAt("");
      setVendor("");
      setDowntime("");
      setNotes("");
      await load();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : t("maintenance.recordFailed"));
    } finally {
      setBusy(false);
    }
  };

  const departmentName = (id: string) => {
    const dept = departments.find((d) => d.id === id);
    return dept ? localizeField(dept.name, dept.name_hi) : id;
  };

  return (
    <div className="space-y-6">
      {error ? (
        <p role="alert" className="rounded-md bg-danger-muted p-3 text-sm text-danger">
          {error}
        </p>
      ) : null}

      <div className="rounded border border-border p-4">
        <h3 className="text-base font-semibold">{t("maintenance.recordServiceTitle")}</h3>
        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          <label className="text-sm">
            <span className="block text-muted-foreground">{t("maintenance.machine")}</span>
            <input
              className="mt-1 w-full rounded border border-gray-300 p-2"
              placeholder="XR-01"
              value={machineId}
              onChange={(e) => setMachineId(e.target.value)}
            />
          </label>
          <label className="text-sm">
            <span className="block text-muted-foreground">{t("maintenance.department")}</span>
            <select
              className="mt-1 w-full rounded border border-gray-300 p-2"
              value={departmentId}
              onChange={(e) => setDepartmentId(e.target.value)}
            >
              <option value="">{t("common.selectEllipsis")}</option>
              {departments.map((d) => (
                <option key={d.id} value={d.id}>
                  {localizeField(d.name, d.name_hi)}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="block text-muted-foreground">{t("maintenance.type")}</span>
            <select
              className="mt-1 w-full rounded border border-gray-300 p-2"
              value={type}
              onChange={(e) => setType(e.target.value as MaintenanceType)}
            >
              {(Object.keys(TYPE_KEYS) as MaintenanceType[]).map((value) => (
                <option key={value} value={value}>
                  {t(TYPE_KEYS[value])}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="block text-muted-foreground">{t("maintenance.performedAt")}</span>
            <input
              type="datetime-local"
              className="mt-1 w-full rounded border border-gray-300 p-2"
              value={performedAt}
              onChange={(e) => setPerformedAt(e.target.value)}
            />
          </label>
          <label className="text-sm">
            <span className="block text-muted-foreground">{t("maintenance.vendor")}</span>
            <input
              className="mt-1 w-full rounded border border-gray-300 p-2"
              value={vendor}
              onChange={(e) => setVendor(e.target.value)}
            />
          </label>
          <label className="text-sm">
            <span className="block text-muted-foreground">{t("maintenance.downtimeMinutes")}</span>
            <input
              type="number"
              min="0"
              className="mt-1 w-full rounded border border-gray-300 p-2"
              placeholder={t("maintenance.downtimePlaceholder")}
              value={downtime}
              onChange={(e) => setDowntime(e.target.value)}
            />
          </label>
        </div>
        <label className="mt-3 block text-sm">
          <span className="block text-muted-foreground">{t("maintenance.notes")}</span>
          <textarea
            rows={2}
            className="mt-1 w-full rounded border border-gray-300 p-2"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </label>
        <button
          type="button"
          disabled={busy || !machineId.trim() || !departmentId || !performedAt}
          onClick={() => void submit()}
          className="mt-4 rounded bg-blue-700 px-4 py-2 text-sm text-white disabled:bg-gray-300"
        >
          {t("maintenance.recordService")}
        </button>
      </div>

      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <h3 className="text-base font-semibold">{t("maintenance.serviceHistory")}</h3>
          <input
            className="rounded border border-gray-300 p-1 text-sm"
            placeholder={t("maintenance.filterByMachine")}
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </div>

        {logs === null ? (
          <p className="text-sm text-muted-foreground">{t("common.loading")}</p>
        ) : logs.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {filter ? t("maintenance.noServiceForMachine", { machine: filter }) : t("maintenance.noServiceRecorded")}
          </p>
        ) : (
          <ul className="space-y-2">
            {logs.map((log) => (
              <li key={log.id} className="rounded border border-border p-3 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-medium">{log.machine_id}</span>
                  <span className="rounded bg-muted px-2 py-0.5 text-xs">
                    {log.maintenance_type.replace("_", " ")}
                  </span>
                </div>
                <p className="mt-1 text-muted-foreground">
                  {departmentName(log.department_id)} ·{" "}
                  {new Date(log.performed_at).toLocaleString()}
                  {log.performed_by_vendor ? ` · ${log.performed_by_vendor}` : ""}
                </p>
                <p className="mt-1 text-muted-foreground">
                  {t("maintenance.downtimeLabel")}{" "}
                  {log.downtime_minutes === null
                    ? t("maintenance.downtimeNotRecorded")
                    : t("maintenance.downtimeMinutesValue", { minutes: log.downtime_minutes })}
                </p>
                {log.notes ? <p className="mt-1">{log.notes}</p> : null}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
