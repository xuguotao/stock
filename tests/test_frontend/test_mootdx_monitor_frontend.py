from pathlib import Path


def test_mootdx_monitor_formats_queued_manual_tasks_as_waiting_for_runner() -> None:
    source = Path("frontend/src/pages/MootdxMonitor.vue").read_text(encoding="utf-8")
    formatter = Path("frontend/src/features/mootdx/formatters.ts").read_text(encoding="utf-8")

    assert "queued: '等待 runner 接管'" in formatter
    assert "mootdxStatusText(row.status)" in source


def test_mootdx_monitor_clears_post_submit_refresh_when_unmounted() -> None:
    source = Path("frontend/src/pages/MootdxMonitor.vue").read_text(encoding="utf-8")

    assert "let postSubmitTimer: ReturnType<typeof window.setTimeout> | null = null" in source
    assert "postSubmitTimer = window.setTimeout(async () => {" in source
    assert "if (postSubmitTimer) window.clearTimeout(postSubmitTimer)" in source
