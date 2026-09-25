"""Deterministic, budgeted serialization of typed decision context."""

from __future__ import annotations

from mind_runtime.contracts import (
    DecisionContext,
    DiagnosticExpressionContext,
    ExpressionContextItem,
    ExpressionContextKind,
    ProviderExpressionContext,
)
from mind_runtime.expression.context import DecisionContextConfig

SECTION_ORDER = {
    ExpressionContextKind.ACTION: 0,
    ExpressionContextKind.FACT: 1,
    ExpressionContextKind.COGNITIVE_MEANING: 2,
    ExpressionContextKind.INTERNAL_STATE: 2,
    ExpressionContextKind.POLICY_CONSTRAINT: 3,
    ExpressionContextKind.PERSONA_STYLE: 4,
    ExpressionContextKind.HISTORY: 5,
    ExpressionContextKind.PRIOR_EXPRESSION: 6,
    ExpressionContextKind.REWRITE_GUIDANCE: 7,
}

_SECTION_LABEL = {
    ExpressionContextKind.ACTION: "ACTION",
    ExpressionContextKind.FACT: "FACT",
    ExpressionContextKind.COGNITIVE_MEANING: "COGNITIVE_MEANING",
    ExpressionContextKind.INTERNAL_STATE: "INTERNAL_STATE",
    ExpressionContextKind.POLICY_CONSTRAINT: "POLICY_CONSTRAINT",
    ExpressionContextKind.PERSONA_STYLE: "PERSONA_STYLE",
    ExpressionContextKind.HISTORY: "HISTORY",
    ExpressionContextKind.PRIOR_EXPRESSION: "PRIOR_EXPRESSION",
    ExpressionContextKind.REWRITE_GUIDANCE: "REWRITE_GUIDANCE",
}

_TRUSTED_KINDS = {
    ExpressionContextKind.ACTION,
    ExpressionContextKind.POLICY_CONSTRAINT,
    ExpressionContextKind.PERSONA_STYLE,
    ExpressionContextKind.REWRITE_GUIDANCE,
}

_DATA_KINDS = {
    ExpressionContextKind.FACT,
    ExpressionContextKind.INTERNAL_STATE,
}

_UNTRUSTED_KINDS = {
    ExpressionContextKind.COGNITIVE_MEANING,
    ExpressionContextKind.HISTORY,
    ExpressionContextKind.PRIOR_EXPRESSION,
}

_ESSENTIAL_KINDS = {
    ExpressionContextKind.ACTION,
    ExpressionContextKind.POLICY_CONSTRAINT,
}


def _escape_data(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\r", "\\r").replace("\n", "\\n")


def _item_sort_key(item: ExpressionContextItem) -> tuple[int, int, str, tuple[str, ...], str]:
    return (item.priority, SECTION_ORDER[item.kind], item.key, item.source_refs, item.item_id)


class DeterministicContextRenderer:
    """Serialize one typed context into the only provider-visible envelope."""

    def __init__(self, config: DecisionContextConfig) -> None:
        if not isinstance(config, DecisionContextConfig):
            raise ValueError("config must be a DecisionContextConfig")
        self._config = config

    def render(self, context: DecisionContext) -> ProviderExpressionContext:
        if not isinstance(context, DecisionContext):
            raise ValueError("context must be a DecisionContext")
        items = sorted(context.expression_context, key=_item_sort_key)
        included, omitted = self._fit_budget(items)
        return ProviderExpressionContext(
            render_id=f"render-{context.context_id}",
            context_id=context.context_id,
            scope=context.scope,
            origin_runtime_id=context.origin_runtime_id,
            text=_render_text(included),
            included_item_ids=tuple(item.item_id for item in included),
            omitted_item_ids=tuple(item.item_id for item in omitted),
        )

    def render_cognitive_meaning(self, context: DecisionContext) -> str | None:
        """Return only meanings admitted into the same provider envelope."""
        rendered = self.render(context)
        admitted = set(rendered.included_item_ids)
        meanings = [
            item for item in context.expression_context
            if item.kind is ExpressionContextKind.COGNITIVE_MEANING
            and item.item_id in admitted
        ]
        return _render_text(sorted(meanings, key=_item_sort_key)) if meanings else None

    def render_diagnostic(self, context: DecisionContext) -> DiagnosticExpressionContext:
        if not isinstance(context, DecisionContext):
            raise ValueError("context must be a DecisionContext")
        items = sorted(context.expression_context, key=_item_sort_key)
        included, omitted = self._fit_budget(items)
        lines = [f"diagnostic {context.context_id}"]
        for item in included:
            refs = ",".join(item.source_refs)
            lines.append(
                f"- {item.item_id} kind={item.kind.value} priority={item.priority} refs={refs}"
            )
        if omitted:
            ids = ",".join(item.item_id for item in omitted)
            lines.append(f"omitted: {ids}")
        return DiagnosticExpressionContext(
            render_id=f"diag-{context.context_id}",
            context_id=context.context_id,
            text="\n".join(lines),
        )

    def _fit_budget(
        self, items: list[ExpressionContextItem]
    ) -> tuple[list[ExpressionContextItem], list[ExpressionContextItem]]:
        remaining = list(items)
        omitted: list[ExpressionContextItem] = []
        while len(_render_text(remaining)) > self._config.max_render_chars:
            removable = [item for item in remaining if item.kind not in _ESSENTIAL_KINDS]
            if not removable:
                raise ValueError("essential provider context exceeds render budget")
            dropped = removable[-1]
            remaining.remove(dropped)
            omitted.append(dropped)
        return remaining, omitted


def _render_text(items: list[ExpressionContextItem]) -> str:
    lines: list[str] = []
    current_section: ExpressionContextKind | None = None
    for item in items:
        if item.kind is not current_section:
            current_section = item.kind
            lines.append(f"[{_SECTION_LABEL[item.kind]}]")
        value = _escape_data(item.value)
        if item.kind in _UNTRUSTED_KINDS:
            if item.kind is ExpressionContextKind.COGNITIVE_MEANING:
                import json

                quoted = json.dumps(item.value, ensure_ascii=False)
                lines.append(f"- [APPRAISAL_DATA] {item.key}: {quoted}")
            else:
                lines.append(f"- [UNTRUSTED_DATA] {item.key}: {value}")
        elif item.kind in _DATA_KINDS:
            lines.append(f"- [DATA] {item.key}: {value}")
        else:
            lines.append(f"- {item.key}: {value}")
    return "\n".join(lines)
