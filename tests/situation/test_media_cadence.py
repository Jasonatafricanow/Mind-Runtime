"""LR-pure: the media photo cadence rule (C6B read/derivation half).

Legacy gap #6 (docs/legacy/kayla-rule-map.md image.quota_frequency): an
image becomes OPTIONAL once >= N settled proactive prompts have passed
since the last settled SEND_PHOTO, where N is REQUIRED deployment
configuration. ``threshold=None`` disables the cadence feature entirely —
a generic runtime never inherits one deployment's 1-per-3 rule (the
algorithm is generic; the numbers are configuration). Eligibility is
never an obligation, the daily media cap stays ActionPolicy authority,
and a missing counter fails closed (not eligible).
"""

import pytest

from mind_runtime.situation.derived import media_photo_cadence_eligible


def test_disabled_when_no_threshold_configured() -> None:
    """threshold=None is the generic runtime default: feature off."""
    assert media_photo_cadence_eligible(None, threshold=None) is False
    assert media_photo_cadence_eligible(0, threshold=None) is False
    assert media_photo_cadence_eligible(999, threshold=None) is False


def test_missing_counter_fails_closed() -> None:
    assert media_photo_cadence_eligible(None, threshold=3) is False
    assert media_photo_cadence_eligible(None, threshold=5) is False


def test_below_threshold_is_not_eligible() -> None:
    for count in (0, 1, 2):
        assert media_photo_cadence_eligible(count, threshold=3) is False


def test_threshold_reached_is_eligible_and_sticky() -> None:
    for count in (3, 4, 10):
        assert media_photo_cadence_eligible(count, threshold=3) is True


def test_threshold_is_configuration_not_law() -> None:
    assert media_photo_cadence_eligible(2, threshold=2) is True
    assert media_photo_cadence_eligible(1, threshold=2) is False
    # The same counter flips with a different deployment's threshold.
    assert media_photo_cadence_eligible(3, threshold=5) is False
    assert media_photo_cadence_eligible(5, threshold=5) is True


def test_invalid_threshold_is_rejected() -> None:
    for threshold in (0, -1, True):
        with pytest.raises(ValueError, match="positive integer"):
            media_photo_cadence_eligible(3, threshold=threshold)


def test_negative_count_is_rejected() -> None:
    with pytest.raises(ValueError, match="negative"):
        media_photo_cadence_eligible(-1, threshold=3)
