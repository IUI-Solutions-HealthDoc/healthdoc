"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { Button } from "@/components/ui/Button";
import { formatDateTime, getUserFacingError } from "@/lib/api";
import { listExternalReferrals, type ExternalReferral, type ReferralPage, type ReferralState } from "../api/externalReferrals";
import { ExternalResultPanel } from "./ExternalResultPanel";
import { useLocale, translate } from "@/lib/i18n";

const PAGE_SIZE = 25;

export function ExternalReferralInbox() {
  const { t } = useLocale();
  const [state, setState] = useState<ReferralState>("pending");
  const [offset, setOffset] = useState(0);
  return <Stack spacing={2}>
    <Typography component="h1" sx={{ fontSize: "1.5rem", fontWeight: 700 }}>{t("doctor.resultsTabExternal")}</Typography>
    <Typography>{t("doctor.ui.yourReferredOrdersAcrossVisitsIncluding")}</Typography>
    {/* Its own row and width: the filter's text was cut off at the edge and
        crowded the count line beneath it (QA 12 Oct 2026). */}
    <label className="flex flex-wrap items-center gap-2 pb-1">{t("doctor.ui.referralStatus")}<select value={state} onChange={(event) => {
      setState(event.target.value as ReferralState); setOffset(0);
    }} className="min-w-52 rounded border p-2">
      <option value="pending">{t("doctor.ui.pendingReceipt")}</option><option value="completed">{t("appointment.status.completed")}</option>
      <option value="cancelled">{t("appointment.status.cancelled")}</option><option value="all">{t("doctor.ui.allReferrals")}</option>
    </select></label>
    {/* A query change removes old patient details/drafts before any read settles. */}
    <ReferralPageView key={`${state}:${offset}`} state={state} offset={offset} onPage={setOffset} />
  </Stack>;
}

function ReferralPageView({ state, offset, onPage }: { state: ReferralState; offset: number; onPage: (offset: number) => void }) {
  const { t } = useLocale();
  const [page, setPage] = useState<ReferralPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<ExternalReferral | null>(null);
  const live = useRef(false), generation = useRef(0);
  const refresh = useCallback(async () => {
    const request = ++generation.current;
    setLoading(true); setError(null);
    try {
      const result = await listExternalReferrals(state, offset, PAGE_SIZE);
      if (live.current && request === generation.current) setPage(result);
    } catch (cause) {
      if (live.current && request === generation.current) {
        setPage(null); setError(getUserFacingError(cause, translate("doctor.msg.theReferralInboxCouldNotBe")));
      }
    } finally {
      if (live.current && request === generation.current) setLoading(false);
    }
  }, [state, offset]);
  useEffect(() => {
    const requests = generation;
    live.current = true; void refresh();
    return () => { live.current = false; requests.current++; };
  }, [refresh]);
  // Keep a confirmed receipt visible when its order leaves the pending filter.
  const current = selected && (page?.items.find((row) => row.id === selected.id) ?? selected);
  return <Stack spacing={2}>
    <Button disabled={loading} onClick={() => void refresh()}>{t("doctor.ui.refreshReferrals")}</Button>
    {loading ? <p role="status">{t("doctor.ui.loadingReferrals")}</p> : error ? <Alert severity="error">{error}</Alert> : page && <>
      <p role="status">{page.total}{" "}{t("doctor.ui.matchingReferrals")}{" "}{page.items.length ? `${offset + 1}–${offset + page.items.length}` : t("doctor.ui.noRowsOnThisPage")}</p>
      {page.items.length === 0 ? <Typography>{offset > 0 ? t("doctor.ui.noReferralsOnThisPageGo") : page.total === 0 ? t("doctor.ui.noReferralsWithThisStatusChoose") : t("doctor.ui.noReferralsOnThisPage")}</Typography> :
        <Box sx={{ overflowX: "auto" }}><table className="w-full text-left text-sm">
          <caption className="sr-only">{t("doctor.ui.externalReferralOrders")}</caption>
          <thead><tr>{["Patient", "Order / visit", "Status", "Received", "Action"].map((label) => <th scope="col" className="p-2" key={label}>{label}</th>)}</tr></thead>
          <tbody>{page.items.map((row) => <tr key={row.id} className="border-t">
            <td className="p-2">{row.patient_name}<br />{row.patient_identifier || t("doctor.ui.identifierNotRecorded")}</td>
            <td className="p-2">{row.order_number} · {row.order_type}<br />{t("doctor.ui.visit")}{" "}{row.visit_number}<br />{formatDateTime(row.ordered_at)}</td>
            <td className="p-2">{row.status} · {row.priority}</td>
            <td className="p-2">{row.result_count}{" "}{t("doctor.ui.entries")}{row.last_received_at && <><br />{formatDateTime(row.last_received_at)}</>}</td>
            <td className="p-2"><Button aria-label={translate("doctor.msg.outsideResultsForOrderNumber", undefined, { order_number: row.order_number })} onClick={() => setSelected(row)}>{t("doctor.outsideResults")}</Button></td>
          </tr>)}</tbody>
        </table></Box>}
    </>}
    <Stack direction="row" spacing={2}>
      <Button disabled={loading || offset === 0} onClick={() => onPage(Math.max(0, offset - PAGE_SIZE))}>{t("doctor.ui.previousReferrals")}</Button>
      <Button disabled={loading || !page || offset + PAGE_SIZE >= page.total} onClick={() => onPage(offset + PAGE_SIZE)}>{t("doctor.ui.nextReferrals")}</Button>
    </Stack>
    {current && <Box sx={{ border: "1px solid", borderColor: "divider", borderRadius: 3, p: 2 }}>
      <Button onClick={() => setSelected(null)}>{t("doctor.ui.closeOutsideResults")}</Button>
      <ExternalResultPanel order={{ ...current, detail_status: "header_only", item_label: current.order_type }}
        patientId={current.patient_id} patientLabel={`${current.patient_name} · ${current.patient_identifier || translate("doctor.ui.identifierNotRecorded")} · Visit ${current.visit_number}`}
        onSaved={refresh} />
    </Box>}
  </Stack>;
}
