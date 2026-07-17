"""Tests for explicit, fail-closed research adjustment builds."""
from __future__ import annotations

from datetime import date, datetime

from scripts import build_research_adjustment_data


class _Store:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def ensure_tables(self) -> None:
        self.calls.append(("ensure_tables",))

    def write_candidate_events(self, run_id: str, formula_version: str, rows: list[dict]) -> int:
        self.calls.append(("events", run_id, formula_version, rows))
        return len(rows)

    def write_candidate_factors(self, run_id: str, formula_version: str, rows: list[dict]) -> int:
        self.calls.append(("factors", run_id, formula_version, rows))
        return len(rows)

    def write_candidate_raw_bars(self, run_id: str, formula_version: str, rows: list[dict]) -> int:
        self.calls.append(("raw_bars", run_id, formula_version, rows))
        return len(rows)

    def publish_run(self, **kwargs: object) -> None:
        self.calls.append(("publish", kwargs))

    def current_run(self, _formula_version: str):
        return None


class _MootdxClient:
    def execute(self, sql: str, _params: object | None = None):
        normalized = " ".join(sql.lower().split())
        if "select ingest_seq, status from mootdx_ingestion_runs" in normalized:
            return [(1, "succeeded")]
        if "select distinct symbol from mootdx_stock_kline as k" in normalized:
            return [("000001.SZ",)]
        if "from mootdx_stock_kline" in normalized:
            return [
                ("000001.SZ", date(2026, 7, 15), 10.0, 10.0, 10.0, 10.0, 100, 1000.0, datetime(2026, 7, 16, 17, 20)),
                ("000001.SZ", date(2026, 7, 16), 9.0, 9.0, 9.0, 9.0, 100, 900.0, datetime(2026, 7, 16, 17, 20)),
            ]
        if "argmax(name, version_key)" in normalized and "from mootdx_xdxr" in normalized:
            return [("000001.SZ", date(2026, 7, 16), 1, "cash", 1.0, 0.0, 0.0, 0.0, 1.0)]
        raise AssertionError(sql)


class _IncrementalStore(_Store):
    def current_run(self, _formula_version: str):
        return {
            "run_id": "prior-run", "formula_version": "v1",
            "published_at": datetime(2026, 7, 16, 17, 25),
            "input_watermark": datetime(2026, 7, 16, 17, 20),
            "input_ingest_seq": 17,
        }


class _IncrementalMootdxClient(_MootdxClient):
    def execute(self, sql: str, _params: object | None = None):
        normalized = " ".join(sql.lower().split())
        if "select ingest_seq, status from mootdx_ingestion_runs" in normalized:
            return [(seq, "succeeded") for seq in range(1, 22)]
        if "from research_daily_adjustment_factors final" in normalized:
            return [("600519.SH", date(2026, 7, 15), 1.0, 1.0, 0, 0, "approved")]
        if "from research_adjustment_events final" in normalized:
            return []
        if "from research_adjustment_raw_bars final" in normalized:
            return []
        if "select distinct symbol" in normalized and "ingest_seq >" in normalized:
            # One XDXR change and one daily-bar-only change must both be rebuilt.
            if "mootdx_xdxr" in normalized:
                return [("000001.SZ",)]
            return [("000002.SZ",)]
        if "from mootdx_stock_kline" in normalized:
            return [
                ("000001.SZ", date(2026, 7, 15), 10.0, 10.0, 10.0, 10.0, 100, 1000.0, datetime(2026, 7, 16, 17, 20)),
                ("000001.SZ", date(2026, 7, 16), 9.0, 9.0, 9.0, 9.0, 100, 900.0, datetime(2026, 7, 16, 17, 20)),
                ("000002.SZ", date(2026, 7, 15), 20.0, 20.0, 20.0, 20.0, 100, 2000.0, datetime(2026, 7, 16, 17, 20)),
            ]
        if "argmax(name, version_key)" in normalized and "from mootdx_xdxr" in normalized:
            return [("000001.SZ", date(2026, 7, 16), 1, "cash", 1.0, 0.0, 0.0, 0.0, 1.0)]
        raise AssertionError(sql)


