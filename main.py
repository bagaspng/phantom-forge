# main.py
import logging
from scanner import FormScanner
from executor import FormExecutor
from config import QNN_CONFIG

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("XoS-Main")

def run_hybrid_automation(target_url: str, form_data: dict, proxy_url: str = None) -> bool:
    logger.info(f"Memulai automasi hybrid untuk target: {target_url}")
    
    # Phase 1: Scan
    scanner = FormScanner(url=target_url, timeout=10)
    try:
        metadata = scanner.scan()
    except Exception as e:
        logger.error(f"Fase 1 Gagal: {e}")
        return False
        
    if not metadata.form_fields:
        logger.error("─── Fase 1 dihentikan: Tidak ada field form valid yang ditemukan pada DOM target. (Aborting Phase 2) ───")
        return False
        
    # Phase 2-4: Execute with Retry Logic
    MAX_RETRIES = 3
    for attempt in range(1, MAX_RETRIES + 1):
        logger.info(f"Percobaan {attempt}/{MAX_RETRIES}...")
        executor = FormExecutor(metadata=metadata, proxy_url=proxy_url)
        success = executor.execute(form_data)
        if success:
            logger.info("─── Siklus automasi selesai dengan status: BERHASIL ───")
            return True
            
        logger.warning(f"Percobaan {attempt} gagal.")
        if attempt < MAX_RETRIES:
            logger.info("Menginisialisasi ulang executor...")
            
    logger.error("─── Siklus automasi selesai dengan status: GAGAL ───")
    return False

if __name__ == "__main__":
    run_hybrid_automation(
        target_url=QNN_CONFIG.url,
        form_data=QNN_CONFIG.form_data_bank,
        proxy_url=None
    )
