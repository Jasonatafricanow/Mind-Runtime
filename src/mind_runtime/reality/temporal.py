"""Deterministic temporal normalization for Reality observations (MR-REALITY §4-§6)."""

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from mind_runtime.contracts import (
    EffectiveWindow,
    EffectiveWindowKind,
    ObservationModality,
    SemanticDaypart,
    SemanticPrecision,
    SemanticRelation,
    SemanticTime,
)


@dataclass(frozen=True, slots=True)
class NormalizedTemporal:
    """The deterministic temporal normalization result for one proposition."""

    modality: ObservationModality
    semantic_time: SemanticTime
    effective_window: EffectiveWindow | None


def resolve_trusted_timezone(
    *,
    user_tz: ZoneInfo | str | None = None,
    host_tz: ZoneInfo | str | None = None,
    source_tz: ZoneInfo | str | None = None,
    source_trusted: bool = False,
) -> ZoneInfo | None:
    """Resolve timezone by strict authority precedence: user > host > source (trusted only)."""

    def _to_zoneinfo(tz: ZoneInfo | str | None) -> ZoneInfo | None:
        if tz is None:
            return None
        if isinstance(tz, ZoneInfo):
            return tz
        if isinstance(tz, str):
            try:
                return ZoneInfo(tz)
            except Exception:
                return None
        return None

    if (resolved := _to_zoneinfo(user_tz)) is not None:
        return resolved
    if (resolved := _to_zoneinfo(host_tz)) is not None:
        return resolved
    if source_trusted and (resolved := _to_zoneinfo(source_tz)) is not None:
        return resolved
    return None


