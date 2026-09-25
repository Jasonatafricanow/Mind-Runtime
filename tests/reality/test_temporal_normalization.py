"""RED 4 tests for deterministic temporal normalization and timezone authority."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from mind_runtime.contracts import (
    EffectiveWindow,
    EffectiveWindowKind,
    ObservationModality,
    SemanticDaypart,
    SemanticPrecision,
    SemanticRelation,
)
from mind_runtime.reality.temporal import (
    normalize_temporal,
    resolve_trusted_timezone,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
NEW_YORK = ZoneInfo("America/New_York")
ANCHOR_UTC = datetime(2026, 9, 9, 14, 0, tzinfo=UTC)  # 2026-09-09 22:00 Shanghai


def test_current_instant_normalization() -> None:
    """Phrase '我现在胃疼' and '我刚睡醒' normalize to current/instant with open interval."""
    for text in ["我现在胃疼", "我刚睡醒"]:
        result = normalize_temporal(text, anchor=ANCHOR_UTC, timezone=SHANGHAI)
        assert result.modality is ObservationModality.ASSERTED
        assert result.semantic_time.relation is SemanticRelation.CURRENT
        assert result.semantic_time.precision is SemanticPrecision.INSTANT
        assert result.semantic_time.daypart is None
        assert result.effective_window == EffectiveWindow(
            kind=EffectiveWindowKind.OPEN_INTERVAL,
            start_at=ANCHOR_UTC,
            end_at=None,
        )


def test_past_night_normalization_with_trusted_timezone() -> None:
    """Phrase '我昨晚没睡好' normalizes to past/daypart/night with prior night interval."""
    result = normalize_temporal("我昨晚没睡好", anchor=ANCHOR_UTC, timezone=SHANGHAI)
    assert result.modality is ObservationModality.ASSERTED
    assert result.semantic_time.relation is SemanticRelation.PAST
    assert result.semantic_time.precision is SemanticPrecision.DAYPART
    assert result.semantic_time.daypart is SemanticDaypart.NIGHT

    # In Shanghai (UTC+8), anchor is 2026-09-09 22:00 (Wednesday).
    # Prior night started 2026-09-08 21:00 (Tuesday) to 2026-09-09 06:00 (Wednesday).
    # 2026-09-08 21:00 CST = 2026-09-08 13:00 UTC
    # 2026-09-09 06:00 CST = 2026-09-08 22:00 UTC
    expected_start = datetime(2026, 9, 8, 21, 0, tzinfo=SHANGHAI).astimezone(UTC)
    expected_end = datetime(2026, 9, 9, 6, 0, tzinfo=SHANGHAI).astimezone(UTC)

    assert result.effective_window == EffectiveWindow(
        kind=EffectiveWindowKind.INTERVAL,
        start_at=expected_start,
        end_at=expected_end,
    )


def test_past_night_normalization_without_trusted_timezone_falls_back_to_null_window() -> None:
    """Without a trusted timezone, '我昨晚没睡好' retains semantic time but window is None."""
    result = normalize_temporal("我昨晚没睡好", anchor=ANCHOR_UTC, timezone=None)
    assert result.modality is ObservationModality.ASSERTED
    assert result.semantic_time.relation is SemanticRelation.PAST
    assert result.semantic_time.precision is SemanticPrecision.DAYPART
    assert result.semantic_time.daypart is SemanticDaypart.NIGHT
    assert result.effective_window is None


def test_future_daypart_planned_vs_tentative() -> None:
    """'明天下午去写书法' is PLANNED, while '明天下午可能去写书法' is TENTATIVE."""
    planned = normalize_temporal("我明天下午去写书法", anchor=ANCHOR_UTC, timezone=SHANGHAI)
    assert planned.modality is ObservationModality.PLANNED
    assert planned.semantic_time.relation is SemanticRelation.FUTURE
    assert planned.semantic_time.precision is SemanticPrecision.DAYPART
    assert planned.semantic_time.daypart is SemanticDaypart.AFTERNOON

    # Tomorrow in Shanghai is 2026-09-10. Afternoon: 12:00 to 18:00 CST.
    # 2026-09-10 12:00 CST = 04:00 UTC, 18:00 CST = 10:00 UTC
    expected_start = datetime(2026, 9, 10, 12, 0, tzinfo=SHANGHAI).astimezone(UTC)
    expected_end = datetime(2026, 9, 10, 18, 0, tzinfo=SHANGHAI).astimezone(UTC)

    assert planned.effective_window == EffectiveWindow(
        kind=EffectiveWindowKind.INTERVAL,
        start_at=expected_start,
        end_at=expected_end,
    )

    tentative = normalize_temporal("我明天下午可能去写书法", anchor=ANCHOR_UTC, timezone=SHANGHAI)
    assert tentative.modality is ObservationModality.TENTATIVE
    assert tentative.semantic_time == planned.semantic_time
    assert tentative.effective_window == planned.effective_window


def test_future_daypart_without_timezone_yields_null_window() -> None:
    """Without trusted timezone, relative date cannot resolve to UTC bounds."""
    result = normalize_temporal("我明天下午去写书法", anchor=ANCHOR_UTC, timezone=None)
    assert result.modality is ObservationModality.PLANNED
    assert result.semantic_time.relation is SemanticRelation.FUTURE
    assert result.semantic_time.precision is SemanticPrecision.DAYPART
    assert result.semantic_time.daypart is SemanticDaypart.AFTERNOON
    assert result.effective_window is None


def test_unresolved_future_range() -> None:
    """'我可能换工作' normalizes to TENTATIVE future range with null window."""
    result = normalize_temporal("我可能换工作", anchor=ANCHOR_UTC, timezone=SHANGHAI)
    assert result.modality is ObservationModality.TENTATIVE
    assert result.semantic_time.relation is SemanticRelation.FUTURE
    assert result.semantic_time.precision is SemanticPrecision.RANGE
    assert result.semantic_time.daypart is None
    assert result.effective_window is None


def test_timezone_precedence_user_over_host_over_source() -> None:
    """Precedence: user > host > source (only when trusted)."""
    # 1. User overrides host and source
    tz1 = resolve_trusted_timezone(
        user_tz="Asia/Shanghai",
        host_tz="America/New_York",
        source_tz="Europe/London",
        source_trusted=True,
    )
    assert tz1 == SHANGHAI

    # 2. Host overrides source
    tz2 = resolve_trusted_timezone(
        user_tz=None,
        host_tz=NEW_YORK,
        source_tz="Europe/London",
        source_trusted=True,
    )
    assert tz2 == NEW_YORK

    # 3. Source used only when source_trusted is True
    tz3 = resolve_trusted_timezone(
        user_tz=None,
        host_tz=None,
        source_tz="Asia/Shanghai",
        source_trusted=True,
    )
    assert tz3 == SHANGHAI

    # 4. Untrusted source is ignored -> None
    tz4 = resolve_trusted_timezone(
        user_tz=None,
        host_tz=None,
        source_tz="Asia/Shanghai",
        source_trusted=False,
    )
    assert tz4 is None
