# solver.py
import re
import logging
import os
import urllib.request
import random
import pydub
import speech_recognition
import time
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


class GoogleRecaptchaAudioSolver(BaseCaptchaSolver):
    TEMP_DIR = os.getenv("TEMP") if os.name == "nt" else "/tmp"
    
    def solve(self, page: Any, captcha_metadata: Any) -> None:
        logger.info("Memulai pemecahan Google reCAPTCHA menggunakan Audio Challenge.")
        
        # 1. Menunggu iframe recaptcha utama muncul (checkbox)
        try:
            # Gunakan pseudo-class :visible untuk menghindari iframe ganda yang tersembunyi
            recaptcha_frame = page.wait_for_selector("iframe[title*='reCAPTCHA']:visible", timeout=10000)
            frame = recaptcha_frame.content_frame()
            if not frame:
                raise ValueError("Tidak dapat mengakses context frame reCAPTCHA")
                
            logger.info("  -> Menekan checkbox reCAPTCHA...")
            frame.click(".rc-anchor-content", timeout=5000)
        except Exception as e:
            raise RuntimeError(f"Gagal memicu checkbox reCAPTCHA: {e}")
            
        # Tunggu animasi
        page.wait_for_timeout(3000)
        
        # Cek jika langsung lolos tanpa challenge
        if self._is_solved(page):
            logger.info("  -> [OK] reCAPTCHA langsung terselesaikan (One-click pass).")
            return
            
        # 2. Beralih ke frame challenge
        logger.info("  -> Beralih ke tantangan reCAPTCHA...")
        # Mencari iframe challenge yang terlihat atau menggunakan selector bframe
        try:
            challenge_frame_element = page.wait_for_selector("iframe[src*='bframe']:visible", timeout=10000)
        except Exception:
            # Fallback
            challenge_frame_element = page.wait_for_selector("iframe[title*='recaptcha challenge']:visible", timeout=10000)
            
        challenge_frame = challenge_frame_element.content_frame()
        if not challenge_frame:
             raise ValueError("Tidak dapat mengakses frame challenge reCAPTCHA")
             
        # 3. Klik tombol audio
        logger.info("  -> Mengakses Audio Challenge...")
        try:
            audio_btn = challenge_frame.wait_for_selector("#recaptcha-audio-button", timeout=5000)
            audio_btn.scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            audio_btn.click()
        except Exception as e:
            raise RuntimeError(f"Gagal menekan tombol audio reCAPTCHA. Kemungkinan IP di-flag: {e}")
            
        page.wait_for_timeout(2000)
        
        if self._is_detected(challenge_frame):
            raise RuntimeError("Captcha mendeteksi perilaku bot (Rate limited).")
            
        # 4. Ambil URL audio
        try:
            audio_src_ele = challenge_frame.wait_for_selector("#audio-source", state="attached", timeout=5000)
            audio_url = audio_src_ele.get_attribute("src")
            if not audio_url:
                raise ValueError("URL sumber audio kosong.")
            logger.info(f"  -> URL Audio didapatkan.")
        except Exception as e:
            raise RuntimeError(f"Gagal mendapatkan URL audio: {e}")
            
        # 5. Proses audio
        try:
            logger.info("  -> Mengunduh dan mentranskripsi audio...")
            text_response = self._process_audio_challenge(audio_url)
            logger.info(f"  -> Hasil Transkripsi: '{text_response}'")
            
            # 6. Injeksi jawaban
            challenge_frame.fill("#audio-response", text_response.lower())
            challenge_frame.click("#recaptcha-verify-button")
            page.wait_for_timeout(2000)
            
            if not self._is_solved(page):
                raise RuntimeError("Gagal memecahkan captcha setelah injeksi audio.")
                
            logger.info("  -> [OK] reCAPTCHA berhasil dipecahkan.")
        except Exception as e:
            raise RuntimeError(f"Gagal memecahkan audio challenge: {e}")

    def _process_audio_challenge(self, audio_url: str) -> str:
        mp3_path = os.path.join(self.TEMP_DIR, f"recaptcha_{random.randrange(1,1000)}.mp3")
        wav_path = os.path.join(self.TEMP_DIR, f"recaptcha_{random.randrange(1,1000)}.wav")

        try:
            urllib.request.urlretrieve(audio_url, mp3_path)
            
            # Konversi mp3 ke wav menggunakan pydub
            sound = pydub.AudioSegment.from_mp3(mp3_path)
            sound.export(wav_path, format="wav")

            # Kenali suara
            recognizer = speech_recognition.Recognizer()
            with speech_recognition.AudioFile(wav_path) as source:
                audio = recognizer.record(source)

            return recognizer.recognize_google(audio)
        finally:
            for path in (mp3_path, wav_path):
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                        
    def _is_solved(self, page) -> bool:
        try:
            frame_ele = page.wait_for_selector("iframe[title*='reCAPTCHA']", timeout=2000)
            frame = frame_ele.content_frame()
            checkbox = frame.wait_for_selector(".recaptcha-checkbox", timeout=2000)
            return checkbox.get_attribute("aria-checked") == "true"
        except Exception:
            return False

    def _is_detected(self, challenge_frame) -> bool:
        try:
            # Cek class spesifik DOS captcha dari Google
            msg = challenge_frame.query_selector(".rc-doscaptcha-header-text, .rc-doscaptcha-body-text")
            return msg is not None
        except Exception:
            return False
