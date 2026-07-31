# scanner.py
# Fase 1: Ekstraksi peta struktural DOM tanpa overhead JavaScript engine.
# Dependensi: pip install requests beautifulsoup4 lxml

import requests
from bs4 import BeautifulSoup
from dataclasses import dataclass, field
from typing import Optional
import logging

logger = logging.getLogger("XoS-Scanner")

@dataclass
class CaptchaMetadata:
    detected: bool
    provider: str
    data: dict = field(default_factory=dict)

# Kontrak data antar fase — dikirim sebagai handoff ke FormExecutor
@dataclass
class FormMetadata:
    url: str
    form_fields: dict[str, str]          # {name_attr: css_selector}
    submit_selector: str
    captcha: CaptchaMetadata
    honeypot_fields: list[str]           # Field yang harus diabaikan oleh executor

class FormScanner:
    # Header standar browser modern untuk menghindari pemblokiran trivial oleh server
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8",
    }
    # Kata kunci yang mengindikasikan field honeypot atau token CSRF yang tidak boleh diisi
    IGNORE_KEYWORDS = {"honeypot", "token", "csrf", "_method", "nonce"}
    # Kata kunci signature captcha yang umum ditemukan dalam atribut HTML
    CAPTCHA_SIGNATURES = {"captcha", "robot", "puzzle", "verify", "challenge"}

    def __init__(self, url: str, timeout: int = 10):
        self.url = url
        self.timeout = timeout

    def scan(self) -> FormMetadata:
        logger.info(f"[Phase 1] Memulai pre-flight HTTP scan ke: {self.url}")
        try:
            # Menonaktifkan verifikasi SSL untuk mempermudah tes pada domain target tertentu (misal lokal atau tanpa SSL valid)
            resp = requests.get(self.url, headers=self.HEADERS, timeout=self.timeout, verify=False)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise ConnectionError(f"Pre-flight scan gagal: {e}") from e

        soup = BeautifulSoup(resp.text, "lxml")
        metadata = self._extract_metadata(soup)
        
        if not metadata.form_fields:
            logger.warning("[Phase 1] HTTP murni tidak menemukan field (kemungkinan SPA). Memulai Playwright fallback...")
            metadata = self._scan_with_playwright()
            
        return metadata

    def _scan_with_playwright(self) -> FormMetadata:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(user_agent=self.HEADERS["User-Agent"])
            page = context.new_page()
            try:
                # Mengubah networkidle menjadi domcontentloaded untuk navigasi awal
                page.goto(self.url, wait_until="domcontentloaded", timeout=self.timeout * 1000)
                
                # Beri waktu tambahan untuk React/Vue me-render form (SPA asinkron)
                try:
                    # Menunggu spesifik hingga tag <form> muncul (lebih cerdas dari networkidle)
                    page.wait_for_selector("form, input", timeout=10000)
                    page.wait_for_timeout(2000)  # Beri waktu tambahan untuk widget (reCAPTCHA)
                except Exception:
                    pass
                
                html_content = page.content()
            except Exception as e:
                logger.error(f"[Phase 1] SPA Fallback gagal navigasi awal: {e}")
                html_content = ""
            finally:
                context.close()
                browser.close()
                
        if html_content:
            soup = BeautifulSoup(html_content, "lxml")
            return self._extract_metadata(soup)
            
        return FormMetadata(self.url, {}, "button[type='submit']", CaptchaMetadata(False, ""), [])

    def _extract_metadata(self, soup: BeautifulSoup) -> FormMetadata:
        form_fields: dict[str, str] = {}
        optional_fields: dict[str, str] = {}
        honeypot_fields: list[str] = []
        captcha = CaptchaMetadata(detected=False, provider="")
        submit_selector = "button[type='submit'], input[type='submit']"

        # DOM-wide deteksi untuk 3rd-party CAPTCHA providers FIRST
        # Google reCAPTCHA
        if soup.find("iframe", src=lambda s: s and "recaptcha" in s.lower()) or soup.find("div", class_="g-recaptcha"):
            captcha.detected = True
            captcha.provider = "google_recaptcha"
        # hCaptcha
        elif soup.find("iframe", src=lambda s: s and "hcaptcha" in s.lower()) or soup.find("div", class_="h-captcha"):
            captcha.detected = True
            captcha.provider = "hcaptcha"
        # Cloudflare Turnstile
        elif soup.find("iframe", src=lambda s: s and "turnstile" in s.lower()) or soup.find("div", class_="cf-turnstile"):
            captcha.detected = True
            captcha.provider = "cloudflare_turnstile"
            
        form = soup.find("form")
        if not form:
            # Fallback: scan seluruh DOM jika form tag tidak eksplisit
            logger.warning("[Phase 1] Tag <form> tidak ditemukan. Scanning seluruh DOM...")
            form = soup

        # Iterasi semua elemen input dan textarea dalam form
        interactable_tags = form.find_all(["input", "textarea", "select"])

        for tag in interactable_tags:
            tag_type = tag.get("type", "text").lower()
            name = tag.get("name", "")
            tag_id = tag.get("id", "")

            # Abaikan field tersembunyi dan hidden inputs
            if tag_type in {"hidden", "submit", "reset", "button", "file", "image"}:
                if tag_type == "submit":
                    # Ekstrak selector submit secara dinamis jika ditemukan
                    if name:
                        submit_selector = f"[name='{name}']"
                    elif tag_id:
                        submit_selector = f"#{tag_id}"
                continue

            # Deteksi dan isolasi honeypot/field yang harus diabaikan
            combined_attrs = f"{name} {tag_id} {tag.get('class', '')}".lower()
            if any(kw in combined_attrs for kw in self.IGNORE_KEYWORDS):
                logger.info(f"  [IGNORE] Field '{name}' diidentifikasi sebagai honeypot/token.")
                honeypot_fields.append(name)
                continue

            # Deteksi signature captcha pada atribut field (math puzzle/internal)
            if any(kw in combined_attrs for kw in self.CAPTCHA_SIGNATURES):
                if not captcha.detected:
                    captcha.detected = True
                    captcha.provider = "math_puzzle"
                    sig = f"#{tag_id}" if tag_id else f"[name='{name}']"
                    captcha.data['signature'] = sig
                logger.info(f"  [CAPTCHA] Math puzzle signature terdeteksi pada field: '{name}'")
                continue  # Captcha dihandle terpisah oleh solver, bukan form_fields

            # Susun CSS selector dengan hierarki prioritas: id > name > tag+index
            if tag_id:
                selector = f"#{tag_id}"
            elif name:
                selector = f"[name='{name}']"
            else:
                # Field tanpa identifikasi unik — lewati untuk menghindari ambiguitas
                logger.warning(f"  [SKIP] Field tanpa name/id ditemukan: {tag}")
                continue

            # Deteksi apakah field ini wajib (required)
            is_required = tag.has_attr("required")
            if not is_required:
                # Cari berdasarkan label for=id
                if tag_id:
                    label = soup.find("label", {"for": tag_id})
                    if label and "*" in label.text:
                        is_required = True
                # Cari berdasarkan parent label
                if not is_required:
                    parent_label = tag.find_parent("label")
                    if parent_label and "*" in parent_label.text:
                        is_required = True
            
            if not is_required:
                logger.info(f"  [OPTIONAL] Field '{name or tag_id}' ditandai opsional (tidak required / tidak ada *).")
                optional_fields[name or tag_id] = selector
                continue

            form_fields[name or tag_id] = selector
            logger.info(f"  [MAP] '{name or tag_id}' → '{selector}'")

        # Fallback: Jika setelah iterasi tidak ada form field wajib sama sekali,
        # kita gunakan semua field opsional agar tetap ada yang diisi.
        if len(form_fields) == 0 and len(optional_fields) > 0:
            logger.info("  [FALLBACK] Tidak ada field wajib terdeteksi. Menggunakan semua field opsional.")
            form_fields = optional_fields

        # Deteksi checkbox "robot" sebagai captcha gate (pola umum pada QNN)
        if not captcha.detected:
            robot_checkbox = soup.find("input", {"type": "checkbox"})
            if robot_checkbox:
                cb_attrs = f"{robot_checkbox.get('name','')} {robot_checkbox.get('id','')}".lower()
                if any(kw in cb_attrs for kw in self.CAPTCHA_SIGNATURES):
                    captcha.detected = True
                    captcha.provider = "math_puzzle"
                    captcha.data['signature'] = f"#{robot_checkbox.get('id')}" if robot_checkbox.get("id") else "[type='checkbox']"
        
        if captcha.detected:
            logger.info(f"  [CAPTCHA] Provider terdeteksi: {captcha.provider}")

        logger.info(
            f"[Phase 1] Scan selesai. Fields: {len(form_fields)}, "
            f"Captcha: {captcha.detected} ({captcha.provider}), Honeypots: {len(honeypot_fields)}"
        )
        return FormMetadata(
            url=self.url,
            form_fields=form_fields,
            submit_selector=submit_selector,
            captcha=captcha,
            honeypot_fields=honeypot_fields,
        )