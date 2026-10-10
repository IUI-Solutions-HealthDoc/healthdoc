"use client";

import { useEffect, useRef, useState } from "react";

import type { NowServing, QueueDisplayEvent, StreamStatus } from "./types";

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1";

/**
 * Subscribe to one department's queue display stream.
 *
 * Uses `EventSource` rather than the shared `api()` client on purpose: this is
 * an unauthenticated endpoint (with /public/availability), and `EventSource`
 * cannot send an Authorization header anyway. It also reconnects on its own,
 * which is exactly what a screen left running for a fortnight needs.
 *
 * KNOWN GAP — no initial state.
 * The stream only carries events published from this moment on. There is no
 * public endpoint returning the queue's current state, so a display that
 * reboots at 3pm shows an empty board until the next token is called. The
 * screen says so rather than rendering a blank that looks like an empty
 * waiting room. Closing this properly needs a small public
 * `GET /queue/display/{department_id}` snapshot endpoint, built to the same
 * PII-free contract as the stream.
 */
export function useQueueStream(departmentId: string | null) {
  const [status, setStatus] = useState<StreamStatus>("connecting");
  const [serving, setServing] = useState<Record<string, NowServing>>({});
  const [receivedAny, setReceivedAny] = useState(false);
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!departmentId) return;

    const url = `${BASE}/queue/display/${departmentId}/stream`;
    const source = new EventSource(url);
    sourceRef.current = source;

    source.onopen = () => setStatus("live");

    source.onmessage = (event: MessageEvent<string>) => {
      // A malformed frame must not kill a wall screen nobody is watching.
      let parsed: QueueDisplayEvent;
      try {
        parsed = JSON.parse(event.data) as QueueDisplayEvent;
      } catch {
        console.warn("[queue-display] unparseable frame", event.data);
        return;
      }

      if (parsed.event_type !== "token_called" || !parsed.payload) return;

      setReceivedAny(true);
      setStatus("live");
      setServing((current) => ({
        ...current,
        // Keyed by queue, not department: an OPD floor runs several doctors at
        // once and each counter shows its own number.
        [parsed.payload.queue_id]: {
          ...parsed.payload,
          received_at: Date.now(),
        },
      }));
    };

    source.onerror = () => {
      // EventSource retries by itself; surface it rather than tearing down and
      // hand-rolling a backoff that would be worse.
      setStatus("reconnecting");
    };

    return () => {
      source.close();
      sourceRef.current = null;
    };
  }, [departmentId]);

  return { status, serving, receivedAny };
}
