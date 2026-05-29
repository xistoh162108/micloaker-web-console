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

document.querySelectorAll("form").forEach((form) => {
  const method = (form.getAttribute("method") || "get").toLowerCase();
  if (method !== "post" || form.dataset.nativeSubmit === "true") return;
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
