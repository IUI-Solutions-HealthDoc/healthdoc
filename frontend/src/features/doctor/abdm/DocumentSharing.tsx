"use client";

import { useEffect, useRef, useState } from "react";
import { api, getUserFacingError, newIdempotencyKey } from "@/lib/api";
import { useLocale } from "@/lib/i18n";

interface Context { id: string; reference: string; display: string; hi_type: string }
interface LinkStatus { id: string; status: string; care_context_references: string[] }
interface UploadedFile { id: string; patient_id: string | null; erased_at: string | null }

const MAX_RELEASE_BYTES = 1024 * 1024;

/** One uploaded PDF released as a HealthDocumentRecord. The upload alone
 * shares nothing; the release offers it for linking. */
function ReleaseDocument({ patientId, onReleased }: { patientId: string; onReleased: () => void }) {
  const { t } = useLocale();
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [documentDate, setDocumentDate] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // An upload that succeeded is reused if the release then fails, so a retry
  // does not leave a second copy on the chart.
  const uploaded = useRef<{ source: File; id: string } | null>(null);
  const retry = useRef<{ signature: string; key: string } | null>(null);
  const valid = !!file && /\.pdf$/i.test(file.name) && file.size > 0 && file.size <= MAX_RELEASE_BYTES;
  async function release() {
    if (!file || !valid || !title.trim() || !documentDate) {
      setError(t("doctor.abdm.releaseNotPdf"));
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      if (uploaded.current?.source !== file) {
        const body = new FormData();
        body.append("upload", file);
        body.append("patient_id", patientId);
        body.append("owner_module", "patients");
        body.append("sensitivity", "sensitive");
        // /files/upload has no idempotency protocol; never auto-retry it.
        const saved = await api<UploadedFile>("/files/upload", { method: "POST", body, idempotencyKey: null });
        if (saved.patient_id !== patientId || saved.erased_at) throw new Error(t("doctor.abdm.releaseFailed"));
        uploaded.current = { source: file, id: saved.id };
      }
      const payload = { file_id: uploaded.current.id, title: title.trim(), document_date: documentDate };
      const signature = JSON.stringify(payload);
      if (retry.current?.signature !== signature) retry.current = { signature, key: newIdempotencyKey() };
      await api(`/abdm/hip/patients/${patientId}/documents`, {
        method: "POST",
        body: signature,
        idempotencyKey: retry.current.key,
      });
      setNotice(t("doctor.abdm.releaseDone"));
      setFile(null);
      setTitle("");
      setDocumentDate("");
      uploaded.current = null;
      retry.current = null;
      onReleased();
    } catch (reason) {
      setError(getUserFacingError(reason, t("doctor.abdm.releaseFailed")));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="space-y-3 rounded border border-border p-4">
      <h3 className="font-semibold">{t("doctor.abdm.releaseTitle")}</h3>
      <p className="text-sm text-muted-foreground">{t("doctor.abdm.releaseIntro")}</p>
      {error && <p role="alert" className="text-danger">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      <label className="block text-sm">
        {t("doctor.abdm.releaseFile")}
        <input
          type="file"
          accept="application/pdf,.pdf"
          className="mt-1 block"
          disabled={busy}
          onChange={(event) => {
            setError(null);
            setFile(event.target.files?.[0] ?? null);
          }}
        />
      </label>
      <label className="block text-sm">
        {t("doctor.abdm.releaseDocTitle")}
        <input
          className="mt-1 block w-full rounded border border-border px-2 py-1"
          maxLength={100}
          value={title}
          disabled={busy}
          onChange={(event) => setTitle(event.target.value)}
        />
      </label>
      <label className="block text-sm">
        {t("doctor.abdm.releaseDocDate")}
        <input
          type="date"
          className="mt-1 block rounded border border-border px-2 py-1"
          value={documentDate}
          disabled={busy}
          onChange={(event) => setDocumentDate(event.target.value)}
        />
      </label>
      <button
        type="button"
        className="rounded bg-primary px-4 py-2 text-white disabled:opacity-50"
        disabled={busy || !valid || !title.trim() || !documentDate}
        onClick={() => void release()}
      >
        {t("doctor.abdm.releaseButton")}
      </button>
    </div>
  );
}

export function DocumentSharing({ patientId, verified }: { patientId: string; verified: boolean }) {
  const { t } = useLocale();
  const [contexts, setContexts] = useState<Context[]>([]);
  const [links, setLinks] = useState<LinkStatus[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const retry = useRef<{ signature: string; key: string } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      api<Context[]>(`/abdm/hip/patients/${patientId}/care-contexts?limit=50&offset=${offset}`, { signal: controller.signal }),
      api<LinkStatus[]>(`/abdm/hip/patients/${patientId}/links`, { signal: controller.signal }),
    ])
      .then(([documents, states]) => {
        if (!controller.signal.aborted) {
          setContexts(documents);
          setLinks(states);
        }
      })
      .catch((reason) => {
        if (!controller.signal.aborted) {
          setContexts([]);
          setLinks([]);
          setError(getUserFacingError(reason, t("doctor.abdm.errSharingUnavailable")));
        }
      });
    return () => controller.abort();
  }, [patientId, offset, refresh, t]);
  async function link() {
    if (!verified || !selected.length || selected.length > 50) return;
    const signature = JSON.stringify([...selected].sort());
    if (retry.current?.signature !== signature) retry.current = { signature, key: newIdempotencyKey() };
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await api<LinkStatus[]>(`/abdm/hip/patients/${patientId}/links`, {
        method: "POST",
        body: JSON.stringify({ context_ids: selected }),
        idempotencyKey: retry.current.key,
      });
      setNotice(t("doctor.abdm.noticeLinkQueued"));
      setSelected([]);
      retry.current = null;
      setRefresh((value) => value + 1);
    } catch (reason) {
      setError(getUserFacingError(reason, t("doctor.abdm.errLinkFailed")));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="surface-card space-y-4 p-5" aria-label="Share finalized documents">
      <h2 className="text-xl font-semibold">{t("doctor.abdm.shareTitle")}</h2>
      <p className="text-sm text-muted-foreground">{t("doctor.abdm.shareIntro")}</p>
      <ReleaseDocument patientId={patientId} onReleased={() => setRefresh((value) => value + 1)} />
      {!verified && <p>{t("doctor.abdm.verifyBeforeLinking")}</p>}
      {error && <p role="alert" className="text-danger">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      <ul className="space-y-3">
        {contexts.map((context) => {
          const states = links
            .filter((link) => link.care_context_references.includes(context.reference))
            .map((link) => link.status);
          const protectedState = states.includes("confirmed") || states.includes("pending");
          return (
            <li key={context.id}>
              <label className="flex items-start gap-3">
                <input
                  type="checkbox"
                  className="mt-1"
                  disabled={busy || !verified || protectedState}
                  checked={selected.includes(context.id)}
                  onChange={(event) =>
                    setSelected((current) =>
                      event.target.checked
                        ? [...current, context.id]
                        : current.filter((id) => id !== context.id),
                    )
                  }
                />
                <span>
                  {context.display} · {context.hi_type}
                  <span className="block text-sm text-muted-foreground">
                    {states.length ? [...new Set(states)].join(", ") : t("doctor.abdm.notLinked")}
                  </span>
                </span>
              </label>
            </li>
          );
        })}
      </ul>
      {!contexts.length && <p>{t("doctor.abdm.noShareableDocuments")}</p>}
      <div className="flex flex-wrap gap-4">
        <button
          type="button"
          className="rounded bg-primary px-4 py-2 text-white disabled:opacity-50"
          disabled={busy || !verified || !selected.length}
          onClick={() => void link()}
        >
          {t("doctor.abdm.linkSelectedDocuments")}
        </button>
        <button
          type="button"
          className="underline"
          onClick={() => {
            setError(null);
            setRefresh((value) => value + 1);
          }}
        >
          {t("doctor.abdm.refreshLinkStatus")}
        </button>
        <button
          type="button"
          className="underline disabled:opacity-50"
          disabled={offset === 0 || busy}
          onClick={() => {
            setSelected([]);
            setOffset(Math.max(0, offset - 50));
          }}
        >
          {t("doctor.abdm.previous50")}
        </button>
        <button
          type="button"
          className="underline disabled:opacity-50"
          disabled={busy}
          onClick={() => {
            setSelected([]);
            setOffset(offset + 50);
          }}
        >
          {t("doctor.abdm.next50")}
        </button>
      </div>
    </section>
  );
}