def test_parse_args_supports_explicit_research_build_scope() -> None:
    args = build_research_adjustment_data.parse_args(
        ["--symbols", "000001.SZ,600519.SH", "--formula-version", "v2", "--full"]
    )

    assert args.symbols == ["000001.SZ", "600519.SH"]
    assert args.formula_version == "v2"
    assert args.full is True


def test_build_writes_candidates_before_publishing_complete_result() -> None:
    store = _Store()

    result = build_research_adjustment_data.build_research_adjustment_data(
        symbols=["000001.SZ"], formula_version="v1", full=False, store=store,
        candidate_builder=lambda **_kwargs: {
            "events": [],
            "factors": [{"symbol": "000001.SZ", "trade_date": "2026-07-16", "forward_factor": 1, "backward_factor": 1}],
        },
        run_id_factory=lambda: "run-1",
    )

    assert result == {"run_id": "run-1", "event_count": 0, "factor_count": 1}
    assert [call[0] for call in store.calls] == ["ensure_tables", "events", "factors", "raw_bars", "publish"]
    assert store.calls[-1][1] == {
            "run_id": "run-1", "formula_version": "v1", "completed": True,
                "expected_event_count": 0, "expected_factor_count": 1,
            "expected_raw_bar_count": 0,
            "input_ingest_seq": 0, "base_run_id": None,
    }


def test_default_build_constructs_candidates_from_mootdx_raw_inputs() -> None:
    store = _Store()

    result = build_research_adjustment_data.build_research_adjustment_data(
        formula_version="v1", store=store, client=_MootdxClient(), run_id_factory=lambda: "run-raw"
    )

    assert result == {"run_id": "run-raw", "event_count": 1, "factor_count": 2}
    event = store.calls[1][3][0]
    factors = store.calls[2][3]
    assert event["status"] == "approved"
    assert event["ratio"] == 0.9
    assert [(row["trade_date"], row["forward_factor"]) for row in factors] == [
        (date(2026, 7, 15), 0.9),
        (date(2026, 7, 16), 1.0),
    ]


def test_candidate_reads_are_bounded_by_captured_input_ingest_sequence() -> None:
    captured = 1
    store = _Store()

    class _StableSnapshotClient(_MootdxClient):
        def execute(self, sql: str, params: object | None = None):
            normalized = " ".join(sql.lower().split())
            if "argmax(close, version_key)" in normalized and "from mootdx_stock_kline" in normalized:
                assert params == {"symbols": ("000001.SZ",), "captured_input_ingest_seq": captured}
                # A later bar must remain for the following build.
                return [
                    ("000001.SZ", date(2026, 7, 15), 10.0, 10.0, 10.0, 10.0, 100, 1000.0, captured),
                    ("000001.SZ", date(2026, 7, 16), 9.0, 9.0, 9.0, 9.0, 100, 900.0, captured),
                ]
            if "argmax(name, version_key)" in normalized and "from mootdx_xdxr" in normalized:
                assert params == {"symbols": ("000001.SZ",), "captured_input_ingest_seq": captured}
                # The post-capture event is likewise absent from this snapshot.
                return [("000001.SZ", date(2026, 7, 16), 1, "cash", 1.0, 0.0, 0.0, 0.0, 1.0)]
            return super().execute(sql, params)

    result = build_research_adjustment_data.build_research_adjustment_data(
        formula_version="v1", full=True, store=store, client=_StableSnapshotClient(), run_id_factory=lambda: "run-stable"
    )

    assert result == {"run_id": "run-stable", "event_count": 1, "factor_count": 2}


