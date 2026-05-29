document.querySelectorAll("[data-copy-target]").forEach((button) => {
  button.addEventListener("click", async () => {
    const target = document.getElementById(button.dataset.copyTarget);
    if (!target) return;
    await navigator.clipboard.writeText(target.textContent || "");
    const original = button.textContent;
    button.textContent = "Copied";
    setTimeout(() => {
      button.textContent = original;
    }, 1200);
  });
});

document.querySelectorAll("[data-tabs]").forEach((tabs) => {
  const buttons = Array.from(tabs.querySelectorAll("[data-tab-target]"));
  const panels = Array.from(tabs.querySelectorAll(".tab-panel"));
  buttons.forEach((button) => {
    button.addEventListener("click", () => {
      const target = button.dataset.tabTarget;
      buttons.forEach((item) => {
        item.classList.toggle("active", item === button);
        item.classList.toggle("tab-active", item === button);
      });
      panels.forEach((panel) => panel.classList.toggle("active", panel.id === target));
    });
  });
});

document.querySelectorAll("[data-filter-input]").forEach((input) => {
  const target = document.querySelector(input.dataset.filterTarget || "");
  if (!target) return;
  const items = Array.from(target.querySelectorAll("[data-filter-item]"));
  input.addEventListener("input", () => {
    const needle = input.value.trim().toLowerCase();
    items.forEach((item) => {
      const haystack = String(item.dataset.filterItem || item.textContent || "").toLowerCase();
      item.hidden = Boolean(needle) && !haystack.includes(needle);
    });
  });
});

document.querySelectorAll("[data-open-selected-run]").forEach((button) => {
  button.addEventListener("click", () => {
    const select = button.closest(".card-body")?.querySelector("[data-existing-run-select]");
    if (select?.value) window.location.href = select.value;
  });
});

document.querySelectorAll("[data-run-helper-form]").forEach((form) => {
  const sessionTarget = form.querySelector("[data-session-target]");
  const target = form.querySelector("[data-run-target]");
  if (!target) return;
  const runOptions = Array.from(target.options);
  const actionButtons = Array.from(form.querySelectorAll("[data-helper-action]"));
  const routeSuffix = {
    "Validate Playback": "validate-playback",
    Play: "play",
    "Stop Playback": "stop",
    "Play & Dev Capture": "play-and-capture-mock",
    "Play & Capture DAQ": "play-and-capture-daq",
    "Play & Dev Record": "play-and-record-mock",
    "Play & Record DAQ": "play-and-record-daq",
  };
  const updateRunActions = () => {
    const [sessionId, runId] = String(target.value || "").split("|");
    if (!sessionId || !runId) return;
    actionButtons.forEach((button) => {
      const suffix = routeSuffix[button.dataset.helperAction];
      if (suffix) button.setAttribute("formaction", `/mac-helper/sessions/${sessionId}/runs/${runId}/${suffix}`);
    });
    form.setAttribute("action", `/mac-helper/sessions/${sessionId}/runs/${runId}/validate-playback`);
  };
  const updateRunChoices = () => {
    if (!sessionTarget) return;
    const sessionId = sessionTarget.value;
    let firstVisible = null;
    runOptions.forEach((option) => {
      const visible = option.dataset.sessionId === sessionId;
      option.hidden = !visible;
      option.disabled = !visible;
      if (visible && !firstVisible) firstVisible = option;
    });
    if (target.selectedOptions[0]?.disabled && firstVisible) {
      target.value = firstVisible.value;
    }
    updateRunActions();
  };
  sessionTarget?.addEventListener("change", updateRunChoices);
  target.addEventListener("change", updateRunActions);
  updateRunChoices();
});

document.querySelectorAll("[data-async-helper-form]").forEach((form) => {
  const output = document.createElement("div");
  output.className = "metric-readout helper-inline-result";
  output.textContent = "Mac playback settings are kept on this page after validate/play.";
  form.appendChild(output);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submitter = event.submitter;
    const action = submitter?.getAttribute("formaction") || form.getAttribute("action") || window.location.href;
    const body = new FormData(form);
    const buttons = Array.from(form.querySelectorAll('button[type="submit"]'));
    buttons.forEach((button) => {
      button.disabled = true;
    });
    try {
      const response = await fetch(action, {
        method: "POST",
        body,
        headers: { Accept: "application/json" },
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.ok === false || data.detail?.error_code || data.error_code) {
        const detail = data.detail || data;
        output.textContent = structuredMessage(detail, `Mac Helper request failed (${response.status})`);
        window.alert(output.textContent);
        return;
      }
      const label = submitter?.dataset.helperAction || submitter?.textContent?.trim() || "Mac Helper action";
      output.textContent = `${label}: ${helperPlaybackText(data).title}`;
      document.querySelectorAll("[data-helper-playback-status]").forEach((panel) => renderHelperPlaybackStatus(panel, data));
    } catch (error) {
      output.textContent = `Network or server error: ${error?.message || error}`;
      window.alert(output.textContent);
    } finally {
      buttons.forEach((button) => {
        button.disabled = false;
      });
    }
  });
});

