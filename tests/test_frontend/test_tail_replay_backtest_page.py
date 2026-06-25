from pathlib import Path


def test_tail_replay_backtest_page_exposes_cutoff_backtest_controls() -> None:
    source = Path("frontend/src/pages/TailReplayBacktest.vue").read_text(encoding="utf-8")

    assert "尾盘时段回放回测" in source
    assert "cutoff_times" in source
    assert "14:30" in source
    assert "14:55" in source
    assert "时间点收益对比" in source
    assert "因子诊断" in source
    assert "策略建议" in source
    assert "策略卖出收益" in source
    assert "参数组合优化" in source
    assert "best_plan" in source


def test_app_adds_tail_replay_backtest_navigation() -> None:
    source = Path("frontend/src/App.vue").read_text(encoding="utf-8")

    assert 'index="tail-replay"' in source
    assert "TailReplayBacktest" in source


def test_app_adds_tail_model_lab_navigation() -> None:
    source = Path("frontend/src/App.vue").read_text(encoding="utf-8")
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")

    assert 'index="tail-model-lab"' in source
    assert "TailModelLab" in source
    assert "getTailMlModels" in client
    assert "TailMlModelsResponse" in client
    assert "trainTailMlModel" in client
    assert "promoteTailMlModel" in client
    assert "TailMlTrainPayload" in client


def test_tail_model_lab_exposes_training_action() -> None:
    source = Path("frontend/src/pages/TailModelLab.vue").read_text(encoding="utf-8")

    assert "训练模型" in source
    assert "trainTailMlModel" in source
    assert "推广" in source
    assert "promoteTailMlModel" in source
    assert "training" in source


def test_jobs_page_can_open_tail_replay_results() -> None:
    source = Path("frontend/src/pages/Jobs.vue").read_text(encoding="utf-8")

    assert "tail_session_replay_backtest" in source
    assert "tail-replay" in source
