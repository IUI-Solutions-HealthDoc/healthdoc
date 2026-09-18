const UHID_PATTERN = /^IN-[A-Z]{2}-[A-Z0-9_]{1,20}-\d{4}-\d{6,}-\d$/;
const THID_PATTERN = /^TH-[A-Z0-9_]{1,20}-\d{6}-\d{4,}$/;
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
  const norm = normaliseUhidInput(value);
  return UHID_PATTERN.test(norm) || THID_PATTERN.test(norm);
}

export interface DerivedAgeInfo {
  years: number;
  months: number;
  days: number;
  displayText: string;
}

export function deriveAgeFromDob(dobString: string, referenceDate = new Date()): DerivedAgeInfo | null {
  if (!dobString) return null;
  const dob = new Date(dobString);
  if (isNaN(dob.getTime())) return null;

  let years = referenceDate.getFullYear() - dob.getFullYear();
  let months = referenceDate.getMonth() - dob.getMonth();
  let days = referenceDate.getDate() - dob.getDate();

  if (days < 0) {
    months -= 1;
    const prevMonthDays = new Date(referenceDate.getFullYear(), referenceDate.getMonth(), 0).getDate();
    days += prevMonthDays;
  }
  if (months < 0) {
    years -= 1;
    months += 12;
  }

  if (years < 0) return null;

  let displayText = "";
  if (years === 0 && months === 0) {
    displayText = `${days} day${days === 1 ? "" : "s"} (Newborn)`;
  } else if (years === 0) {
    displayText = `${months} month${months === 1 ? "" : "s"}, ${days} day${days === 1 ? "" : "s"} (Infant)`;
  } else if (years < 5) {
    displayText = `${years} year${years === 1 ? "" : "s"}, ${months} month${months === 1 ? "" : "s"}`;
  } else {
    displayText = `${years} years`;
  }

  return { years, months, days, displayText };
}

