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

const PAGE_SIZE = 25;

export function ExternalReferralInbox() {
  const [state, setState] = useState<ReferralState>("pending");
  const [offset, setOffset] = useState(0);
  return <Stack spacing={2}>
    <Typography component="h1" sx={{ fontSize: "1.5rem", fontWeight: 700 }}>External referrals</Typography>
    <Typography>Your referred orders across visits, including completed consultations. Recording an outside report is separate from local clinical review.</Typography>
    <label>Referral status{" "}<select value={state} onChange={(event) => {
      setState(event.target.value as ReferralState); setOffset(0);
    }} className="rounded border p-2">
      <option value="pending">Pending receipt</option><option value="completed">Completed</option>
      <option value="cancelled">Cancelled</option><option value="all">All referrals</option>
    </select></label>
    {/* A query change removes old patient details/drafts before any read settles. */}
    <ReferralPageView key={`${state}:${offset}`} state={state} offset={offset} onPage={setOffset} />
  </Stack>;
}

function ReferralPageView({ state, offset, onPage }: { state: ReferralState; offset: number; onPage: (offset: number) => void }) {
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
        setPage(null); setError(getUserFacingError(cause, "The referral inbox could not be loaded."));
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
    <Button disabled={loading} onClick={() => void refresh()}>Refresh referrals</Button>
    {loading ? <p role="status">Loading referrals…</p> : error ? <Alert severity="error">{error}</Alert> : page && <>
      <p role="status">{page.total} matching referrals · {page.items.length ? `${offset + 1}–${offset + page.items.length}` : "No rows on this page"}</p>
      {page.items.length === 0 ? <Typography>No referrals on this page. Change the status filter or return to an earlier page.</Typography> :
        <Box sx={{ overflowX: "auto" }}><table className="w-full text-left text-sm">
          <caption className="sr-only">External referral orders</caption>
          <thead><tr>{["Patient", "Order / visit", "Status", "Received", "Action"].map((label) => <th scope="col" className="p-2" key={label}>{label}</th>)}</tr></thead>
          <tbody>{page.items.map((row) => <tr key={row.id} className="border-t">
            <td className="p-2">{row.patient_name}<br />{row.patient_identifier || "Identifier not recorded"}</td>
            <td className="p-2">{row.order_number} · {row.order_type}<br />Visit {row.visit_number}<br />{formatDateTime(row.ordered_at)}</td>
            <td className="p-2">{row.status} · {row.priority}</td>
            <td className="p-2">{row.result_count} entries{row.last_received_at && <><br />{formatDateTime(row.last_received_at)}</>}</td>
            <td className="p-2"><Button aria-label={`Outside results for ${row.order_number}`} onClick={() => setSelected(row)}>Outside results</Button></td>
          </tr>)}</tbody>
        </table></Box>}
    </>}
    <Stack direction="row" spacing={2}>
      <Button disabled={loading || offset === 0} onClick={() => onPage(Math.max(0, offset - PAGE_SIZE))}>Previous referrals</Button>
      <Button disabled={loading || !page || offset + PAGE_SIZE >= page.total} onClick={() => onPage(offset + PAGE_SIZE)}>Next referrals</Button>
    </Stack>
    {current && <Box sx={{ border: "1px solid", borderColor: "divider", borderRadius: 3, p: 2 }}>
      <Button onClick={() => setSelected(null)}>Close outside results</Button>
      <ExternalResultPanel order={{ ...current, detail_status: "header_only", item_label: current.order_type }}
        patientId={current.patient_id} patientLabel={`${current.patient_name} · ${current.patient_identifier || "Identifier not recorded"} · Visit ${current.visit_number}`}
        onSaved={refresh} />
    </Box>}
  </Stack>;
}
