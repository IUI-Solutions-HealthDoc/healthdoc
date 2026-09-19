import { api } from "@/lib/api";

export interface PortalBinding {
  id: string;
  patient_id: string;
  verification_method: "abha_otp" | "in_person_document";
  verified_at: string;
}

export interface PortalAbha {
  patient_id: string;
  abha_number: string | null;
  linked_at: string | null;
  linked: boolean;
}

export interface PortalConsent {
  id: string;
  purpose_code: string;
  purpose_description: string | null;
  status: string;
  granted_at: string;
  expires_at: string | null;
  scope: string[] | null;
  channel: string;
}

export interface PortalAccessItem {
  accessed_at: string;
  staff_name: string | null;
  role: string | null;
  resource_type: string | null;
  purpose_code: string | null;
  access_channel: string;
  emergency_access: boolean;
}

export interface PortalAccessHistory {
  total: number;
  limit: number;
  offset: number;
  items: PortalAccessItem[];
}

export interface PortalDashboard {
  binding: PortalBinding;
  abha: PortalAbha;
  consents: PortalConsent[];
  accessHistory: PortalAccessHistory;
}

export async function getPortalDashboard(): Promise<PortalDashboard> {
  const [binding, abha, consents, accessHistory] = await Promise.all([
    api<PortalBinding>("/patient-portal/binding"),
    api<PortalAbha>("/patient-portal/me/abha"),
    api<PortalConsent[]>("/patient-portal/me/consents"),
    api<PortalAccessHistory>("/patient-portal/me/access-history?limit=50&offset=0"),
  ]);
  return { binding, abha, consents, accessHistory };
}

export interface PortalDocumentItem {
  id: string;
  document_type: "prescription" | "lab_report" | "radiology" | "discharge_summary" | "vaccine";
  title: string;
  date: string;
  doctor_name: string | null;
  facility_name: string | null;
  status: string;
  summary: string;
  details?: Record<string, unknown> | null;
}

export interface PortalDocumentsOut {
  total: number;
  limit: number;
  offset: number;
  items: PortalDocumentItem[];
}

export interface PortalDocumentDetail {
  id: string;
  document_type: string;
  title: string;
  date: string;
  doctor_name: string | null;
  facility_name: string | null;
  facility_address: string | null;
  patient_uhid: string | null;
  patient_name: string;
  patient_age_gender: string | null;
  status: string;
  summary: string;
  content: Record<string, unknown>;
  verified_at: string | null;
}

export async function getPortalDocuments(category?: string): Promise<PortalDocumentsOut> {
  const query = category && category !== "all" ? `?category=${encodeURIComponent(category)}` : "";
  return api<PortalDocumentsOut>(`/patient-portal/me/documents${query}`);
}

export async function getPortalDocumentDetail(
  docType: string,
  docId: string,
): Promise<PortalDocumentDetail> {
  return api<PortalDocumentDetail>(
    `/patient-portal/me/documents/${encodeURIComponent(docType)}/${encodeURIComponent(docId)}`,
  );
}

