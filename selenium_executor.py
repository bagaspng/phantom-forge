# selenium_executor.py
# Executor khusus untuk target yang dilindungi Cloudflare Turnstile.
# Menggunakan Selenium + undetected-chromedriver dalam mode GUI (headless=False)
# agar fingerprint browser sedekat mungkin dengan pengguna nyata.

import logging
import time
import random
from typing import Optional

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from scanner import FormMetadata
from turnstile_solver.sync_solver import build_uc_driver, read_turnstile_token
from turnstile_solver.solver import Solver

logger = logging.getLogger("XoS-SeleniumExecutor")


# ---------------------------------------------------------------------------
# Helper: humanized typing untuk Selenium
# (Playwright humanizer.py tidak kompatibel dengan Selenium — buat versi sendiri)
# ---------------------------------------------------------------------------

def _human_type_selenium(element, text: str) -> None:
    """
    Simulasi pengetikan manusia pada Selenium WebElement.
    Distribusi delay: lognormal(mu=-2.5, sigma=0.5), clamp [20ms, 300ms].
    5% peluang cognitive pause (400–1200ms).
    """
    import math
    element.clear()
    for char in text:
        delay_s = random.lognormvariate(-2.5, 0.5)
        delay_s = max(0.02, min(0.3, delay_s))
        if random.random() < 0.05:
            delay_s += random.uniform(0.4, 1.2)
        element.send_keys(char)
        time.sleep(delay_s)
    # Terminal pause
    time.sleep(random.uniform(0.3, 0.8))


