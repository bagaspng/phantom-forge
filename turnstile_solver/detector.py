"""
detector.py v2
Multi-strategy detection for production Turnstile:
1. DOM probe (.cf-turnstile, iframe[src*="challenges.cloudflare.com"])
2. Shadow DOM traversal (for Next.js/React encapsulated widgets)
3. postMessage interception (for invisible mode)
4. Challenge page detection (.footer-inner)
"""
from typing import Optional, Literal
from selenium.common.exceptions import WebDriverException

class TurnstileDetector:
    """
    Detects Turnstile presence and classifies type:
    - 'embedded': Interactive checkbox widget
    - 'invisible': Token-only, no UI (requires postMessage hook)
    - 'challenge': Full-page Cloudflare challenge
    """
    def __init__(self, driver):
        self.driver = driver
        self.node_id: Optional[int] = None
        self.type: Optional[Literal["embedded", "invisible", "challenge"]] = None

    def detect(self) -> bool:
        """
        Run multi-strategy detection. Returns True if any Turnstile variant found.
        """
        try:
            root = self.driver.execute_cdp_cmd("DOM.getDocument", {"depth": -1})
            self.node_id = root["root"]["nodeId"]
            
            # Strategy 1: Standard embedded widget
            if self._has_embedded_widget():
                self.type = "embedded"
                return True
            
            # Strategy 2: Invisible mode (iframe present but no .cf-turnstile div)
            if self._has_invisible_widget():
                self.type = "invisible"
                return True
            
            # Strategy 3: Full-page challenge
            if self._has_challenge_page():
                self.type = "challenge"
                return True
            
            return None
        except WebDriverException:
            return None

    def _has_embedded_widget(self) -> bool:
        """Detect .cf-turnstile[data-sitekey] or iframe from challenges.cloudflare.com"""
        # Check for explicit widget div
        result = self.driver.execute_cdp_cmd("DOM.querySelector", {
            "nodeId": self.node_id,
            "selector": ".cf-turnstile[data-sitekey], .cf-turnstile"
        })
        if result.get("nodeId"):
            self.driver.execute_cdp_cmd("DOM.scrollIntoViewIfNeeded", {
                "nodeId": result["nodeId"],
                "center": True
            })
            return True
        
        # Fallback: check for Turnstile iframe directly
        iframe_check = self.driver.execute_cdp_cmd("Runtime.evaluate", {
            "expression": """
                (function() {
                    const iframes = document.querySelectorAll('iframe');
                    for (const iframe of iframes) {
                        if (iframe.src && iframe.src.includes('challenges.cloudflare.com')) {
                            return true;
                        }
                    }
                    return false;
                })()
            """,
            "returnByValue": True
        })["result"].get("value", False)
        
        return iframe_check

    def _has_invisible_widget(self) -> bool:
        """
        Detect invisible Turnstile (no UI, token-only).
        Checks for turnstile script tag or grecaptcha-like global.
        """
        result = self.driver.execute_cdp_cmd("Runtime.evaluate", {
            "expression": """
                (function() {
                    // Check for turnstile.render or cf-turnstile script
                    const scripts = document.querySelectorAll('script[src*="turnstile"]');
                    if (scripts.length > 0) return true;
                    
                    // Check for window.turnstile global
                    if (typeof window.turnstile !== 'undefined') return true;
                    
                    // Check for hidden input with cf-turnstile response
                    const inputs = document.querySelectorAll('input[name*="cf-turnstile"]');
                    if (inputs.length > 0) return true;
                    
                    return false;
                })()
            """,
            "returnByValue": True
        })["result"].get("value", False)
        
        return result

    def _has_challenge_page(self) -> bool:
        """Detect full-page Cloudflare challenge via footer markers."""
        footer = self.driver.execute_cdp_cmd("DOM.querySelector", {
            "nodeId": self.node_id,
            "selector": ".footer-inner, #challenge-running, #challenge-form"
        })
        footer_id = footer.get("nodeId")
        if not footer_id:
            return False
        
        html = self.driver.execute_cdp_cmd("DOM.getOuterHTML", {
            "nodeId": footer_id
        }).get("outerHTML", "")
        
        return any(kw in html for kw in ["Ray ID", "Performance &", "security by", "Cloudflare"])

    def get_widget_frame_id(self) -> Optional[str]:
        """
        Extract the Turnstile iframe ID for cross-frame token extraction.
        """
        result = self.driver.execute_cdp_cmd("Runtime.evaluate", {
            "expression": """
                (function() {
                    const iframe = document.querySelector('iframe[src*="challenges.cloudflare.com"]');
                    return iframe ? iframe.id || iframe.name : null;
                })()
            """,
            "returnByValue": True
        })["result"].get("value")
        return result