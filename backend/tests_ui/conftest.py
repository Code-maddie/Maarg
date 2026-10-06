"""Browser-level test harness (Phase 21+).

Starts the real backend (uvicorn) and the static frontend (http.server),
builds a full-scale world, then drives the installed Chrome through the
existing portals with Playwright.

Run separately from the unit suite:

    .venv/Scripts/python.exe -m pytest tests_ui -q

Auth: the backend runs with AUTH_MODE=disabled because the four existing
test accounts (anita / rahul / suresh / meera @maarg.demo) are not Firebase
users (verified read-only; see srihitha.md). The login page still attempts
Firebase sign-in with those same accounts and falls back to the demo
session — that path is asserted by the tests.
"""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
SITE_DIR = BACKEND_DIR.parent / "frontend" / "sidecar-site"
API = "http://localhost:8000"
WEB = "http://localhost:5173"

ACCOUNTS = {
    "admin": ("anita@maarg.demo", "admin.html"),
    "dispatcher": ("rahul@maarg.demo", "dispatcher.html"),
    "driver": ("suresh@maarg.demo", "driver.html"),
    "customer": ("meera@maarg.demo", "customer.html"),
}


def _port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _wait(url: str, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            return
        except Exception:  # noqa: BLE001 - polling
            time.sleep(0.3)
    raise RuntimeError(f"{url} did not come up")


def http(method: str, path: str, body=None, timeout: float = 60.0):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(API + path, method=method, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        text = r.read().decode()
        return json.loads(text) if text else None


@pytest.fixture(scope="session")
def servers():
    for port in (8000, 5173):
        if _port_open(port):
            pytest.fail(f"port {port} is already in use; stop the other server first")

    db = BACKEND_DIR / "sh205_ui.db"
    for suffix in ("", "-wal", "-shm"):
        Path(str(db) + suffix).unlink(missing_ok=True)

    env = {**os.environ, "AUTH_MODE": "disabled", "FIRESTORE_ENABLED": "false",
           "DATABASE_URL": f"sqlite:///{db.as_posix()}", "LOG_LEVEL": "WARNING"}
    backend = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=BACKEND_DIR, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    site = subprocess.Popen(
        [sys.executable, "-m", "http.server", "5173", "--directory", str(SITE_DIR)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        _wait(API + "/health")
        _wait(WEB + "/login.html")
        http("POST", "/simulate/reset", {"seed": 42, "hub_count": 30, "vehicle_count": 200,
                                         "shipment_count": 5000, "leg_count": 600})
        # Wait for the 205 MB E1 model, then advance so shipments depart and get scored.
        deadline = time.time() + 180
        while http("GET", "/model/status")["state"] != "loaded" and time.time() < deadline:
            time.sleep(1)
        http("POST", "/simulate/tick", {"ticks": 40})
        yield {"api": API, "web": WEB}
    finally:
        for proc in (backend, site):
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


@pytest.fixture(scope="session")
def browser(servers):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        yield b
        b.close()


@pytest.fixture()
def page(browser):
    ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    yield pg
    ctx.close()


def login(page, role: str, *, expect_live: bool = True):
    """Signs in through the real login form with an existing test account."""
    email, target = ACCOUNTS[role]
    page.goto(f"{WEB}/login.html?role={role}")
    page.click("#fill")
    assert page.input_value("#em") == email
    page.click("#lf button[type=submit]")
    page.wait_for_url(f"**/{target}*", timeout=30000)
    page.wait_for_selector("#maargSource[data-source]", timeout=30000)
    return page.get_attribute("#maargSource", "data-source")
