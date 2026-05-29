const levels = document.getElementById("live-levels");
const stateOutput = document.getElementById("live-state");
const finalizationOutput = document.getElementById("live-finalization");
const finalRunOutput = document.getElementById("live-final-run");
const finalRunLink = document.getElementById("live-final-run-link");
const finalMetricsLink = document.getElementById("live-final-metrics-link");
const finalLogLink = document.getElementById("live-final-log-link");
const clippingOutput = document.getElementById("live-clipping");
const logTailOutput = document.getElementById("live-log-tail");
const waveformCanvas = document.getElementById("live-waveform");
const waveformCtx = waveformCanvas ? waveformCanvas.getContext("2d") : null;
const psdCanvas = document.getElementById("live-psd");
const psdCtx = psdCanvas ? psdCanvas.getContext("2d") : null;
const specCanvas = document.getElementById("live-spectrogram");
const specCtx = specCanvas ? specCanvas.getContext("2d") : null;
const spectrogramBufferCanvas = document.createElement("canvas");
const spectrogramBufferCtx = spectrogramBufferCanvas.getContext("2d");
const recordingGuardMessage = document.getElementById("recording-guard-message");
let timer = null;
let currentIntervalMs = null;
let pendingChartFrame = false;
let latestChartData = null;

async function post(url, data) {
  const options = { method: "POST" };
  if (data) options.body = data;
  const res = await fetch(url, options);
  return res.json();
}

async function refresh() {
  const res = await fetch("/live/snapshot");
  const data = await res.json();
  if (stateOutput) stateOutput.textContent = data.recording_state || "Stopped";
  if (finalizationOutput) finalizationOutput.textContent = data.finalization_status || data.preview_label || "";
  renderFinalRun(data);
  if (clippingOutput) clippingOutput.textContent = data.clipping ? "CLIPPING POSSIBLE" : "no clipping";
  if (logTailOutput) logTailOutput.textContent = (data.log_tail && data.log_tail.length) ? data.log_tail.join("\n") : "No log entries yet.";
  if (levels) levels.textContent = JSON.stringify({
    rms_v: data.rms_v,
    peak_v: data.peak_v,
    sample_rate_hz: data.sample_rate_hz,
    preview_source: data.preview_source,
    preview_saved: data.preview_saved,
    final_metrics_source: data.final_metrics_source,
    waveform_points: data.waveform_point_count,
    psd_bins: data.psd_bin_count,
    spectrogram_rows: data.spectrogram_row_count,
    recommended_update_rates_hz: data.recommended_update_rates_hz,
    payload_limits: data.payload_limits,
    preview: data.preview_label,
  }, null, 2);
  scheduleChartRender(data);
  updateRecordingGuard(data);
  scheduleRefresh(data);
}

function scheduleChartRender(data) {
  latestChartData = data;
  if (pendingChartFrame) return;
  pendingChartFrame = true;
  requestAnimationFrame(renderCharts);
}

function renderCharts() {
  pendingChartFrame = false;
  const data = latestChartData || {};
  if (waveformCtx && data.waveform) drawLine(waveformCtx, waveformCanvas, data.waveform, "#245b63", "bipolar");
  if (psdCtx && data.psd) drawLine(psdCtx, psdCanvas, data.psd.map(v => Math.log10(v + 1e-18)), "#6b4e16", "auto");
  if (specCtx && data.spectrogram) drawSpectrogram(data.spectrogram);
}

function updateRecordingGuard(data) {
  const locked = Boolean(data.active_recording || data.finalization_job || data.recording_state === "Recording" || data.recording_state === "Finalizing");
  document.querySelectorAll("[data-recording-submit]").forEach((button) => {
    button.disabled = locked;
  });
  document.querySelectorAll("[data-live-start]").forEach((button) => {
    const isDaqPreview = button.dataset.liveSource === "daq";
    button.disabled = isDaqPreview && Boolean(data.active_recording || data.recording_state === "Recording");
  });
  if (recordingGuardMessage) {
    recordingGuardMessage.hidden = !locked;
    recordingGuardMessage.textContent = locked ? "Recording/finalization is active. Wait before starting another capture." : "";
  }
}

function scheduleRefresh(data) {
  const intervals = data.client_poll_intervals_ms || {};
  const state = data.recording_state || "Stopped";
  const nextInterval = (state === "Recording" || data.running) ? (intervals.preview || intervals.recording || 200) : (intervals.idle || 1000);
  if (timer && currentIntervalMs === nextInterval) return;
  if (timer) clearInterval(timer);
  timer = setInterval(refresh, nextInterval);
  currentIntervalMs = nextInterval;
}

