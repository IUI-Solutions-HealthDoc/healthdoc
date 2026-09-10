"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import FormHelperText from "@mui/material/FormHelperText";
import InputLabel from "@mui/material/InputLabel";
import OutlinedInput from "@mui/material/OutlinedInput";
import Typography from "@mui/material/Typography";
import { Button } from "@/components/ui/Button";
import { ApiError, formatDateTime, getUserFacingError, newIdempotencyKey } from "@/lib/api";
import { listExternalResults, recordExternalResult, type ExternalResult, type ExternalResultInput } from "../api/externalResults";
import { externalResultSchema } from "../lib/external-result-form";
import type { PlacedOrder } from "../types";
import { ExternalResultDownload, ExternalResultUpload, type AttachmentSelection } from "./ExternalResultAttachment";

interface Props {
  order: PlacedOrder;
  patientId: string;
  patientLabel?: string;
  onSaved: () => void;
}

/** Explicit label/helper wiring keeps the MUI outline without FormControl's
 * redundant filled-state updates on each input event. In the installed runtime
 * those pending updates can hit React's render-depth guard during rapid input.
 * Values remain controlled, including patient switches and correction resets. */
function DraftField({ id, label, value, onChange, disabled, error, helperText, multiline = false, required = false, type = "text" }: {
  id: string; label: string; value: string; onChange: (value: string) => void;
  disabled: boolean; error?: string; helperText?: string; multiline?: boolean; required?: boolean; type?: string;
}) {
  const help = error || helperText;
  return <Box sx={{ display: "inline-flex", flexDirection: "column", position: "relative", minWidth: 0 }}>
    <InputLabel htmlFor={id} variant="outlined" shrink required={required} disabled={disabled} error={!!error}
      sx={{ position: "absolute", left: 0, top: 0 }}>{label}</InputLabel>
    <OutlinedInput id={id} label={label} notched fullWidth value={value} type={type}
      required={required} disabled={disabled} error={!!error} multiline={multiline} minRows={multiline ? 4 : undefined}
      aria-describedby={help ? `${id}-help` : undefined} onChange={(event) => onChange(event.target.value)} />
    {help && <FormHelperText id={`${id}-help`} variant="outlined" error={!!error} disabled={disabled}>{help}</FormHelperText>}
  </Box>;
}

export function ExternalResultPanel(props: Props) {
  if (props.order.fulfilment_mode !== "external_referral") return <Alert severity="warning">This order is not confirmed as an external referral.</Alert>;
  // Reset before paint, including an in-flight save, not after a fetch finishes.
  return <ResultSession key={`${props.patientId}:${props.order.id}`} {...props} />;
}

