import { api } from "@/lib/api";

export interface OutboxEvent {
  id: string;
  aggregate_type: string;
  aggregate_id: string;
  event_type: string;
  sensitivity: string;
  status: "pending" | "in_flight" | "sent" | "dead_letter";
  attempts: number;
  last_error: string | null;
  sent_at: string | null;
  sequence: number;
  created_at: string;
}

export interface OutboxDeadLetter {
  id: string;
  original_event_id: string | null;
  aggregate_type: string;
  aggregate_id: string;
  event_type: string;
  payload_redacted: Record<string, unknown>;
  error_message: string;
  failed_at: string;
  replay_count: number;
  created_at: string;
}

export interface OutboxMetrics {
  pending_count: number;
  in_flight_count: number;
  sent_count: number;
  dead_letter_count: number;
  total_events: number;
  delivery_lag_seconds: number;
}

export function fetchOutboxMetrics(): Promise<OutboxMetrics> {
  return api<OutboxMetrics>("/outbox/metrics");
}

export function fetchOutboxEvents(params: {
  status?: string;
  aggregate_type?: string;
  limit?: number;
} = {}): Promise<OutboxEvent[]> {
  const q = new URLSearchParams();
  if (params.status) q.set("status", params.status);
  if (params.aggregate_type) q.set("aggregate_type", params.aggregate_type);
  if (params.limit) q.set("limit", String(params.limit));
  return api<OutboxEvent[]>(`/outbox/events?${q.toString()}`);
}

export function fetchDeadLetters(limit: number = 50): Promise<OutboxDeadLetter[]> {
  return api<OutboxDeadLetter[]>(`/outbox/dead-letter?limit=${limit}`);
}

export function replayDeadLetter(id: string): Promise<OutboxEvent> {
  return api<OutboxEvent>(`/outbox/dead-letter/${id}/replay`, {
    method: "POST",
  });
}
