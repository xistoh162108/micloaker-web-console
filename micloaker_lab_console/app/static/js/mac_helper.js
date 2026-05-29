async function helperGet(path, targetId) {
  const output = document.getElementById(targetId);
  try {
    const res = await fetch(path);
    const data = await res.json();
    renderHelperResult(output, data, res.ok);
    return data;
  } catch (error) {
    const data = { ok: false, error_code: "HELPER_REQUEST_FAILED", message: error?.message || String(error), suggestion: "Check the Helper URL and Tailscale/Mac Helper process, then retry." };
    renderHelperResult(output, data, false);
    return data;
  }
}

async function helperPost(path, targetId, formData) {
  const output = document.getElementById(targetId);
  const options = { method: "POST" };
  if (formData) options.body = formData;
  try {
    const res = await fetch(path, options);
    const data = await res.json();
    renderHelperResult(output, data, res.ok);
    return data;
  } catch (error) {
    const data = { ok: false, error_code: "HELPER_REQUEST_FAILED", message: error?.message || String(error), suggestion: "Check the Helper URL and Tailscale/Mac Helper process, then retry." };
    renderHelperResult(output, data, false);
    return data;
  }
}

function renderHelperResult(output, data, httpOk) {
  if (output) output.textContent = helperSummary(data);
  if (!httpOk || data?.ok === false || data?.error_code || data?.detail?.error_code) {
    window.alert(helperAlertMessage(data));
  }
}

function helperSummary(data) {
  if (!data) return "No response.";
  const detail = data.detail || data;
  const lines = [];
  if (detail.ok !== undefined) lines.push(`Status: ${detail.ok ? "OK" : "Failed"}`);
  if (detail.connected !== undefined) lines.push(`Connected: ${detail.connected ? "yes" : "no"}`);
  if (detail.playing !== undefined) lines.push(`Playing: ${detail.playing ? "yes" : "no"}`);
  if (detail.hostname) lines.push(`Host: ${detail.hostname}`);
  if (detail.service) lines.push(`Service: ${detail.service}`);
  if (detail.message) lines.push(`Message: ${detail.message}`);
  if (detail.suggestion) lines.push(`Suggestion: ${detail.suggestion}`);
  if (Array.isArray(detail.output_devices)) lines.push(`Output devices: ${detail.output_devices.length}`);
  if (Array.isArray(detail.files)) lines.push(`Files: ${detail.files.length}`);
  if (detail.file) lines.push(`File: ${detail.file}`);
  if (detail.device_id !== undefined) lines.push(`Device ID: ${detail.device_id}`);
  if (detail.sample_rate !== undefined) lines.push(`Sample rate: ${detail.sample_rate}`);
  if (detail.play_id) lines.push(`Play ID: ${detail.play_id}`);
  return lines.length ? lines.join("\n") : JSON.stringify(data, null, 2);
}

function helperAlertMessage(data) {
  const detail = data?.detail || data || {};
  const parts = [detail.error_code, detail.message, detail.suggestion].filter(Boolean);
  return parts.join("\n\n") || "Mac Helper request failed.";
}

function setOptions(selectId, rows, valueKey, labelFn) {
  const select = document.getElementById(selectId);
  if (!select) return;
  select.innerHTML = "";
  for (const row of rows || []) {
    const option = document.createElement("option");
    option.value = row[valueKey];
    option.textContent = labelFn(row);
    select.appendChild(option);
  }
}

function playbackFormData(includeDelay) {
  const form = document.getElementById("helper-playback-form");
  const data = new FormData(form);
  const fileSelect = document.getElementById("helper-file-select");
  const deviceSelect = document.getElementById("helper-device-select");
  const rateSelect = document.getElementById("helper-sample-rate");
  const customRate = document.getElementById("helper-custom-sample-rate");
  data.set("file", fileSelect?.value || "");
  data.set("device_id", deviceSelect?.value || "");
  data.set("sample_rate", rateSelect?.value === "custom" ? customRate?.value || "" : rateSelect?.value || "");
  if (!includeDelay) data.delete("delay_ms");
  return data;
}

document.getElementById("helper-health")?.addEventListener("click", () => helperGet("/mac-helper/health", "helper-connection-output"));
document.getElementById("helper-discover")?.addEventListener("click", () => helperGet("/mac-helper/discover", "helper-connection-output"));
document.getElementById("helper-devices")?.addEventListener("click", async () => {
  const data = await helperGet("/mac-helper/devices", "helper-devices-output");
  setOptions("helper-device-select", data.output_devices || [], "id", (row) => `${row.id}: ${row.name} (${row.max_output_channels} ch, ${row.default_samplerate} Hz)`);
});
document.getElementById("helper-files")?.addEventListener("click", async () => {
  const data = await helperGet("/mac-helper/files", "helper-files-output");
  setOptions("helper-file-select", data.files || [], "path", (row) => `${row.path} (${row.sample_rate || "?"} Hz)`);
});
document.getElementById("helper-validate")?.addEventListener("click", () => helperPost("/mac-helper/validate-playback", "helper-playback-output", playbackFormData(false)));
document.getElementById("helper-play")?.addEventListener("click", () => helperPost("/mac-helper/play", "helper-playback-output", playbackFormData(true)));
document.getElementById("helper-status")?.addEventListener("click", () => helperGet("/mac-helper/status", "helper-status-output"));
document.getElementById("helper-stop")?.addEventListener("click", () => helperPost("/mac-helper/stop", "helper-status-output"));
