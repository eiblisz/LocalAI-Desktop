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


def test_split_actions_inherit_only_global_parent_constraints():
    prompt = """Válaszolj kizárólag magyarul az AI-val működő asztali alkalmazás munkanapjáról.

1. Hogyan indul a reggel?
2. Hogyan kezeli a dokumentumokat?
3. Hogyan zárul a munkanap?"""

    contracts = ActionRuntime().plan_many(prompt)

    assert len(contracts) == 3
    assert all(isinstance(item.constraints, TaskConstraints) for item in contracts)
    assert all(item.explicit_batch_child for item in contracts)
    assert all(item.constraints.response_language == "hu" for item in contracts)
    assert all(item.constraints.explicit_batch_child for item in contracts)
    assert contracts[0].constraints.parent_intent == "Hogyan indul a reggel?"
    assert contracts[1].constraints.parent_intent == "Hogyan kezeli a dokumentumokat?"
    assert all("answer only in Hungarian" in item.constraints.user_explicit_constraints for item in contracts)


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


def test_explicit_batch_child_instruction_excludes_sibling_entities():
    prompt = """Válaszolj magyarul, röviden.
1. Ki Alice Example?
2. Mikor alakult a Beta Example zenekar?"""
    contracts = ActionRuntime().plan_many(prompt)

    instruction = task_constraints_instruction(
        contracts[0].constraints,
        current_subtask=contracts[0].prompt,
    )

    assert "explicit batch child" in instruction
    assert "Beta Example" not in instruction
    assert "Format constraints: concise" in instruction



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
