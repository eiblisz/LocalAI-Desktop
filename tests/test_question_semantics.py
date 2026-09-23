from app.question_semantics import analyze_question
from app.request_semantics import TASK_DIRECT_FACT, classify_request
from app.direct_fact import derive_premise_neutral_query


def test_temporal_creation_semantics_are_separate_from_activity_depth():
    semantics = analyze_question("Mikor írta a Szerző az Ének című verset?")
    profile = classify_request("Mikor írta a Szerző az Ének című verset?")

    assert semantics.requested_fact == "temporal"
    assert semantics.relation == "authorship_creation"
    assert semantics.premise_check_required is True
    assert profile.kind == TASK_DIRECT_FACT
    assert profile.response_depth == "concise"
    assert profile.relation == "authorship_creation"
    assert profile.response_language == "hu"


def test_formation_and_explanation_semantics_remain_distinct():
    formation = analyze_question("Mikor alakult a Példa zenekar?")
    explanation = analyze_question("Miért működik így ez a folyamat?")

    assert (formation.requested_fact, formation.relation) == ("temporal", "formation")
    assert (explanation.requested_fact, explanation.relation) == ("cause", "cause")


def test_work_type_context_expands_c_dot_without_general_typo_translation():
    query, strategy = derive_premise_neutral_query(
        "Mikor írta a Szerző az Ének c. verset?",
        requested_fact="temporal",
    )

    assert query == "Ének composition writing date year"
    assert strategy == "premise_neutral_title_relation"
