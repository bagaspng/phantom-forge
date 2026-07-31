from playwright.sync_api import sync_playwright
from solver import GoogleRecaptchaAudioSolver
import time
import logging

logging.basicConfig(level=logging.INFO)

class DummyMetadata:
    pass

def test_solver():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto("https://www.google.com/recaptcha/api2/demo")
        
        solver = GoogleRecaptchaAudioSolver()
        try:
            solver.solve(page, DummyMetadata())
            print("Successfully solved!")
        except Exception as e:
            print(f"Error solving: {e}")
            
        time.sleep(2)
        page.click("#recaptcha-demo-submit")
        time.sleep(2)
        browser.close()

if __name__ == "__main__":
    test_solver()
