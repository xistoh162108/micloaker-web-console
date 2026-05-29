from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


URLS = ["/", "/sessions", "/runs/new", "/compare", "/mac-helper", "/ops", "/live"]
VIEWPORTS = [(1440, 1000), (390, 900)]
MIN_TOUCH_GAP_PX = 4
DASHBOARD_GAP_PAIRS = [
    ("#live-final-run", ".finalization-panel nav.actions", 8, "finalization status summary vs action buttons"),
    (".result-grid", ".card.priority-card:nth-of-type(3) > .card-body > .button-row", 8, "latest run/comparison panels vs export buttons"),
]
RUN_DETAIL_GAP_PAIRS = [
    ('form[action$="/play"] .form-actions', 'form[action$="/stop"] .form-actions', 8, "run detail Play vs Stop Playback"),
]
COMPONENT_SELECTOR = (
    "main.page > section, main.page > nav, main.page > .alert, "
    ".card-body > form, .card-body > .form, .card-body > .button-row, .card-body > .actions, "
    ".card-body > .table-scroll, .card-body > table, .card-body > pre, .card-body > .plots, "
    ".card-body > .dashboard-artifacts, .card-body > .metric-readout, .card-body > .final-run-summary, "
    ".panel > .actions, .panel > pre, .panel > canvas, .panel > .metric-readout, .panel > .final-run-summary"
)


def visible_box(el):
    box = el.bounding_box()
    if not box:
        return None
    if box["width"] <= 1 or box["height"] <= 1:
        return None
    return box


def intersects(a, b) -> bool:
    return not (
        a["x"] + a["width"] <= b["x"]
        or b["x"] + b["width"] <= a["x"]
        or a["y"] + a["height"] <= b["y"]
        or b["y"] + b["height"] <= a["y"]
    )


def vertical_gap(a, b) -> float:
    return b["y"] - (a["y"] + a["height"])


def horizontal_overlap(a, b) -> float:
    return min(a["x"] + a["width"], b["x"] + b["width"]) - max(a["x"], b["x"])


