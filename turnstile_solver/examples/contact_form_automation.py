

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, asdict
from typing import Optional
from urllib.parse import urlparse

from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from solver import Solver
from sync_solver import build_chrome_driver, read_turnstile_token

DEFAULT_URL = "https://qnn.net.id/kontak-kami"
DEFAULT_ALLOWED_HOSTS = {"qnn.net.id", "www.qnn.net.id"}


@dataclass
class AutomationResult:
    url: str
    fields_filled: list[str]
    turnstile_detected: bool
    turnstile_solved: bool
    turnstile_token_present: bool
    submitted: bool
    elapsed_time_seconds: float
    error: Optional[str] = None


FIELD_SELECTORS = {
    "name": {
        "css": [
            "input[name='name']",
            "input[name='nama']",
            "input[id='name']",
            "input[id='nama']",
            "input[placeholder*='Nama']",
        ],
        "xpath": [
            "//*[normalize-space()='Nama']/following::input[1]",
            "//input[contains(translate(@placeholder, 'NAMA', 'nama'), 'nama')]",
        ],
    },
    "company": {
        "css": [
            "input[name='company']",
            "input[name='perusahaan']",
            "input[id='company']",
            "input[id='perusahaan']",
            "input[placeholder*='Perusahaan']",
        ],
        "xpath": [
            "//*[normalize-space()='Perusahaan']/following::input[1]",
            "//input[contains(translate(@placeholder, 'PERUSAHAAN', 'perusahaan'), 'perusahaan')]",
        ],
    },
    "email": {
        "css": [
            "input[type='email']",
            "input[name='email']",
            "input[id='email']",
            "input[placeholder*='Email']",
        ],
        "xpath": [
            "//*[normalize-space()='Email']/following::input[1]",
            "//input[contains(translate(@placeholder, 'EMAIL', 'email'), 'email')]",
        ],
    },
    "message": {
        "css": [
            "textarea[name='message']",
            "textarea[name='pesan']",
            "textarea[id='message']",
            "textarea[id='pesan']",
            "textarea[placeholder*='Pesan']",
        ],
        "xpath": [
            "//*[normalize-space()='Pesan']/following::textarea[1]",
            "//textarea[contains(translate(@placeholder, 'PESAN', 'pesan'), 'pesan')]",
        ],
    },
}

SUBMIT_XPATHS = [
    "//button[contains(normalize-space(), 'Kirim Pesan')]",
    "//button[@type='submit']",
    "//input[@type='submit']",
]


def assert_allowed_url(url: str, allowed_hosts: set[str]) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("URL must use http or https")
    if parsed.hostname not in allowed_hosts:
        allowed = ", ".join(sorted(allowed_hosts))
        raise ValueError(f"Refusing to automate host '{parsed.hostname}'. Allowed: {allowed}")


def first_visible(elements):
    for element in elements:
        try:
            if element.is_displayed() and element.is_enabled():
                return element
        except Exception:
            continue
    return None


def find_field(driver, field_name: str):
    config = FIELD_SELECTORS[field_name]

    for selector in config["css"]:
        element = first_visible(driver.find_elements(By.CSS_SELECTOR, selector))
        if element:
            return element

    for xpath in config["xpath"]:
        element = first_visible(driver.find_elements(By.XPATH, xpath))
        if element:
            return element

    raise NoSuchElementException(f"Could not find form field: {field_name}")


def set_field_value(driver, element, value: str) -> None:
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
    time.sleep(0.2)
    element.click()
    try:
        element.clear()
    except Exception:
        pass
    element.send_keys(value)


def fill_contact_form(driver, args) -> list[str]:
    values = {
        "name": args.name,
        "company": args.company,
        "email": args.email,
        "message": args.message,
    }
    filled = []

    for field, value in values.items():
        if value is None:
            continue
        element = find_field(driver, field)
        set_field_value(driver, element, value)
        filled.append(field)

    return filled


