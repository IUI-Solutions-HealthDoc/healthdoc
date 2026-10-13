/**
 * Maternal and child health records. Record only: nothing here computes a
 * schedule, a due date or a risk; a clinician enters each of those.
 * Writes carry an Idempotency-Key (clinical writes, replayed on retry).
 */
import { api } from "@/lib/api";

export interface AncVisit {
  id: string;
  visit_date: string;
  gestation_weeks: number | null;
  weight_kg: string | null;
  bp_systolic: number | null;
  bp_diastolic: number | null;
  hemoglobin_g_dl: string | null;
  fundal_height_cm: number | null;
  fetal_heart_rate: number | null;
  urine_albumin: string | null;
  urine_sugar: string | null;
  ifa_tablets: number | null;
  notes: string | null;
}

export interface Pregnancy {
  id: string;
  patient_id: string;
  lmp_date: string | null;
  edd: string | null;
  gravida: number | null;
  para: number | null;
  rch_id: string | null;
  status: "active" | "delivered" | "ended";
  high_risk: boolean;
  high_risk_reason: string | null;
  end_reason: string | null;
  created_at: string;
  anc_visits: AncVisit[];
  delivery: {
    id: string;
    delivered_at: string;
    mode: string;
    notes: string | null;
    newborns: { id: string; outcome: string; sex: string; birth_weight_g: number | null }[];
  } | null;
}

const post = <T,>(path: string, body: unknown, key: string) =>
  api<T>(path, { method: "POST", idempotencyKey: key, body: JSON.stringify(body) });

export function listPregnancies(patientId: string): Promise<Pregnancy[]> {
  return api<Pregnancy[]>(`/mch/patients/${patientId}/pregnancies`);
}

export function registerPregnancy(body: Record<string, unknown>, key: string): Promise<Pregnancy> {
  return post<Pregnancy>("/mch/pregnancies", body, key);
}

export function recordAncVisit(id: string, body: Record<string, unknown>, key: string): Promise<Pregnancy> {
  return post<Pregnancy>(`/mch/pregnancies/${id}/anc-visits`, body, key);
}

export function flagRisk(id: string, body: { high_risk: boolean; reason: string | null }, key: string): Promise<Pregnancy> {
  return post<Pregnancy>(`/mch/pregnancies/${id}/risk`, body, key);
}

export function endPregnancy(id: string, reason: string, key: string): Promise<Pregnancy> {
  return post<Pregnancy>(`/mch/pregnancies/${id}/end`, { reason }, key);
}

export function recordDelivery(id: string, body: Record<string, unknown>, key: string): Promise<Pregnancy> {
  return post<Pregnancy>(`/mch/pregnancies/${id}/delivery`, body, key);
}
