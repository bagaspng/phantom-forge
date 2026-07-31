# executor.py
# Fase 2: Eksekusi pengisian form dengan Playwright + event native JavaScript.
# Dependensi: pip install playwright && playwright install chromium

import logging
from typing import Optional
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from scanner import FormMetadata
from typing import Any

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

            try:
                # Navigasi dan tunggu hingga DOM siap (domcontentloaded lebih tahan terhadap script pelacakan yang lama)
                logger.info("[Phase 2] Navigasi ke URL target...")
                page.goto(self.metadata.url, wait_until="domcontentloaded", timeout=self.timeout)

                # --- Pengisian Field Form ---
                # Menggunakan FormMetadata dari Scanner dan mencocokkan dengan form_data (Data Bank)
                logger.info("[Phase 2] Mengisi field form berdasarkan mapping Scanner...")
                for field_name, selector in self.metadata.form_fields.items():
                    # Cari nilai di Data Bank berdasarkan nama field (case-insensitive)
                    value = form_data.get(field_name.lower())
                    if not value:
                        logger.warning(f"  [SKIP] Tidak ada data di Bank Data untuk field wajib: '{field_name}'. Melewati field ini.")
                        continue
                        
                    page.fill(selector, value, timeout=self.timeout)
                    logger.info(f"  -> [OK] '{field_name}' → '{selector}' terisi dengan '{value}'.")

                # --- Pemicu Captcha Gate ---
                if self.metadata.captcha.detected and solver:
                    logger.info(f"[Phase 2] Menggunakan solver untuk: {self.metadata.captcha.provider}")
                    solver.solve(page, self.metadata.captcha)
                # --- Validasi State Submit ---
                # Playwright's wait_for_selector does not support state="enabled". Valid states are: attached, detached, visible, hidden.
                # We wait for the button to be visible, then ensure it is enabled before clicking.
                logger.info("[Phase 2] Menunggu tombol submit transisi ke state visible...")
                page.wait_for_selector(
                    self.metadata.submit_selector,
                    state="visible",
                    timeout=self.timeout,
                )
                
                # Tunggu jika tombol sedang disabled (sering terjadi jika validator React/Vue ada animasi delay)
                logger.info("[Phase 2] Menunggu tombol submit aktif (tidak disabled)...")
                try:
                    # Menghindari syntax error pada string JS jika selector menggunakan single quote
                    safe_selector = self.metadata.submit_selector.replace("'", "\\'")
                    page.wait_for_function(
                        f"() => !document.querySelector('{safe_selector}').disabled",
                        timeout=self.timeout
                    )
                except PWTimeout:
                    logger.warning("Tombol submit tetap disabled setelah timeout. Melanjutkan klik secara paksa (force).")

                # --- Eksekusi Submit ---
                logger.info("[Phase 2] Menekan tombol submit...")
                page.click(self.metadata.submit_selector, force=True, timeout=self.timeout)

                # Tunggu respons server setelah submit
                # Pada SPA, seringkali tidak ada navigasi (page reload), sehingga wait_for_load_state bisa timeout.
                # Kita coba tunggu sejenak untuk memberi waktu XHR selesai.
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except PWTimeout:
                    logger.info("  [INFO] Timeout saat menunggu networkidle pasca-submit (Wajar untuk SPA tanpa navigasi).")
                    # Fallback sleep singkat untuk memastikan request terkirim
                    page.wait_for_timeout(3000)
                logger.info(f"[Phase 2] Eksekusi selesai. URL akhir: {page.url}")
                return True

            except Exception as e:
                logger.error(f"[Phase 2] Kegagalan eksekusi: {e}")
                page.screenshot(path="error_playwright.png")
                logger.info("  Screenshot error disimpan ke 'error_playwright.png'.")
                return False
            finally:
                context.close()
                browser.close()
                logger.info("[Phase 2] Browser instance ditutup. Memori dibebaskan.")