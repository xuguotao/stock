from pathlib import Path


def test_jobs_page_shows_job_health_and_heartbeat() -> None:
    source = Path("frontend/src/pages/Jobs.vue").read_text(encoding="utf-8")
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")

    assert "健康状态" in source
    assert "心跳时间" in source
    assert "healthType" in source
    assert "stale" in source
    assert "heartbeat_at" in source
    assert "health: 'pending' | 'running' | 'stale' | 'completed' | 'failed' | string" in client
    assert "heartbeat_at: string | null" in client
