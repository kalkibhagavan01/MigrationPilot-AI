from dataclasses import dataclass

from app.core.enums import MappingDecision
from app.policies.autonomy_policy import AutonomyAction, AutonomyPolicy, MappingAutonomyInput


@dataclass(frozen=True)
class MappingDecisionInput:
    target_field: str | None
    final_score: float
    second_best_score: float
    type_score: float
    has_inherent_value_ambiguity: bool = False


class DecisionEngine:
    def __init__(self, autonomy_policy: AutonomyPolicy | None = None) -> None:
        self.autonomy_policy = autonomy_policy or AutonomyPolicy()

    def decide_mapping(self, decision_input: MappingDecisionInput) -> MappingDecision:
        decision = self.autonomy_policy.decide_mapping(
            MappingAutonomyInput(
                target_field=decision_input.target_field,
                final_score=decision_input.final_score,
                second_best_score=decision_input.second_best_score,
                type_score=decision_input.type_score,
                has_inherent_value_ambiguity=decision_input.has_inherent_value_ambiguity,
            )
        )
        if decision.action == AutonomyAction.AUTO:
            return MappingDecision.AUTO_APPROVED
        if decision.action == AutonomyAction.STOP:
            return MappingDecision.BLOCKED
        return MappingDecision.NEEDS_REVIEW
