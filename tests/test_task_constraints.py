from app.action_runtime import ActionRuntime
from app.task_constraints import (
    TaskConstraints,
    build_task_constraints,
    task_constraints_instruction,
)


def test_hungarian_parent_constraints_are_structured():
    constraints = build_task_constraints(
        "Válaszolj kizárólag magyarul. Írj rövid összefoglalót az AI Desktop munkanapjáról."
    )

    assert constraints.response_language == "hu"
    assert constraints.output_style == "natural_hungarian"
    assert constraints.forbidden_language_drift is True
    assert "AI Desktop munkanapjáról" in constraints.parent_intent
    assert "concise" in constraints.format_constraints
    assert "answer only in Hungarian" in constraints.user_explicit_constraints


def test_all_split_actions_keep_same_parent_task_constraints():
    prompt = """Válaszolj kizárólag magyarul az AI-val működő asztali alkalmazás munkanapjáról.

1. Hogyan indul a reggel?
2. Hogyan kezeli a dokumentumokat?
3. Hogyan zárul a munkanap?"""

    contracts = ActionRuntime().plan_many(prompt)

    assert len(contracts) == 3
    assert all(isinstance(item.constraints, TaskConstraints) for item in contracts)
    assert all(item.constraints.response_language == "hu" for item in contracts)
    assert all(item.constraints.parent_intent == contracts[0].constraints.parent_intent for item in contracts)
    assert all("asztali alkalmazás munkanapjáról" in item.constraints.parent_intent for item in contracts)


def test_constraint_instruction_binds_subtask_to_parent_scope():
    constraints = build_task_constraints(
        "Válaszolj magyarul egy AI Desktop teljes munkanapjáról."
    )

    instruction = task_constraints_instruction(
        constraints,
        current_subtask="Hogyan indul a reggel?",
    )

    assert "Expected response language: Hungarian" in instruction
    assert "Parent task:" in instruction
    assert "AI Desktop teljes munkanapjáról" in instruction
    assert "Current subtask: Hogyan indul a reggel?" in instruction
    assert "not as an unrelated standalone topic" in instruction



def test_task_constraints_carry_request_semantics_profile():
    constraints = build_task_constraints(
        "Mit tudsz az Ezüst Hold zenekarról?"
    )

    assert constraints.request_profile is not None
    assert constraints.request_profile.kind == "entity_overview"
    assert constraints.request_profile.response_depth == "overview"
    assert constraints.request_profile.query_budget == 1
    assert constraints.request_profile.source_budget == 8

    instruction = task_constraints_instruction(constraints)
    assert "Request kind: entity_overview" in instruction
    assert "Response depth: overview" in instruction
    assert "Research breadth: balanced" in instruction
