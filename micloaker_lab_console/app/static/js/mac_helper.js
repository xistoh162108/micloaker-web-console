async function helperGet(path, targetId) {
  const output = document.getElementById(targetId);
  const res = await fetch(path);
  const data = await res.json();
  output.textContent = JSON.stringify(data, null, 2);
  return data;
}

async function helperPost(path, targetId, formData) {
  const output = document.getElementById(targetId);
  const options = { method: "POST" };
  if (formData) options.body = formData;
  const res = await fetch(path, options);
  const data = await res.json();
  output.textContent = JSON.stringify(data, null, 2);
  return data;
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