def solve_turnstile(driver, args) -> tuple[bool, bool, bool]:
    solver = Solver(
        driver,
        enable_logging=args.debug,
        theme=args.theme,
        grayscale=args.grayscale,
        thresh=args.threshold,
        click_method=args.click_method,
    )

    try:
        detected = bool(solver.detect(timeout=args.detect_timeout, interval=1))
        if not detected:
            return False, False, bool(read_turnstile_token(driver))

        solved = bool(solver.solve(timeout=args.solve_timeout, interval=1, verify=args.verify))
        deadline = time.time() + args.token_timeout
        token = read_turnstile_token(driver)
        while not token and time.time() < deadline:
            time.sleep(0.5)
            token = read_turnstile_token(driver)

        return True, solved, bool(token)
    finally:
        solver.cleanup()


def find_submit_button(driver):
    for xpath in SUBMIT_XPATHS:
        element = first_visible(driver.find_elements(By.XPATH, xpath))
        if element:
            return element
    raise NoSuchElementException("Could not find submit button")


def submit_form(driver, timeout: int, original_url: str) -> None:
    button = find_submit_button(driver)
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
    time.sleep(0.2)
    button.click()
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.current_url != original_url
            or "berhasil" in d.page_source.lower()
            or "terkirim" in d.page_source.lower()
        )
    except TimeoutException:
        pass


def parse_args():
    parser = argparse.ArgumentParser(description="Automate ERPSKRIP contact form testing")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--allowed-host", action="append", dest="allowed_hosts")
    parser.add_argument("--name", default="QA Automation")
    parser.add_argument("--company", default="PT Graha Skrip Infra Prima")
    parser.add_argument("--email", default="qa@example.test")
    parser.add_argument("--message", default="Pesan test automation Turnstile. Abaikan jika terkirim.")
    parser.add_argument("--submit", action="store_true", help="Actually click the submit button")
    parser.add_argument("--allow-submit-without-token", action="store_true")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--useragent")
    parser.add_argument("--browser-binary")
    parser.add_argument("--driver-path")
    parser.add_argument("--detect-timeout", type=int, default=10)
    parser.add_argument("--solve-timeout", type=int, default=45)
    parser.add_argument("--token-timeout", type=int, default=10)
    parser.add_argument("--submit-wait", type=int, default=8)
    parser.add_argument("--verify", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--theme", choices=["auto", "light", "dark"], default="auto")
    parser.add_argument("--grayscale", action="store_true")
    parser.add_argument("--threshold", type=float, default=0.8)
    parser.add_argument("--click-method", choices=["cdp", "pyautogui"], default="cdp")
    parser.add_argument("--screenshot", help="Optional output screenshot path")
    return parser.parse_args()


def main():
    args = parse_args()
    allowed_hosts = set(args.allowed_hosts or DEFAULT_ALLOWED_HOSTS)
    assert_allowed_url(args.url, allowed_hosts)

    start = time.time()
    driver = build_chrome_driver(
        headless=args.headless,
        useragent=args.useragent,
        browser_binary=args.browser_binary,
        driver_path=args.driver_path,
    )

    result = AutomationResult(
        url=args.url,
        fields_filled=[],
        turnstile_detected=False,
        turnstile_solved=False,
        turnstile_token_present=False,
        submitted=False,
        elapsed_time_seconds=0,
    )

    try:
        driver.get(args.url)
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        result.fields_filled = fill_contact_form(driver, args)

        detected, solved, has_token = solve_turnstile(driver, args)
        result.turnstile_detected = detected
        result.turnstile_solved = solved
        result.turnstile_token_present = has_token

        if args.submit:
            if not has_token and not args.allow_submit_without_token:
                raise RuntimeError(
                    "Turnstile token was not present. Use --allow-submit-without-token "
                    "only if this is intentional."
                )
            submit_form(driver, args.submit_wait, args.url)
            result.submitted = True

        if args.screenshot:
            driver.save_screenshot(args.screenshot)

    except Exception as exc:
        result.error = str(exc)
    finally:
        result.elapsed_time_seconds = round(time.time() - start, 3)
        print(json.dumps(asdict(result), indent=2))
        driver.quit()


if __name__ == "__main__":
    main()