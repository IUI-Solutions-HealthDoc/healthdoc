export type ExtractedErrors = {
  fieldErrors: Record<string, string>;
  summary: string | null;
};

export { extractValidationErrors, getActionableErrorMessage } from "./errors.mjs";
