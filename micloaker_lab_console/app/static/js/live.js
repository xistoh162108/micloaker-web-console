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
const waveformReadout = document.getElementById("live-waveform-readout");
const psdCanvas = document.getElementById("live-psd");
const psdCtx = psdCanvas ? psdCanvas.getContext("2d") : null;
const psdReadout = document.getElementById("live-psd-readout");
const specCanvas = document.getElementById("live-spectrogram");
const specCtx = specCanvas ? specCanvas.getContext("2d") : null;
const specReadout = document.getElementById("live-spectrogram-readout");
const spectrogramBufferCanvas = document.createElement("canvas");
const spectrogramBufferCtx = spectrogramBufferCanvas.getContext("2d");
const recordingGuardMessage = document.getElementById("recording-guard-message");
let timer = null;
let currentIntervalMs = null;
let pendingChartFrame = false;
let latestChartData = null;
let cachedSpectrogramImage = null;
let cachedSpectrogramCols = 0;
let cachedSpectrogramBins = 0;
const chartPointers = {
  waveform: null,
  psd: null,
  spectrogram: null,
};

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
  if (waveformCtx && data.waveform) {
    drawLine(waveformCtx, waveformCanvas, data.waveform, "#0a8793", "bipolar");
    drawCrosshair(waveformCtx, waveformCanvas, chartPointers.waveform);
  }
  if (psdCtx && data.psd) {
    drawLine(psdCtx, psdCanvas, data.psd.map(v => Math.log10(v + 1e-18)), "#2f5f93", "auto");
    drawCrosshair(psdCtx, psdCanvas, chartPointers.psd);
  }
  if (specCtx && data.spectrogram) {
    drawSpectrogram(data.spectrogram);
    drawCrosshair(specCtx, specCanvas, chartPointers.spectrogram);
  }
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
  if (!points.length) return;
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
  const image = spectrogramImage(cols, bins);
  const data = image.data;
  const bounds = nestedBounds(rows);
  const span = Math.max(1e-12, bounds.max - bounds.min);
  for (let x = 0; x < cols; x += 1) {
    const row = rows[x];
    for (let y = 0; y < bins; y += 1) {
      const yIdx = bins - 1 - y;
      const norm = Math.max(0, Math.min(1, (row[yIdx] - bounds.min) / span));
      const offset = (y * cols + x) * 4;
      data[offset] = 18 + Math.floor(norm * 214);
      data[offset + 1] = 52 + Math.floor(norm * 154);
      data[offset + 2] = 76 + Math.floor((1 - norm) * 110);
      data[offset + 3] = 255;
    }
  }
  spectrogramBufferCtx.putImageData(image, 0, 0);
  specCtx.imageSmoothingEnabled = false;
  specCtx.clearRect(0, 0, width, height);
  specCtx.drawImage(spectrogramBufferCanvas, 0, 0, width, height);
}

function drawCrosshair(ctx, canvas, pointer) {
  if (!pointer) return;
  const x = pointer.xNorm * canvas.width;
  const y = pointer.yNorm * canvas.height;
  ctx.save();
  ctx.strokeStyle = "rgba(11, 111, 121, 0.72)";
  ctx.lineWidth = Math.max(1, Math.round((window.devicePixelRatio || 1)));
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(x, 0);
  ctx.lineTo(x, canvas.height);
  ctx.moveTo(0, y);
  ctx.lineTo(canvas.width, y);
  ctx.stroke();
  ctx.restore();
}

function spectrogramImage(cols, bins) {
  if (cachedSpectrogramImage && cachedSpectrogramCols === cols && cachedSpectrogramBins === bins) {
    return cachedSpectrogramImage;
  }
  cachedSpectrogramCols = cols;
  cachedSpectrogramBins = bins;
  spectrogramBufferCanvas.width = cols;
  spectrogramBufferCanvas.height = bins;
  cachedSpectrogramImage = spectrogramBufferCtx.createImageData(cols, bins);
  return cachedSpectrogramImage;
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
  for (let i = 0; i < points.length; i += 1) {
    const v = points[i];
    if (v < min) min = v;
    if (v > max) max = v;
  }
  return { min, max };
}

