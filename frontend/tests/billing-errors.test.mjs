import assert from "node:assert/strict";
import test from "node:test";

import { extractValidationErrors, getActionableErrorMessage } from "../src/features/billing/lib/errors.mjs";

test("extractValidationErrors extracts field-level errors from FastAPI 422 detail payload", () => {
  const error = {
    code: 422,
    message: "Please check the highlighted fields and try again.",
    payload: [
      {
        loc: ["body", "amount"],
        msg: "Input should be greater than 0",
        type: "greater_than",
      },
    ],
  };

  const { fieldErrors, summary } = extractValidationErrors(error);

  assert.equal(fieldErrors.amount, "Input should be greater than 0");
  assert.equal(summary, "Amount: Input should be greater than 0");
});

test("extractValidationErrors handles multiple validation errors", () => {
  const error = {
    code: 422,
    message: "Please check the highlighted fields and try again.",
    payload: {
      detail: [
        { loc: ["body", "amount"], msg: "Value error, Amount exceeds balance" },
        { loc: ["body", "mode"], msg: "Input should be 'cash', 'upi', 'card' or 'netbanking'" },
      ],
    },
  };

  const { fieldErrors, summary } = extractValidationErrors(error);

  assert.equal(fieldErrors.amount, "Amount exceeds balance");
  assert.equal(fieldErrors.mode, "Input should be 'cash', 'upi', 'card' or 'netbanking'");
  assert.match(summary, /Amount: Amount exceeds balance/);
  assert.match(summary, /Mode: Input should be/);
});

test("getActionableErrorMessage falls back gracefully when no field details exist", () => {
  const error = { code: 409, message: "Payment amount 50.00 exceeds remaining balance.", payload: null };
  assert.equal(getActionableErrorMessage(error), "Payment amount 50.00 exceeds remaining balance.");

  const genericError = { code: 422, message: "Please check the highlighted fields and try again.", payload: null };
  assert.equal(getActionableErrorMessage(genericError), "Please check the highlighted fields and try again.");
});
