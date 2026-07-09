from pathlib import Path


def test_tail_live_feature_exposes_shared_types_and_formatters() -> None:
    types = Path("frontend/src/features/tail-live/types.ts").read_text(encoding="utf-8")
    formatters = Path("frontend/src/features/tail-live/formatters.ts").read_text(encoding="utf-8")
    links = Path("frontend/src/features/tail-live/links.ts").read_text(encoding="utf-8")
    job = Path("frontend/src/features/tail-live/useTailLiveJob.ts").read_text(encoding="utf-8")
    data_health = Path("frontend/src/features/tail-live/useTailLiveDataHealth.ts").read_text(encoding="utf-8")
    page = Path("frontend/src/pages/TailLiveSelection.vue").read_text(encoding="utf-8")
    table = Path("frontend/src/pages/tail-live/TailSelectionTable.vue").read_text(encoding="utf-8")

    assert "export interface SelectionRow" in types
    assert "export interface TailLiveResult" in types
    assert "export function formatPercent" in formatters
    assert "export function modelDecisionText" in formatters
    assert "export function stockTrendUrl" in links
    assert "export function useTailLiveJob" in job
    assert "export function useTailLiveDataHealth" in data_health
    assert "from '../features/tail-live/types'" in page
    assert "useTailLiveJob" in page
    assert "useTailLiveDataHealth" in page
    assert "from '../../features/tail-live/types'" in table
    assert "interface TailSelectionRow" not in table
    assert "function modelDecisionText" not in table
    assert "async function pollJobUntilDone" not in page
    assert "async function loadDataHealth" not in page
