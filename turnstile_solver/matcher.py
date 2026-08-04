"""
matcher.py v3
Adaptive Turnstile matcher with strategy priority: DOM Location → Token Extraction → Template Matching (fallback).
Designed for Selenium/CDP driver (undetected_chromedriver).
"""
import base64
import os
from typing import Literal, Optional, Tuple
import cv2
import numpy as np


def get_cdp_screenshot(driver) -> np.ndarray:
    """Capture screenshot via CDP, return as NumPy BGR array."""
    result = driver.execute_cdp_cmd("Page.captureScreenshot", {
        "format": "png",
        "fromSurface": True
    })
    img_bytes = base64.b64decode(result["data"])
    return np.frombuffer(img_bytes, dtype=np.uint8)


class TurnstileMatcher:
    """
    Adaptive matcher with multi-strategy fallback chain.
    Priority order (2025 anti-detection standard):
    1. DOM Location (fastest, zero visual footprint)
    2. Token Extraction (invisible/managed mode, no click needed)
    3. Template Matching (last resort when DOM obfuscated)
    """
    def __init__(
        self,
        driver,
        theme: Literal["light", "dark", "auto"] = "auto",
        grayscale: bool = False,
        thresh: float = 0.75
    ):
        self.driver = driver
        self.theme = theme
        self.grayscale = grayscale
        self.thresh = thresh

        base_dir = os.path.dirname(__file__)
        self.images = {
            "light": os.path.join(base_dir, "assets", "light_turnstile.png"),
            "dark": os.path.join(base_dir, "assets", "dark_turnstile.png"),
        }
        self.templates = self._load_templates()

    def _load_templates(self) -> list[np.ndarray]:
        flag = cv2.IMREAD_GRAYSCALE if self.grayscale else cv2.IMREAD_COLOR
        paths = list(self.images.values()) if self.theme == "auto" else [self.images[self.theme]]
        templates = []
        for path in paths:
            img = cv2.imread(str(path), flag)
            if img is None:
                raise FileNotFoundError(f"Template not found: {path}")
            templates.append(img)
        return templates

    def match(self) -> Optional[Tuple[int, int]]:
        """
        Multi-strategy match. Returns (x, y) viewport coordinates or None.
        Priority: DOM Location → Token Extraction → Template Matching
        """
        # Priority 1: DOM Location (fastest, most accurate, no visual analysis)
        coords = self._locate_input_field()
        if coords:
            return coords

        # Priority 2: Token Extraction (invisible/managed mode - no click needed)
        if self._try_extract_token():
            return (0, 0)  # Signal: token already extracted, no click needed

        # Priority 3: Template Matching (fallback for obfuscated DOM)
        return self._template_match()

    def _locate_input_field(self) -> Optional[Tuple[int, int]]:
        """
        Locate Turnstile widget via DOM and return its top-left viewport coordinates.
        Uses getBoundingClientRect() on .cf-turnstile container.
        This is the primary strategy - zero fingerprint, works cross-origin.
        """
        result = self.driver.execute_cdp_cmd("Runtime.evaluate", {
            "expression": """
                (function() {
                    const widget = document.querySelector('.cf-turnstile');
                    if (!widget) return null;
                    const rect = widget.getBoundingClientRect();
                    return {
                        x: Math.round(rect.left),
                        y: Math.round(rect.top),
                        width: Math.round(rect.width),
                        height: Math.round(rect.height)
                    };
                })()
            """,
            "returnByValue": True
        })["result"].get("value")

        if result:
            # Return center of widget for clicking
            center_x = result["x"] + result["width"] // 2
            center_y = result["y"] + result["height"] // 2
            return (center_x, center_y)
        return None

    def _try_extract_token(self) -> bool:
        """
        Attempt direct token extraction via window.turnstile.getResponse().
        Works for invisible/managed mode where widget auto-solves.
        If token found, stores in sessionStorage for observer to pick up.
        """
        result = self.driver.execute_cdp_cmd("Runtime.evaluate", {
            "expression": """
                (function() {
                    if (typeof window.turnstile === 'undefined') return false;

                    const containers = document.querySelectorAll('.cf-turnstile, [data-sitekey]');
                    for (const container of containers) {
                        try {
                            const widgetId = container.getAttribute('data-widget-id') ||
                                            container.dataset.widgetId;
                            if (widgetId) {
                                const token = window.turnstile.getResponse(widgetId);
                                if (token && token.length > 50) {
                                    sessionStorage.setItem('turnstile_token', token);
                                    sessionStorage.setItem('turnstile_verified', 'true');
                                    return true;
                                }
                            }
                        } catch(e) {}
                    }
                    return false;
                })()
            """,
            "returnByValue": True
        })["result"].get("value", False)
        return result

    def _template_match(self) -> Optional[Tuple[int, int]]:
        """
        OpenCV template matching on CDP screenshot.
        Fallback when DOM is obfuscated (e.g., shadow DOM, dynamic classes).
        Uses TM_CCOEFF_NORMED with configurable threshold.
        """
        flag = cv2.IMREAD_GRAYSCALE if self.grayscale else cv2.IMREAD_COLOR
        screenshot = get_cdp_screenshot(self.driver)
        canvas = cv2.imdecode(screenshot, flag)

        best_val = 0.0
        best_loc = None
        for template in self.templates:
            if canvas.shape[0] < template.shape[0] or canvas.shape[1] < template.shape[1]:
                continue
            result = cv2.matchTemplate(canvas, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            if max_val > best_val and max_val >= self.thresh:
                best_val = max_val
                best_loc = max_loc

        if best_loc:
            # Return center of matched template
            h, w = self.templates[0].shape[:2]
            return (best_loc[0] + w // 2, best_loc[1] + h // 2)
        return None