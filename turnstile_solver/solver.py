"""
solver.py v2
Production-ready Turnstile solver with temporal entropy.
"""
import time
import random
from typing import Literal
from .anti_fingerprint import apply_stealth
from .clicker import TurnstileClicker
from .detector import TurnstileDetector
from .matcher import TurnstileMatcher
from .observer import TurnstileObserver
import random # Pastikan random diimpor di bagian atas file

def _validate_timeout_interval(timeout, interval):
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ValueError("timeout must be positive")
    if not isinstance(interval, (int, float)) or interval <= 0:
        raise ValueError("interval must be positive")
    if interval > timeout:
        raise ValueError("interval cannot exceed timeout")

class Solver:
    """
    Production Turnstile solver with multi-strategy detection and temporal entropy.
    """
    def __init__(
        self,
        driver,
        enable_logging: bool = False,
        theme: Literal["auto", "dark", "light"] = "auto",
        grayscale: bool = False,
        thresh: float = 0.75,
        click_method: Literal["cdp", "pyautogui", "hybrid"] = "hybrid",
    ):
        self.driver = driver
        self.enable_logging = enable_logging
        self.theme = theme
        self.grayscale = grayscale
        self.thresh = thresh
        self.click_method = click_method
        self._detected = None
        
        # Apply stealth patches
        apply_stealth(driver)
        driver.execute_cdp_cmd("Page.enable", {})
        
        self._initialize_components()

    def _initialize_components(self):
        self._detector = TurnstileDetector(self.driver)
        self._observer = TurnstileObserver(self.driver)
        self._matcher = TurnstileMatcher(self.driver, self.theme, self.grayscale, self.thresh)
        self._clicker = TurnstileClicker(self.driver, method=self.click_method)

    def _log(self, message: str):
        if self.enable_logging:
            print(f"[Solver] {message}")

    def cleanup(self):
        if self._clicker:
            self._clicker.remove_mousemove_listener()
        if self._observer:
            self._observer.remove()

    def detect(self, timeout=10, interval=1) -> bool | str:
        """
        Detect Turnstile with exponential backoff.
        """
        _validate_timeout_interval(timeout, interval)
        self._observer.detect_timeout = timeout
        start_time = time.time()
        attempt = 0
        
        while time.time() - start_time <= timeout:
            if self._detector.detect():
                self._detected = self._detector.type
                self._log(f"Turnstile detected: {self._detected}")
                return self._detected
            
            # Exponential backoff with jitter
            attempt += 1
            delay = min(interval * (1.5 ** attempt), 3.0)
            delay += random.gauss(0, 0.2)  # Gaussian jitter
            time.sleep(max(0.3, delay))
        
        self._log("No Turnstile widget detected.")
        return False

    def solve(self, timeout=45, interval=1.5, verify=True) -> bool:
        """
        Solve with temporal entropy (Gaussian jitter, not linear).
        """
        _validate_timeout_interval(timeout, interval)
        if not self._detected:
            raise RuntimeError("Call detect() first.")
        
        if verify:
            self._observer.start(cf_type=self._detected, solve_timeout=timeout)
        
        start_time = time.time()
        attempt = 0
        
        while time.time() - start_time <= timeout:
            # Check verification first
            if verify and self._observer.is_verified():
                self._log(f"Turnstile verified: {self._detected}")
                return True
            
            # Attempt match and click
            coords = self._matcher.match()
            if coords:
                # For invisible mode with token already extracted, skip click
                if coords == (0, 0):
                    self._log("Token extracted directly, no click needed.")
                    time.sleep(1)
                    continue
                
                x, y = coords[0] + 30, coords[1] + 25  # Offset to checkbox center
                self._clicker.click(x, y)
                self._log(f"Clicked at ({x}, {y}) via {self.click_method}")
                
                if not verify:
                    return True
            
            # Temporal entropy: Gaussian delay, not linear
            attempt += 1
            delay = interval + random.gauss(0, interval * 0.3)
            time.sleep(max(0.5, delay))
        
        self._log(f"Turnstile not {'verified' if verify else 'clicked'} within timeout.")
        return False

def solve(
    driver,
    detect_timeout=10,
    solve_timeout=45,
    interval=1.5,
    verify=True,
    enable_logging=False,
    theme="auto",
    grayscale=False,
    thresh=0.75,
    click_method="hybrid",
) -> bool | None:
    """One-shot solver with production defaults."""
    solver = Solver(
        driver,
        enable_logging=enable_logging,
        theme=theme,
        grayscale=grayscale,
        thresh=thresh,
        click_method=click_method,
    )
    try:
        if not solver.detect(timeout=detect_timeout, interval=interval):
            return None
        return solver.solve(timeout=solve_timeout, interval=interval, verify=verify)
    finally:
        solver.cleanup()