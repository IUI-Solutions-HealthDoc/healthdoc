"use client";

import { useEffect, useRef, useState } from "react";
import Alert from "@mui/material/Alert";
import Stack from "@mui/material/Stack";
import { Button } from "@/components/ui/Button";
import { ApiError, getUserFacingError } from "@/lib/api";
import { prepareResultDownload, uploadResultFile, validateResultFile, type ResultFile } from "../api/externalAttachments";
import { useLocale, translate } from "@/lib/i18n";

export interface AttachmentSelection { fileId: string | null; blocked: boolean }

/** Parent is keyed by patient+order; no file, URL or callback survives a switch. */
export function ExternalResultUpload({ patientId, disabled, onChange }: {
  patientId: string; disabled: boolean; onChange: (selection: AttachmentSelection) => void;
}) {
  const { t } = useLocale();
  const [file, setFile] = useState<File | null>(null);
  const [saved, setSaved] = useState<ResultFile | null>(null);
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [inputKey, setInputKey] = useState(0);
  const live = useRef(false), writing = useRef(false);
  useEffect(() => { live.current = true; return () => { live.current = false; }; }, []);

  async function upload() {
    if (!file || disabled || writing.current || uncertain || saved) return;
    const invalid = validateResultFile(file);
    if (invalid) { setError(invalid); return; }
    writing.current = true; setBusy(true); setError(null);
    try {
      const result = await uploadResultFile(file, patientId);
      if (!live.current) return;
      setSaved(result); onChange({ fileId: result.id, blocked: false });
    } catch (cause) {
      if (!live.current) return;
      const rejected = cause instanceof ApiError && [400, 403, 404, 413, 415, 422].includes(cause.code);
      setUncertain(!rejected);
      setError(rejected ? getUserFacingError(cause, translate("doctor.msg.theAttachmentWasRejected")) :
        translate("doctor.msg.uploadOutcomeIsUnknownAPatient"));
    } finally {
      writing.current = false;
      if (live.current) setBusy(false);
    }
  }
  return <Stack spacing={1}>
    <label>{t("doctor.ui.outsideReportAttachmentOptional")}<input key={inputKey} type="file" accept=".pdf,.png,.jpg,.jpeg"
      disabled={disabled || busy || uncertain || !!saved} onChange={(event) => {
        const chosen = event.target.files?.[0] ?? null;
        setFile(chosen); setError(chosen ? validateResultFile(chosen) : null);
        onChange({ fileId: null, blocked: !!chosen });
      }} /></label>
    <p>{t("doctor.ui.pdfPngOrJpegUpTo")}</p>
    {error && <Alert severity="error">{error}</Alert>}
    {saved ? <Alert severity="info">{t("doctor.ui.uploaded")}{" "}{saved.original_name || t("doctor.ui.outsideReport")}{t("doctor.ui.itWillBeLinkedWhenThis")}</Alert> :
      <Button disabled={disabled || busy || uncertain || !file || !!(file && validateResultFile(file))} onClick={() => void upload()}>{busy ? t("doctor.ui.uploadingAttachment") : t("doctor.ui.uploadAttachment")}</Button>}
    {(file || saved) && <Button disabled={disabled || busy || uncertain} onClick={() => {
      setFile(null); setSaved(null); setError(null); setInputKey((key) => key + 1);
      onChange({ fileId: null, blocked: false });
    }}>{t("doctor.ui.removeAttachmentSelection")}</Button>}
  </Stack>;
}

export function ExternalResultDownload({ fileId, patientId }: { fileId: string; patientId: string }) {
  const { t } = useLocale();
  const [link, setLink] = useState<Awaited<ReturnType<typeof prepareResultDownload>> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const live = useRef(false), reading = useRef(false);
  useEffect(() => { live.current = true; return () => { live.current = false; }; }, []);
  async function prepare() {
    if (reading.current) return;
    reading.current = true; setBusy(true); setLink(null); setError(null);
    try {
      const result = await prepareResultDownload(fileId, patientId);
      if (live.current) setLink(result);
    } catch (cause) {
      if (live.current) setError(getUserFacingError(cause, translate("doctor.msg.theReportCannotBeOpenedIt")));
    } finally { reading.current = false; if (live.current) setBusy(false); }
  }
  return <Stack spacing={1}>
    <Button disabled={busy} onClick={() => void prepare()}>{busy ? t("doctor.ui.preparingAttachment") : t("doctor.ui.prepareAttachmentDownload")}</Button>
    {error && <Alert severity="error">{error}</Alert>}
    {link && <a href={link.url} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer" className="underline" onClick={(event) => {
      if (Date.now() >= link.expiresAt) { event.preventDefault(); setLink(null); setError(translate("doctor.msg.thisDownloadLinkExpiredPrepareA")); }
    }}>{t("doctor.ui.openNameTemporaryLink", { name: link.name })}</a>}
  </Stack>;
}