document.querySelectorAll("form").forEach((form) => {
  const method = (form.getAttribute("method") || "get").toLowerCase();
  if (method !== "post" || form.dataset.nativeSubmit === "true" || form.dataset.asyncHelperForm !== undefined) return;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submitter = event.submitter;
    const action = submitter?.getAttribute("formaction") || form.getAttribute("action") || window.location.href;
    const formMethod = (submitter?.getAttribute("formmethod") || method).toUpperCase();
    const body = new FormData(form);
    if (submitter?.name) {
      body.append(submitter.name, submitter.value || "");
    }
    const buttons = Array.from(form.querySelectorAll('button[type="submit"], input[type="submit"]'));
    buttons.forEach((button) => {
      button.disabled = true;
    });
    try {
      const response = await fetch(action, {
        method: formMethod,
        body,
        headers: { Accept: "application/json, text/html;q=0.9" },
      });
      if (response.ok) {
        window.location.href = response.redirected ? response.url : window.location.href;
        return;
      }
      let message = `Request failed (${response.status})`;
      try {
        const data = await response.json();
        const detail = data.detail || data;
        if (typeof detail === "string") {
          message = detail;
        } else {
          const parts = [detail.error_code, detail.message, detail.suggestion].filter(Boolean);
          message = parts.join("\n\n") || message;
        }
      } catch {
        const text = await response.text();
        if (text.trim()) message = text.trim().slice(0, 800);
      }
      window.alert(message);
    } catch (error) {
      window.alert(`Network or server error.\n\n${error?.message || error}`);
    } finally {
      buttons.forEach((button) => {
        button.disabled = false;
      });
    }
  });
});

document.querySelectorAll('form[action="/ops/validation"]').forEach((form) => {
  const gate = form.querySelector('select[name="gate"]');
  const evidence = form.querySelector('textarea[name="evidence"]');
  const preview = form.querySelector("#validation-checklist-preview");
  const draftButton = form.querySelector("#validation-draft-button");
  if (!gate || !evidence || !preview) return;
  let currentChecklist = [];
  const updateValidationHint = () => {
    const selected = gate.options[gate.selectedIndex];
    const checklist = selected?.dataset.checklist || "";
    const hint = selected?.dataset.hint || "";
    currentChecklist = checklist.split(";").map((item) => item.trim()).filter(Boolean);
    preview.value = checklist ? `Checklist fields: ${checklist}` : "";
    evidence.placeholder = hint ? `${hint} Checklist fields: ${checklist}` : evidence.placeholder;
  };
  draftButton?.addEventListener("click", () => {
    evidence.value = currentChecklist.map((item) => `${item}: `).join("\n");
    evidence.focus();
  });
  gate.addEventListener("change", updateValidationHint);
  updateValidationHint();
});

function structuredMessage(detail, fallback) {
  let message = fallback || "Request failed";
  if (typeof detail === "string") {
    message = detail;
  } else if (detail) {
    const parts = [detail.error_code, detail.message, detail.suggestion].filter(Boolean);
    message = parts.join("\n\n") || message;
  }
  return message;
}

document.querySelectorAll("[data-daq-health-alert]").forEach((button) => {
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      const response = await fetch("/daq/health", { headers: { Accept: "application/json" } });
      const data = await response.json();
      const message = data.available
        ? `DAQ ready\n\nBackend: ${data.backend || "unknown"}\n${data.message || ""}`.trim()
        : structuredMessage(
            {
              error_code: data.error_code || "DAQ_UNAVAILABLE",
              message: data.message || "DAQ hardware or driver is not available.",
              suggestion: "Connect/configure DAQ hardware before real recording, or import a saved raw .bin file.",
            },
            "DAQ unavailable",
          );
      window.alert(message);
    } catch (error) {
      window.alert(`DAQ health check failed.\n\n${error?.message || error}`);
    } finally {
      button.disabled = false;
    }
  });
});

document.querySelectorAll("[data-run-stop-all]").forEach((button) => {
  button.addEventListener("click", async () => {
    button.disabled = true;
    document.getElementById("live-stop")?.click();
    const messages = ["Live preview stopped."];
    try {
      const response = await fetch(button.dataset.helperStopUrl || "/mac-helper/stop", {
        method: "POST",
        body: new FormData(),
        headers: { Accept: "application/json" },
      });
      const data = await response.json().catch(() => ({}));
      messages.push(response.ok && data.ok !== false ? "Mac playback stop requested." : structuredMessage(data.detail || data, "Mac playback stop request failed."));
    } catch (error) {
      messages.push(`Mac playback stop request failed: ${error?.message || error}`);
    }
    try {
      const status = await fetch("/recording/status", { headers: { Accept: "application/json" } }).then((response) => response.json());
      if (status.active) {
        messages.push("DAQ recording/finalization is already running and cannot be interrupted safely from the browser; wait for the current run to finish.");
      }
    } catch {
      messages.push("Recording status could not be checked.");
    }
    window.alert(messages.join("\n"));
    button.disabled = false;
  });
});

