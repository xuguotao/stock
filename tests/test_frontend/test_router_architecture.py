from pathlib import Path


def test_frontend_uses_vue_router_with_page_routes() -> None:
    main = Path("frontend/src/main.ts").read_text(encoding="utf-8")
    router = Path("frontend/src/router.ts").read_text(encoding="utf-8")
    app = Path("frontend/src/App.vue").read_text(encoding="utf-8")

    assert "createRouter" in router
    assert "createWebHistory" in router
    for name in [
        "dashboard",
        "data",
        "stock-list",
        "tail-live",
        "watchlist-monitor",
        "stock-trend",
        "tail-replay",
        "backtest",
        "fund-tail",
        "jobs",
    ]:
        assert f"name: '{name}'" in router
    assert "normalizeLegacyPageQuery" in router
    assert "redirect: (to) => legacyPageRedirect(to.query)" in router
    assert ".use(router)" in main
    assert "<RouterView" in app
    assert "activePage" not in app
    assert "v-else-if" not in app
