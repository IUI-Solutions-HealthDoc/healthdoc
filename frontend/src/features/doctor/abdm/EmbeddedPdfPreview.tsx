"use client";

import { useEffect, useRef, useState } from "react";
import type { PDFDocumentLoadingTask, RenderTask } from "pdfjs-dist";
import { pdfBytes } from "./pdfAttachments";

/** Canvas only: no PDF scripting manager, forms, annotation links or downloads. */
export function EmbeddedPdfPreview({ data, title }: { data: string; title: string }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(0);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let disposed = false;
    let task: PDFDocumentLoadingTask | undefined;
    let rendering: RenderTask | undefined;
    let worker: Worker | undefined;
    const surface = canvas.current;
    const clear = () => { if (surface) { surface.width = 0; surface.height = 0; } };
    const deadline = window.setTimeout(() => {
      if (!disposed) { disposed = true; clear(); setError("PDF preview timed out. Close it and try again."); rendering?.cancel(); void task?.destroy(); worker?.terminate(); }
    }, 15000);
    async function render() {
      try {
        const pdf = await import("pdfjs-dist");
        if (disposed) return;
        worker = new Worker(new URL("pdfjs-dist/build/pdf.worker.mjs", import.meta.url), { type: "module" });
        const pdfWorker = pdf.PDFWorker.create({ port: worker });
        task = pdf.getDocument({ data: pdfBytes(data), worker: pdfWorker,
          enableXfa: false, useWorkerFetch: false, useWasm: false, disableAutoFetch: true,
          disableStream: true, disableRange: true, disableFontFace: true, useSystemFonts: true,
          maxImageSize: 4_000_000, canvasMaxAreaInBytes: 16_000_000, stopAtErrors: true, verbosity: 0 });
        const document = await task.promise;
        if (disposed) return;
        if (document.numPages > 100) throw new Error("Too many pages");
        setPages(document.numPages);
        const current = await document.getPage(page);
        if (disposed || !surface) return;
        const original = current.getViewport({ scale: 1 });
        const scale = Math.min(1.5, 1800 / original.width, 2400 / original.height);
        const viewport = current.getViewport({ scale });
        if (!Number.isFinite(viewport.width * viewport.height) || viewport.width <= 0 || viewport.height <= 0) throw new Error("Invalid page dimensions");
        surface.width = Math.ceil(viewport.width); surface.height = Math.ceil(viewport.height);
        rendering = current.render({ canvas: surface, viewport, annotationMode: pdf.AnnotationMode.DISABLE });
        await rendering.promise;
        if (!disposed) setError(null);
      } catch {
        if (!disposed) { clear(); setError("This PDF could not be safely previewed. The structured record remains available."); }
      } finally { window.clearTimeout(deadline); }
    }
    void render();
    return () => { disposed = true; window.clearTimeout(deadline); rendering?.cancel(); void task?.destroy(); worker?.terminate(); clear(); };
  }, [data, page]);
  return <section className="space-y-3" aria-label={title}>
    <p className="text-sm">PDF preview only. Links, scripts, downloads and interactive forms are disabled.</p>
    {error && <p role="alert" className="text-danger">{error}</p>}
    <div className="flex items-center gap-4">
      <button type="button" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Previous page</button>
      <span>Page {page}{pages > 0 ? ` of ${pages}` : ""}</span>
      <button type="button" disabled={!pages || page >= pages} onClick={() => setPage((p) => p + 1)}>Next page</button>
    </div>
    <canvas ref={canvas} className="max-w-full border" aria-label={`${title}, page ${page}`} />
  </section>;
}
