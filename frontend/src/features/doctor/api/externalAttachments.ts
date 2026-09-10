import { api } from "@/lib/api";

export interface ResultFile {
  id: string;
  original_name: string | null;
  patient_id: string | null;
  erased_at: string | null;
}

function assertPatientFile(file: ResultFile, patientId: string, expectedId?: string) {
  if (!file?.id || file.patient_id !== patientId || file.erased_at || (expectedId && file.id !== expectedId)) {
    throw new Error("Attachment does not match the current patient or is unavailable");
  }
}

export function validateResultFile(file: File): string | null {
  if (file.size === 0) return "Choose a non-empty report file.";
  if (file.size > 25 * 1024 * 1024) return "The report must be 25 MB or smaller.";
  // Only these formats are offered here. Backend magic-byte validation remains
  // authoritative; an extension is not evidence that a file is safe to read.
  if (!/\.(pdf|png|jpe?g)$/i.test(file.name)) return "Choose a PDF, PNG or JPEG report.";
  return null;
}

export async function uploadResultFile(file: File, patientId: string): Promise<ResultFile> {
  const invalid = validateResultFile(file);
  if (invalid) throw new Error(invalid);
  const body = new FormData();
  body.append("upload", file);
  body.append("patient_id", patientId);
  body.append("owner_module", "orders");
  body.append("sensitivity", "sensitive");
  // /files/upload has no idempotency protocol. Do not invent one or auto-retry
  // an uncertain upload: it may already have created a patient file.
  const saved = await api<ResultFile>("/files/upload", { method: "POST", body, idempotencyKey: null });
  assertPatientFile(saved, patientId);
  return saved;
}

export async function prepareResultDownload(fileId: string, patientId: string) {
  const file = await api<ResultFile>(`/files/${encodeURIComponent(fileId)}`);
  assertPatientFile(file, patientId, fileId);
  const link = await api<{ url: string; expires_in_seconds: number }>(`/files/${encodeURIComponent(fileId)}/download-url`);
  const url = new URL(link.url);
  const localHttp = url.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
  if ((url.protocol !== "https:" && !localHttp) || url.username || url.password ||
      !Number.isFinite(link.expires_in_seconds) || link.expires_in_seconds <= 0) {
    throw new Error("The attachment download address is not safely configured");
  }
  return { url: url.href, name: file.original_name || "Outside report", expiresAt: Date.now() + link.expires_in_seconds * 1000 };
}