document.querySelectorAll("[data-run-duration]").forEach((timer) => {
  const output = timer.querySelector("[data-run-countdown]");
  if (!output) return;
  const duration = Number(timer.dataset.runDuration || 0);
  const renderIdle = () => {
    output.textContent = Number.isFinite(duration) && duration > 0 ? `will stop after ${duration.toFixed(2)} s` : "duration not set";
  };
  const update = async () => {
    try {
      const status = await fetch("/recording/status", { headers: { Accept: "application/json" } }).then((response) => response.json());
      const startedAt = status.recording?.started_at;
      if (!status.active || !startedAt || !Number.isFinite(duration) || duration <= 0) {
        renderIdle();
        return;
      }
      const elapsed = Math.max(0, (Date.now() - Date.parse(startedAt)) / 1000);
      const remaining = Math.max(0, duration - elapsed);
      output.textContent = `${remaining.toFixed(1)} s remaining`;
    } catch {
      renderIdle();
    }
  };
  renderIdle();
  update();
  setInterval(update, 1000);
});

function helperPlaybackText(data) {
  const detail = data?.detail || data || {};
  if (detail.connected === false || detail.error_code === "HELPER_DISCONNECTED") {
    return {
      ok: false,
      playing: false,
      title: "Mac Helper disconnected",
      detail: detail.message || "Start Helper on the Mac or use Linux-only recording.",
    };
  }
  const playing = detail.playing === true;
  const file = detail.file || "no file";
  const playId = detail.current_play_id || detail.play_id || "";
  const elapsed = Number(detail.elapsed_s || 0);
  const duration = Number(detail.expected_end_after_s || detail.duration_s || 0);
  const remaining = playing && Number.isFinite(duration) && duration > 0 ? Math.max(0, duration - elapsed) : null;
  if (playing) {
    return {
      ok: true,
      playing: true,
      title: `Playing: ${file}`,
      detail: [
        playId ? `play id ${playId}` : "",
        Number.isFinite(elapsed) ? `${elapsed.toFixed(1)} s elapsed` : "",
        remaining !== null ? `${remaining.toFixed(1)} s remaining` : "",
        detail.sample_rate ? `${detail.sample_rate} Hz` : "",
        detail.device_id !== undefined ? `device ${detail.device_id}` : "",
      ].filter(Boolean).join(" / "),
    };
  }
  return {
    ok: true,
    playing: false,
    title: "Playback stopped",
    detail: detail.last_error ? `${detail.last_error_code || "Helper error"}: ${detail.last_error}` : "No active Mac playback.",
  };
}

function renderHelperPlaybackStatus(panel, data) {
  const badge = panel.querySelector("[data-helper-playing-badge]");
  const title = panel.querySelector("[data-helper-playing-title]");
  const detail = panel.querySelector("[data-helper-playing-detail]");
  const text = helperPlaybackText(data);
  if (badge) {
    badge.textContent = text.playing ? "Playing" : (text.ok ? "Stopped" : "Disconnected");
    badge.classList.toggle("badge-success", text.playing);
    badge.classList.toggle("badge-warning", !text.playing && text.ok);
    badge.classList.toggle("badge-error", !text.ok);
  }
  if (title) title.textContent = text.title;
  if (detail) detail.textContent = text.detail;
}

document.querySelectorAll("[data-helper-playback-status]").forEach((panel) => {
  const url = panel.dataset.helperStatusUrl || "/mac-helper/status";
  const update = async () => {
    try {
      const response = await fetch(url, { headers: { Accept: "application/json" } });
      const data = await response.json();
      renderHelperPlaybackStatus(panel, data);
    } catch (error) {
      renderHelperPlaybackStatus(panel, {
        connected: false,
        error_code: "HELPER_STATUS_FAILED",
        message: error?.message || String(error),
      });
    }
  };
  update();
  setInterval(update, 1000);
});

const plotDialog = document.createElement("div");
plotDialog.className = "plot-modal";
plotDialog.hidden = true;
plotDialog.innerHTML = `
  <div class="plot-modal-bar">
    <a class="btn btn-outline" href="#" target="_blank" rel="noopener">Open image</a>
    <button type="button" class="btn btn-outline" data-plot-close>Close</button>
  </div>
  <div class="plot-modal-stage"><img alt="Expanded plot"></div>
`;
document.body.appendChild(plotDialog);
const plotDialogImage = plotDialog.querySelector("img");
const plotDialogLink = plotDialog.querySelector("a");
const closePlotDialog = () => {
  plotDialog.hidden = true;
  plotDialogImage.removeAttribute("src");
};
document.querySelectorAll("[data-plot-zoom]").forEach((button) => {
  button.addEventListener("click", () => {
    const src = button.dataset.plotZoom;
    if (!src) return;
    plotDialogImage.src = src;
    plotDialogLink.href = src;
    plotDialog.hidden = false;
  });
});
plotDialog.querySelector("[data-plot-close]")?.addEventListener("click", closePlotDialog);
plotDialog.addEventListener("click", (event) => {
  if (event.target === plotDialog) closePlotDialog();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !plotDialog.hidden) closePlotDialog();
});