def normalize_temporal(
    text: str,
    *,
    anchor: datetime,
    timezone: ZoneInfo | None = None,
    certainty_hint: str | None = None,
    time_expression_hint: str | None = None,
) -> NormalizedTemporal:
    """Deterministically normalize proposition modality, semantic time, and effective window.

    Rules (MR-REALITY §3-§6):
      1. Anchor is always the original Evidence.received_at (aware UTC).
      2. Timezone is only used if trusted; without trusted timezone, timezone-dependent
         relative intervals fall back to effective_window = None.
      3. Modality reflects assertion status (ASSERTED, PLANNED, TENTATIVE, ESTIMATED, INFERRED),
         independent of numeric extraction confidence.
    """
    if anchor.tzinfo is None or anchor.utcoffset() != timedelta(0):
        raise ValueError("anchor must be an aware UTC datetime")

    # 1. Modality derivation
    is_tentative = (
        "可能" in text
        or "也许" in text
        or "大概" in text
        or certainty_hint in {"tentative", "uncertain"}
    )
    is_planned = (
        ("明天" in text or "下周" in text or certainty_hint == "planned")
        and not is_tentative
    )
    is_estimated = (
        "大约" in text or "估计" in text or certainty_hint == "estimated"
    ) and not is_tentative

    if is_tentative:
        modality = ObservationModality.TENTATIVE
    elif is_planned:
        modality = ObservationModality.PLANNED
    elif is_estimated:
        modality = ObservationModality.ESTIMATED
    else:
        modality = ObservationModality.ASSERTED

    # 2. Semantic time and effective window derivation
    # Past night: "昨晚", "昨天晚上", "昨天夜里"
    if (
        "昨晚" in text
        or "昨天晚上" in text
        or "昨天夜里" in text
        or time_expression_hint in {"last_night", "yesterday_night"}
    ):
        semantic_time = SemanticTime(
            relation=SemanticRelation.PAST,
            precision=SemanticPrecision.DAYPART,
            daypart=SemanticDaypart.NIGHT,
        )
        effective_window = None
        if timezone is not None:
            anchor_local = anchor.astimezone(timezone)
            yesterday = anchor_local.date() - timedelta(days=1)
            start_local = datetime.combine(yesterday, time(21, 0), tzinfo=timezone)
            end_local = datetime.combine(anchor_local.date(), time(6, 0), tzinfo=timezone)
            effective_window = EffectiveWindow(
                kind=EffectiveWindowKind.INTERVAL,
                start_at=start_local.astimezone(UTC),
                end_at=end_local.astimezone(UTC),
            )
        return NormalizedTemporal(
            modality=modality,
            semantic_time=semantic_time,
            effective_window=effective_window,
        )

    # Tomorrow afternoon: "明天下午"
    if "明天下午" in text or time_expression_hint == "tomorrow_afternoon":
        semantic_time = SemanticTime(
            relation=SemanticRelation.FUTURE,
            precision=SemanticPrecision.DAYPART,
            daypart=SemanticDaypart.AFTERNOON,
        )
        effective_window = None
        if timezone is not None:
            anchor_local = anchor.astimezone(timezone)
            tomorrow = anchor_local.date() + timedelta(days=1)
            start_local = datetime.combine(tomorrow, time(12, 0), tzinfo=timezone)
            end_local = datetime.combine(tomorrow, time(18, 0), tzinfo=timezone)
            effective_window = EffectiveWindow(
                kind=EffectiveWindowKind.INTERVAL,
                start_at=start_local.astimezone(UTC),
                end_at=end_local.astimezone(UTC),
            )
        return NormalizedTemporal(
            modality=modality,
            semantic_time=semantic_time,
            effective_window=effective_window,
        )

    # Tomorrow morning: "明天上午" / "明天早上"
    if "明天上午" in text or "明天早上" in text:
        semantic_time = SemanticTime(
            relation=SemanticRelation.FUTURE,
            precision=SemanticPrecision.DAYPART,
            daypart=SemanticDaypart.MORNING,
        )
        effective_window = None
        if timezone is not None:
            anchor_local = anchor.astimezone(timezone)
            tomorrow = anchor_local.date() + timedelta(days=1)
            start_local = datetime.combine(tomorrow, time(6, 0), tzinfo=timezone)
            end_local = datetime.combine(tomorrow, time(12, 0), tzinfo=timezone)
            effective_window = EffectiveWindow(
                kind=EffectiveWindowKind.INTERVAL,
                start_at=start_local.astimezone(UTC),
                end_at=end_local.astimezone(UTC),
            )
        return NormalizedTemporal(
            modality=modality,
            semantic_time=semantic_time,
            effective_window=effective_window,
        )

    # Tomorrow evening / night: "明天晚上"
    if "明天晚上" in text:
        semantic_time = SemanticTime(
            relation=SemanticRelation.FUTURE,
            precision=SemanticPrecision.DAYPART,
            daypart=SemanticDaypart.NIGHT,
        )
        effective_window = None
        if timezone is not None:
            anchor_local = anchor.astimezone(timezone)
            tomorrow = anchor_local.date() + timedelta(days=1)
            start_local = datetime.combine(tomorrow, time(21, 0), tzinfo=timezone)
            end_local = datetime.combine(tomorrow + timedelta(days=1), time(6, 0), tzinfo=timezone)
            effective_window = EffectiveWindow(
                kind=EffectiveWindowKind.INTERVAL,
                start_at=start_local.astimezone(UTC),
                end_at=end_local.astimezone(UTC),
            )
        return NormalizedTemporal(
            modality=modality,
            semantic_time=semantic_time,
            effective_window=effective_window,
        )

    # Today / tonight
    if "今天" in text or time_expression_hint == "today":
        semantic_time = SemanticTime(
            relation=SemanticRelation.CURRENT,
            precision=SemanticPrecision.DAY,
            daypart=None,
        )
        effective_window = None
        if timezone is not None:
            anchor_local = anchor.astimezone(timezone)
            today = anchor_local.date()
            start_local = datetime.combine(today, time(0, 0), tzinfo=timezone)
            end_local = datetime.combine(today + timedelta(days=1), time(0, 0), tzinfo=timezone)
            effective_window = EffectiveWindow(
                kind=EffectiveWindowKind.INTERVAL,
                start_at=start_local.astimezone(UTC),
                end_at=end_local.astimezone(UTC),
            )
        return NormalizedTemporal(
            modality=modality,
            semantic_time=semantic_time,
            effective_window=effective_window,
        )

    # Unresolved future range (e.g. "换工作", "过阵子", "以后")
    if (
        "换工作" in text
        or "过阵子" in text
        or "以后" in text
        or (is_tentative and "现在" not in text and "刚" not in text)
    ):
        return NormalizedTemporal(
            modality=modality,
            semantic_time=SemanticTime(
                relation=SemanticRelation.FUTURE,
                precision=SemanticPrecision.RANGE,
                daypart=None,
            ),
            effective_window=None,
        )

    # Default / Current instant: "现在", "刚", "刚刚", or default ongoing state
    return NormalizedTemporal(
        modality=modality,
        semantic_time=SemanticTime(
            relation=SemanticRelation.CURRENT,
            precision=SemanticPrecision.INSTANT,
            daypart=None,
        ),
        effective_window=EffectiveWindow(
            kind=EffectiveWindowKind.OPEN_INTERVAL,
            start_at=anchor,
            end_at=None,
        ),
    )
