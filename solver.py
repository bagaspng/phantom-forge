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


class CloudflareTurnstileSolver(BaseCaptchaSolver):
    """
    Menyelesaikan Cloudflare Turnstile via Playwright Page.
    Strategi multi-layer (mirip turnstile_solver module):
    1. DOM Location - cari .cf-turnstile container atau iframe challenges.cloudflare.com
    2. Shadow DOM traversal - untuk widget tersembunyi di shadow root
    3. Token extraction - coba ambil token via window.turnstile.getResponse()
    4. Human-like click dengan behavioral entropy
    5. Verifikasi token cf-turnstile-response
    """
    def solve(self, page: Any, captcha_metadata: Any) -> None:
        logger.info("Memulai penyelesaian Cloudflare Turnstile.")

        # Strategi 1: Coba ekstrak token langsung (invisible/managed mode)
        if self._try_extract_token(page):
            logger.info("  -> Token Turnstile sudah tersedia (invisible mode), tidak perlu klik.")
            return

        # Strategi 2: Tunggu dan lokasi widget via DOM
        widget_info = self._locate_widget(page)
        if not widget_info:
            logger.warning("  [WARN] Widget Turnstile tidak terdeteksi setelah strategi penuh.")
            logger.info("  -> Melewati penyelesaian Turnstile (asumsi tidak aktif/dihilangkan oleh server target).")
            return

        # Strategi 3: Klik checkbox dengan gerakan manusia
        self._human_click_checkbox(page, widget_info)

        # Strategi 4: Tunggu token terisi
        self._wait_for_token(page)
        logger.info("Penyelesaian Cloudflare Turnstile selesai.")

    def _try_extract_token(self, page: Any) -> bool:
        """Coba ambil token via window.turnstile.getResponse() untuk invisible mode."""
        try:
            result = page.evaluate("""
                () => {
                    if (typeof window.turnstile === 'undefined') return false;
                    const containers = document.querySelectorAll('.cf-turnstile, [data-sitekey]');
                    for (const container of containers) {
                        try {
                            const widgetId = container.getAttribute('data-widget-id') || container.dataset.widgetId;
                            if (widgetId) {
                                const token = window.turnstile.getResponse(widgetId);
                                if (token && token.length > 50) {
                                    return true;
                                }
                            }
                        } catch(e) {}
                    }
                    return false;
                }
            """)
            return result
        except Exception:
            return False

    def _locate_widget(self, page: Any) -> dict | None:
        """
        Lokasi widget Turnstile via multiple strategies.
        Return: dict dengan x, y, width, height, frame (iframe element atau None)
        """
        # Strategi A: Cari .cf-turnstile container di main frame
        try:
            widget = page.wait_for_selector(".cf-turnstile", state="attached", timeout=8000)
            if widget:
                box = widget.bounding_box()
                if box:
                    logger.info("  -> Widget Turnstile ditemukan di main frame (.cf-turnstile).")
                    return {"x": box["x"], "y": box["y"], "width": box["width"], "height": box["height"], "frame": None}
        except Exception:
            pass

        # Strategi B: Cari iframe challenges.cloudflare.com
        try:
            iframe = page.wait_for_selector("iframe[src*='challenges.cloudflare.com']", state="attached", timeout=5000)
            if iframe:
                box = iframe.bounding_box()
                if box:
                    logger.info("  -> Widget Turnstile ditemukan di iframe challenges.cloudflare.com.")
                    # Switch ke frame iframe
                    frame = iframe.content_frame()
                    if frame:
                        # Di dalam iframe, cari checkbox
                        inner_widget = frame.wait_for_selector(".cf-turnstile, .widget", state="attached", timeout=5000)
                        if inner_widget:
                            inner_box = inner_widget.bounding_box()
                            if inner_box:
                                # Koordinat relatif ke viewport main frame
                                return {
                                    "x": box["x"] + inner_box["x"],
                                    "y": box["y"] + inner_box["y"],
                                    "width": inner_box["width"],
                                    "height": inner_box["height"],
                                    "frame": frame
                                }
                        # Fallback: gunakan center iframe
                        return {
                            "x": box["x"] + box["width"] / 2,
                            "y": box["y"] + box["height"] / 2,
                            "width": box["width"],
                            "height": box["height"],
                            "frame": frame
                        }
        except Exception:
            pass

        # Strategi C: Shadow DOM traversal
        try:
            result = page.evaluate("""
                () => {
                    function findInShadow(root) {
                        if (!root) return null;
                        // Cari di shadow root
                        if (root.shadowRoot) {
                            const widget = root.shadowRoot.querySelector('.cf-turnstile, iframe[src*="challenges.cloudflare.com"]');
                            if (widget) return widget;
                            // Rekursif ke nested shadow roots
                            for (const el of root.shadowRoot.querySelectorAll('*')) {
                                const found = findInShadow(el);
                                if (found) return found;
                            }
                        }
                        // Cari di light DOM
                        const widget = root.querySelector?.('.cf-turnstile, iframe[src*="challenges.cloudflare.com"]');
                        if (widget) return widget;
                        for (const el of root.querySelectorAll?.('*') || []) {
                            const found = findInShadow(el);
                            if (found) return found;
                        }
                        return null;
                    }
                    return findInShadow(document.body);
                }
            """)
            if result:
                # Evaluate bounding box di browser context
                box = page.evaluate("""(el) => el.getBoundingClientRect()""", result)
                if box:
                    logger.info("  -> Widget Turnstile ditemukan via Shadow DOM traversal.")
                    return {"x": box["x"], "y": box["y"], "width": box["width"], "height": box["height"], "frame": None}
        except Exception:
            pass

        # Strategi D: Cari via postMessage listener (invisible mode yang butuh trigger)
        try:
            # Trigger render jika ada data-sitekey tapi belum dirender
            page.evaluate("""
                () => {
                    if (typeof window.turnstile !== 'undefined' && window.turnstile.render) {
                        const containers = document.querySelectorAll('[data-sitekey]:not(.cf-turnstile)');
                        containers.forEach(c => {
                            if (!c.querySelector('.cf-turnstile')) {
                                try { window.turnstile.render(c); } catch(e) {}
                            }
                        });
                    }
                }
            """)
            page.wait_for_timeout(2000)
            # Coba lagi strategi A
            widget = page.wait_for_selector(".cf-turnstile", state="attached", timeout=5000)
            if widget:
                box = widget.bounding_box()
                if box:
                    logger.info("  -> Widget Turnstile muncul setelah trigger render.")
                    return {"x": box["x"], "y": box["y"], "width": box["width"], "height": box["height"], "frame": None}
        except Exception:
            pass

        return None

    def _human_click_checkbox(self, page: Any, widget_info: dict) -> None:
        """Klik checkbox dengan gerakan mouse human-like (behavioral entropy)."""
        x = widget_info["x"] + widget_info["width"] / 2
        y = widget_info["y"] + widget_info["height"] / 2

        # Dapatkan posisi mouse saat ini
        try:
            start = page.evaluate("() => window._mousePos || { x: window.innerWidth/2, y: window.innerHeight/2 }")
            start_x, start_y = start["x"], start["y"]
        except Exception:
            start_x, start_y = page.mouse._x, page.mouse._y

        # Generate Bézier path dengan Gaussian noise
        path = self._generate_bezier_path(start_x, start_y, x, y)

        # Phase 1: Smooth movement
        for px, py in path:
            page.mouse.move(px, py)
            page.wait_for_timeout(random.randint(5, 20))

        # Phase 2: Pre-click hesitation
        page.wait_for_timeout(random.randint(100, 300))

        # Phase 3: Click
        target_frame = widget_info.get("frame") or page
        checkbox = target_frame.locator("input[type='checkbox']").first
        if checkbox.count() > 0:
            checkbox.click()
        else:
            # Fallback: click di koordinat
            page.mouse.click(x, y)

        logger.info(f"  -> Checkbox Turnstile diklik di ({int(x)}, {int(y)}) via {'iframe' if widget_info.get('frame') else 'main frame'}.")
        page.wait_for_timeout(3000)

    def _generate_bezier_path(self, start_x: float, start_y: float, end_x: float, end_y: float, steps: int = 30) -> list:
        """Generate quadratic Bézier curve dengan Gaussian control point dan easing."""
        import math
        dx = end_x - start_x
        dy = end_y - start_y
        distance = math.hypot(dx, dy)

        if distance < 1:
            return [(int(end_x), int(end_y))]

        # Control point dengan Gaussian offset (25% distance)
        ctrl_offset = distance * 0.25
        ctrl_x = (start_x + end_x) / 2 + random.gauss(0, ctrl_offset / 2)
        ctrl_y = (start_y + end_y) / 2 + random.gauss(0, ctrl_offset / 2)

        path = []
        for i in range(steps + 1):
            t = i / steps
            # Ease-out cubic (Fitts' law: deceleration near target)
            t_eased = 1 - (1 - t) ** 3

            # Quadratic Bézier
            x = (1 - t_eased) ** 2 * start_x + 2 * (1 - t_eased) * t_eased * ctrl_x + t_eased ** 2 * end_x
            y = (1 - t_eased) ** 2 * start_y + 2 * (1 - t_eased) * t_eased * ctrl_y + t_eased ** 2 * end_y

            # Micro-tremor noise
            x += random.gauss(0, 1.5)
            y += random.gauss(0, 1.5)

            path.append((int(round(x)), int(round(y))))

        return path

    def _wait_for_token(self, page: Any, timeout: int = 20000) -> bool:
        """Tunggu token cf-turnstile-response terisi."""
        try:
            page.wait_for_function(
                "document.querySelector('[name=\"cf-turnstile-response\"]')?.value?.length > 0",
                timeout=timeout
            )
            logger.info("  -> [OK] Token Turnstile terdeteksi.")
            return True
        except Exception:
            logger.warning("  [WARN] Token Turnstile tidak terisi dalam waktu timeout.")
            return False