def latest_run_detail_path() -> str | None:
    metadata_dir = Path("workspace/sessions")
    if not metadata_dir.exists():
        return None
    candidates = sorted(metadata_dir.glob("*/metadata/*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        session_id = path.parent.parent.name
        run_id = payload.get("run_id") or path.stem
        if session_id and run_id:
            return f"/sessions/{session_id}/runs/{run_id}"
    return None


def check_gap_pair(page, path: str, width: int, failures: list[str], top_selector: str, bottom_selector: str, min_gap: int, label: str) -> None:
    top = page.locator(top_selector).first
    bottom = page.locator(bottom_selector).first
    if not top.count() or not bottom.count():
        return
    top_box = visible_box(top)
    bottom_box = visible_box(bottom)
    if not top_box or not bottom_box:
        return
    gap = vertical_gap(top_box, bottom_box)
    if gap < min_gap:
        failures.append(f"{path} vertical gap too small at {width}px for {label}: {gap:.1f}px")


def check_component_touching(page, path: str, width: int, failures: list[str]) -> None:
    targets = page.locator(COMPONENT_SELECTOR).all()
    boxes = []
    for idx, el in enumerate(targets):
        box = visible_box(el)
        if box:
            label = el.evaluate(
                """element => {
                    const id = element.id ? `#${element.id}` : "";
                    const cls = String(element.className || "").trim().split(/\\s+/).filter(Boolean).slice(0, 3).join(".");
                    return `${element.tagName.toLowerCase()}${id}${cls ? "." + cls : ""}`;
                }"""
            )
            boxes.append((idx, label, box))
    for i, (idx_a, label_a, box_a) in enumerate(boxes):
        for idx_b, label_b, box_b in boxes[i + 1 :]:
            x_overlap = horizontal_overlap(box_a, box_b)
            if x_overlap <= min(box_a["width"], box_b["width"]) * 0.35:
                continue
            gap_ab = vertical_gap(box_a, box_b)
            gap_ba = vertical_gap(box_b, box_a)
            if 0 <= gap_ab < MIN_TOUCH_GAP_PX:
                failures.append(f"{path} components touch vertically at {width}px: {label_a}[{idx_a}] vs {label_b}[{idx_b}], gap {gap_ab:.1f}px")
            if 0 <= gap_ba < MIN_TOUCH_GAP_PX:
                failures.append(f"{path} components touch vertically at {width}px: {label_b}[{idx_b}] vs {label_a}[{idx_a}], gap {gap_ba:.1f}px")


def main() -> int:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    out_dir = Path("workspace/.micloaker/playwright")
    out_dir.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    urls = list(URLS)
    run_detail_path = latest_run_detail_path()
    if run_detail_path:
        urls.append(run_detail_path)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for width, height in VIEWPORTS:
                page = browser.new_page(viewport={"width": width, "height": height})
                try:
                    for path in urls:
                        url = base_url.rstrip("/") + path
                        page.goto(url, wait_until="domcontentloaded", timeout=20000)
                        page.wait_for_load_state("load", timeout=20000)
                        page.screenshot(path=str(out_dir / f"{path.strip('/').replace('/', '_') or 'dashboard'}_{width}.png"), full_page=True)
                        if page.locator("body").bounding_box() is None:
                            failures.append(f"{path} body did not render at {width}px")
                        for selector in ["button", ".btn", "input[type=checkbox]", "audio", "canvas"]:
                            count = page.locator(selector).count()
                            for idx in range(count):
                                box = visible_box(page.locator(selector).nth(idx))
                                if not box:
                                    continue
                                if box["x"] < -1 or box["x"] + box["width"] > width + 1:
                                    failures.append(f"{path} {selector}[{idx}] overflows horizontally at {width}px: {box}")
                        targets = page.locator("button, .btn, input[type=checkbox]").all()
                        boxes = []
                        for idx, el in enumerate(targets):
                            box = visible_box(el)
                            if box:
                                boxes.append((idx, box))
                        for i, (idx_a, box_a) in enumerate(boxes):
                            for idx_b, box_b in boxes[i + 1 :]:
                                if intersects(box_a, box_b):
                                    overlap_area = (
                                        min(box_a["x"] + box_a["width"], box_b["x"] + box_b["width"]) - max(box_a["x"], box_b["x"])
                                    ) * (
                                        min(box_a["y"] + box_a["height"], box_b["y"] + box_b["height"]) - max(box_a["y"], box_b["y"])
                                    )
                                    if overlap_area > 16:
                                        failures.append(f"{path} controls overlap at {width}px: target {idx_a} vs {idx_b}")
                                else:
                                    gap_ab = vertical_gap(box_a, box_b)
                                    gap_ba = vertical_gap(box_b, box_a)
                                    x_overlap = horizontal_overlap(box_a, box_b)
                                    if x_overlap > min(box_a["width"], box_b["width"]) * 0.25:
                                        if 0 <= gap_ab < MIN_TOUCH_GAP_PX:
                                            failures.append(f"{path} controls touch vertically at {width}px: target {idx_a} vs {idx_b}, gap {gap_ab:.1f}px")
                                        if 0 <= gap_ba < MIN_TOUCH_GAP_PX:
                                            failures.append(f"{path} controls touch vertically at {width}px: target {idx_b} vs {idx_a}, gap {gap_ba:.1f}px")
                        if path == "/":
                            for top_selector, bottom_selector, min_gap, label in DASHBOARD_GAP_PAIRS:
                                check_gap_pair(page, path, width, failures, top_selector, bottom_selector, min_gap, label)
                        if "/runs/" in path:
                            for top_selector, bottom_selector, min_gap, label in RUN_DETAIL_GAP_PAIRS:
                                check_gap_pair(page, path, width, failures, top_selector, bottom_selector, min_gap, label)
                        check_component_touching(page, path, width, failures)
                finally:
                    page.close()
        finally:
            browser.close()

    if failures:
        print("FAIL: Playwright UI validation found issues")
        for failure in failures:
            print(f"  {failure}")
        return 1
    print(f"PASS: Playwright UI validation completed for {base_url}")
    print(f"Screenshots: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
