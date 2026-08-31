const UHID_PATTERN = /^IN-[A-Z]{2}-[A-Z0-9_]{1,20}-\d{4}-\d{6,}-\d$/;
const FORBIDDEN_NAME_CHARACTERS = /[\d<>{}\[\]|\\^~`@#$%*_=+;]/u;

export function digitsOnly(value: string): string {
  return value.replace(/\D/g, "");
}

export function normaliseIndianMobileInput(value: string): string | null {
  const raw = value.trim();
  if (!raw) return null;
  if (/[^\d+\- ]/.test(raw) || (raw.includes("+") && !raw.startsWith("+"))) return null;

  let digits = digitsOnly(raw);
  if (digits.length === 12 && digits.startsWith("91")) digits = digits.slice(2);
  else if (digits.length === 11 && digits.startsWith("0")) digits = digits.slice(1);

  if (!/^[6-9]\d{9}$/.test(digits)) return null;
  return `+91${digits}`;
}

export function isValidPatientName(value: string): boolean {
  const name = value.trim().replace(/\s+/g, " ");
  return name.length >= 2 && !FORBIDDEN_NAME_CHARACTERS.test(name);
}

export function isValidAbhaInput(value: string): boolean {
  const raw = value.trim();
  return /^[\d -]+$/.test(raw) && digitsOnly(raw).length === 14;
}

export function normaliseUhidInput(value: string): string {
  return value.trim().toUpperCase();
}

export function isValidUhidInput(value: string): boolean {
  return UHID_PATTERN.test(normaliseUhidInput(value));
}