def test_full_build_selects_targets_only_through_captured_input_ingest_sequence() -> None:
    captured = 1
    store = _Store()

    class _StableTargetClient(_MootdxClient):
        def execute(self, sql: str, params: object | None = None):
            normalized = " ".join(sql.lower().split())
            if "select distinct symbol from mootdx_stock_kline as k" in normalized:
                assert "frequency = 'daily'" in normalized
                assert "ingest_seq <= %(captured_input_ingest_seq)s" in normalized
                assert params == {"captured_input_ingest_seq": captured}
                # A symbol ingested after capture must wait for the next run.
                return [("000001.SZ",)]
            return super().execute(sql, params)

    result = build_research_adjustment_data.build_research_adjustment_data(
        formula_version="v1", full=True, store=store, client=_StableTargetClient(), run_id_factory=lambda: "run-targets"
    )

    assert result == {"run_id": "run-targets", "event_count": 1, "factor_count": 2}


def test_default_incremental_no_change_is_a_successful_unpublished_no_op() -> None:
    store = _IncrementalStore()

    class _EmptyClient:
        def execute(self, _sql: str, _params: object | None = None):
            return []

    result = build_research_adjustment_data.build_research_adjustment_data(
        store=store, client=_EmptyClient()
    )

    assert result == {"run_id": None, "event_count": 0, "factor_count": 0, "published": False}
    assert store.calls == []


def test_incremental_uses_only_succeeded_sequences_between_published_and_settled_bound() -> None:
    class _SequenceStore(_Store):
        def current_run(self, _formula_version: str):
            return {"run_id": "run-17", "formula_version": "v1", "input_ingest_seq": 17}

    class _SequenceClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object | None]] = []

        def execute(self, sql: str, params: object | None = None):
            self.calls.append((sql, params))
            normalized = " ".join(sql.lower().split())
            if "select ingest_seq, status from mootdx_ingestion_runs" in normalized:
                return [(seq, "succeeded" if seq in {18, 21} else "failed") for seq in range(1, 22)]
            if "select distinct symbol" in normalized and "mootdx_xdxr" in normalized:
                return [("000001.SZ",)]
            if "select distinct symbol" in normalized and "mootdx_stock_kline" in normalized:
                return [("000002.SZ",)]
            if "from mootdx_stock_kline" in normalized:
                return [
                    ("000001.SZ", date(2026, 7, 15), 10., 10., 10., 10., 1, 10., datetime.now()),
                    ("000002.SZ", date(2026, 7, 15), 20., 20., 20., 20., 1, 20., datetime.now()),
                ]
            if "from mootdx_xdxr" in normalized:
                return []
            if "research_daily_adjustment_factors" in normalized:
                return []
            if "research_adjustment_events" in normalized or "research_adjustment_raw_bars" in normalized:
                return []
            raise AssertionError(sql)

    store, client = _SequenceStore(), _SequenceClient()
    result = build_research_adjustment_data.build_research_adjustment_data(
        store=store, client=client, run_id_factory=lambda: "run-21"
    )

    assert result["run_id"] == "run-21"
    changed = [(sql, params) for sql, params in client.calls if "select distinct symbol" in sql.lower()]
    assert len(changed) == 2
    assert all("ingestion.status = 'succeeded'" in sql.lower() for sql, _ in changed)
    assert all(params == {"previous_input_ingest_seq": 17, "captured_input_ingest_seq": 21} for _, params in changed)
    assert store.calls[-1][1]["input_ingest_seq"] == 21


def test_daily_bars_selects_as_of_sequence_version_without_physical_duplicates() -> None:
    class _DuplicateBarClient:
        def execute(self, sql: str, params: object | None = None):
            normalized = " ".join(sql.lower().split())
            old = ("000001.SZ", date(2026, 7, 16), 10., 10., 10., 10., 1, 10., datetime(2026, 7, 16))
            new = ("000001.SZ", date(2026, 7, 16), 11., 11., 11., 11., 1, 11., datetime(2026, 7, 17))
            # This models physical ReplacingMergeTree duplicates from seq 17/21.
            if "argmax" in normalized:
                return [old] if params["captured_input_ingest_seq"] == 17 else [new]
            return [old, new]

    bars = build_research_adjustment_data._daily_bars(
        _DuplicateBarClient(), ["000001.SZ"], input_ingest_seq=17
    )

    assert bars == {"000001.SZ": [(date(2026, 7, 16), 10.0)]}
    assert [row["close"] for row in bars.raw_rows] == [10.0]

    newer_bars = build_research_adjustment_data._daily_bars(
        _DuplicateBarClient(), ["000001.SZ"], input_ingest_seq=21
    )
    assert newer_bars == {"000001.SZ": [(date(2026, 7, 16), 11.0)]}


