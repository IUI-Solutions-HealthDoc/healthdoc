"use client";

import { useEffect, useRef, useState } from "react";
import { api, getUserFacingError, newIdempotencyKey } from "@/lib/api";
import { useLocale } from "@/lib/i18n";

interface Context { id: string; reference: string; display: string; hi_type: string }
interface LinkStatus { id: string; status: string; care_context_references: string[] }

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
