"use client";

import { useEffect, useRef, useState } from "react";
import Alert from "@mui/material/Alert";
import Stack from "@mui/material/Stack";
import { Button } from "@/components/ui/Button";
import { ApiError, getUserFacingError } from "@/lib/api";
import { prepareResultDownload, uploadResultFile, validateResultFile, type ResultFile } from "../api/externalAttachments";

export interface AttachmentSelection { fileId: string | null; blocked: boolean }

/** Parent is keyed by patient+order; no file, URL or callback survives a switch. */
export function ExternalResultUpload({ patientId, disabled, onChange }: {
  patientId: string; disabled: boolean; onChange: (selection: AttachmentSelection) => void;
}) {
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
      setError(rejected ? getUserFacingError(cause, "The attachment was rejected.") :
        "Upload outcome is unknown. A patient file may already exist. Do not upload it again; ask an administrator to reconcile the upload before continuing. Leaving this page loses this warning.");
    } finally {
      writing.current = false;
      if (live.current) setBusy(false);
    }
  }
  return <Stack spacing={1}>
    <label>Outside report attachment (optional)<input key={inputKey} type="file" accept=".pdf,.png,.jpg,.jpeg"
      disabled={disabled || busy || uncertain || !!saved} onChange={(event) => {
        const chosen = event.target.files?.[0] ?? null;
        setFile(chosen); setError(chosen ? validateResultFile(chosen) : null);
        onChange({ fileId: null, blocked: !!chosen });
      }} /></label>
    <p>PDF, PNG or JPEG, up to 25 MB. Upload first, then record the result to attach it. File contents are validated by the server.</p>
    {error && <Alert severity="error">{error}</Alert>}
    {saved ? <Alert severity="info">Uploaded: {saved.original_name || "Outside report"}. It will be linked when this result is recorded. Removing the selection does not erase the uploaded patient file.</Alert> :
      <Button disabled={disabled || busy || uncertain || !file || !!(file && validateResultFile(file))} onClick={() => void upload()}>{busy ? "Uploading attachment…" : "Upload attachment"}</Button>}
    {(file || saved) && <Button disabled={disabled || busy || uncertain} onClick={() => {
      setFile(null); setSaved(null); setError(null); setInputKey((key) => key + 1);
      onChange({ fileId: null, blocked: false });
    }}>Remove attachment selection</Button>}
  </Stack>;
}

export function ExternalResultDownload({ fileId, patientId }: { fileId: string; patientId: string }) {
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
      if (live.current) setError(getUserFacingError(cause, "The report cannot be opened. It may be unavailable or its download address needs configuration."));
    } finally { reading.current = false; if (live.current) setBusy(false); }
  }
  return <Stack spacing={1}>
    <Button disabled={busy} onClick={() => void prepare()}>{busy ? "Preparing attachment…" : "Prepare attachment download"}</Button>
    {error && <Alert severity="error">{error}</Alert>}
    {link && <a href={link.url} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer" className="underline" onClick={(event) => {
      if (Date.now() >= link.expiresAt) { event.preventDefault(); setLink(null); setError("This download link expired. Prepare a new download."); }
    }}>Open {link.name} (temporary link)</a>}
  </Stack>;
}
