from __future__ import annotations

from src.data import research_adjustment_refresh as refresh_module


class _Client:
    def __init__(self, rows: list[tuple[int, str, str, str]]) -> None:
        self.rows = rows
        self.inserts: list[tuple[str, object]] = []

    def execute(self, query: str, params: object = None) -> list[tuple[int, str, str, str]]:
        if "mootdx_ingestion_runs" in query:
            return self.rows
        if "insert into research_adjustment_refresh_audits" in query.lower():
            self.inserts.append((query, params))
        return []


class _Store:
    def __init__(self, client: _Client) -> None:
        self.client = client

    def ensure_tables(self) -> None:
        pass

    def current_run(self, formula_version: str) -> dict[str, object]:
        assert formula_version == "v1"
        return {"run_id": "previous", "input_ingest_seq": 4}


def test_refresh_publishes_when_only_xdxr_has_new_success(monkeypatch) -> None:
    client = _Client([(5, "xdxr", "succeeded", "xdxr-run")])
    monkeypatch.setattr(refresh_module, "ResearchAdjustmentStore", _Store)
    calls: list[dict[str, object]] = []

    def builder(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return {"run_id": "published"}

    result = refresh_module.refresh_research_adjustments(client=client, builder=builder)

    assert result["decision"] == "published"
    assert result["published_run_id"] == "published"
    assert calls == [{"client": client, "formula_version": "v1"}]
    assert len(client.inserts) == 1


def test_refresh_blocks_when_new_upstream_run_is_not_successful(monkeypatch) -> None:
    client = _Client([(5, "xdxr", "failed", "xdxr-run")])
    monkeypatch.setattr(refresh_module, "ResearchAdjustmentStore", _Store)

    result = refresh_module.refresh_research_adjustments(
        client=client,
        builder=lambda **_kwargs: {"run_id": "must-not-publish"},
    )

    assert result["decision"] == "blocked"
    assert result["block_reason"] == "upstream_not_succeeded:xdxr"
    assert result["published_run_id"] is None