function ResultSession({ order, patientId, patientLabel, onSaved }: Props) {
  const [rows, setRows] = useState<ExternalResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [readError, setReadError] = useState<string | null>(null);
  const [writeError, setWriteError] = useState<string | null>(null);
  const [form, setForm] = useState({ provider_name: "", observed_on: "", summary: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [confirmed, setConfirmed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [receipt, setReceipt] = useState<ExternalResult | null>(null);
  const [attachment, setAttachment] = useState<AttachmentSelection>({ fileId: null, blocked: false });
  const [attempt, setAttempt] = useState<{ key: string; body: ExternalResultInput } | null>(null);
  const live = useRef(false), generation = useRef(0), writing = useRef(false);

  const refresh = useCallback(async () => {
    const request = ++generation.current;
    setLoading(true); setReadError(null);
    try {
      const results = await listExternalResults(order.id);
      if (live.current && request === generation.current) setRows(results);
    } catch (cause) {
      if (live.current && request === generation.current) {
        setRows([]);
        setReadError(getUserFacingError(cause, "Outside result history could not be loaded."));
      }
    } finally {
      if (live.current && request === generation.current) setLoading(false);
    }
  }, [order.id]);

  useEffect(() => {
    const requests = generation;
    live.current = true;
    void refresh();
    return () => { live.current = false; requests.current++; };
  }, [refresh]);

  async function submit() {
    if (writing.current || loading || readError || receipt || attachment.blocked || order.status === "cancelled" || order.fulfilment_mode !== "external_referral") return;
    const today = new Date();
    const localDate = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
    const parsed = externalResultSchema(localDate).safeParse(form);
    if (!attempt && (!parsed.success || !confirmed)) {
      setErrors({ ...(!parsed.success ? Object.fromEntries(parsed.error.issues.map((issue) => [String(issue.path[0]), issue.message])) : {}),
        ...(!confirmed ? { confirmed: "Confirm the patient and order before recording." } : {}) });
      return;
    }
    if (!attempt && !parsed.success) return;
    const action = attempt ?? { key: newIdempotencyKey(), body: { ...parsed.data!, result_file_id: attachment.fileId } };
    writing.current = true;
    setAttempt(action); setSaving(true); setWriteError(null); setErrors({});
    try {
      const saved = await recordExternalResult(order.id, action.body, action.key);
      if (!live.current) return;
      setReceipt(saved);
      // Keep the receipt even if read-back fails; never resubmit a confirmed
      // write to repair a failed read.
      void refresh();
      onSaved();
    } catch (cause) {
      if (!live.current) return;
      setWriteError(getUserFacingError(cause, "Submission was not confirmed. Retry this same result; review history before starting a different entry."));
      // Network/server/409 ambiguity retains the original payload and key.
      if (cause instanceof ApiError && [400, 403, 404, 422].includes(cause.code)) setAttempt(null);
    } finally {
      writing.current = false;
      if (live.current) setSaving(false);
    }
  }

  return <Stack spacing={2} aria-label="Outside result details">
    <Typography component="h3" sx={{ fontWeight: 700 }}>Outside results — {order.order_number}</Typography>
    <Typography>{patientLabel || `Patient record: ${patientId}`}</Typography>
    <Alert severity="info">Recording an outside report completes the referred order. It does not locally verify the report, sign it off, or publish an ABDM document. Corrections are new entries; earlier entries remain unchanged.</Alert>
    <Box>
      <Button disabled={loading || saving} onClick={() => void refresh()}>Refresh result history</Button>
      {loading ? <p role="status">Loading outside results…</p> : readError ? <Alert severity="error">{readError}</Alert> : rows.length === 0 ? <p>{attempt ? "History may predate this submission. Refresh history or retry the same entry." : "No outside results recorded."}</p> :
        <ol>{rows.map((row) => <li key={row.id} className="my-3 border-b pb-3">
          <p><strong>{row.provider_name || "Provider not recorded"}</strong> · Observed: {row.observed_on || "Not recorded"}</p>
          <p className="whitespace-pre-wrap break-words">{row.summary}</p>
          <p>Recorded {formatDateTime(row.recorded_at)} · Staff ID: {row.recorded_by}</p>
          {row.result_file_id && <ExternalResultDownload key={`${patientId}:${row.result_file_id}`} fileId={row.result_file_id} patientId={patientId} />}
        </li>)}</ol>}
    </Box>
    {order.status === "cancelled" ? <Alert severity="warning">This order is cancelled. History is read-only.</Alert> : receipt ? <>
      <Alert severity="success">Result recorded for {order.order_number}. Entry ID: {receipt.id}. Do not submit it again.</Alert>
      <Button onClick={() => { setReceipt(null); setAttempt(null); setConfirmed(false); setAttachment({ fileId: null, blocked: false }); setForm({ provider_name: "", observed_on: "", summary: "" }); }}>Record another result / correction</Button>
    </> : <Box component="form" noValidate onSubmit={(event) => { event.preventDefault(); void submit(); }}>
      <Stack spacing={2}>
        {writeError && <Alert severity="error">{writeError}{attempt && " The original entry is locked for a safe retry. Leaving this patient or reloading loses that retry key; inspect history before entering it again."}</Alert>}
        <DraftField id={`${order.id}-provider`} label="Outside provider (optional)" value={form.provider_name} disabled={!!attempt} error={errors.provider_name} onChange={(value) => setForm((current) => ({ ...current, provider_name: value }))} />
        <DraftField id={`${order.id}-observed`} label="Observed date (optional)" type="date" value={form.observed_on} disabled={!!attempt} error={errors.observed_on} onChange={(value) => setForm((current) => ({ ...current, observed_on: value }))} />
        <DraftField id={`${order.id}-summary`} label="Outside result summary" required multiline value={form.summary} disabled={!!attempt} error={errors.summary} helperText="Transcribe the outside report accurately. This is not local verification." onChange={(value) => setForm((current) => ({ ...current, summary: value }))} />
        <ExternalResultUpload patientId={patientId} disabled={!!attempt || loading || !!readError} onChange={setAttachment} />
        <label><input type="checkbox" checked={confirmed} disabled={!!attempt} onChange={(e) => setConfirmed(e.target.checked)} /> I confirm this result belongs to the patient and order shown above.</label>
        {errors.confirmed && <Alert severity="error">{errors.confirmed}</Alert>}
        <Button type="submit" variant="contained" disabled={saving || loading || !!readError || attachment.blocked}>{saving ? "Recording…" : attempt ? "Retry same result" : "Record outside result"}</Button>
      </Stack>
    </Box>}
  </Stack>;
}
