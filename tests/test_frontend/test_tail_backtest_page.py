from pathlib import Path


def test_tail_backtest_page_defaults_to_clickhouse_without_local_dataset_picker() -> None:
    source = Path("frontend/src/pages/TailBacktest.vue").read_text(encoding="utf-8")

    assert "ClickHouse daily_kline" in source
    assert "不再依赖本地 parquet" in source
    assert "source: 'clickhouse'" in source
    assert "api.listDatasets" not in source
    assert "api.getDataset" not in source
    assert "选择本地 research dataset" not in source
    assert "本地数据集" not in source
