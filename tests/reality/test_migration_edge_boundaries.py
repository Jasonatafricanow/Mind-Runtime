"""Migration regressions for Reality input failure and temporal authority edges."""

import io
import json
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from mind_runtime.contracts import (
    EffectiveWindow,
    EffectiveWindowKind,
    ObservationModality,
    SemanticDaypart,
    SemanticPrecision,
    SemanticRelation,
    SemanticTime,
)
from mind_runtime.reality.extraction import (
    OpenAICompatRealityExtractor,
    RealityCandidate,
    validate_reality_payload,
)
from mind_runtime.reality.temporal import normalize_temporal, resolve_trusted_timezone

ANCHOR = datetime(2026, 9, 9, 14, 0, tzinfo=UTC)
SHANGHAI = ZoneInfo("Asia/Shanghai")


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ('```json\n[{"type":"sleep"}]\n```', [{"type": "sleep"}]),
        ('Result: [{"type":"awake"}] done', [{"type": "awake"}]),
        ("no JSON array", ()),
    ],
)
def test_optional_provider_parses_only_bounded_arrays(
    monkeypatch: pytest.MonkeyPatch, content: str, expected: object
) -> None:
    calls: list[tuple[str, float, dict[str, object]]] = []

    def fake_urlopen(request: urllib.request.Request, timeout: float) -> io.BytesIO:
        calls.append((request.full_url, timeout, json.loads(request.data or b"{}")))
        return io.BytesIO(
            json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    provider = OpenAICompatRealityExtractor(
        base_url="https://example.invalid/v1/", model="bounded-model", timeout=4.0
    )
    assert provider.extract("我刚睡醒") == expected
    assert len(calls) == 1
    url, timeout, payload = calls[0]
    assert url == "https://example.invalid/v1/chat/completions"
    assert timeout == 4.0
    assert payload["model"] == "bounded-model"
    assert payload["temperature"] == 0.0
    assert payload["max_tokens"] == 512
    messages = payload["messages"]
    assert isinstance(messages, list)
    assert messages[1] == {
        "role": "user",
        "content": "User message: 我刚睡醒\n\nJSON array only:",
    }


@pytest.mark.parametrize("failure", ["offline", "invalid_json"])
def test_optional_provider_failure_returns_no_proposals(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    def fake_urlopen(request: urllib.request.Request, timeout: float) -> io.BytesIO:
        del request, timeout
        if failure == "offline":
            raise urllib.error.URLError("offline")
        return io.BytesIO(b"not json")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    provider = OpenAICompatRealityExtractor(base_url="https://example.invalid/v1", model="m")
    assert provider.extract("复合叙述") == ()


def test_structured_payload_rejects_unsafe_items_and_keeps_exact_targets() -> None:
    def item(kind: str, key: object, value: str, confidence: object = 0.9) -> dict[str, object]:
        return {
            "type": kind,
            "key": key,
            "value": value,
            "confidence": confidence,
            "certainty": "confirmed",
            "time_expression": "now",
        }

    assert validate_reality_payload("not an array", source_text="x") == ()
    proposals = validate_reality_payload(
        [
            None,
            item("unknown", "exercise", "done"),
            {**item("activity", "exercise", "done"), "certainty": "fictional"},
            {**item("activity", "exercise", "done"), "time_expression": "next_year"},
            item("activity", "exercise", "done", "not-a-number"),
            item("activity", "exercise", "done", float("inf")),
            item("activity", "", "done"),
            item("activity", "exercise", ""),
            item("plan", "书法", "cancelled"),
            item("activity", "游泳", "done"),
            item("resolve", "胃", "better"),
            item("awake", "ignored", ""),
            item("sleep", "ignored", ""),
        ],
        source_text="明确的用户叙述",
    )
    assert [(item.observation_key, item.value) for item in proposals] == [
        ("user.plan.calligraphy.cancelled", "cancelled"),
        ("user.activity.swimming.completed", "done"),
        ("user.health.stomach_pain.resolved", "better"),
        ("user.sleep.phase.observed", "awake"),
        ("user.sleep.phase.observed", "sleeping"),
    ]
    assert all(isinstance(item, RealityCandidate) for item in proposals)


@pytest.mark.parametrize(
    ("utterance", "daypart", "start", "end"),
    [
        ("我明天早上去跑步", SemanticDaypart.MORNING, (10, 6), (10, 12)),
        ("我明天晚上去跑步", SemanticDaypart.NIGHT, (10, 21), (11, 6)),
    ],
)
def test_future_local_dayparts_have_bounded_utc_windows_but_are_not_current(
    utterance: str,
    daypart: SemanticDaypart,
    start: tuple[int, int],
    end: tuple[int, int],
) -> None:
    result = normalize_temporal(utterance, anchor=ANCHOR, timezone=SHANGHAI)
    assert result.modality is ObservationModality.PLANNED
    assert result.semantic_time == SemanticTime(
        relation=SemanticRelation.FUTURE,
        precision=SemanticPrecision.DAYPART,
        daypart=daypart,
    )
    assert result.effective_window == EffectiveWindow(
        kind=EffectiveWindowKind.INTERVAL,
        start_at=datetime(2026, 9, start[0], start[1], tzinfo=SHANGHAI).astimezone(UTC),
        end_at=datetime(2026, 9, end[0], end[1], tzinfo=SHANGHAI).astimezone(UTC),
    )


def test_today_estimate_needs_trusted_timezone_for_current_interval() -> None:
    text = "我估计今天要休息"
    resolved = normalize_temporal(text, anchor=ANCHOR, timezone=SHANGHAI)
    unresolved = normalize_temporal(text, anchor=ANCHOR, timezone=None)
    assert resolved.modality is ObservationModality.ESTIMATED
    assert resolved.semantic_time.relation is SemanticRelation.CURRENT
    assert resolved.semantic_time.precision is SemanticPrecision.DAY
    assert resolved.effective_window == EffectiveWindow(
        kind=EffectiveWindowKind.INTERVAL,
        start_at=datetime(2026, 9, 9, tzinfo=SHANGHAI).astimezone(UTC),
        end_at=datetime(2026, 9, 10, tzinfo=SHANGHAI).astimezone(UTC),
    )
    assert unresolved.effective_window is None


def test_invalid_timezone_and_non_utc_anchor_never_gain_time_authority() -> None:
    assert resolve_trusted_timezone(user_tz="not/a-zone", host_tz=None) is None
    with pytest.raises(ValueError, match="aware UTC"):
        normalize_temporal("现在", anchor=ANCHOR.astimezone(SHANGHAI), timezone=SHANGHAI)
    with pytest.raises(ValueError, match="aware UTC"):
        normalize_temporal("现在", anchor=datetime(2026, 9, 9, 14), timezone=SHANGHAI)


@pytest.mark.parametrize(
    ("field", "bad"),
    [("relation", "distant"), ("precision", "month"), ("daypart", "sunrise")],
)
def test_semantic_time_rejects_unknown_vocabulary(field: str, bad: str) -> None:
    raw: dict[str, object] = {"relation": "future", "precision": "daypart", "daypart": "morning"}
    raw[field] = bad
    with pytest.raises(ValueError, match=f"invalid semantic {field}"):
        SemanticTime(**raw)


def test_contract_accepts_known_strings_and_rejects_unknown_window_kind() -> None:
    assert SemanticTime("future", "daypart", "morning") == SemanticTime(
        SemanticRelation.FUTURE, SemanticPrecision.DAYPART, SemanticDaypart.MORNING
    )
    assert EffectiveWindow("interval", ANCHOR, ANCHOR + timedelta(hours=1)).kind is (
        EffectiveWindowKind.INTERVAL
    )
    with pytest.raises(ValueError, match="invalid effective window kind"):
        EffectiveWindow("unresolved", ANCHOR)