class TurnstileFormExecutor:
    """
    Mengeksekusi pengisian form pada halaman yang dilindungi Cloudflare Turnstile.

    Alur kerja:
    1. Inisialisasi UC-driver (undetected-chromedriver, GUI mode)
    2. Navigasi ke URL target
    3. Isi semua field form dengan pengetikan humanized
    4. Jalankan Turnstile solver (detect → solve → tunggu token)
    5. Submit form & verifikasi hasil
    """

    def __init__(
        self,
        metadata: FormMetadata,
        proxy_url: Optional[str] = None,
        detect_timeout: int = 20,
        solve_timeout: int = 60,
        token_timeout: int = 15,
        click_method: str = "hybrid",
    ):
        self.metadata = metadata
        self.proxy_url = proxy_url
        self.detect_timeout = detect_timeout
        self.solve_timeout = solve_timeout
        self.token_timeout = token_timeout
        self.click_method = click_method

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def execute(self, form_data: dict) -> bool:
        """
        Eksekusi penuh: isi form, solve Turnstile, submit.
        Return: True jika proses selesai tanpa exception fatal, False jika gagal.
        """
        logger.info(f"[Phase 2 / Selenium] Inisialisasi UC-driver untuk: {self.metadata.url}")
        driver = build_uc_driver(headless=False)

        try:
            # --- Navigasi ---
            logger.info("[Phase 2 / Selenium] Navigasi ke URL target...")
            driver.get(self.metadata.url)
            # Tunggu DOM stabil (lebih handal dari time.sleep konstan)
            WebDriverWait(driver, 15).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            # Jeda manusiawi setelah halaman muat
            time.sleep(random.uniform(1.5, 3.0))

            # --- Isi Field Form ---
            logger.info("[Phase 2 / Selenium] Mengisi field form (humanized)...")
            self._fill_fields(driver, form_data)

            # --- Solve Turnstile ---
            logger.info("[Phase 2 / Selenium] Menjalankan Turnstile solver...")
            token = self._solve_turnstile(driver)
            if token:
                logger.info(f"  -> [OK] Token Turnstile diperoleh (panjang={len(token)}).")
            else:
                logger.warning(
                    "  [WARN] Token Turnstile tidak berhasil diperoleh. "
                    "Submit tetap dilanjutkan (mungkin invisible mode sudah auto-verified)."
                )

            # --- Submit ---
            logger.info("[Phase 2 / Selenium] Menekan tombol submit...")
            success = self._submit(driver)

            if success:
                logger.info(f"[Phase 2 / Selenium] Eksekusi selesai. URL akhir: {driver.current_url}")
            else:
                logger.error("[Phase 2 / Selenium] Submit terdeteksi GAGAL berdasarkan respons halaman.")

            return success

        except Exception as e:
            logger.error(f"[Phase 2 / Selenium] Kegagalan eksekusi: {e}")
            try:
                driver.save_screenshot("error_selenium.png")
                logger.info("  Screenshot error disimpan ke 'error_selenium.png'.")
            except Exception:
                pass
            return False

        finally:
            try:
                driver.quit()
            except Exception:
                pass
            logger.info("[Phase 2 / Selenium] Browser instance ditutup. Memori dibebaskan.")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fill_fields(self, driver, form_data: dict) -> None:
        """Isi semua field form berdasarkan mapping dari FormMetadata."""
        wait = WebDriverWait(driver, 10)

        for field_name, selector in self.metadata.form_fields.items():
            value = form_data.get(field_name.lower())
            if not value:
                logger.warning(
                    f"  [SKIP] Tidak ada data di Bank Data untuk field '{field_name}'. Melewati."
                )
                continue

            try:
                # Konversi CSS selector Playwright (contoh: [name='nama']) ke Selenium
                element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
                # Scroll ke elemen agar terlihat (mirip perilaku manusia)
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                time.sleep(random.uniform(0.2, 0.6))

                _human_type_selenium(element, value)
                logger.info(f"  -> [OK] '{field_name}' → '{selector}' terisi (humanized).")

            except (TimeoutException, NoSuchElementException) as e:
                logger.warning(f"  [WARN] Field '{field_name}' tidak ditemukan dengan selector '{selector}': {e}")

    def _solve_turnstile(self, driver) -> Optional[str]:
        """
        Jalankan turnstile_solver.solver.Solver untuk mendeteksi dan menyelesaikan widget.
        Return: token string jika berhasil, None jika gagal atau widget tidak muncul.
        """
        solver = Solver(
            driver,
            enable_logging=True,
            click_method=self.click_method,
        )
        try:
            detected = solver.detect(timeout=self.detect_timeout, interval=1)
            if not detected:
                logger.warning("  [WARN] Widget Turnstile tidak terdeteksi setelah polling.")
                solver.cleanup()
                return None

            logger.info(f"  -> Widget Turnstile terdeteksi: tipe='{detected}'")
            solved = solver.solve(timeout=self.solve_timeout, interval=1.5, verify=True)

            if not solved:
                logger.warning("  [WARN] Solver tidak dapat menyelesaikan Turnstile dalam timeout.")

            # Baca token dari DOM (polling sampai token_timeout)
            deadline = time.time() + self.token_timeout
            token = read_turnstile_token(driver)
            while not token and time.time() < deadline:
                time.sleep(0.5)
                token = read_turnstile_token(driver)

            return token

        finally:
            try:
                solver.cleanup()
            except Exception:
                pass

    def _submit(self, driver) -> bool:
        """
        Tekan tombol submit, tunggu respons, dan verifikasi hasilnya
        dengan memeriksa teks error/toast pada halaman.
        Return: True jika tidak ada indikator error, False jika ada.
        """
        wait = WebDriverWait(driver, 15)
        try:
            submit_btn = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, self.metadata.submit_selector))
            )
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", submit_btn)
            time.sleep(random.uniform(0.3, 0.8))
            submit_btn.click()
        except TimeoutException:
            # Force-click jika tombol masih disabled (mirip perilaku executor Playwright)
            logger.warning("Tombol submit tidak clickable setelah timeout. Mencoba force-click via JS...")
            try:
                btn = driver.find_element(By.CSS_SELECTOR, self.metadata.submit_selector)
                driver.execute_script("arguments[0].click();", btn)
            except NoSuchElementException as e:
                logger.error(f"Tombol submit tidak ditemukan: {e}")
                return False

        # Tunggu respons server
        time.sleep(3.5)

        # Cek teks error pada halaman (toast, alert, dsb)
        try:
            body_text = driver.find_element(By.TAG_NAME, "body").text.lower()
        except Exception:
            body_text = ""

        error_keywords = {"cek koneksi", "gagal", "error", "failed", "terjadi kesalahan"}
        success_keywords = {"terima kasih", "berhasil", "success", "pesan anda", "dikirim"}

        if any(kw in body_text for kw in error_keywords):
            logger.error(
                f"  -> [GAGAL] Ditemukan indikator error pada halaman setelah submit. "
                f"URL: {driver.current_url}"
            )
            return False

        if any(kw in body_text for kw in success_keywords):
            logger.info("  -> [OK] Indikator sukses ditemukan pada halaman.")
            return True

        # Ambiguous — tidak ada error juga tidak ada konfirmasi sukses
        logger.info("  -> [OK] Tidak ada pesan error terdeteksi. Asumsi submit berhasil.")
        return True
