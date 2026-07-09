from __future__ import annotations

from datetime import datetime, timedelta

from src.data_ops.models import DataOpsTaskConfig, encode_progress_message
from src.data_ops.repository import ClickHouseDataOpsRepository


class FakeClickHouseClient:
    def __init__(self) -> None:
        self.commands: list[str] = []
        self.configs: dict[str, dict] = {}
        self.runs: dict[str, dict] = {}
        self.heartbeats: dict[tuple[str, str], dict] = {}

    def execute(self, query: str, params=None):
        self.commands.append(" ".join(query.split()))
        return []


def test_repository_ensures_tables_and_seeds_defaults() -> None:
    client = FakeClickHouseClient()
    repo = ClickHouseDataOpsRepository(client=client)

    repo.ensure_tables()
    repo.seed_default_configs(now=datetime(2026, 6, 12, 9, 0))

    assert any("data_ops_task_config" in command for command in client.commands)
    assert set(client.configs) == {
        "post_close_maintenance",
        "stock_master_sync",
        "minute5_intraday_sync",
        "quote_snapshot_capture",
        "quote_rollup_refresh",
        "quality_snapshot",
        "xdxr_sync",
        "stock_readiness_snapshot",
        "stock_readiness_repair",
    }


def test_repository_upgrades_legacy_stock_readiness_snapshot_default_config() -> None:
    client = FakeClickHouseClient()
    repo = ClickHouseDataOpsRepository(client=client)
    repo.upsert_task_config(
        DataOpsTaskConfig(
            task_key="stock_readiness_snapshot",
            enabled=True,
            schedule_kind="daily_time",
            schedule_config={"time": "15:40"},
        ),
        now=datetime(2026, 7, 8, 10, 0),
    )

    repo.seed_default_configs(now=datetime(2026, 7, 8, 10, 1))

    snapshot = repo._get_config("stock_readiness_snapshot")
    assert snapshot.schedule_config == {
        "time": "15:40",
        "lookback_days": 180,
        "dimensions": ["daily", "minute5"],
    }


def test_repository_upserts_config_and_lists_status() -> None:
    client = FakeClickHouseClient()
    repo = ClickHouseDataOpsRepository(client=client)
    now = datetime(2026, 6, 12, 9, 0)

    repo.upsert_task_config(
        DataOpsTaskConfig(
            task_key="quality_snapshot",
            enabled=False,
            schedule_kind="manual",
            schedule_config={},
        ),
        now=now,
    )
    statuses = repo.list_task_statuses(now=now)

    assert statuses[0].task_key == "quality_snapshot"
    assert statuses[0].enabled is False
    assert statuses[0].status == "disabled"


def test_repository_records_run_and_heartbeat() -> None:
    client = FakeClickHouseClient()
    repo = ClickHouseDataOpsRepository(client=client)
    started = datetime(2026, 6, 12, 10, 0)
    finished = started + timedelta(seconds=3)

    run_id = repo.start_run("quality_snapshot", "runner-a", now=started)
    repo.finish_run(run_id, "success", {"rows": 3}, "", now=finished)
    repo.write_heartbeat("runner-a", "quality_snapshot", "running", "working", now=started)

    assert client.runs[run_id]["status"] == "success"
    assert client.runs[run_id]["duration_seconds"] == 3.0
    assert client.heartbeats[("runner-a", "quality_snapshot")]["message"] == "working"


def test_repository_latest_run_query_prefers_completed_append_row() -> None:
    class QueryOnlyClient:
        def __init__(self) -> None:
            self.commands: list[str] = []

        def execute(self, query: str, params=None):
            self.commands.append(" ".join(query.split()))
            return []

    client = QueryOnlyClient()
    repo = ClickHouseDataOpsRepository(client=client)

    repo._latest_run("quality_snapshot")

    assert any("order by started_at desc, isNull(finished_at) asc, finished_at desc" in command for command in client.commands)


