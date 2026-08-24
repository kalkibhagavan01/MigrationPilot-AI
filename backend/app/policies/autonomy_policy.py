from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from app.core.constants import (
    AUTO_MAPPING_MIN_GAP,
    AUTO_MAPPING_MIN_SCORE,
    AUTO_MAPPING_MIN_TYPE_SCORE,
    TARGET_FIELD_TYPES,
)


class AutonomyAction(StrEnum):
    AUTO = "AUTO"
    HITL = "HITL"
    STOP = "STOP"


class EscalationType(StrEnum):
    MAPPING_AMBIGUITY = "MAPPING_AMBIGUITY"
    VALUE_AMBIGUITY = "VALUE_AMBIGUITY"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"
    DUPLICATE_CONFLICT = "DUPLICATE_CONFLICT"
    VALIDATION_FAILURE = "VALIDATION_FAILURE"
    UNSUPPORTED_TRANSFORMATION = "UNSUPPORTED_TRANSFORMATION"
    LOW_CONFIDENCE_TRANSFORMATION = "LOW_CONFIDENCE_TRANSFORMATION"
    SYSTEM_FAILURE = "SYSTEM_FAILURE"


@dataclass(frozen=True)
class AutonomyDecision:
    action: AutonomyAction
    decision_type: EscalationType | None
    confidence: float
    reason: str
    evidence: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class MappingAutonomyInput:
    target_field: str | None
    final_score: float
    second_best_score: float
    type_score: float
    has_inherent_value_ambiguity: bool = False


class AutonomyPolicy:
    def decide_mapping(self, policy_input: MappingAutonomyInput) -> AutonomyDecision:
        if policy_input.target_field is None:
            return AutonomyDecision(
                action=AutonomyAction.HITL,
                decision_type=EscalationType.MAPPING_AMBIGUITY,
                confidence=policy_input.final_score,
                reason="No safe target field could be selected.",
                evidence=_mapping_evidence(policy_input),
            )

        if policy_input.target_field not in TARGET_FIELD_TYPES:
            return AutonomyDecision(
                action=AutonomyAction.STOP,
                decision_type=EscalationType.SYSTEM_FAILURE,
                confidence=policy_input.final_score,
                reason="The proposed target field is not present in the target schema.",
                evidence=_mapping_evidence(policy_input),
            )

        if policy_input.has_inherent_value_ambiguity:
            return AutonomyDecision(
                action=AutonomyAction.HITL,
                decision_type=EscalationType.VALUE_AMBIGUITY,
                confidence=policy_input.final_score,
                reason="The sample values are inherently ambiguous and should not be guessed.",
                evidence=_mapping_evidence(policy_input),
            )

        if Decimal(str(policy_input.type_score)) < AUTO_MAPPING_MIN_TYPE_SCORE:
            return AutonomyDecision(
                action=AutonomyAction.HITL,
                decision_type=EscalationType.UNSUPPORTED_TRANSFORMATION,
                confidence=policy_input.final_score,
                reason="The source values do not match the expected target field type.",
                evidence=_mapping_evidence(policy_input),
            )

        final_score = Decimal(str(policy_input.final_score))
        score_gap = Decimal(str(policy_input.final_score - policy_input.second_best_score))
        if final_score >= AUTO_MAPPING_MIN_SCORE and score_gap >= AUTO_MAPPING_MIN_GAP:
            return AutonomyDecision(
                action=AutonomyAction.AUTO,
                decision_type=None,
                confidence=policy_input.final_score,
                reason="The proposed field has high confidence and a clear lead over alternatives.",
                evidence=_mapping_evidence(policy_input),
            )

        decision_type = (
            EscalationType.MAPPING_AMBIGUITY
            if score_gap < AUTO_MAPPING_MIN_GAP
            else EscalationType.LOW_CONFIDENCE_TRANSFORMATION
        )
        return AutonomyDecision(
            action=AutonomyAction.HITL,
            decision_type=decision_type,
            confidence=policy_input.final_score,
            reason="The mapping is not safe enough to approve automatically.",
            evidence=_mapping_evidence(policy_input),
        )


def _mapping_evidence(policy_input: MappingAutonomyInput) -> dict[str, object]:
    return {
        "target_field": policy_input.target_field,
        "final_score": policy_input.final_score,
        "second_best_score": policy_input.second_best_score,
        "candidate_gap": round(policy_input.final_score - policy_input.second_best_score, 4),
        "type_score": policy_input.type_score,
        "has_inherent_value_ambiguity": policy_input.has_inherent_value_ambiguity,
    }
