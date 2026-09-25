"use client";

import { useEffect, useState } from "react";
import { getUserFacingError } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { loadRecord } from "./api";
import { EmbeddedPdfPreview } from "./EmbeddedPdfPreview";
import { embeddedPdfs, type EmbeddedPdf } from "./pdfAttachments";

/** Narratives remain escaped text; PDF bytes are rendered separately to canvas. */
function Value({ value, depth = 0 }: { value: unknown; depth?: number }) {
  if (depth > 12) return <span>Nested content omitted from this view.</span>;
  if (value == null) return <span>—</span>;
  if (typeof value !== "object") return <span className="whitespace-pre-wrap break-words">{String(value)}</span>;
  if (Array.isArray(value)) return <ul className="space-y-2 border-l pl-3">{value.map((entry, index) => <li key={index}><Value value={entry} depth={depth + 1} /></li>)}</ul>;
  return <dl className="space-y-2">{Object.entries(value).filter(([name]) => !(name === "data" && "contentType" in value)).map(([name, child]) => <div key={name}>
    <dt className="text-xs font-semibold text-muted-foreground">{name}</dt><dd className="pl-2"><Value value={child} depth={depth + 1} /></dd>
  </div>)}</dl>;
}

export function ExternalRecordViewer({ id, close }: { id: string; close: () => void }) {
  return <ExternalRecordBody key={id} id={id} close={close} />;
}

function ExternalRecordBody({ id, close }: { id: string; close: () => void }) {
  const { t } = useLocale();
  const [bundle, setBundle] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedPdf, setSelectedPdf] = useState<number | null>(null);
  useEffect(() => {
    let current: AbortController | null = null;
    let disposed = false;
    async function refresh() {
      current?.abort();
      current = new AbortController();
      const controller = current;
      setBundle(null); // Never continue displaying a record after a failed access refresh.
      if (document.hidden) return;
      try {
        const data = await loadRecord(id, controller.signal);
        if (!disposed && !controller.signal.aborted) { setBundle(data); setError(null); }
      } catch (reason) {
        if (!disposed && !controller.signal.aborted) {
          setError(getUserFacingError(reason, t("doctor.abdm.errRecordAccess")));
        }
      }
    }
    const onVisibility = () => { void refresh(); };
    void refresh();
    const timer = window.setInterval(onVisibility, 15000);
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("blur", onVisibility);
    return () => { disposed = true; current?.abort(); window.clearInterval(timer); document.removeEventListener("visibilitychange", onVisibility); window.removeEventListener("blur", onVisibility); };
  }, [id, t]);
  const entries = Array.isArray(bundle?.entry) ? bundle.entry : [];
  let attachments: EmbeddedPdf[] = [];
  let attachmentError = false;
  try { attachments = bundle ? embeddedPdfs(bundle) : []; } catch { attachmentError = true; }
  return <section className="surface-card space-y-4 p-5" aria-label="External clinical record">
    <div className="flex justify-between gap-4">
      <h2 className="text-xl font-semibold">{t("doctor.abdm.externalRecordTitle")}</h2>
      <button type="button" className="underline" onClick={close}>
        {t("doctor.abdm.closeRecord")}
      </button>
    </div>
    <p className="text-sm text-muted-foreground">{t("doctor.abdm.externalRecordIntro")}</p>
    {error && <p role="alert" className="text-danger">{error}</p>}
    {!bundle && !error && <p role="status">{t("doctor.abdm.checkingConsent")}</p>}
    {attachmentError && <p role="alert">{t("doctor.abdm.errPdfAttachments")}</p>}
    {attachments.map((pdf, index) => <div key={index} className="space-y-3 rounded border p-3">
      <button type="button" className="underline" onClick={() => setSelectedPdf(selectedPdf === index ? null : index)}>{selectedPdf === index ? "Close PDF preview" : `Preview ${pdf.title}`}</button>
      {selectedPdf === index && <EmbeddedPdfPreview key={`${id}:${index}`} data={pdf.data} title={pdf.title} />}
    </div>)}
    {entries.map((entry: unknown, index) => {
      const resource = typeof entry === "object" && entry !== null && "resource" in entry ? entry.resource : entry;
      const title = typeof resource === "object" && resource !== null && "resourceType" in resource ? String(resource.resourceType) : "Resource";
      return <details key={index} open={index === 0} className="rounded border border-border p-3"><summary className="cursor-pointer font-medium">{title}</summary><div className="mt-3 text-sm"><Value value={resource} /></div></details>;
    })}
  </section>;
}
