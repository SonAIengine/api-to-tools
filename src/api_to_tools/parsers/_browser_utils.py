"""Shared Playwright utilities for browser-based crawlers.

Used by both the generic crawler.py and the Nexacro-specific nexacro.py.
Keeps browser setup, login, and navigation logic in one place.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin, urlparse

from api_to_tools.constants import (
    AUTH_KEYWORDS,
    MUTATION_KEYWORDS,
    READ_KEYWORDS,
    SAFE_HTTP_METHODS,
)
from api_to_tools.types import AuthConfig


# ──────────────────────────────────────────────
# Browser launcher
# ──────────────────────────────────────────────

def launch_browser(playwright: Any, backend: str, headless: bool) -> Any:
    """Launch a browser with the specified backend.

    Backends:
      - "auto": try system Chrome first, fall back to Playwright Chromium
      - "system": system Chrome (requires Chrome installed, no download)
      - "playwright": Playwright-bundled Chromium
      - "lightpanda": Connect to running Lightpanda CDP server on :9222
    """
    if backend in ("auto", "system"):
        try:
            return playwright.chromium.launch(channel="chrome", headless=headless)
        except Exception:
            if backend == "system":
                raise RuntimeError(
                    "System Chrome not found. Install Chrome or use backend='playwright'."
                )
            # auto: fall through to playwright

    if backend in ("auto", "playwright"):
        try:
            return playwright.chromium.launch(headless=headless)
        except Exception as e:
            raise RuntimeError(
                "Playwright Chromium not found. Install with:\n"
                "  python -m playwright install chromium\n"
                "Or install Chrome and use backend='system'."
            ) from e

    if backend == "lightpanda":
        return playwright.chromium.connect_over_cdp("ws://127.0.0.1:9222/")

    raise ValueError(f"Unknown backend: {backend}")


# ──────────────────────────────────────────────
# Login automation
# ──────────────────────────────────────────────

USERNAME_SELECTORS = [
    'input[name="loginId"]', 'input[name="username"]', 'input[name="email"]',
    'input[name="user"]', 'input[name="id"]', 'input[type="email"]',
    'input[id*="login" i]', 'input[id*="user" i]',
]
PASSWORD_SELECTORS = [
    'input[name="password"]', 'input[name="passwd"]', 'input[name="pwd"]',
    'input[type="password"]',
]
SUBMIT_SELECTORS = [
    'button[type="submit"]', 'input[type="submit"]',
    'button:has-text("로그인")', 'button:has-text("Login")',
    'button:has-text("Sign in")', 'button:has-text("Sign In")',
]


def attempt_login(page: Any, auth: AuthConfig, wait_time: float) -> None:
    """Fill and submit a login form, trying common selectors."""
    if not auth.username:
        return

    _fill_first_matching(page, USERNAME_SELECTORS, auth.username)
    _fill_first_matching(page, PASSWORD_SELECTORS, auth.password or "")

    for sel in SUBMIT_SELECTORS:
        try:
            if page.locator(sel).count() > 0:
                page.locator(sel).first.click()
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                page.wait_for_timeout(int(wait_time * 1000))
                return
        except Exception:
            continue


def _fill_first_matching(page: Any, selectors: list[str], value: str) -> None:
    for sel in selectors:
        try:
            if page.locator(sel).count() > 0:
                page.locator(sel).first.fill(value)
                return
        except Exception:
            continue


# ──────────────────────────────────────────────
# Link / navigation helpers
# ──────────────────────────────────────────────

def collect_href_links(page: Any, base_origin: str) -> list[str]:
    """Collect internal href links from the current page."""
    try:
        hrefs = page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
    except Exception:
        return []

    base_host = urlparse(base_origin).netloc
    result: list[str] = []
    for href in hrefs:
        if not href:
            continue
        parsed = urlparse(href)
        if parsed.netloc and parsed.netloc != base_host:
            continue
        if href.startswith("javascript:") or href.startswith("#"):
            continue
        if parsed.scheme not in ("", "http", "https"):
            continue
        clean = urljoin(base_origin, href).split("#")[0]
        if clean not in result:
            result.append(clean)
    return result


def click_menu_items(
    page: Any,
    base_origin: str,
    max_clicks: int,
    wait_time: float,
    visited: set,
) -> None:
    """Click on sidebar/menu items to navigate SPAs without href links."""
    menu_selectors = [
        'nav a', 'nav button', 'aside a', 'aside button',
        '[role="navigation"] a', '[role="navigation"] button',
        '[class*="sidebar" i] a', '[class*="sidebar" i] button',
        '[class*="menu" i] a', '[class*="menu" i] button',
        '[class*="nav" i] a', '[class*="nav" i] button',
        'li[role="menuitem"]',
    ]

    clicked = 0
    for sel in menu_selectors:
        if clicked >= max_clicks:
            break
        try:
            count = page.locator(sel).count()
        except Exception:
            continue

        for i in range(min(count, max_clicks - clicked)):
            try:
                element = page.locator(sel).nth(i)
                if not element.is_visible(timeout=500):
                    continue
                element.click(timeout=2000)
                try:
                    page.wait_for_load_state("networkidle", timeout=3000)
                except Exception:
                    pass
                page.wait_for_timeout(int(wait_time * 500))
                clicked += 1
                visited.add(page.url)
            except Exception:
                continue


def exhaustive_interact(
    page: Any,
    *,
    max_clicks: int = 200,
    wait_per_click: float = 1.0,
    timeout_per_click: float = 2000,
) -> None:
    """Aggressively click every interactive element on the page to trigger
    all lazily-loaded API calls.

    Uses a click → wait → collect → click cycle, skipping elements that
    would open external navigation, close the page, or submit forms with
    destructive intent. Relies on Playwright's auto-waiting + the caller's
    safe_mode network interceptor to avoid actual damage.
    """
    clicked_signatures: set[str] = set()

    # Selectors that cover most interactive widgets
    interactive_selectors = [
        'button:not([type="submit"])',
        '[role="button"]',
        '[role="tab"]',
        '[role="menuitem"]',
        '[role="option"]',
        'a[href]:not([href^="mailto:"]):not([href^="tel:"])',
        '[onclick]',
        '[class*="btn"]:visible',
        '[class*="tab"]:visible',
        'summary',
    ]

    def _element_signature(el) -> str:
        """Build a stable signature so we don't click the same element twice."""
        try:
            tag = el.evaluate("e => e.tagName") or ""
            text = (el.inner_text(timeout=200) or "").strip()[:50]
            cls = (el.evaluate("e => e.className || ''") or "")[:40]
            return f"{tag}::{text}::{cls}"
        except Exception:
            return str(id(el))

    clicks_done = 0
    for selector in interactive_selectors:
        if clicks_done >= max_clicks:
            break
        try:
            count = page.locator(selector).count()
        except Exception:
            continue

        for i in range(min(count, max_clicks - clicks_done)):
            if clicks_done >= max_clicks:
                break
            try:
                element = page.locator(selector).nth(i)
                if not element.is_visible(timeout=300):
                    continue

                sig = _element_signature(element)
                if sig in clicked_signatures:
                    continue
                clicked_signatures.add(sig)

                # Skip obviously destructive-looking buttons
                sig_lower = sig.lower()
                if any(kw in sig_lower for kw in (
                    "delete", "remove", "삭제", "로그아웃", "logout",
                    "sign out", "unregister", "탈퇴",
                )):
                    continue

                element.click(timeout=int(timeout_per_click), force=False, no_wait_after=True)
                clicks_done += 1

                # Brief settle time for any fetch/XHR to fire
                page.wait_for_timeout(int(wait_per_click * 1000))

                # Dismiss any dialog/modal that opened
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
            except Exception:
                continue

    return None


