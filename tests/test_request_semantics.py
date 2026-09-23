from app.request_semantics import (
    TASK_COMPARISON,
    TASK_DEEP_RESEARCH,
    TASK_DIRECT_FACT,
    TASK_ENTITY_OVERVIEW,
    TASK_GENERAL,
    classify_request,
    classify_requested_fact,
    request_profile_instruction,
)


def test_direct_fact_profile_is_narrow_and_concise():
    profile = classify_request(
        "Mikor írta Nimbus Szerző az Ezüst Történetet?"
    )

    assert profile.kind == TASK_DIRECT_FACT
    assert profile.response_depth == "concise"
    assert profile.research_breadth == "narrow"
    assert profile.query_budget == 1
    assert profile.source_budget == 4
    assert profile.page_fetch_budget == 2


def test_entity_formation_date_is_a_narrow_direct_fact():
    profile = classify_request("Mikor alakult a Sample Band?")

    assert profile.kind == TASK_DIRECT_FACT
    assert profile.requested_fact == "temporal"
    assert profile.query_budget == 1
    assert profile.page_fetch_budget == 2


def test_entity_overview_profile_is_not_treated_as_direct_fact():
    profile = classify_request(
        "Mit tudsz az Ezüst Hold zenekarról?"
    )

    assert profile.kind == TASK_ENTITY_OVERVIEW
    assert profile.response_depth == "overview"
    assert profile.research_breadth == "balanced"
    assert profile.query_budget == 1
    assert profile.source_budget == 8
    assert profile.page_fetch_budget == 2

    instruction = request_profile_instruction(profile)
    assert "substantive overview" in instruction
    assert "major development or milestones" in instruction


def test_entity_overview_equivalents_work_across_languages():
    assert classify_request(
        "Tell me about the Silver Observatory."
    ).kind == TASK_ENTITY_OVERVIEW
    assert classify_request(
        "Was weißt du über das Silver Observatory?"
    ).kind == TASK_ENTITY_OVERVIEW


def test_explicit_detailed_overview_preserves_overview_activity():
    profile = classify_request(
        "Mesélj részletesen az Ezüst Hold zenekarról."
    )

    assert profile.kind == TASK_ENTITY_OVERVIEW
    assert profile.response_depth == "detailed"
    assert profile.research_breadth == "balanced"
    assert profile.query_budget == 3
    assert profile.source_budget == 10
    assert profile.page_fetch_budget == 4


def test_detailed_comparison_keeps_activity_and_depth_separate():
    profile = classify_request("Hasonlítsd össze részletesen Alpha és Beta rendszert.")

    assert profile.kind == TASK_COMPARISON
    assert profile.response_depth == "detailed"


def test_requested_fact_semantics_are_entity_generic():
    profile = classify_request("Mikor írta Wrong Author a Silver Story című művet?")

    assert profile.kind == TASK_DIRECT_FACT
    assert profile.requested_fact == "temporal"
    assert classify_requested_fact("Where was the Silver Story published?") == "location"


def test_comparison_profile_has_balanced_multi_query_budget():
    profile = classify_request(
        "Hasonlítsd össze az Alpha és Beta rendszert."
    )

    assert profile.kind == TASK_COMPARISON
    assert profile.response_depth == "standard"
    assert profile.query_budget == 2
    assert profile.source_budget == 8


def test_explicit_concise_overrides_default_overview_depth():
    profile = classify_request(
        "Röviden: mit tudsz az Ezüst Hold zenekarról?"
    )

    assert profile.kind == TASK_ENTITY_OVERVIEW
    assert profile.response_depth == "concise"
    assert profile.query_budget == 1
    assert profile.source_budget <= 5


def test_general_question_stays_standard_not_forced_to_three_sentences():
    profile = classify_request(
        "Milyen szerepe van a gyorsítótárnak egy asztali alkalmazásban?"
    )

    assert profile.kind == TASK_GENERAL
    assert profile.response_depth == "standard"
