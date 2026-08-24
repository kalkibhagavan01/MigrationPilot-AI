from app.policies.autonomy_policy import (
    AutonomyAction,
    AutonomyPolicy,
    EscalationType,
    MappingAutonomyInput,
)


def test_policy_auto_approves_clear_high_confidence_mapping() -> None:
    decision = AutonomyPolicy().decide_mapping(
        MappingAutonomyInput(
            target_field="employee_id",
            final_score=0.96,
            second_best_score=0.20,
            type_score=1.0,
        )
    )

    assert decision.action == AutonomyAction.AUTO
    assert decision.decision_type is None


def test_policy_escalates_close_mapping_candidates() -> None:
    decision = AutonomyPolicy().decide_mapping(
        MappingAutonomyInput(
            target_field="joining_date",
            final_score=0.90,
            second_best_score=0.86,
            type_score=1.0,
        )
    )

    assert decision.action == AutonomyAction.HITL
    assert decision.decision_type == EscalationType.MAPPING_AMBIGUITY


def test_policy_escalates_inherently_ambiguous_values_even_with_high_confidence() -> None:
    decision = AutonomyPolicy().decide_mapping(
        MappingAutonomyInput(
            target_field="joining_date",
            final_score=0.98,
            second_best_score=0.10,
            type_score=1.0,
            has_inherent_value_ambiguity=True,
        )
    )

    assert decision.action == AutonomyAction.HITL
    assert decision.decision_type == EscalationType.VALUE_AMBIGUITY


def test_policy_stops_for_unknown_target_schema_field() -> None:
    decision = AutonomyPolicy().decide_mapping(
        MappingAutonomyInput(
            target_field="missing_target",
            final_score=0.99,
            second_best_score=0.0,
            type_score=1.0,
        )
    )

    assert decision.action == AutonomyAction.STOP
    assert decision.decision_type == EscalationType.SYSTEM_FAILURE
