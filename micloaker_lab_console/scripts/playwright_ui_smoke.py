from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


URLS = ["/", "/sessions", "/runs/new", "/compare", "/mac-helper", "/ops", "/live"]
VIEWPORTS = [(1440, 1000), (390, 900)]


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


def main() -> int:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    out_dir = Path("workspace/.micloaker/playwright")
    out_dir.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for width, height in VIEWPORTS:
                page = browser.new_page(viewport={"width": width, "height": height})
                try:
                    for path in URLS:
                        url = base_url.rstrip("/") + path
                        page.goto(url, wait_until="networkidle", timeout=15000)
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
