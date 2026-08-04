"""
observer.py v2
Hybrid state synchronization:
1. postMessage interception (primary, works cross-origin)
2. MutationObserver on input attributes (fallback)
3. Token presence polling (last resort)
"""
from typing import Literal

class TurnstileObserver:
    """
    Monitors Turnstile verification via multiple channels.
    """
    SCRIPT_IDS = {"challenge": None, "embedded": None, "invisible": None}

    def __init__(self, driver):
        self.driver = driver
        self.detect_timeout = 5
        self._was_detected = {"embedded": False, "challenge": False, "invisible": False}

    def _observe_embedded(self, solve_timeout, detect_timeout) -> None:
        """
        Hybrid observer: postMessage + MutationObserver + token polling.
        """
        js = f"""
            const widgetStartTime = Date.now();
            if (window.top === window.self) {{
                // Channel 1: postMessage interception (cross-origin safe)
                window.addEventListener('message', (event) => {{
                    if (event.data && typeof event.data === 'object') {{
                        if (event.data.type === 'turnstile-callback' || 
                            event.data.event === 'success' ||
                            (event.data.token && event.data.token.length > 50)) {{
                            sessionStorage.setItem('turnstile_verified', 'true');
                            if (event.data.token) {{
                                sessionStorage.setItem('turnstile_token', event.data.token);
                            }}
                        }}
                    }}
                }});
                
                function observeWidget() {{
                    if ((Date.now() - widgetStartTime) / 1000 >= {detect_timeout}) {{
                        window._embeddedDetected = false;
                        return;
                    }}
                    
                    const widget = document.querySelector('.cf-turnstile[data-sitekey]');
                    if (!widget) return setTimeout(observeWidget, 500);
                    
                    const input = widget.querySelector('input[name*="cf-turnstile"]');
                    if (!input) return setTimeout(observeWidget, 500);
                    
                    window._embeddedDetected = true;
                    
                    // Channel 2: MutationObserver on input
                    const observer = new MutationObserver(() => {{
                        sessionStorage.setItem('turnstile_verified', 'true');
                        observer.disconnect();
                    }});
                    observer.observe(input, {{ attributes: true }});
                    
                    // Channel 3: Token polling (every 300ms)
                    const pollInterval = setInterval(() => {{
                        const token = input.value;
                        if (token && token.length > 50) {{
                            sessionStorage.setItem('turnstile_verified', 'true');
                            sessionStorage.setItem('turnstile_token', token);
                            clearInterval(pollInterval);
                            observer.disconnect();
                        }}
                    }}, 300);
                    
                    setTimeout(() => {{
                        observer.disconnect();
                        clearInterval(pollInterval);
                    }}, {solve_timeout} * 1000);
                }}
                observeWidget();
            }}
        """
        res = self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": js})
        TurnstileObserver.SCRIPT_IDS["embedded"] = res["identifier"]
        self.driver.execute_cdp_cmd("Runtime.evaluate", {"expression": js})

    def _observe_invisible(self, solve_timeout, detect_timeout) -> None:
        """Observer for invisible mode (token-only, no UI)."""
        js = f"""
            const startTime = Date.now();
            if (window.top === window.self) {{
                // postMessage hook for invisible callback
                window.addEventListener('message', (event) => {{
                    if (event.data && event.data.token) {{
                        sessionStorage.setItem('turnstile_verified', 'true');
                        sessionStorage.setItem('turnstile_token', event.data.token);
                    }}
                }});
                
                function pollToken() {{
                    if ((Date.now() - startTime) / 1000 >= {detect_timeout}) {{
                        window._invisibleDetected = false;
                        return;
                    }}
                    
                    if (typeof window.turnstile !== 'undefined') {{
                        window._invisibleDetected = true;
                        const containers = document.querySelectorAll('[data-sitekey]');
                        for (const c of containers) {{
                            try {{
                                const widgetId = c.dataset.widgetId;
                                if (widgetId) {{
                                    const token = window.turnstile.getResponse(widgetId);
                                    if (token && token.length > 50) {{
                                        sessionStorage.setItem('turnstile_verified', 'true');
                                        sessionStorage.setItem('turnstile_token', token);
                                        return;
                                    }}
                                }}
                            }} catch(e) {{}}
                        }}
                    }}
                    setTimeout(pollToken, 400);
                }}
                pollToken();
            }}
        """
        res = self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": js})
        TurnstileObserver.SCRIPT_IDS["invisible"] = res["identifier"]
        self.driver.execute_cdp_cmd("Runtime.evaluate", {"expression": js})

    def _observe_challenge(self, solve_timeout, detect_timeout) -> None:
        """Observer for full-page challenge."""
        js = f"""
            const challengeStartTime = Date.now();
            if (window.top === window.self) {{
                function observeChallenge() {{
                    if ((Date.now() - challengeStartTime) / 1000 >= {detect_timeout}) {{
                        window._challengeDetected = false;
                        return;
                    }}
                    const target = document.querySelector('#challenge-success-text, .cf-turnstile input');
                    if (!target) return setTimeout(observeChallenge, 500);
                    
                    window._challengeDetected = true;
                    function check() {{
                        if (target.getClientRects().length > 0 || target.value.length > 50) {{
                            sessionStorage.setItem('turnstile_verified', 'true');
                            observer.disconnect();
                        }}
                    }}
                    const observer = new MutationObserver(check);
                    observer.observe(target.parentElement || target, {{
                        childList: true, attributes: true, characterData: true, subtree: true
                    }});
                    check();
                    setTimeout(() => observer.disconnect(), {solve_timeout} * 1000);
                }}
                observeChallenge();
            }}
        """
        res = self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": js})
        TurnstileObserver.SCRIPT_IDS["challenge"] = res["identifier"]
        self.driver.execute_cdp_cmd("Runtime.evaluate", {"expression": js})

    def start(self, cf_type: Literal["challenge", "embedded", "invisible"], solve_timeout) -> None:
        """Start observing based on detected type."""
        if cf_type == "embedded":
            if not TurnstileObserver.SCRIPT_IDS[cf_type]:
                self._observe_embedded(solve_timeout, self.detect_timeout)
        elif cf_type == "invisible":
            if not TurnstileObserver.SCRIPT_IDS[cf_type]:
                self._observe_invisible(solve_timeout, self.detect_timeout)
        elif cf_type == "challenge":
            if not TurnstileObserver.SCRIPT_IDS[cf_type]:
                self._observe_challenge(solve_timeout, self.detect_timeout)

    def is_verified(self) -> bool:
        """Check verification status via sessionStorage flag."""
        result = self.driver.execute_cdp_cmd("Runtime.evaluate", {
            "expression": """
                (function() {
                    const val = sessionStorage.getItem('turnstile_verified');
                    const token = sessionStorage.getItem('turnstile_token');
                    if (val) {
                        sessionStorage.removeItem('turnstile_verified');
                        if (token) sessionStorage.removeItem('turnstile_token');
                    }
                    return {
                        verified: val === 'true',
                        token: token || null,
                        detected: {
                            embedded: (typeof window._embeddedDetected !== 'undefined') ? window._embeddedDetected : null,
                            invisible: (typeof window._invisibleDetected !== 'undefined') ? window._invisibleDetected : null,
                            challenge: (typeof window._challengeDetected !== 'undefined') ? window._challengeDetected : null
                        }
                    };
                })()
            """,
            "returnByValue": True
        })["result"]
        
        verified = result.get("value", {}).get("verified", False)
        detected = result.get("value", {}).get("detected", {})
        
        if verified:
            for key in self._was_detected:
                self._was_detected[key] = False
            return True
        
        for key, det in detected.items():
            if det is True:
                self._was_detected[key] = True
            elif det is False and self._was_detected[key]:
                self._was_detected[key] = False
                return True
        return False

    def remove(self) -> None:
        """Remove all injected observers."""
        for key, script_id in TurnstileObserver.SCRIPT_IDS.items():
            if script_id:
                self.driver.execute_cdp_cmd("Page.removeScriptToEvaluateOnNewDocument", {
                    "identifier": script_id
                })
                TurnstileObserver.SCRIPT_IDS[key] = None