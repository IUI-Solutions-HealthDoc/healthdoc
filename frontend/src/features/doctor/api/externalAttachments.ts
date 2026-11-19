import { api } from "@/lib/api";
import { translate } from "@/lib/i18n";

export interface ResultFile {
  id: string;
  original_name: string | null;
  patient_id: string | null;
  erased_at: string | null;
}

function assertPatientFile(file: ResultFile, patientId: string, expectedId?: string) {
  if (!file?.id || file.patient_id !== patientId || file.erased_at || (expectedId && file.id !== expectedId)) {
    throw new Error(translate("doctor.msg.attachmentDoesNotMatchTheCurrent"));
  }
}

export function validateResultFile(file: File): string | null {
  if (file.size === 0) return translate("doctor.msg.chooseANonEmptyReportFile");
  if (file.size > 25 * 1024 * 1024) return translate("doctor.msg.theReportMustBe25Mb");
  // Only these formats are offered here. Backend magic-byte validation remains
  // authoritative; an extension is not evidence that a file is safe to read.
  if (!/\.(pdf|png|jpe?g)$/i.test(file.name)) return translate("doctor.msg.chooseAPdfPngOrJpeg");
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
    throw new Error(translate("doctor.msg.theAttachmentDownloadAddressIsNot"));
  }
  return { url: url.href, name: file.original_name || translate("doctor.ui.outsideReport"), expiresAt: Date.now() + link.expires_in_seconds * 1000 };
}
