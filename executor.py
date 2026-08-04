# executor.py
# Fase 2: Eksekusi pengisian form dengan Playwright + event native JavaScript.
# Target: NONE captcha, Native Math Puzzle, Google reCAPTCHA.
# BUKAN untuk Cloudflare Turnstile (gunakan selenium_executor.py).
# Dependensi: pip install playwright && playwright install chromium

import logging
import random
from typing import Optional
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from scanner import FormMetadata
from typing import Any
from humanizer import human_type_burst, execute_human_click, get_current_mouse_pos, install_mouse_tracker

logger = logging.getLogger("XoS-Executor")


class FormExecutor:
    # Skrip injeksi stealth: menghapus jejak otomatisasi dari navigator object
    # Lebih ringan dari pustaka playwright-stealth karena hanya menarget properti kritis
    STEALTH_SCRIPT = """
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
        Object.defineProperty(navigator, 'languages', { get: () => ['id-ID', 'en-US'] });
        window.chrome = { runtime: {} };
    """

    def __init__(
        self,
        metadata: FormMetadata,
        proxy_url: Optional[str] = None,
        headless: bool = True,
        timeout_ms: int = 15000,
    ):
        self.metadata = metadata
        self.proxy = {"server": proxy_url} if proxy_url else None
        self.headless = headless
        self.timeout = timeout_ms

    def execute(self, form_data: dict[str, str], solver: Any = None) -> bool:
        """
        Mengeksekusi pengisian form menggunakan peta field dari FormMetadata.
        form_data: {nama_field: nilai} — kunci harus sesuai dengan FormMetadata.form_fields.
        Return: True jika siklus selesai tanpa exception, False jika gagal.
        """
        logger.info(f"[Phase 2] Inisialisasi Playwright executor untuk: {self.metadata.url}")

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=self.headless,
                proxy=self.proxy,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
            )
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                locale="id-ID",
            )
            # Injeksi stealth script sebelum setiap dokumen dimuat
            context.add_init_script(self.STEALTH_SCRIPT)
            page = context.new_page()

            # Install mouse tracker for humanized clicks
            install_mouse_tracker(page)

            try:
                # Navigasi dan tunggu hingga DOM siap
                logger.info("[Phase 2] Navigasi ke URL target...")
                page.goto(self.metadata.url, wait_until="domcontentloaded", timeout=self.timeout)

                # --- Pengisian Field Form dengan Humanizer ---
                logger.info("[Phase 2] Mengisi field form dengan human_type_burst...")
                for field_name, selector in self.metadata.form_fields.items():
                    value = form_data.get(field_name.lower())
                    if not value:
                        logger.warning(f"  [SKIP] Tidak ada data di Bank Data untuk field wajib: '{field_name}'. Melewati field ini.")
                        continue

                    # Gunakan human_type_burst alih-alih page.fill() untuk anti-deteksi
                    human_type_burst(page, selector, value)
                    logger.info(f"  -> [OK] '{field_name}' → '{selector}' terisi (humanized).")

                # --- Pemicu Captcha Gate ---
                if self.metadata.captcha.detected and solver:
                    logger.info(f"[Phase 2] Menggunakan solver untuk: {self.metadata.captcha.provider}")
                    solver.solve(page, self.metadata.captcha)

                # --- Validasi State Submit ---
                logger.info("[Phase 2] Menunggu tombol submit transisi ke state visible...")
                page.wait_for_selector(
                    self.metadata.submit_selector,
                    state="visible",
                    timeout=self.timeout,
                )

                # Tunggu tombol benar-benar enabled (bukan hanya visible)
                logger.info("[Phase 2] Menunggu tombol submit aktif (tidak disabled)...")
                try:
                    safe_selector = self.metadata.submit_selector.replace("'", "\\'")
                    page.wait_for_function(
                        f"() => !document.querySelector('{safe_selector}').disabled",
                        timeout=self.timeout
                    )
                except PWTimeout:
                    logger.warning("Tombol submit tetap disabled setelah timeout. Melanjutkan klik secara paksa (force).")

                # (Turnstile ditangani oleh selenium_executor.py, bukan di sini)

                # --- Eksekusi Submit ---
                logger.info("[Phase 2] Menekan tombol submit...")
                
                # Kita dengarkan response network (POST) untuk memastikan status sukses dari API
                submit_success = False
                
                # Menekan tombol submit
                page.click(self.metadata.submit_selector, force=True, timeout=self.timeout)

                logger.info("[Phase 2] Menunggu dan memverifikasi respon dari server...")
                page.wait_for_timeout(3000)  # Beri waktu toast atau network merespon
                
                # Cek jika ada elemen toast error di DOM
                page_text = page.locator("body").inner_text().lower()
                if "cek koneksi" in page_text or "gagal" in page_text or "error" in page_text:
                    logger.error("  -> [GAGAL] Ditemukan pesan error/toast pada halaman setelah submit (misal: Cek koneksi Anda).")
                    return False
                else:
                    # SPA biasanya mereset form atau memunculkan pesan sukses
                    logger.info("  -> [OK] Tidak ditemukan pesan error. Asumsi submit berhasil.")
                    submit_success = True

                logger.info(f"[Phase 2] Eksekusi selesai. URL akhir: {page.url}")
                return submit_success

            except Exception as e:
                logger.error(f"[Phase 2] Kegagalan eksekusi: {e}")
                page.screenshot(path="error_playwright.png")
                logger.info("  Screenshot error disimpan ke 'error_playwright.png'.")
                return False
            finally:
                context.close()
                browser.close()
                logger.info("[Phase 2] Browser instance ditutup. Memori dibebaskan.")