function nestedBounds(rows) {
  let min = Infinity;
  let max = -Infinity;
  for (let r = 0; r < rows.length; r += 1) {
    const row = rows[r];
    for (let c = 0; c < row.length; c += 1) {
      const v = row[c];
      if (v < min) min = v;
      if (v > max) max = v;
    }
  }
  return { min, max };
}

function bindChartReadout(canvas, readout, key, formatter) {
  if (!canvas || !readout) return;
  canvas.addEventListener("pointermove", (event) => {
    const rect = canvas.getBoundingClientRect();
    const xNorm = Math.max(0, Math.min(1, (event.clientX - rect.left) / Math.max(1, rect.width)));
    const yNorm = Math.max(0, Math.min(1, (event.clientY - rect.top) / Math.max(1, rect.height)));
    chartPointers[key] = { xNorm, yNorm };
    readout.textContent = formatter(xNorm, yNorm, latestChartData || {});
    scheduleChartRender(latestChartData || {});
  });
  canvas.addEventListener("pointerleave", () => {
    chartPointers[key] = null;
    readout.textContent = readout.dataset.defaultLabel || readout.textContent;
    scheduleChartRender(latestChartData || {});
  });
  readout.dataset.defaultLabel = readout.textContent;
}

function formatScientific(value, digits = 3) {
  if (!Number.isFinite(value)) return "n/a";
  const absValue = Math.abs(value);
  if (absValue !== 0 && (absValue < 0.001 || absValue >= 10000)) return value.toExponential(2);
  return value.toFixed(digits);
}

function waveformReadoutText(xNorm, _yNorm, data) {
  const points = data.waveform || [];
  if (!points.length) return "waveform: no preview samples";
  const idx = Math.round(xNorm * (points.length - 1));
  const previewSeconds = Number(data.preview_window_s || 0.25);
  const t = xNorm * previewSeconds;
  return `waveform t~${formatScientific(t, 4)} s | sample ${idx + 1}/${points.length} | V ${formatScientific(points[idx], 5)}`;
}

function psdReadoutText(xNorm, _yNorm, data) {
  const values = data.psd || [];
  if (!values.length) return "PSD: no preview bins";
  const idx = Math.round(xNorm * (values.length - 1));
  const freqs = data.psd_freq_hz || [];
  const hz = Number.isFinite(freqs[idx]) ? freqs[idx] : xNorm * Number(data.sample_rate_hz || 0) / 2;
  const logPower = Math.log10(values[idx] + 1e-18);
  return `PSD ${formatScientific(hz, 1)} Hz | bin ${idx + 1}/${values.length} | log10 ${formatScientific(logPower, 4)}`;
}

function spectrogramReadoutText(xNorm, yNorm, data) {
  const rows = data.spectrogram || [];
  if (!rows.length || !rows[0].length) return "spectrogram: no preview rows";
  const rowIdx = Math.round(xNorm * (rows.length - 1));
  const bins = rows[rowIdx].length;
  const binIdx = Math.round((1 - yNorm) * (bins - 1));
  const hz = bins > 1 ? (binIdx / (bins - 1)) * Number(data.sample_rate_hz || 0) / 2 : 0;
  return `spectrogram row ${rowIdx + 1}/${rows.length} | ${formatScientific(hz, 1)} Hz | value ${formatScientific(rows[rowIdx][binIdx], 4)}`;
}

bindChartReadout(waveformCanvas, waveformReadout, "waveform", waveformReadoutText);
bindChartReadout(psdCanvas, psdReadout, "psd", psdReadoutText);
bindChartReadout(specCanvas, specReadout, "spectrogram", spectrogramReadoutText);

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
