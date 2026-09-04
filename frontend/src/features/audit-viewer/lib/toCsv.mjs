/**
 * Serialise rows to CSV for the audit screen's client-side exports.
 *
 * The Access log, File access and Integrity tabs have no server export
 * endpoint, so their CSV is built from the rows on screen. That makes escaping
 * this module's whole job: audit rows carry free text (reasons, justifications,
 * user agents) that contains commas, quotes and newlines, and a naive
 * `values.join(",")` silently shifts every later column into the wrong header
 * on exactly the rows an investigator cares about.
 *
 * RFC 4180: quote a field if it contains a comma, quote, CR or LF, and escape
 * an inner quote by doubling it.
 */

function serialise(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function escape(value) {
  const text = serialise(value);
  if (!/[",\r\n]/.test(text)) return text;
  return `"${text.replace(/"/g, '""')}"`;
}

/**
 * Header order comes from the union of every row's keys, not row zero's.
 *
 * Audit rows are sparse — an entry with no patient_id omits the key entirely —
 * so taking the first row's keys drops columns that later rows populate.
 */
export function toCsv(rows) {
  if (rows.length === 0) return "";

  const headers = [];
  for (const row of rows) {
    for (const key of Object.keys(row)) {
      if (!headers.includes(key)) headers.push(key);
    }
  }

  const lines = [headers.map(escape).join(",")];
  for (const row of rows) {
    lines.push(headers.map((header) => escape(row[header])).join(","));
  }
  // CRLF, which is what RFC 4180 specifies and what Excel expects.
  return lines.join("\r\n");
}
