from pathlib import Path


def test_app_registers_investment_channel_pages() -> None:
    app = Path("frontend/src/App.vue").read_text(encoding="utf-8")

    assert 'index="reits-channel"' in app
    assert "REITs 配置" in app
    assert "ReitsChannel" in app
    assert 'index="options-strategy"' in app
    assert "期权策略" in app
    assert "OptionsStrategy" in app


def test_reits_channel_page_exposes_screening_framework() -> None:
    page = Path("frontend/src/pages/ReitsChannel.vue").read_text(encoding="utf-8")

    assert "REITs 配置" in page
    assert "目标仓位" in page
    assert "资产类型" in page
    assert "分红率" in page
    assert "候选池" in page
    assert "不过度追新" in page
    assert "管理人" in page


def test_options_strategy_page_exposes_risk_controls() -> None:
    page = Path("frontend/src/pages/OptionsStrategy.vue").read_text(encoding="utf-8")

    assert "期权策略" in page
    assert "cash-secured put" in page
    assert "covered call" in page
    assert "naked call" in page
    assert "义务仓上限" in page
    assert "现金预留" in page
    assert "行权价" in page
    assert "退出条件" in page
