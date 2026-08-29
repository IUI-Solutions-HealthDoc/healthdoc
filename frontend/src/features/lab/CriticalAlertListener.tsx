"use client";

import { useEffect } from "react";

import { toast } from "@/components/ui/toast";
import { API_BASE_URL, getAccessToken } from "@/lib/api";
import { retryDelayMs } from "@/lib/resilience.mjs";
import { useAuth } from "@/providers/auth-provider";

import type { CriticalLabAlert } from "./types";

function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = window.setTimeout(resolve, ms);
    signal.addEventListener("abort", () => {
      window.clearTimeout(timer);
      resolve();
    }, { once: true });
  });
}

function showAlert(raw: string) {
  try {
    const alert = JSON.parse(raw) as CriticalLabAlert;
    toast.warning(
      "Critical lab result",
      `Accession ${alert.accession_number} requires immediate review.`,
    );
  } catch {
    console.warn("[lab] ignored malformed critical-alert event");
  }
}

async function readEventStream(response: Response, signal: AbortSignal) {
  if (!response.body) throw new Error("Critical-alert stream has no response body");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (!signal.aborted) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true }).replaceAll("\r\n", "\n");
      let boundary = buffer.indexOf("\n\n");
      while (boundary >= 0) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const data = block
          .split("\n")
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trimStart())
          .join("\n");
        if (data) showAlert(data);
        boundary = buffer.indexOf("\n\n");
      }
    }
  } finally {
    // Abort normally rejects the pending read, but explicitly cancelling the
    // reader closes the HTTP body as well. Without it, dev-proxy buffering left
    // upstream SSE requests alive after the page/context had been closed.
    try {
      await reader.cancel();
    } catch {
      // The fetch abort may already have closed the stream.
    }
    reader.releaseLock();
  }
}

export function CriticalAlertListener() {
  const { user, isLoading } = useAuth();

  useEffect(() => {
    if (isLoading || !user?.role || !["doctor", "lab_tech"].includes(user.role)) return;
    const controller = new AbortController();

    async function connect() {
      let failedAttempts = 0;
      while (!controller.signal.aborted) {
        const token = getAccessToken();
        if (!token) {
          await wait(retryDelayMs(failedAttempts++), controller.signal);
          continue;
        }
        try {
          const response = await fetch(`${API_BASE_URL}/pathology/critical-alerts/stream`, {
            headers: { Authorization: `Bearer ${token}` },
            cache: "no-store",
            signal: controller.signal,
          });
          if (!response.ok) throw new Error(`Critical-alert stream returned ${response.status}`);
          failedAttempts = 0;
          await readEventStream(response, controller.signal);
        } catch (reason) {
          if (!controller.signal.aborted) {
            console.warn("[lab] critical-alert stream disconnected", reason);
          }
        }
        if (!controller.signal.aborted) {
          await wait(retryDelayMs(failedAttempts++), controller.signal);
        }
      }
    }

    void connect();
    return () => controller.abort();
  }, [isLoading, user?.role]);

  return null;
}
