"""Versioned one-pass output protocol owned by Host composition."""

import json
import re
from dataclasses import dataclass

PROMPT_VERSION = "semantic_delta_prompt_v1"
PROMPT = """semantic_delta_prompt_v1
Use the normal conversation and MR context to answer the user. On the final response, return
one JSON object: {"assistant_response":"normal prose","semantic_delta":{
"schema_version":"semantic_delta_v1","points":[],"dependencies":[]}}.
Both outputs must come from this same inference. Do not call another semantic model.
The sidecar describes ONLY new/changed/retracted meaning caused by the latest raw USER turn.
Never re-emit existing or unchanged historical cognition, persistent constraints,
or old memory text.
"Other things unchanged" requires no preserve points or edges.
Each point has local point_id, context-resolved faithful natural-language meaning, status
(resolved/defer), speech_act (assertion/question/directive/other),
polarity (positive/negative/unknown),
epistemic_status (asserted/uncertain/hypothetical/counterfactual/planned/reported/unknown),
temporal_scope (past/current/future/atemporal/unknown), optional temporal_expression
and unresolved_refs.
Do not guess absolute time. Ambiguous references must DEFER; do not guess or strengthen meaning.
Dependencies have from_point_id, target_kind (point/memory), target_id, natural-language relation,
boundary_policy (cohabit/context), lifecycle_effect (none/supersede).
Cohabit only between current local points when separation changes the original meaning.
Context keeps separate cognition identity. Supersede only an activated memory with context.
Independent points need no edges. Never emit pairwise separate edges or full lifecycle graphs.
Memory targets MUST use only the supplied activated IDs. Do not output final Block grouping,
canonical IDs, source identities, scope, interaction ID, runtime ID, known_at, or compiler version.
Emit assistant_response first. The semantic_delta value may be a JSON object or JSON string;
invalid or missing sidecar does not invalidate the normal response.
"""


@dataclass(frozen=True, slots=True)
class BodyTurnResultV1:
    assistant_response: str
    semantic_delta: object | None


def _unique_object(pairs):
    data = {}
    for key, value in pairs:
        if key in data:
            raise ValueError("duplicate envelope/sidecar key")
        data[key] = value
    return data


def _invalid_constant(value):
    raise ValueError("non-JSON constant")


def parse_body_turn_result(value) -> BodyTurnResultV1:
    """Recover independently valid prose even when a JSON sidecar is malformed."""
    if isinstance(value, dict):
        data = value
    elif isinstance(value, str):
        text = value.strip()
        if text.startswith("```") and text.endswith("```"):
            text = re.sub(r"^\`\`\`(?:json)?\s*|\`\`\`$", "", text).strip()
        try:
            data = json.loads(
                text, object_pairs_hook=_unique_object, parse_constant=_invalid_constant
            )
        except (ValueError, RecursionError):
            # Only the explicit first sibling field grants response bytes, never the sidecar.
            match = re.match(r'^\s*\{\s*"assistant_response"\s*:\s*', text)
            if match:
                try:
                    response, _ = json.JSONDecoder().raw_decode(text[match.end() :])
                    if isinstance(response, str):
                        return BodyTurnResultV1(response, None)
                except ValueError:
                    pass
            return BodyTurnResultV1(value, None)
    else:
        raise ValueError("Body response must be text or envelope")
    if not isinstance(data, dict) or not isinstance(data.get("assistant_response"), str):
        return BodyTurnResultV1(value if isinstance(value, str) else "", None)
    # Extra authority fields invalidate the sidecar, while prose remains independent.
    sidecar = data.get("semantic_delta", data.get("semantic_sidecar"))
    if set(data) - {"assistant_response", "semantic_delta", "semantic_sidecar"}:
        sidecar = None
    return BodyTurnResultV1(data["assistant_response"], sidecar)
