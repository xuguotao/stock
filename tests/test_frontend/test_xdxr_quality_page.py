from pathlib import Path


def test_xdxr_quality_frontend_wiring_exposes_the_independent_read_only_page() -> None:
    router_text = Path("frontend/src/router.ts").read_text(encoding="utf-8")
    client_text = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")
    monitor_text = Path("frontend/src/pages/MootdxMonitor.vue").read_text(encoding="utf-8")

    assert "XdxrQuality" in router_text
    assert "mootdx-xdxr-quality" in router_text
    assert "/mootdx/xdxr-quality" in router_text
    assert "getMootdxXdxrQuality" in client_text
    assert "getMootdxXdxrRunDetail" in client_text
    assert "MootdxXdxrQualityResponse" in client_text
    assert "MootdxXdxrRunDetail" in client_text
    assert "XDXR 质量" in monitor_text
    assert "router.push({ name: 'mootdx-xdxr-quality' })" in monitor_text
