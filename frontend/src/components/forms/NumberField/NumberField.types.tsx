import {
  FieldError,
  UseFormRegisterReturn,
} from "react-hook-form";

export interface NumberFieldProps {
  label: string;

  placeholder?: string;

  registration: UseFormRegisterReturn;

  error?: FieldError;

  /**
   * Native step constraint. Defaults to "any" so decimal measurements are
   * accepted; pass "1" only where the browser refusing a decimal is genuinely
   * better than the schema explaining why.
   */
  step?: string | number;
}