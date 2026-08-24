import json
from dataclasses import dataclass

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import SOURCE_FIELD_SYNONYMS, TARGET_FIELD_TYPES
from app.core.enums import MappingDecision
from app.models.column_profile import ColumnProfile
from app.models.mapping import Mapping
from app.models.source_file import SourceFile
from app.schemas.mapping import MappingCandidate
from app.services.decision import DecisionEngine, MappingDecisionInput
from app.services.llm import LLMProvider, LLMProviderUnavailable, NullLLMProvider


@dataclass(frozen=True)
class ScoredCandidate:
    target_field: str | None
    semantic_score: float
    name_score: float
    type_score: float
    value_score: float
    final_score: float
    reasoning: str
    alternatives: list[dict[str, object]]
    decision_source: str


STRING_IDENTIFIER_FIELDS = {
    "employee_id",
    "manager_id",
    "bank_account_number",
    "tax_identifier",
}


class MappingService:
    def __init__(
        self,
        db: Session,
        llm_provider: LLMProvider | None = None,
        decision_engine: DecisionEngine | None = None,
    ) -> None:
        self.db = db
        self.llm_provider = llm_provider or NullLLMProvider()
        self.decision_engine = decision_engine or DecisionEngine()

    def generate_for_migration(self, migration_id: str) -> list[Mapping]:
        existing = list(
            self.db.scalars(
                select(Mapping)
                .where(Mapping.migration_id == migration_id)
                .order_by(Mapping.source_column)
            ).all()
        )
        if existing:
            return existing

        profiles = self._profiles_for_migration(migration_id)
        mappings: list[Mapping] = []
        for profile in profiles:
            scored = self._score_profile(profile)
            second_best = _second_best_score(scored.alternatives)
            decision = self.decision_engine.decide_mapping(
                MappingDecisionInput(
                    target_field=scored.target_field,
                    final_score=scored.final_score,
                    second_best_score=second_best,
                    type_score=scored.type_score,
                )
            )
            mapping = Mapping(
                migration_id=migration_id,
                source_file_id=profile.source_file_id,
                source_column=profile.column_name,
                target_field=scored.target_field,
                semantic_score=scored.semantic_score,
                name_score=scored.name_score,
                type_score=scored.type_score,
                value_score=scored.value_score,
                final_score=scored.final_score,
                decision=decision,
                decision_source=scored.decision_source,
                reasoning=scored.reasoning,
                alternatives_json=json.dumps(scored.alternatives, sort_keys=True),
            )
            self.db.add(mapping)
            mappings.append(mapping)

        self.db.flush()
        return mappings

    def _profiles_for_migration(self, migration_id: str) -> list[ColumnProfile]:
        statement = (
            select(ColumnProfile)
            .join(SourceFile)
            .where(SourceFile.migration_id == migration_id)
            .order_by(SourceFile.original_name, ColumnProfile.column_name)
        )
        return list(self.db.scalars(statement).all())

    def _score_profile(self, profile: ColumnProfile) -> ScoredCandidate:
        deterministic = _deterministic_target(profile.normalized_name)
        sample_values = json.loads(profile.sample_values_json)

        if deterministic is not None:
            candidate = MappingCandidate(
                source_field=profile.column_name,
                target_field=deterministic,
                semantic_confidence=1.0,
                reasoning_summary="Matched by exact target name or configured synonym.",
            )
            decision_source = "DETERMINISTIC"
        else:
            try:
                candidate = self.llm_provider.propose_mapping(
                    profile.column_name,
                    profile.inferred_type,
                    sample_values,
                )
                decision_source = "LLM"
            except (LLMProviderUnavailable, ValueError):
                candidate = MappingCandidate(
                    source_field=profile.column_name,
                    target_field=None,
                    semantic_confidence=0.0,
                    reasoning_summary="LLM unavailable or invalid; requires review.",
                )
                decision_source = "FALLBACK"

        return _score_candidate(profile, candidate, decision_source)


def _deterministic_target(normalized_name: str) -> str | None:
    if normalized_name in TARGET_FIELD_TYPES:
        return normalized_name
    return SOURCE_FIELD_SYNONYMS.get(normalized_name)


def _score_candidate(
    profile: ColumnProfile,
    candidate: MappingCandidate,
    decision_source: str,
) -> ScoredCandidate:
    target_field = candidate.target_field
    name_score = _name_score(profile.normalized_name, target_field)
    type_score = _type_score(profile.inferred_type, target_field)
    value_score = _value_score(profile.inferred_type, target_field)
    semantic_score = candidate.semantic_confidence
    final_score = round(
        0.35 * semantic_score + 0.25 * name_score + 0.20 * type_score + 0.20 * value_score,
        4,
    )
    alternatives = [
        alternative.model_dump()
        for alternative in candidate.alternatives
        if alternative.target_field != target_field
    ]
    return ScoredCandidate(
        target_field=target_field,
        semantic_score=semantic_score,
        name_score=name_score,
        type_score=type_score,
        value_score=value_score,
        final_score=final_score,
        reasoning=candidate.reasoning_summary,
        alternatives=alternatives,
        decision_source=decision_source,
    )


def _name_score(normalized_name: str, target_field: str | None) -> float:
    if target_field is None:
        return 0.0
    if normalized_name == target_field or SOURCE_FIELD_SYNONYMS.get(normalized_name) == target_field:
        return 1.0
    return round(fuzz.token_sort_ratio(normalized_name, target_field) / 100, 4)


def _type_score(source_type: str, target_field: str | None) -> float:
    if target_field is None:
        return 0.0
    target_type = TARGET_FIELD_TYPES[target_field]
    if source_type == target_type:
        return 1.0
    if target_type == "string" and source_type in {"string", "email", "phone"}:
        return 0.85
    if target_field in STRING_IDENTIFIER_FIELDS and source_type == "number":
        return 0.85
    if target_type == "number" and source_type == "string":
        return 0.4
    if target_type == "date" and source_type == "string":
        return 0.6
    return 0.0


def _value_score(source_type: str, target_field: str | None) -> float:
    if target_field is None:
        return 0.0
    target_type = TARGET_FIELD_TYPES[target_field]
    if source_type == target_type:
        return 1.0
    if target_type == "string":
        return 0.8
    return 0.5


def _second_best_score(alternatives: list[dict[str, object]]) -> float:
    scores = [float(item.get("confidence", 0.0)) for item in alternatives]
    return max(scores, default=0.0)
