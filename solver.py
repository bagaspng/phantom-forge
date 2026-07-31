# solver.py
import re
import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger("XoS-Solver")

class BaseCaptchaSolver(ABC):
    @abstractmethod
    def solve(self, page: Any, captcha_metadata: Any) -> None:
        """
        Selesaikan captcha pada halaman (menggunakan Playwright Page)
        berdasarkan metadata yang diberikan.
        """
        pass

class MathPuzzleSolver(BaseCaptchaSolver):
    def solve(self, page: Any, captcha_metadata: Any) -> None:
        signature = captcha_metadata.data.get('signature', '')
        logger.info(f"Memicu captcha gate: {signature}")
        
        if signature:
            page.click(signature, timeout=5000)
            
        # Ekstrak payload string dari soal matematika
        question_text = ""
        
        # Coba tunggu elemen pertanyaan muncul menggunakan MutationObserver implisit
        try:
            page.wait_for_selector("p:has-text('Pertanyaan:') + p", timeout=5000, state="visible")
            question_text = page.inner_text("p:has-text('Pertanyaan:') + p").strip()
        except Exception:
            pass
            
        # Fallback: cari pola teks alternatif jika struktur HTML berbeda
        if not question_text:
            try:
                question_text = page.evaluate("""
                    () => {
                        const paragraphs = [...document.querySelectorAll('p')];
                        const marker = paragraphs.find(p => p.textContent.includes('Pertanyaan:'));
                        return marker?.nextElementSibling?.textContent?.trim() || null;
                    }
                """)
            except Exception:
                pass
                
        if not question_text:
            raise ValueError("Ekstraksi payload captcha gagal pada strategi MathPuzzleSolver.")

        logger.info(f"  -> Payload captcha: '{question_text}'")
        
        # Solve
        match = re.search(r'(\d+)\s*([\+\-\*])\s*(\d+)', question_text)
        if not match:
            logger.warning("Tidak dapat mengekstrak pola puzzle dari teks.")
            ans = "0"
        else:
            num1 = int(match.group(1))
            op = match.group(2)
            num2 = int(match.group(3))
            if op == '+': ans = num1 + num2
            elif op == '-': ans = num1 - num2
            elif op == '*': ans = num1 * num2
            else: ans = 0
            ans = str(ans)
            
        logger.info(f"  -> Kalkulasi solver: {ans}")
        
        # Injeksi ke input
        captcha_input_selector = "input[name='captcha_answer']"
        # We need a robust way if captcha_input_selector doesn't exist, but since FormExecutor filled everything else, 
        # doing an injection via XPath or fallback text input is required.
        # Let's keep it simple or use the fallback from old executor.
        if not page.query_selector(captcha_input_selector):
            captcha_input_selector = "input[type='text']:not([readonly]):not([disabled])"
            
        page.fill(captcha_input_selector, ans)
        logger.info("  -> [OK] Jawaban captcha diinjeksi ke field target.")
