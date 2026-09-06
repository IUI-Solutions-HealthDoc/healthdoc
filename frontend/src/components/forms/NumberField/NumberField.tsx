import { NumberFieldProps } from "./NumberField.types";

export default function NumberField({
  label,
  placeholder,
  registration,
  error,
  // `step` defaults to 1 on a native number input, so 37.1 is "invalid" and
  // the browser blocks the whole form submit — showing a native bubble and no
  // in-app message, which is how a nurse lost every attempt to chart a
  // temperature. `inputMode="decimal"` below already advertises decimals; this
  // makes the element agree. Fields that genuinely need whole numbers say so
  // in their zod schema, where the message is readable.
  step = "any",
}: NumberFieldProps) {
  const fieldId = `field-${registration.name}`;
  const errorId = `${fieldId}-error`;

  return (
    <div className="space-y-2">
      <label htmlFor={fieldId} className="text-sm font-medium">
        {label}
      </label>

      <input
        id={fieldId}
        type="number"
        step={step}
        inputMode="decimal"
        placeholder={placeholder}
        aria-invalid={!!error}
        aria-describedby={error ? errorId : undefined}
        className="
          w-full
          rounded-lg
          border
          border-border
          bg-background
          px-3
          py-2.5
          text-sm
          outline-none
          focus:border-primary
        "
        {...registration}
      />

      {error && (
        <p id={errorId} className="text-xs text-danger">
          {error.message}
        </p>
      )}
    </div>
  );
}
