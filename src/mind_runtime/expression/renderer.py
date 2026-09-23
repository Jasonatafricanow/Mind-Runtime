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
    ExpressionContextKind.SURFACE_GUIDANCE: 3,
    ExpressionContextKind.SURFACE_CONTROL: 3,
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
    ExpressionContextKind.SURFACE_GUIDANCE: "SURFACE_GUIDANCE",
    ExpressionContextKind.SURFACE_CONTROL: "SURFACE_GUIDANCE",
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
    ExpressionContextKind.SURFACE_GUIDANCE,
    ExpressionContextKind.SURFACE_CONTROL,
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
    ExpressionContextKind.SURFACE_GUIDANCE,
    ExpressionContextKind.SURFACE_CONTROL,
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
        surface_mode = any(item.kind is ExpressionContextKind.SURFACE_GUIDANCE for item in items)
        if surface_mode:
            guidance = {item.key for item in items
                        if item.kind is ExpressionContextKind.SURFACE_GUIDANCE}
            if guidance != {"directness", "warmth", "restraint"}:
                raise ValueError("SURFACE_ESSENTIAL_BUNDLE_INCOMPLETE")
            if sum(item.kind is ExpressionContextKind.ACTION for item in items) != 1:
                raise ValueError("SURFACE_ESSENTIAL_BUNDLE_INCOMPLETE")
            if any(item.kind in (ExpressionContextKind.INTERNAL_STATE,
                                 ExpressionContextKind.SURFACE_CONTROL) for item in items):
                raise ValueError("SURFACE_PROVIDER_ISOLATION_VIOLATION")
        included, omitted = self._fit_budget(items)
        rendered_text = _render_text(included)
        if surface_mode:
            self.verify_provider_information_isolation(rendered_text)
        return ProviderExpressionContext(
            render_id=f"render-{context.context_id}",
            context_id=context.context_id,
            scope=context.scope,
            origin_runtime_id=context.origin_runtime_id,
            text=rendered_text,
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

    @classmethod
    def render_surface_bundle(cls, context: DecisionContext) -> dict[str, str]:
        """Extract admitted qualitative guidance bundle from DecisionContext."""
        guidance: dict[str, str] = {}
        if not hasattr(context, "expression_context"):
            return guidance
        for item in context.expression_context:
            if item.kind in (
                ExpressionContextKind.SURFACE_GUIDANCE,
                ExpressionContextKind.SURFACE_CONTROL,
            ):
                guidance[item.key] = item.value
        return guidance

    @staticmethod
    def format_surface_guidance(guidance: dict[str, str]) -> str:
        """Format qualitative guidance dictionary into bounded provider lines."""
        lines = ["Expression guidance:"]
        for key in sorted(guidance.keys()):
            lines.append(f"- {key}: {guidance[key]}")
        return "\n".join(lines)

    @staticmethod
    def verify_provider_information_isolation(text: str) -> bool:
        """Verify that provider context contains ZERO raw numbers, traits, dynamics, or digests."""
        import re

        # 1. Zero raw floats (e.g. 0.41, 0.410, 1.05, -0.4, 0.500)
        # 1. Zero raw Persona trait names
        forbidden_traits = [
            "stability",
            "expressiveness",
            "relational_acuity",
            "assertiveness",
        ]
        for trait in forbidden_traits:
            if re.search(rf"\b{re.escape(trait)}\b\s*[:=]", text):
                raise AssertionError(
                    f"Information isolation violation: raw trait '{trait}' "
                    "assignment found in provider text"
                )

        # 2. Zero raw affect/dynamics dimension names
        forbidden_dynamics = [
            "attachment_approach",
            "longing",
            "closeness_craving",
            "anger",
            "sharing_urge",
            "curiosity",
            "sadness",
            "diligence_pressure",
            "confrontation_readiness",
            "expressive_warmth_bias",
            "social_pull",
        ]
        for dim in forbidden_dynamics:
            if re.search(rf"\b{re.escape(dim)}\b", text):
                raise AssertionError(
                    f"Information isolation violation: raw dynamics dimension '{dim}' "
                    "found in provider text"
                )

        # 3. Zero excluded surface controls (contact_seeking, initiative)
        for excluded in ("contact_seeking", "initiative"):
            if re.search(rf"\b{re.escape(excluded)}\b", text):
                raise AssertionError(
                    f"Information isolation violation: excluded surface control '{excluded}' "
                    "found in provider text"
                )

        # 4. Zero Slow numeric state references
        if re.search(r"slow_\w+\s*=\s*\d+", text) or re.search(r"slow_state\s*:", text):
            raise AssertionError(
                "Information isolation violation: slow numeric state found in provider text"
            )

        # 5. Zero internal cryptographic hashes (64-char hex strings)
        hex_hashes = re.findall(r"\b[0-9a-f]{64}\b", text)
        if hex_hashes:
            raise AssertionError(
                "Information isolation violation: internal content digests found in "
                f"provider text: {hex_hashes}"
            )

        # 6. Zero raw floats (e.g. 0.41, 0.410, 1.05, -0.4, 0.500)
        # Matches decimal numbers
        float_matches = re.findall(r"(?<![a-zA-Z0-9_])[-+]?\d+\.\d+(?![a-zA-Z0-9_])", text)
        if float_matches:
            raise AssertionError(
                "Information isolation violation: raw floats found in provider "
                f"text: {float_matches}"
            )

        for diagnostic in (
            r"\battempt\s*=", r"\bsituation_ref\b", r"\bcontrols_id\b",
            r"\bprojection_id\b", r"\bstate_id\b", r"\bdependency_digest\b",
            r"\bpersona_content_digest\b", r"\brecipe_digest\b",
        ):
            if re.search(diagnostic, text, flags=re.IGNORECASE):
                raise AssertionError("Information isolation violation: diagnostic reference")

        return True

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
