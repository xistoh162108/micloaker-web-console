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
const runPreviewUrl = document.querySelector("[data-run-preview-url]")?.dataset.runPreviewUrl || "";
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
  const payload = await res.json();
  if (!res.ok) {
    showStructuredAlert(payload.detail || payload, `Request failed (${res.status})`);
  }
  return payload;
}

function showStructuredAlert(detail, fallback) {
  let message = fallback || "Request failed";
  if (typeof detail === "string") {
    message = detail;
  } else if (detail) {
    const parts = [detail.error_code || detail.preview_error_code, detail.message || detail.preview_error, detail.suggestion].filter(Boolean);
    message = parts.join("\n\n") || message;
  }
  window.alert(message);
}

async function refresh() {
  const liveRes = await fetch("/live/snapshot");
  let data = await liveRes.json();
  const captureActive = Boolean(data.active_recording || data.finalization_job || data.recording_state === "Recording" || data.recording_state === "Finalizing");
  const liveHasSamples = Boolean(data.running && (data.waveform?.length || data.psd?.length || data.spectrogram?.length));
  if (runPreviewUrl && !captureActive && !liveHasSamples) {
    try {
      const runRes = await fetch(runPreviewUrl);
      if (runRes.ok) data = await runRes.json();
    } catch {
      // Keep the generic live snapshot when the run-specific preview cannot load.
    }
  }
  if (stateOutput) stateOutput.textContent = data.recording_state || "Stopped";
  if (finalizationOutput) finalizationOutput.textContent = data.finalization_status || data.preview_label || "";
  renderFinalRun(data);
  if (clippingOutput) clippingOutput.textContent = data.clipping ? "CLIPPING POSSIBLE" : "no clipping";
  if (logTailOutput) logTailOutput.textContent = compactLogTail(data.log_tail);
  if (levels) levels.innerHTML = metricReadoutHtml(data);
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
    drawLine(waveformCtx, waveformCanvas, data.waveform, "#0a8793", "auto", "V", data.preview_window_s || 0.25);
    drawCrosshair(waveformCtx, waveformCanvas, chartPointers.waveform);
  }
  if (psdCtx && data.psd) {
    drawLine(psdCtx, psdCanvas, data.psd.map(v => Math.log10(v + 1e-18)), "#2f5f93", "auto", "log PSD", Number(data.sample_rate_hz || 0) / 2);
    drawCrosshair(psdCtx, psdCanvas, chartPointers.psd);
  }
  if (specCtx && data.spectrogram) {
    drawSpectrogram(data.spectrogram, Number(data.sample_rate_hz || 0));
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
  const recommended = data.recommended_update_rates_hz || {};
  const state = data.recording_state || "Stopped";
  const recommendedPreviewMs = recommended.preview ? Math.max(100, Math.round(1000 / Number(recommended.preview))) : null;
  const nextInterval = (state === "Recording" || data.running) ? (intervals.preview || intervals.recording || recommendedPreviewMs || 200) : (intervals.idle || 1000);
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
  finalRunOutput.innerHTML = failed ? failedRunSummaryHtml(data, sessionId, runId) : finalRunSummaryHtml(data, sessionId, runId);
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

function metricReadoutHtml(data) {
  const rms = formatMetric(data.rms_v, " V");
  const peak = formatMetric(data.peak_v, " V");
  const rate = Number.isFinite(Number(data.sample_rate_hz)) ? `${Number(data.sample_rate_hz).toLocaleString()} Hz` : "n/a";
  const finalSource = data.final_metrics_source || ".bin";
  const clipping = data.clipping ? "check" : "clear";
  const waveformPoints = Number.isFinite(Number(data.waveform_point_count)) ? Number(data.waveform_point_count).toLocaleString() : "0";
  const psdBins = Number.isFinite(Number(data.psd_bin_count)) ? Number(data.psd_bin_count).toLocaleString() : "0";
  const spectrogramRows = Number.isFinite(Number(data.spectrogram_row_count)) ? Number(data.spectrogram_row_count).toLocaleString() : "0";
  return `
    <div class="metric-readout-grid">
      <div><span class="metric-label">RMS</span><strong>${rms}</strong></div>
      <div><span class="metric-label">Peak</span><strong>${peak}</strong></div>
      <div><span class="metric-label">Sample rate</span><strong>${rate}</strong></div>
      <div><span class="metric-label">Preview</span><strong>${escapeHtml(data.preview_source || "daq")}</strong></div>
      <div><span class="metric-label">Clipping</span><strong>${clipping}</strong></div>
      <div><span class="metric-label">Waveform pts</span><strong>${waveformPoints}</strong></div>
      <div><span class="metric-label">PSD bins</span><strong>${psdBins}</strong></div>
      <div><span class="metric-label">Spec rows</span><strong>${spectrogramRows}</strong></div>
      <div><span class="metric-label">Final source</span><strong>${escapeHtml(finalSource)}</strong></div>
    </div>
  `;
}

function finalRunSummaryHtml(data, sessionId, runId) {
  return `
    <div class="summary-grid">
      <div><span class="metric-label">Status</span><strong>finalized</strong></div>
      <div><span class="metric-label">Run</span><strong>${escapeHtml(runId)}</strong></div>
      <div><span class="metric-label">Grade</span><strong>${escapeHtml(data.final_result_grade || "report")}</strong></div>
      <div><span class="metric-label">Source</span><strong>${data.finalized_from_saved_bin ? "saved .bin" : "unknown"}</strong></div>
      <div><span class="metric-label">Samples</span><strong>${formatInteger(data.final_raw_sample_count)}</strong></div>
      <div><span class="metric-label">Raw</span><strong>${escapeHtml(data.final_bin_path || "n/a")}</strong></div>
    </div>
    <details><summary>Raw finalization fields</summary><pre class="scroll-pre">${escapeHtml(JSON.stringify({
      session_id: sessionId,
      run_id: runId,
      finalized_at: data.finalized_at,
      raw_bin_path: data.final_bin_path,
      wav_peak_path: data.final_wav_peak_path,
      wav_range_path: data.final_wav_range_path,
      plot_paths: data.final_plot_paths,
      raw_size_bytes: data.final_raw_size_bytes,
      raw_dtype: data.final_raw_dtype,
    }, null, 2))}</pre></details>
  `;
}

function failedRunSummaryHtml(data, _sessionId, runId) {
  return `
    <div class="summary-grid">
      <div><span class="metric-label">Status</span><strong>failed</strong></div>
      <div><span class="metric-label">Run</span><strong>${escapeHtml(runId)}</strong></div>
      <div><span class="metric-label">Error</span><strong>${escapeHtml(data.finalization_error || "unknown")}</strong></div>
      <div><span class="metric-label">Log</span><strong>${escapeHtml(data.finalization_error_log || "n/a")}</strong></div>
    </div>
  `;
}

function compactLogTail(lines) {
  if (!lines || !lines.length) return "No log entries yet.";
  return lines.slice(-8).join("\n");
}

function formatMetric(value, suffix = "") {
  const number = Number(value);
  if (!Number.isFinite(number)) return "n/a";
  return `${formatScientific(number, 5)}${suffix}`;
}

function formatInteger(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString() : "n/a";
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[char]);
}

