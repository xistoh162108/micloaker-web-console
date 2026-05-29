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

document.querySelectorAll('form[action="/ops/validation"]').forEach((form) => {
  const gate = form.querySelector('select[name="gate"]');
  const evidence = form.querySelector('textarea[name="evidence"]');
  const preview = form.querySelector("#validation-checklist-preview");
  if (!gate || !evidence || !preview) return;
  const updateValidationHint = () => {
    const selected = gate.options[gate.selectedIndex];
    const checklist = selected?.dataset.checklist || "";
    const hint = selected?.dataset.hint || "";
    preview.value = checklist ? `Checklist fields: ${checklist}` : "";
    evidence.placeholder = hint ? `${hint} Checklist fields: ${checklist}` : evidence.placeholder;
  };
  gate.addEventListener("change", updateValidationHint);
  updateValidationHint();
});
