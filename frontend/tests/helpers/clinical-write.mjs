import { randomUUID } from "node:crypto";
import { compile } from "./component-harness.mjs";
import { apiErrorCode } from "../../src/lib/api-error-policy.mjs";

export class TestApiError extends Error {
  constructor(code, message = "Explicit refusal", payload) { super(message); this.code = code; this.payload = payload; }
}
export const clinicalWrite = (runtime) => compile(
  new URL("../../src/lib/useClinicalWrite.ts", import.meta.url), {
    ...runtime, "@/lib/api": { ApiError: TestApiError, newIdempotencyKey: randomUUID },
    "@/lib/api-error-policy.mjs": { apiErrorCode },
  },
);
