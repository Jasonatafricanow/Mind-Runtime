"""Fake read-only historical provider for golden scenarios."""

from collections.abc import Mapping

from mind_runtime.contracts import HistoricalContextBundle, HistoricalContextQuery


class FakeHistoricalProvider:
    """Serves canned bundles by signature key; read-only, no Memory write."""

    def __init__(self, bundles: Mapping[tuple[str, ...], HistoricalContextBundle]) -> None:
        self._bundles = dict(bundles)

    def query(self, query: HistoricalContextQuery, *, signature: str) -> HistoricalContextBundle:
        try:
            return self._bundles[(signature,)]
        except KeyError:
            raise KeyError(f"unserved signature: {signature}") from None
