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

/**
 * Today on this machine's calendar as YYYY-MM-DD. `toISOString()` is the UTC
 * date, which is still yesterday in India until 05:30 — a baby born after
 * midnight could not have their date of birth entered.
 */
export function localToday(now = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** India Post PIN codes are six digits and never start with 0. */
export function isValidPincodeInput(value: string): boolean {
  return /^[1-9]\d{5}$/.test(value.trim());
}

/** ISO 3166-2:IN subdivision codes, the same scheme the state field's examples use. */
export const INDIAN_STATES: ReadonlyArray<{ code: string; name: string }> = [
  { code: "AN", name: "Andaman and Nicobar Islands" },
  { code: "AP", name: "Andhra Pradesh" },
  { code: "AR", name: "Arunachal Pradesh" },
  { code: "AS", name: "Assam" },
  { code: "BR", name: "Bihar" },
  { code: "CH", name: "Chandigarh" },
  { code: "CT", name: "Chhattisgarh" },
  { code: "DH", name: "Dadra and Nagar Haveli and Daman and Diu" },
  { code: "DL", name: "Delhi" },
  { code: "GA", name: "Goa" },
  { code: "GJ", name: "Gujarat" },
  { code: "HP", name: "Himachal Pradesh" },
  { code: "HR", name: "Haryana" },
  { code: "JH", name: "Jharkhand" },
  { code: "JK", name: "Jammu and Kashmir" },
  { code: "KA", name: "Karnataka" },
  { code: "KL", name: "Kerala" },
  { code: "LA", name: "Ladakh" },
  { code: "LD", name: "Lakshadweep" },
  { code: "MH", name: "Maharashtra" },
  { code: "ML", name: "Meghalaya" },
  { code: "MN", name: "Manipur" },
  { code: "MP", name: "Madhya Pradesh" },
  { code: "MZ", name: "Mizoram" },
  { code: "NL", name: "Nagaland" },
  { code: "OR", name: "Odisha" },
  { code: "PB", name: "Punjab" },
  { code: "PY", name: "Puducherry" },
  { code: "RJ", name: "Rajasthan" },
  { code: "SK", name: "Sikkim" },
  { code: "TG", name: "Telangana" },
  { code: "TN", name: "Tamil Nadu" },
  { code: "TR", name: "Tripura" },
  { code: "UP", name: "Uttar Pradesh" },
  { code: "UT", name: "Uttarakhand" },
  { code: "WB", name: "West Bengal" },
];

export function isValidStateCode(value: string): boolean {
  return INDIAN_STATES.some((state) => state.code === value);
}

/** Patient photos the server accepts; it sniffs the bytes, this only saves a round trip. */
export const PHOTO_MIME_TYPES: ReadonlyArray<string> = ["image/jpeg", "image/png"];

export interface DerivedAgeInfo {
  years: number;
  months: number;
  days: number;
  displayText: string;
}

export function deriveAgeFromDob(dobString: string, referenceDate = new Date()): DerivedAgeInfo | null {
  if (!dobString) return null;
  // `new Date("YYYY-MM-DD")` is UTC midnight, but the arithmetic below reads
  // local fields; west of UTC that is the previous day. Build it locally.
  const parts = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dobString);
  const dob = parts
    ? new Date(Number(parts[1]), Number(parts[2]) - 1, Number(parts[3]))
    : new Date(dobString);
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

