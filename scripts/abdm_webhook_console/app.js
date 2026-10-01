"use strict";
const byId = id => document.getElementById(id);
let selected = null, loading = false, detailGeneration = 0;
async function read(path) {
  const response = await fetch(path, {headers: {"X-HealthDoc-Operator-View": "1"}, cache: "no-store"});
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
  return body;
}
function cell(row, value) { const td = document.createElement("td"); td.textContent = value ?? "—"; row.append(td); return td; }
async function inspect(id) {
  const generation = ++detailGeneration;
  selected = null; byId("copy").disabled = true; byId("detail").textContent = "Loading…";
  try {
    const result = await read(`/api/receipt?id=${encodeURIComponent(id)}`);
    if (generation !== detailGeneration) return;
    if (!result.length) throw new Error("Receipt unavailable or expired (7-day window).");
    selected = result[0]; byId("detail").textContent = JSON.stringify(selected, null, 2); byId("copy").disabled = false;
  } catch (e) { if (generation === detailGeneration) byId("detail").textContent = e.message; }
}
async function refresh() {
  if (loading) return;
  loading = true;
  const request = byId("request").value.trim();
  try {
    const receipts = await read(`/api/receipts${request ? `?request_id=${encodeURIComponent(request)}` : ""}`);
    byId("rows").replaceChildren();
    const visible = receipts.filter(r => !byId("post-only").checked || r.method === "POST");
    for (const receipt of visible) {
      const row = document.createElement("tr");
      cell(row, receipt.received_at); cell(row, receipt.method); cell(row, receipt.path);
      cell(row, receipt.status_code ?? "Incomplete"); cell(row, receipt.response_request_id || receipt.request_id);
      const button = document.createElement("button"); button.textContent = "Inspect"; button.onclick = () => inspect(receipt.id); cell(row, "").append(button);
      byId("rows").append(row);
    }
    byId("state").textContent = `${visible.length} shown from latest ${receipts.length} receipts. Updated ${new Date().toISOString()}.${visible.length ? "" : " No matching callbacks; uncheck POST only to see probes. This does not prove NHA sent nothing."}`;
  } catch (e) { byId("rows").replaceChildren(); byId("state").textContent = `Read failed: ${e.message}`; }
  finally { loading = false; }
}
async function status() {
  try { byId("operational").textContent = JSON.stringify(await read("/api/status"), null, 2); }
  catch(e) { byId("operational").textContent = `Read failed: ${e.message}`; }
}
byId("filters").onsubmit = e => { e.preventDefault(); refresh(); };
byId("clear").onclick = () => { byId("request").value = ""; refresh(); };
byId("post-only").onchange = refresh;
byId("copy").onclick = async () => {
  if (!selected) return;
  try { await navigator.clipboard.writeText(JSON.stringify(selected, null, 2)); byId("state").textContent = "Redacted callback evidence copied."; }
  catch { byId("state").textContent = "Clipboard unavailable; select and copy the redacted JSON below."; }
};
byId("status-refresh").onclick = status;
setInterval(() => { if (byId("auto").checked) refresh(); }, 5000);
refresh(); status();
