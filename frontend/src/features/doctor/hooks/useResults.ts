"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { toast } from "@/components/ui/toast";
import { useLocale } from "@/lib/i18n";
import {
  createDoctorReview,
  getLabResults,
  getRadiologyReports,
  getReviewsForItem,
  listResultsWorklist,
  updateDoctorReview,
} from "../api";
import type {
  DoctorReview,
  DoctorReviewStatus,
  LabResult,
  RadiologyReport,
  ResultWorklistItem,
} from "../types";

export type ResultsFilter = "all" | "unread" | "critical";

/**
 * Owns the results worklist and the currently opened result.
 *
 * A selected item loads every version (corrections are new rows, never edits)
 * and the viewer defaults to the current one. Sign-off is a doctor_reviews row
 * against the encounter — the result itself is never written to.
 */
export function useResults() {
  const { t } = useLocale();
  const [items, setItems] = useState<ResultWorklistItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<ResultsFilter>("all");

  const [selected, setSelected] = useState<ResultWorklistItem | null>(null);
  const [labVersions, setLabVersions] = useState<LabResult[]>([]);
  const [radVersions, setRadVersions] = useState<RadiologyReport[]>([]);
  const [viewingVersion, setViewingVersion] = useState<number | null>(null);
  const [reviews, setReviews] = useState<DoctorReview[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);
  const [signing, setSigning] = useState(false);

  useEffect(() => {
    let alive = true;
    listResultsWorklist()
      .then((rows) => alive && setItems(rows))
      .catch(
        (e) =>
          alive &&
          setError(e instanceof Error ? e.message : t("doctor.toast.loadResultsFailed")),
      )
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [t]);

  const isOutstanding = (i: ResultWorklistItem) =>
    Boolean(i.result_status) && i.review_status !== "signed_off";

  const visible = useMemo(() => {
    // `critical` here means clinically urgent by ORDER PRIORITY. We do not derive
    // criticality from result values — result_data has no agreed shape and a
    // guessed critical flag is a patient-safety defect.
    if (filter === "critical") return items.filter((i) => i.priority === "stat");
    if (filter === "unread") return items.filter(isOutstanding);
    return items;
  }, [items, filter]);

  const counts = useMemo(
    () => ({
      total: items.length,
      unread: items.filter(isOutstanding).length,
      critical: items.filter((i) => i.priority === "stat").length,
    }),
    [items],
  );

  const select = useCallback(async (item: ResultWorklistItem) => {
    setSelected(item);
    setLabVersions([]);
    setRadVersions([]);
    setReviews([]);
    setViewingVersion(null);
    if (!item.result_status) return; // nothing reported yet

    setDetailLoading(true);
    try {
      if (item.order_type === "lab") {
        const rows = await getLabResults(item.id);
        setLabVersions(rows);
        setViewingVersion((rows.find((r) => r.is_current) ?? rows[0])?.version ?? null);
      } else {
        const rows = await getRadiologyReports(item.id);
        setRadVersions(rows);
        setViewingVersion((rows.find((r) => r.is_current) ?? rows[0])?.version ?? null);
      }
      setReviews(await getReviewsForItem(item.encounter_id, item.id, item.order_type));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t("doctor.toast.loadResultFailed"));
    } finally {
      setDetailLoading(false);
    }
  }, [t]);

  const labResult = useMemo(
    () => labVersions.find((r) => r.version === viewingVersion) ?? null,
    [labVersions, viewingVersion],
  );
  const radReport = useMemo(
    () => radVersions.find((r) => r.version === viewingVersion) ?? null,
    [radVersions, viewingVersion],
  );

  /** You may only review the current version — never a superseded one. */
  const currentVersion = useMemo(() => {
    const current = labVersions.find((r) => r.is_current) ?? radVersions.find((r) => r.is_current);
    return current?.version ?? null;
  }, [labVersions, radVersions]);

  const viewingIsCurrent = viewingVersion !== null && viewingVersion === currentVersion;
  const review = reviews[0] ?? null;
  const reviewStatus: DoctorReviewStatus | null = review?.status ?? null;

  /**
   * Advance the review. `pending` is created on first touch, then the doctor
   * moves it to `reviewed` (seen, not final) or `signed_off` (done).
   */
  const advance = useCallback(
    async (status: Exclude<DoctorReviewStatus, "pending">, notes?: string) => {
      if (!selected) return;
      setSigning(true);
      try {
        // The encounter the order was placed in, from the worklist row —
        // not a fixed mock id. A review filed against the wrong encounter is
        // attached to the wrong consultation in the record.
        const existing = review ?? (await createDoctorReview(selected.encounter_id, {
          lab_order_item_id: selected.order_type === "lab" ? selected.id : undefined,
          radiology_order_item_id: selected.order_type === "radiology" ? selected.id : undefined,
          notes,
        }));
        const updated = await updateDoctorReview(existing.id, { status, notes });
        setReviews([updated]);
        setItems((prev) =>
          prev.map((i) => (i.id === selected.id ? { ...i, review_status: status } : i)),
        );
        setSelected((prev) => (prev ? { ...prev, review_status: status } : prev));
        // No localOnly() suffix: this write really persists now. Keeping it
        // would be a stale reassurance in the other direction — telling a
        // clinician a sign-off did NOT save when it did.
        toast.success(
          status === "signed_off" ? t("doctor.toast.resultSignedOff") : t("doctor.toast.markedReviewed"),
        );
      } catch (e) {
        toast.error(e instanceof Error ? e.message : t("doctor.toast.updateReviewFailed"));
      } finally {
        setSigning(false);
      }
    },
    [review, selected, t],
  );

  return {
    items: visible,
    counts,
    loading,
    error,
    filter,
    setFilter,
    selected,
    select,
    detailLoading,
    labResult,
    radReport,
    labVersions,
    radVersions,
    viewingVersion,
    setViewingVersion,
    viewingIsCurrent,
    review,
    reviewStatus,
    signing,
    advance,
  };
}