def test_xdxr_events_select_as_of_sequence_version_without_final_after_filter() -> None:
    class _DuplicateEventClient:
        def execute(self, sql: str, _params: object | None = None):
            normalized = " ".join(sql.lower().split())
            old = ("000001.SZ", date(2026, 7, 16), 1, "cash", 1.0, 0.0, 0.0, 0.0, 1.0)
            new = ("000001.SZ", date(2026, 7, 16), 1, "cash", 2.0, 0.0, 0.0, 0.0, 1.0)
            return [old] if "argmax(name, version_key)" in normalized else [old, new]

    events = build_research_adjustment_data._xdxr_events(
        _DuplicateEventClient(), ["000001.SZ"], input_ingest_seq=17
    )

    assert events == [{
        "symbol": "000001.SZ", "event_date": date(2026, 7, 16), "category": 1,
        "name": "cash", "fenhong": 1.0, "peigujia": 0.0, "songzhuangu": 0.0,
        "peigu": 0.0, "suogu": 1.0,
    }]


def test_initial_explicit_symbol_build_refuses_to_publish_a_partial_snapshot() -> None:
    try:
        build_research_adjustment_data.build_research_adjustment_data(
            symbols=["000001.SZ"], store=_Store(), client=_MootdxClient()
        )
    except ValueError as exc:
        assert "--full" in str(exc)
    else:
        raise AssertionError("initial partial snapshot must not be published")


def test_incremental_publish_copies_prior_unchanged_factors_and_tracks_daily_changes() -> None:
    store = _IncrementalStore()

    result = build_research_adjustment_data.build_research_adjustment_data(
        formula_version="v1", store=store, client=_IncrementalMootdxClient(), run_id_factory=lambda: "run-next"
    )

    assert result == {"run_id": "run-next", "event_count": 1, "factor_count": 4}
    factors = store.calls[2][3]
    assert {row["symbol"] for row in factors} == {"000001.SZ", "000002.SZ", "600519.SH"}
    assert next(row for row in factors if row["symbol"] == "600519.SH")["quality_status"] == "approved"


def test_incremental_build_uses_persisted_input_sequence_and_captured_upper_bound() -> None:
    store = _IncrementalStore()

    class _SequenceClient(_IncrementalMootdxClient):
        def __init__(self) -> None:
            self.calls: list[tuple[str, object | None]] = []

        def execute(self, sql: str, params: object | None = None):
            self.calls.append((sql, params))
            normalized = " ".join(sql.lower().split())
            return super().execute(sql, params)

    client = _SequenceClient()
    build_research_adjustment_data.build_research_adjustment_data(
        formula_version="v1", store=store, client=client, run_id_factory=lambda: "run-sequence"
    )

    changed_queries = [call for call in client.calls if "ingest_seq >" in call[0].lower()]
    assert len(changed_queries) == 2
    assert all(call[1] == {
        "previous_input_ingest_seq": 17,
        "captured_input_ingest_seq": 21,
    } for call in changed_queries)
    assert store.calls[-1][1]["input_ingest_seq"] == 21
    assert store.calls[-1][1]["base_run_id"] == "prior-run"