def test_repository_finish_run_can_complete_existing_clickhouse_run() -> None:
    class ExistingRunClient:
        def __init__(self) -> None:
            self.inserted: list[tuple] = []

        def execute(self, query: str, params=None):
            normalized = " ".join(query.split())
            if "select run_id, task_key, status, started_at" in normalized and "where run_id" in normalized:
                return [("run-existing", "xdxr_sync", "running", datetime(2026, 7, 8, 10, 0), None, 0.0, "{}", "")]
            if normalized.startswith("insert into data_ops_task_runs"):
                self.inserted.extend(params)
            return []

    client = ExistingRunClient()
    repo = ClickHouseDataOpsRepository(client=client)

    repo.finish_run("run-existing", "failed", {}, "interrupted", now=datetime(2026, 7, 8, 11, 0))

    assert client.inserted[0][1] == "xdxr_sync"
    assert client.inserted[0][2] == "failed"
    assert client.inserted[0][3] == datetime(2026, 7, 8, 10, 0)
    assert client.inserted[0][4] == datetime(2026, 7, 8, 11, 0)


def test_repository_decodes_heartbeat_progress() -> None:
    client = FakeClickHouseClient()
    repo = ClickHouseDataOpsRepository(client=client)
    now = datetime(2026, 6, 12, 10, 0)
    repo.upsert_task_config(
        DataOpsTaskConfig(
            task_key="quality_snapshot",
            enabled=True,
            schedule_kind="interval",
            schedule_config={},
        ),
        now=now,
    )
    repo.write_heartbeat(
        "runner-a",
        "quality_snapshot",
        "running",
        encode_progress_message(percent=45, stage="fetching", message="读取质量状态", processed=9, total=20),
        now=now,
    )

    status = repo.list_task_statuses(now=now)[0]

    assert status.status == "running"
    assert status.progress_percent == 45
    assert status.progress_stage == "fetching"
    assert status.progress_message == "读取质量状态"
    assert status.progress_processed == 9
    assert status.progress_total == 20


def test_repository_running_heartbeat_suppresses_previous_error() -> None:
    client = FakeClickHouseClient()
    repo = ClickHouseDataOpsRepository(client=client)
    started = datetime(2026, 6, 12, 10, 0)
    repo.upsert_task_config(
        DataOpsTaskConfig(
            task_key="minute5_intraday_sync",
            enabled=True,
            schedule_kind="market_interval",
            schedule_config={},
        ),
        now=started,
    )
    run_id = repo.start_run("minute5_intraday_sync", "runner-a", now=started)
    repo.finish_run(run_id, "failed", {}, "previous failure", now=started + timedelta(seconds=10))
    repo.write_heartbeat(
        "runner-b",
        "minute5_intraday_sync",
        "running",
        encode_progress_message(percent=20, stage="fetching", message="继续同步"),
        now=started + timedelta(seconds=20),
    )

    status = repo.list_task_statuses(now=started + timedelta(seconds=30))[0]

    assert status.status == "running"
    assert status.last_error == ""
    assert status.runner_id == "runner-b"


def test_repository_failed_heartbeat_interrupts_unfinished_running_run() -> None:
    client = FakeClickHouseClient()
    repo = ClickHouseDataOpsRepository(client=client)
    started = datetime(2026, 7, 8, 10, 0)
    repo.upsert_task_config(
        DataOpsTaskConfig(
            task_key="xdxr_sync",
            enabled=True,
            schedule_kind="daily_time",
            schedule_config={"time": "15:30"},
        ),
        now=started,
    )
    repo.start_run("xdxr_sync", "runner-a", now=started)
    repo.write_heartbeat("runner-b", "xdxr_sync", "failed", "interrupted", now=started + timedelta(hours=1))

    status = repo.list_task_statuses(now=started + timedelta(hours=1, minutes=1))[0]

    assert status.status == "failed"
    assert status.runner_id == "runner-b"