function drawLine(ctx, canvas, points, color, mode, yLabel, xMax) {
  const width = resizeCanvasForDisplay(canvas);
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  if (!points.length) return;
  const plot = plotArea(width, height);
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.beginPath();
  const bounds = autoBounds(points, mode);
  const min = bounds.min;
  const max = bounds.max;
  const span = Math.max(1e-12, max - min);
  points.forEach((v, i) => {
    const x = plot.left + i * plot.width / Math.max(1, points.length - 1);
    const y = plot.top + (1 - ((v - min) / span)) * plot.height;
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();
  drawAxes(ctx, plot, { xMin: 0, xMax: Number(xMax || points.length - 1), yMin: min, yMax: max, yLabel });
}

function drawSpectrogram(rows, sampleRateHz) {
  if (!rows.length) return;
  const width = resizeCanvasForDisplay(specCanvas);
  const height = specCanvas.height;
  const plot = plotArea(width, height);
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
  specCtx.drawImage(spectrogramBufferCanvas, plot.left, plot.top, plot.width, plot.height);
  drawAxes(specCtx, plot, { xMin: 0, xMax: rows.length, yMin: 0, yMax: Number(sampleRateHz || 0) / 2, yLabel: "Hz" });
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

function autoBounds(points, mode) {
  const bounds = pointBounds(points);
  if (mode === "bipolar") return { min: -0.35, max: 0.35 };
  if (!Number.isFinite(bounds.min) || !Number.isFinite(bounds.max)) return { min: -1, max: 1 };
  const peak = Math.max(Math.abs(bounds.min), Math.abs(bounds.max));
  if (peak > 0 && bounds.min < 0 && bounds.max > 0) {
    const pad = peak * 0.12;
    return { min: -(peak + pad), max: peak + pad };
  }
  const span = Math.max(1e-12, bounds.max - bounds.min);
  return { min: bounds.min - span * 0.08, max: bounds.max + span * 0.08 };
}

function plotArea(width, height) {
  const scale = Math.min(window.devicePixelRatio || 1, 2);
  const left = 62 * scale;
  const right = 14 * scale;
  const top = 16 * scale;
  const bottom = 36 * scale;
  return { left, top, width: Math.max(1, width - left - right), height: Math.max(1, height - top - bottom), bottom: height - bottom, right: width - right };
}

function drawAxes(ctx, plot, { xMin, xMax, yMin, yMax, yLabel }) {
  ctx.save();
  ctx.strokeStyle = "rgba(89, 104, 102, 0.55)";
  ctx.fillStyle = "rgba(61, 76, 73, 0.88)";
  ctx.lineWidth = 1;
  ctx.font = `${Math.max(10, Math.round(11 * Math.min(window.devicePixelRatio || 1, 2)))}px IBM Plex Mono, monospace`;
  ctx.textBaseline = "middle";
  ctx.beginPath();
  ctx.moveTo(plot.left, plot.top);
  ctx.lineTo(plot.left, plot.top + plot.height);
  ctx.lineTo(plot.left + plot.width, plot.top + plot.height);
  ctx.stroke();
  for (let i = 0; i <= 4; i += 1) {
    const x = plot.left + (plot.width * i / 4);
    const y = plot.top + (plot.height * i / 4);
    ctx.strokeStyle = "rgba(178, 188, 185, 0.28)";
    ctx.beginPath();
    ctx.moveTo(x, plot.top);
    ctx.lineTo(x, plot.top + plot.height);
    ctx.moveTo(plot.left, y);
    ctx.lineTo(plot.left + plot.width, y);
    ctx.stroke();
    if (i > 0) {
      ctx.textAlign = "right";
      ctx.fillText(formatAxisValue(yMax - ((yMax - yMin) * i / 4)), plot.left - 8, y);
    }
    if (i % 2 === 0) {
      ctx.textAlign = i === 0 ? "left" : (i === 4 ? "right" : "center");
      ctx.textBaseline = "top";
      ctx.fillText(formatAxisValue(xMin + ((xMax - xMin) * i / 4)), x, plot.top + plot.height + 10);
      ctx.textBaseline = "middle";
    }
  }
  if (yLabel) {
    ctx.fillStyle = "rgba(23, 32, 31, 0.88)";
    ctx.textAlign = "left";
    ctx.textBaseline = "top";
    ctx.fillText(yLabel, plot.left + 6, plot.top + 4);
  }
  ctx.restore();
}

function formatAxisValue(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "";
  const abs = Math.abs(number);
  if (abs >= 1000) return `${Math.round(number / 1000)}k`;
  if (abs >= 10) return number.toFixed(0);
  if (abs >= 1) return number.toFixed(1);
  return number.toFixed(2);
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
    const source = button.dataset.liveSource || "daq";
    payload.set("source", source);
    payload.set("sample_rate_hz", button.dataset.liveSampleRate || "8000");
    payload.set("channel", button.dataset.liveChannel || "0");
    payload.set("input_mode", button.dataset.liveInputMode || "SINGLE_ENDED");
    payload.set("ai_range", button.dataset.liveAiRange || "BIP10VOLTS");
    const started = await post("/live/start", payload);
    if (source === "daq" && started.preview_error_code) {
      showStructuredAlert(started, "DAQ live preview is unavailable.");
    }
    await refresh();
  });
});
document.getElementById("live-stop")?.addEventListener("click", async () => {
  await post("/live/stop");
  await refresh();
});

refresh();