def fill_visible_forms(page: Any) -> None:
    """Fill every visible text input with synthetic data and submit forms."""
    try:
        inputs = page.locator('input[type="text"], input[type="search"], input:not([type])')
        n = min(inputs.count(), 50)
        for i in range(n):
            try:
                el = inputs.nth(i)
                if el.is_visible(timeout=200):
                    el.fill("test", timeout=1000)
            except Exception:
                continue
    except Exception:
        pass

    try:
        selects = page.locator("select")
        for i in range(min(selects.count(), 20)):
            try:
                el = selects.nth(i)
                if el.is_visible(timeout=200):
                    el.select_option(index=0, timeout=1000)
            except Exception:
                continue
    except Exception:
        pass


def normalize_route_url(route: str, base_origin: str) -> str:
    """Normalize a route (possibly relative) into a full URL."""
    if route.startswith("http"):
        return route
    # Collapse any leading slashes so multi-slash routes don't produce //.
    stripped = route.lstrip("/")
    return f"{base_origin}/{stripped}"


# ──────────────────────────────────────────────
# Mutation request detection
# ──────────────────────────────────────────────

def is_mutation_request(method: str, url: str) -> bool:
    """Heuristic: does this request modify server state?

    Returns True only if we're reasonably confident it's a mutation.
    False for reads (even if sent as POST - common in RPC-style APIs).
    """
    if method in SAFE_HTTP_METHODS:
        return False

    url_lower = url.lower()
    last_segment = url_lower.rstrip("/").split("/")[-1].split("?")[0]

    # Auth/session endpoints allowed
    if any(kw in url_lower for kw in AUTH_KEYWORDS):
        return False

    # Read-style RPC endpoints
    if any(last_segment.startswith(kw) for kw in READ_KEYWORDS):
        return False
    if any(kw in last_segment for kw in ("list", "detail", "info", "status")):
        return False

    # DELETE/PUT/PATCH are always mutations
    if method in ("DELETE", "PUT", "PATCH"):
        return True

    # POST with mutation keywords in path
    if any(kw in url_lower for kw in MUTATION_KEYWORDS):
        return True

    return True  # Default POST = mutation (safe side)