def test_repository_marks_latest_running_task_interrupted() -> None:
    client = FakeClickHouseClient()
    repo = ClickHouseDataOpsRepository(client=client)
    started = datetime(2026, 7, 8, 10, 0)
    interrupted_at = started + timedelta(hours=1)
    repo.upsert_task_config(
        DataOpsTaskConfig(
            task_key="xdxr_sync",
            enabled=True,
            schedule_kind="daily_time",
            schedule_config={"time": "15:30"},
        ),
        now=started,
    )
    run_id = repo.start_run("xdxr_sync", "runner-a", now=started)

    repo.mark_task_interrupted("xdxr_sync", "runner-b", "上次运行心跳超时，已标记为中断", now=interrupted_at)

    assert client.runs[run_id]["status"] == "failed"
    assert client.runs[run_id]["finished_at"] == interrupted_at
    assert client.heartbeats[("runner-b", "xdxr_sync")]["status"] == "failed"


def test_repository_does_not_mark_completed_task_stale_after_heartbeat_grace() -> None:
    client = FakeClickHouseClient()
    repo = ClickHouseDataOpsRepository(client=client)
    started = datetime(2026, 6, 12, 10, 0)
    finished = started + timedelta(seconds=3)
    checked = started + timedelta(seconds=400)
    repo.upsert_task_config(
        DataOpsTaskConfig(
            task_key="quality_snapshot",
            enabled=True,
            schedule_kind="interval",
            schedule_config={"interval_seconds": 300},
            stale_after_seconds=180,
        ),
        now=started,
    )
    run_id = repo.start_run("quality_snapshot", "runner-a", now=started)
    repo.finish_run(run_id, "success", {"rows": 3}, "", now=finished)
    repo.write_heartbeat("runner-a", "quality_snapshot", "success", "completed", now=finished)

    status = repo.list_task_statuses(now=checked)[0]

    assert status.status == "success"


def test_repository_marks_running_task_stale_after_heartbeat_grace() -> None:
    client = FakeClickHouseClient()
    repo = ClickHouseDataOpsRepository(client=client)
    started = datetime(2026, 6, 12, 10, 0)
    checked = started + timedelta(seconds=400)
    repo.upsert_task_config(
        DataOpsTaskConfig(
            task_key="quality_snapshot",
            enabled=True,
            schedule_kind="interval",
            schedule_config={"interval_seconds": 300},
            stale_after_seconds=180,
        ),
        now=started,
    )
    repo.start_run("quality_snapshot", "runner-a", now=started)
    repo.write_heartbeat("runner-a", "quality_snapshot", "running", "working", now=started)

    status = repo.list_task_statuses(now=checked)[0]

    assert status.status == "stale"


def test_repository_manual_trigger_is_consumed() -> None:
    client = FakeClickHouseClient()
    repo = ClickHouseDataOpsRepository(client=client)
    repo.upsert_task_config(
        DataOpsTaskConfig(task_key="quality_snapshot", enabled=True, schedule_kind="interval", schedule_config={}),
        now=datetime(2026, 6, 12, 9, 0),
    )

    repo.request_manual_run("quality_snapshot", now=datetime(2026, 6, 12, 9, 1))
    assert repo.list_task_configs()[0].manual_trigger is True

    assert repo.consume_manual_trigger("quality_snapshot", now=datetime(2026, 6, 12, 9, 2)) is True
    assert repo.list_task_configs()[0].manual_trigger is False


def test_repository_retries_once_after_clickhouse_socket_error() -> None:
    class BrokenThenWorkingSource:
        def __init__(self) -> None:
            self.calls = 0

        def _client_instance(self):
            self.calls += 1
            if self.calls == 1:
                class BrokenClient:
                    def execute(self, query, params=None):
                        raise OSError("bad fd")

                return BrokenClient()

            class WorkingClient:
                def execute(self, query, params=None):
                    return []

            return WorkingClient()

    source = BrokenThenWorkingSource()
    repo = ClickHouseDataOpsRepository()
    repo._source = source

    assert repo._execute("select 1") == []
    assert source.calls == 2
