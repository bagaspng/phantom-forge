# main.py
# Orkestrator utama — Strict Deterministic Routing berdasarkan output Phase 1 (FormScanner).
#
# Matriks Routing Engine:
# ┌──────────────────────────────────┬────────────────────────────┬────────────────┐
# │ Captcha Type                     │ Engine                     │ Mode           │
# ├──────────────────────────────────┼────────────────────────────┼────────────────┤
# │ NONE / native / math_puzzle      │ Playwright (executor.py)   │ headless=True  │
# │ google_recaptcha                 │ Playwright (executor.py)   │ headless=True  │
# │ cloudflare_turnstile             │ Selenium (selenium_exec.)  │ headless=False │
# └──────────────────────────────────┴────────────────────────────┴────────────────┘

import logging
from scanner import FormScanner
from executor import FormExecutor
from selenium_executor import TurnstileFormExecutor
from config import Config
from solver import MathPuzzleSolver, GoogleRecaptchaAudioSolver

QNN_CONFIG = Config()

# ---------------------------------------------------------------------------
# Solver factory — hanya untuk engine Playwright
# Turnstile TIDAK membutuhkan solver object karena ditangani penuh oleh
# TurnstileFormExecutor yang membungkus turnstile_solver.solver.Solver.
# ---------------------------------------------------------------------------
def get_playwright_solver(provider: str):
    if provider == "math_puzzle":
        return MathPuzzleSolver()
    elif provider == "google_recaptcha":
        return GoogleRecaptchaAudioSolver()
    return None


logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("XoS-Main")

# Captcha yang ditangani Playwright executor
PLAYWRIGHT_CAPTCHA_TYPES = {"", "native", "math_puzzle", "google_recaptcha"}

# Captcha yang memerlukan Selenium executor (GUI penuh)
SELENIUM_CAPTCHA_TYPES = {"cloudflare_turnstile"}


def run_hybrid_automation(target_url: str, form_data: dict, proxy_url: str = None) -> bool:
    logger.info(f"Memulai automasi hybrid untuk target: {target_url}")

    # =========================================================================
    # PHASE 1: Scan DOM — deteksi field, captcha, dan honeypot
    # =========================================================================
    scanner = FormScanner(url=target_url, timeout=30)
    try:
        metadata = scanner.scan()
    except Exception as e:
        logger.error(f"[Phase 1] GAGAL: {e}")
        return False

    if not metadata.form_fields:
        logger.error(
            "─── Phase 1 DIHENTIKAN: Tidak ada field form valid yang ditemukan. "
            "(Aborting — tidak ada eksekusi browser) ───"
        )
        return False

    captcha_provider = metadata.captcha.provider if metadata.captcha.detected else ""

    # =========================================================================
    # ROUTING — Tentukan engine berdasarkan captcha_type
    # =========================================================================
    if captcha_provider in SELENIUM_CAPTCHA_TYPES:
        # ─────────────────────────────────────────────────────────────────────
        # ROUTE A: Cloudflare Turnstile → Selenium + UC-Driver (GUI mode)
        # ─────────────────────────────────────────────────────────────────────
        logger.info(
            f"[ROUTER] Captcha '{captcha_provider}' terdeteksi → "
            f"Menggunakan Selenium Executor (GUI / headless=False)"
        )
        MAX_RETRIES = 3
        for attempt in range(1, MAX_RETRIES + 1):
            logger.info(f"Percobaan {attempt}/{MAX_RETRIES}...")
            executor = TurnstileFormExecutor(
                metadata=metadata,
                proxy_url=proxy_url,
                detect_timeout=20,
                solve_timeout=60,
                token_timeout=15,
                click_method="hybrid",
            )
            success = executor.execute(form_data)
            if success:
                logger.info("─── Siklus automasi selesai dengan status: BERHASIL ───")
                return True
            logger.warning(f"Percobaan {attempt} gagal.")
            if attempt < MAX_RETRIES:
                logger.info("Menginisialisasi ulang executor...")

        logger.error("─── Siklus automasi selesai dengan status: GAGAL ───")
        return False

    elif captcha_provider in PLAYWRIGHT_CAPTCHA_TYPES:
        # ─────────────────────────────────────────────────────────────────────
        # ROUTE B: Tanpa captcha / Native / reCAPTCHA → Playwright (headless)
        # ─────────────────────────────────────────────────────────────────────
        if captcha_provider:
            logger.info(
                f"[ROUTER] Captcha '{captcha_provider}' terdeteksi → "
                f"Menggunakan Playwright Executor (headless=True)"
            )
        else:
            logger.info("[ROUTER] Tidak ada captcha → Playwright Executor (headless=True)")

        solver = get_playwright_solver(captcha_provider) if captcha_provider else None
        if captcha_provider and solver is None and captcha_provider not in {"", "native"}:
            logger.error(
                f"FAILED\nReason:\nCaptcha detected: {captcha_provider}\n"
                f"Solver: Not Available\nAutomation stopped."
            )
            return False

        MAX_RETRIES = 3
        for attempt in range(1, MAX_RETRIES + 1):
            logger.info(f"Percobaan {attempt}/{MAX_RETRIES}...")
            executor = FormExecutor(
                metadata=metadata,
                proxy_url=proxy_url,
                headless=True,
            )
            success = executor.execute(form_data, solver=solver)
            if success:
                logger.info("─── Siklus automasi selesai dengan status: BERHASIL ───")
                return True
            logger.warning(f"Percobaan {attempt} gagal.")
            if attempt < MAX_RETRIES:
                logger.info("Menginisialisasi ulang executor...")

        logger.error("─── Siklus automasi selesai dengan status: GAGAL ───")
        return False

    else:
        # ─────────────────────────────────────────────────────────────────────
        # ROUTE C: Captcha tidak dikenal — abort
        # ─────────────────────────────────────────────────────────────────────
        logger.error(
            f"[ROUTER] ABORT — Captcha tipe '{captcha_provider}' tidak didukung oleh engine manapun. "
            f"Tambahkan solver baru atau daftarkan ke routing table."
        )
        return False


if __name__ == "__main__":
    run_hybrid_automation(
        target_url=QNN_CONFIG.url,
        form_data=QNN_CONFIG.form_data_bank,
        proxy_url=None,
    )
