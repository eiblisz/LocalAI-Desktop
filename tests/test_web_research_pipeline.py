from app.web_research_pipeline import WebResearchPipeline


class _Worker:
    def _conversation_language_instruction(self):
        return "Respond in Hungarian."


def test_verified_fallback_is_user_facing_not_internal_failure_message():
    pipeline = WebResearchPipeline(_Worker())
    ledgers = [
        {
            "verdict": "ACCEPT",
            "title": "Example 64GB Kit",
            "url": "https://example.com/product",
            "plan": {"currency": "EUR"},
            "fields": {
                "url": {"status": "VERIFIED", "value": "https://example.com/product"},
                "exact_kit": {"status": "VERIFIED", "value": "2x32gb"},
                "memory_type": {"status": "VERIFIED", "value": "DDR4"},
                "speed_mhz": {"status": "VERIFIED", "value": 3200},
                "country": {"status": "VERIFIED", "value": "DE"},
                "price": {"status": "VERIFIED", "value": 606.90},
            },
        }
    ]

    answer = pipeline.deterministic_verified_answer(ledgers)

    assert answer.startswith("Az ellenorzott forrasok alapjan:")
    assert "modell generalt valasza nem ment at" not in answer.lower()
    assert "2x32gb" in answer
    assert "DDR4" in answer
    assert "3200 MHz" in answer
    assert "606.90 EUR" in answer
    assert "https://example.com/product" in answer
