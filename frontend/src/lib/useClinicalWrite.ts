"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, newIdempotencyKey } from "@/lib/api";
import { apiErrorCode } from "@/lib/api-error-policy.mjs";

/** One mounted editor/action. Never persist clinical drafts in browser storage. */
export function useClinicalWrite() {
  const attempt = useRef<{ key: string; body: string } | null>(null);
  const busy = useRef(false);
  const mounted = useRef(true);
  const [retryPending, setRetryPending] = useState(false);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  async function run<Payload, Result>(payload: Payload, send: (body: Payload, key: string) => Promise<Result>): Promise<Result> {
    if (!mounted.current || busy.current) throw new Error("A save is already in progress or this editor is closed.");
    const body = JSON.stringify(payload);
    if (attempt.current && attempt.current.body !== body)
      throw new Error("Retry the unchanged save before editing. Its outcome has not been confirmed.");
    attempt.current ??= { key: newIdempotencyKey(), body };
    const current = attempt.current;
    busy.current = true;
    try {
      const result = await send(JSON.parse(current.body) as Payload, current.key);
      attempt.current = null;
      if (mounted.current) setRetryPending(false);
      return result;
    } catch (error) {
      // Only explicit pre-write refusals allow a new draft/key. Network errors,
      // proxy failures, malformed success bodies and 409 ambiguity keep the key.
      const refused = error instanceof ApiError && (
        [400, 401, 403, 404, 422].includes(error.code) ||
        (error.code === 409 && apiErrorCode(error.payload) === "clinical_write_rejected")
      );
      if (refused) attempt.current = null;
      if (mounted.current) setRetryPending(!refused);
      if (!refused)
        throw new Error("Save outcome is not confirmed. Keep this editor open and retry the unchanged save. If you leave or reload, check the saved records before entering it again.");
      throw error;
    } finally {
      busy.current = false;
    }
  }
  return { run, retryPending, isCurrent: () => mounted.current };
}