function renderFinalRun(data) {
  if (!finalRunOutput) return;
  const sessionId = data.final_session_id || data.failed_session_id;
  const runId = data.final_run_id || data.failed_run_id;
  if (!runId || !sessionId) {
    finalRunOutput.textContent = "none";
    if (finalRunLink) finalRunLink.hidden = true;
    if (finalMetricsLink) finalMetricsLink.hidden = true;
    if (finalLogLink) finalLogLink.hidden = true;
    return;
  }
  const failed = Boolean(data.failed_run_id);
  const payload = failed ? {
    session_id: sessionId,
    run_id: runId,
    status: "failed",
    failed_at: data.failed_at,
    error: data.finalization_error,
    error_log: data.finalization_error_log,
  } : {
    session_id: sessionId,
    run_id: runId,
    status: "finalized",
    finalized_at: data.finalized_at,
    result_grade: data.final_result_grade,
    finalized_from_saved_bin: data.finalized_from_saved_bin,
    raw_bin_path: data.final_bin_path,
    wav_peak_path: data.final_wav_peak_path,
    wav_range_path: data.final_wav_range_path,
    plot_paths: data.final_plot_paths,
    raw_sample_count: data.final_raw_sample_count,
    raw_size_bytes: data.final_raw_size_bytes,
    raw_dtype: data.final_raw_dtype,
  };
  finalRunOutput.textContent = JSON.stringify(payload, null, 2);
  if (finalRunLink) {
    finalRunLink.href = `/sessions/${sessionId}/runs/${runId}`;
    finalRunLink.hidden = false;
  }
  if (finalMetricsLink && data.final_metrics_path) {
    finalMetricsLink.href = `/sessions/${sessionId}/files/${data.final_metrics_path}?download=1`;
    finalMetricsLink.hidden = false;
  } else if (finalMetricsLink) {
    finalMetricsLink.hidden = true;
  }
  const logPath = data.final_log_path || data.finalization_error_log;
  if (finalLogLink && logPath) {
    finalLogLink.href = `/sessions/${sessionId}/files/${logPath}`;
    finalLogLink.hidden = false;
  } else if (finalLogLink) {
    finalLogLink.hidden = true;
  }
}

function drawLine(ctx, canvas, points, color, mode) {
  const width = resizeCanvasForDisplay(canvas);
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.beginPath();
  const bounds = mode === "bipolar" ? { min: -0.35, max: 0.35 } : pointBounds(points);
  const min = bounds.min;
  const max = bounds.max;
  const span = Math.max(1e-12, max - min);
  points.forEach((v, i) => {
    const x = i * width / Math.max(1, points.length - 1);
    const y = height - ((v - min) / span) * height;
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

function drawSpectrogram(rows) {
  if (!rows.length) return;
  const width = resizeCanvasForDisplay(specCanvas);
  const height = specCanvas.height;
  const cols = rows.length;
  const bins = rows[0].length;
  spectrogramBufferCanvas.width = cols;
  spectrogramBufferCanvas.height = bins;
  const image = spectrogramBufferCtx.createImageData(cols, bins);
  const data = image.data;
  const bounds = nestedBounds(rows);
  const span = Math.max(1e-12, bounds.max - bounds.min);
  for (let x = 0; x < cols; x += 1) {
    const row = rows[x];
    for (let y = 0; y < bins; y += 1) {
      const yIdx = bins - 1 - y;
      const norm = Math.max(0, Math.min(1, (row[yIdx] - bounds.min) / span));
      const offset = (y * cols + x) * 4;
      data[offset] = 24 + Math.floor(norm * 220);
      data[offset + 1] = 76 + Math.floor(norm * 120);
      data[offset + 2] = 92 + Math.floor((1 - norm) * 120);
      data[offset + 3] = 255;
    }
  }
  spectrogramBufferCtx.putImageData(image, 0, 0);
  specCtx.imageSmoothingEnabled = false;
  specCtx.clearRect(0, 0, width, height);
  specCtx.drawImage(spectrogramBufferCanvas, 0, 0, width, height);
}

function resizeCanvasForDisplay(canvas) {
  const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
  const cssWidth = Math.max(1, Math.floor(canvas.clientWidth || canvas.width));
  const cssHeight = Math.max(1, Math.floor(canvas.clientHeight || canvas.height));
  const width = Math.floor(cssWidth * pixelRatio);
  const height = Math.floor(cssHeight * pixelRatio);
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  return width;
}

function pointBounds(points) {
  let min = Infinity;
  let max = -Infinity;
  points.forEach((v) => {
    if (v < min) min = v;
    if (v > max) max = v;
  });
  return { min, max };
}

function nestedBounds(rows) {
  let min = Infinity;
  let max = -Infinity;
  rows.forEach((row) => {
    row.forEach((v) => {
      if (v < min) min = v;
      if (v > max) max = v;
    });
  });
  return { min, max };
}

document.querySelectorAll("[data-live-start]").forEach((button) => {
  button.addEventListener("click", async () => {
    const payload = new FormData();
    payload.set("source", button.dataset.liveSource || "mock");
    payload.set("sample_rate_hz", button.dataset.liveSampleRate || "8000");
    payload.set("channel", button.dataset.liveChannel || "0");
    payload.set("input_mode", button.dataset.liveInputMode || "SINGLE_ENDED");
    payload.set("ai_range", button.dataset.liveAiRange || "BIP10VOLTS");
    await post("/live/start", payload);
    await refresh();
  });
});
document.getElementById("live-stop")?.addEventListener("click", async () => {
  await post("/live/stop");
  await refresh();
});

refresh();
