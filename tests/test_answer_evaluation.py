import pytest
from fastapi import HTTPException

import app as system
from inetz.models import display_question


def test_evaluate_mcq_counts_correct_wrong_and_unanswered_from_snapshot():
    snapshot = [{"answer": 2}, {"answer": 0}, {"answer": 1}, {"answer": 3}]
    assert system.evaluate_mcq(snapshot, {"1": 2, "2": 3, "4": 3}) == {
        "score": 2, "max_score": 4, "correct_count": 2,
        "wrong_count": 1, "unanswered_count": 1,
    }


def test_display_question_removes_generated_scenario_label_only():
    assert display_question("Scenario 340: Find the average.") == "Find the average."
    assert display_question("What is a scenario in testing?") == "What is a scenario in testing?"


@pytest.mark.parametrize("answers", [
    {"1": True}, {"1": 1.0}, {"1": "1"}, {"0": 1}, {"2": 0}, {"x": 1},
])
def test_validate_answers_rejects_invalid_indices_and_choice_types(answers):
    with pytest.raises(HTTPException) as error:
        system.validate_answers(answers, 1)
    assert error.value.status_code == 422
