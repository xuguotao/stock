from __future__ import annotations

from pathlib import Path


def test_restart_web_defaults_to_lan_access_and_keeps_api_proxy_configurable() -> None:
    source = Path("scripts/restart_web.sh").read_text(encoding="utf-8")

    assert "source \"$ROOT_DIR/.env\"" in source
    assert 'HOST="${HOST:-0.0.0.0}"' in source
    assert 'BACKEND_PROXY_HOST="${BACKEND_PROXY_HOST:-127.0.0.1}"' in source
    assert "uvicorn src.web.backend.app:app --reload --host" in source
    assert "npm run dev -- --host" in source
    assert "BACKEND_HOST=$(shell_quote \"$BACKEND_PROXY_HOST\")" in source
    assert "detect_lan_host" in source
    assert "PUBLIC_HOST" in source


def test_frontend_vite_dev_server_allows_lan_access_and_proxies_api() -> None:
    source = Path("frontend/vite.config.ts").read_text(encoding="utf-8")
    package_json = Path("frontend/package.json").read_text(encoding="utf-8")

    assert "process.env.BACKEND_HOST ?? '127.0.0.1'" in source
    assert "process.env.BACKEND_PORT ?? '8000'" in source
    assert "host: '0.0.0.0'" in source
    assert "'/api': `http://${backendHost}:${backendPort}`" in source
    assert '"dev": "vite --host 0.0.0.0"' in package_json
    assert '"preview": "vite preview --host 0.0.0.0"' in package_json