def test_incremental_symbol_selection_uses_strict_sequence_boundaries() -> None:
    store = _IncrementalStore()

    class _SequenceBoundaryClient(_IncrementalMootdxClient):
        def __init__(self) -> None:
            self.calls: list[tuple[str, object | None]] = []

        def execute(self, sql: str, params: object | None = None):
            self.calls.append((sql, params))
            return super().execute(sql, params)

    client = _SequenceBoundaryClient()
    build_research_adjustment_data.build_research_adjustment_data(
        formula_version="v1", store=store, client=client, run_id_factory=lambda: "run-sequence-boundary"
    )
    queries = [sql for sql, _ in client.calls if "select distinct symbol" in sql.lower() and "ingest_seq" in sql.lower()]
    assert len(queries) == 2
    assert all("ingest_seq > %(previous_input_ingest_seq)s" in sql.lower() for sql in queries)


def test_incremental_build_with_legacy_run_without_input_sequence_requires_full_rebuild() -> None:
    class _LegacyStore(_IncrementalStore):
        def current_run(self, _formula_version: str):
            return {"run_id": "legacy-run", "formula_version": "v1", "published_at": datetime(2026, 7, 16, 17, 25), "input_watermark": datetime.now(), "input_ingest_seq": None}

    try:
        build_research_adjustment_data.build_research_adjustment_data(
            formula_version="v1", store=_LegacyStore(), client=_IncrementalMootdxClient()
        )
    except ValueError as exc:
        assert "--full" in str(exc)
    else:
        raise AssertionError("legacy published runs cannot establish a safe incremental input boundary")


def test_incremental_build_copies_prior_events_with_unchanged_factor_snapshot() -> None:
    store = _IncrementalStore()

    class _EventCopyClient(_IncrementalMootdxClient):
        def execute(self, sql: str, params: object | None = None):
            normalized = " ".join(sql.lower().split())
            if "max(ingested_at)" in normalized:
                return [(datetime(2026, 7, 16, 17, 40),)]
            if "from research_adjustment_events final" in normalized:
                return [("600519.SH", date(2026, 6, 1), 1, "cash", "approved", 0.98, 9.8, 10.0, 9.8, 0.0, "{}")]
            return super().execute(sql, params)

    build_research_adjustment_data.build_research_adjustment_data(
        formula_version="v1", store=store, client=_EventCopyClient(), run_id_factory=lambda: "run-event-copy"
    )

    copied_events = store.calls[1][3]
    assert {row["symbol"] for row in copied_events} == {"000001.SZ", "600519.SH"}
    assert next(row for row in copied_events if row["symbol"] == "600519.SH")["status"] == "approved"


def test_incremental_build_rejects_a_target_without_daily_factor_coverage() -> None:
    store = _IncrementalStore()

    class _MissingTargetClient(_IncrementalMootdxClient):
        def execute(self, sql: str, params: object | None = None):
            normalized = " ".join(sql.lower().split())
            if "max(ingested_at)" in normalized:
                return [(datetime(2026, 7, 16, 17, 40),)]
            if "argmax(close, version_key)" in normalized and "from mootdx_stock_kline" in normalized:
                return [("000001.SZ", date(2026, 7, 15), 10.0, 10.0, 10.0, 10.0, 100, 1000.0, datetime(2026, 7, 16, 17, 20))]
            return super().execute(sql, params)

    try:
        build_research_adjustment_data.build_research_adjustment_data(
            formula_version="v1", store=store, client=_MissingTargetClient(), run_id_factory=lambda: "run-missing"
        )
    except ValueError as exc:
        assert "factor coverage" in str(exc)
    else:
        raise AssertionError("all selected targets must receive a complete daily factor history")
    assert store.calls == []


def test_main_reports_expected_operational_value_error_without_traceback(monkeypatch, capsys) -> None:
    def _raise_value_error(**_kwargs: object):
        raise ValueError("factor rows are invalid")

    monkeypatch.setattr(build_research_adjustment_data, "build_research_adjustment_data", _raise_value_error)

    assert build_research_adjustment_data.main([]) == 2
    assert "research adjustment build failed: ValueError: factor rows are invalid" in capsys.readouterr().err


def test_script_does_not_depend_on_online_data_aggregator() -> None:
    source = build_research_adjustment_data.__file__
    assert "DataAggregator" not in open(source, encoding="utf-8").read()
