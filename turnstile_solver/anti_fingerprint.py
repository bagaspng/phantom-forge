"""
anti_fingerprint.py
Layer 0: Pre-connection fingerprint evasion.
Patches CDP leak, injects Canvas/WebGL noise, spoofs navigator properties,
and masks automation signals before any page navigation occurs.
"""
from selenium import webdriver

# Stealth scripts injected via Page.addScriptToEvaluateOnNewDocument
STEALTH_SCRIPTS = [
    # 1. Mask navigator.webdriver (primary bot detection vector)
    """
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined
    });
    """,
    # 2. Spoof plugins array (headless has empty plugins)
    """
    Object.defineProperty(navigator, 'plugins', {
        get: () => [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeoLPo' },
            { name: 'Native Client', filename: 'internal-nacl-plugin' }
        ]
    });
    """,
    # 3. Spoof languages
    """
    Object.defineProperty(navigator, 'languages', {
        get: () => ['en-US', 'en', 'id']
    });
    """,
    # 4. Mask chrome runtime (missing in headless)
    """
    window.chrome = {
        runtime: {
            onMessage: { addListener: () => {}, removeListener: () => {} },
            sendMessage: () => {},
            connect: () => {}
        },
        loadTimes: () => {},
        csi: () => {}
    };
    """,
    # 5. Spoof permissions query
    """
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' ?
            Promise.resolve({ state: Notification.permission }) :
            originalQuery(parameters)
    );
    """,
    # 6. Canvas noise injection (defeats canvas fing  rinting)
    """
    const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function(type) {
        const ctx = this.getContext('2d');
        if (ctx) {
            const imageData = ctx.getImageData(0, 0, this.width, this.height);
            for (let i = 0; i < imageData.data.length; i += 4) {
                imageData.data[i] += Math.floor(Math.random() * 2);     // R
                imageData.data[i + 1] += Math.floor(Math.random() * 2); // G
            }
            ctx.putImageData(imageData, 0, 0);
        }
        return originalToDataURL.apply(this, arguments);
    };
    """,
    # 7. WebGL renderer spoof (masks GPU fingerprint)
    """
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(parameter) {
        if (parameter === 37445) return 'Intel Inc.';           // UNMASKED_VENDOR_WEBGL
        if (parameter === 37446) return 'Intel Iris OpenGL Engine'; // UNMASKED_RENDERER_WEBGL
        return getParameter.apply(this, arguments);
    };
    """,
    # 8. Mask AutomationControlled flag
    """
    Object.defineProperty(navigator, 'connection', {
        get: () => ({ rtt: 50, type: 'wifi', downlink: 10, saveData: false })
    });
    """,
    # 9. Spoof screen dimensions (headless often has 800x600)
    """
    Object.defineProperty(screen, 'width', { get: () => 1920 });
    Object.defineProperty(screen, 'height', { get: () => 1080 });
    Object.defineProperty(screen, 'availWidth', { get: () => 1920 });
    Object.defineProperty(screen, 'availHeight', { get: () => 1040 });
    """,
    # 10. Mask CDP Runtime domain leak
    """
    const originalError = Error;
    window.Error = function(message) {
        const err = new originalError(message);
        const stack = err.stack || '';
        if (stack.includes('Runtime.evaluate') || stack.includes('cdp')) {
            err.stack = stack.replace(/Runtime\\.evaluate|cdp/g, '');
        }
        return err;
    };
    """
]

def apply_stealth(driver: webdriver.Chrome) -> None:
    """
    Inject all stealth scripts before any page navigation.
    Must be called immediately after driver initialization.
    """
    combined_script = "\n".join(STEALTH_SCRIPTS)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": combined_script
    })

def get_stealth_chrome_options() -> webdriver.ChromeOptions:
    """
    Return ChromeOptions configured for stealth mode.
    """
    options = webdriver.ChromeOptions()
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--ignore-ssl-errors")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    return options

import undetected_chromedriver as uc

def apply_stealth_uc(driver: uc.Chrome) -> None:
    """
    Inject advanced stealth scripts (WebGL/Canvas noise) on top of UC's native patches.
    """
    # Hanya pertahankan skrip 6 (Canvas) dan 7 (WebGL) karena UC sudah menangani sisanya
    advanced_stealth = [STEALTH_SCRIPTS[5], STEALTH_SCRIPTS[6]] 
    combined_script = "\n".join(advanced_stealth)
    
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": combined_script
    })

def get_stealth_chrome_options_uc() -> uc.ChromeOptions:
    """
    Return UC ChromeOptions configured for stealth mode.
    """
    options = uc.ChromeOptions()
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--ignore-ssl-errors")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1920,1080")
    return options    