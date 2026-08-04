"""Compatibility wrapper for the Selenium-based Turnstile solver."""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from typing import Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

from .solver import Solver
# Tambahkan di bagian atas sync_solver.py
import undetected_chromedriver as uc

from .anti_fingerprint import apply_stealth_uc, get_stealth_chrome_options_uc

def _cleanup_uc_leftovers() -> None:
    """
    Kill lingering chromedriver processes and remove stale patched exe.
    Prevents WinError 183 (file already exists) on Windows.
    """
    import subprocess
    import os

    # Kill ALL chromedriver variants (UC may appear under different names)
    for proc_name in ["undetected_chromedriver.exe", "chromedriver.exe"]:
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", proc_name],
                capture_output=True, timeout=5
            )
        except Exception:
            pass

    time.sleep(1.5)  # Allow OS to release file locks

    # Remove the stale patched exe from UC's cache directory
    uc_dir = os.path.join(os.environ.get("APPDATA", ""), "undetected_chromedriver")
    uc_exe = os.path.join(uc_dir, "undetected_chromedriver.exe")
    if os.path.exists(uc_exe):
        # Try up to 3 times in case file handle not yet released
        for _ in range(3):
            try:
                os.remove(uc_exe)
                break
            except PermissionError:
                time.sleep(1)
            except Exception:
                break


def build_uc_driver(
    headless: bool = False,
    useragent: Optional[str] = None,
    browser_binary: Optional[str] = None,
    driver_path: Optional[str] = None,
):
    import os

    # Gunakan uc.ChromeOptions dari anti_fingerprint
    options = get_stealth_chrome_options_uc()
    
    # PENTING: Headless TIDAK BOLEH AKTIF untuk pyautogui (OS-level click)
    if headless:
        print("[PERINGATAN] Headless dinonaktifkan secara paksa untuk mode Interaktif.")
        
    if useragent:
        options.add_argument(f"--user-agent={useragent}")
    if browser_binary:
        options.binary_location = browser_binary
    
    # Inisialisasi UC Driver dengan retry jika WinError 183
    last_error = None
    for attempt in range(3):
        try:
            _cleanup_uc_leftovers()
            driver = uc.Chrome(options=options, version_main=150)
            driver.maximize_window()
            apply_stealth_uc(driver)
            return driver
        except Exception as e:
            last_error = e
            err_str = str(e)
            if "183" in err_str or "already exists" in err_str.lower():
                print(f"[UC] WinError 183 on attempt {attempt + 1}, retrying after cleanup...")
                time.sleep(2)
            else:
                raise  # Non-recoverable error, don't retry
    
    raise RuntimeError(f"Failed to initialize UC driver after 3 attempts: {last_error}")


@dataclass
class TurnstileResult:
    turnstile_value: Optional[str]
    elapsed_time_seconds: float
    status: str
    reason: Optional[str] = None


def build_chrome_driver(
    headless: bool = False,
    useragent: Optional[str] = None,
    browser_binary: Optional[str] = None,
    driver_path: Optional[str] = None,
):
    options = Options()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1280,720")
    options.add_argument("--lang=en-US")

    if headless:
        options.add_argument("--headless=new")
    if useragent:
        options.add_argument(f"--user-agent={useragent}")
    if browser_binary:
        options.binary_location = browser_binary

    if driver_path:
        return webdriver.Chrome(service=Service(driver_path), options=options)
    return webdriver.Chrome(options=options)


def read_turnstile_token(driver) -> Optional[str]:
    token = driver.execute_script(
        """
        const direct = document.querySelector('[name="cf-turnstile-response"]');
        if (direct && direct.value) return direct.value;

        const candidates = Array.from(document.querySelectorAll('input, textarea'));
        const found = candidates.find((el) => {
            const key = `${el.name || ''} ${el.id || ''}`.toLowerCase();
            return key.includes('turnstile') || key.includes('cf-challenge');
        });
        return found && found.value ? found.value : '';
        """
    )
    return token or None


def get_turnstile_token(
    url: str,
    sitekey: Optional[str] = None,
    debug: bool = False,
    headless: bool = False,
    useragent: Optional[str] = None,
    browser_binary: Optional[str] = None,
    driver_path: Optional[str] = None,
    detect_timeout: int = 10,
    solve_timeout: int = 45,
    token_timeout: int = 10,
    verify: bool = True,
    click_method: str = "cdp",
    **_,
) -> dict:
    """Open a page, solve an embedded Turnstile widget, and return its token."""
    del sitekey  # Sitekey is read from the page by this Selenium implementation.
    start_time = time.time()
    driver = build_chrome_driver(
        headless=headless,
        useragent=useragent,
        browser_binary=browser_binary,
        driver_path=driver_path,
    )

    try:
        driver.get(url)
        solver = Solver(
            driver,
            enable_logging=debug,
            click_method=click_method,
        )
        detected = solver.detect(timeout=detect_timeout, interval=1)
        if not detected:
            return TurnstileResult(
                turnstile_value=None,
                elapsed_time_seconds=round(time.time() - start_time, 3),
                status="failure",
                reason="Turnstile widget was not detected",
            ).__dict__

        solved = solver.solve(timeout=solve_timeout, interval=1, verify=verify)
        deadline = time.time() + token_timeout
        token = read_turnstile_token(driver)
        while not token and time.time() < deadline:
            time.sleep(0.5)
            token = read_turnstile_token(driver)

        elapsed = round(time.time() - start_time, 3)
        if solved or token:
            return TurnstileResult(
                turnstile_value=token,
                elapsed_time_seconds=elapsed,
                status="success",
            ).__dict__

        return TurnstileResult(
            turnstile_value=None,
            elapsed_time_seconds=elapsed,
            status="failure",
            reason="Turnstile was detected but not solved",
        ).__dict__
    finally:
        try:
            solver.cleanup()
        except Exception:
            pass
        driver.quit()


def parse_args():
    parser = argparse.ArgumentParser(description="Solve Turnstile on a page")
    parser.add_argument("--url", default="https://qnn.net.id/kontak-kami")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--useragent")
    parser.add_argument("--browser-binary")
    parser.add_argument("--driver-path")
    parser.add_argument("--detect-timeout", type=int, default=10)
    parser.add_argument("--solve-timeout", type=int, default=45)
    parser.add_argument("--token-timeout", type=int, default=10)
    parser.add_argument("--no-verify", action="store_true")
    parser.add_argument("--click-method", choices=["cdp", "pyautogui"], default="cdp")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    result = get_turnstile_token(
        url=args.url,
        debug=args.debug,
        headless=args.headless,
        useragent=args.useragent,
        browser_binary=args.browser_binary,
        driver_path=args.driver_path,
        detect_timeout=args.detect_timeout,
        solve_timeout=args.solve_timeout,
        token_timeout=args.token_timeout,
        verify=not args.no_verify,
        click_method=args.click_method,
    )
    print(result)