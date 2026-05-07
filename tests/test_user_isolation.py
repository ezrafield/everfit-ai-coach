import sys
sys.path.append("./")  # Add parent directory to path for imports

import json

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.workout.analyzer import analyze_workout_history, load_user_history_from_file


def write_test_workout_history(tmp_path):
    """
    Build a small multi-user workout file with intentionally unique data per user.

    This makes leakage easy to detect:
    - user_a has Dragon Lift and Alex-only profile text
    - user_b has Bench Press and Binh-only profile text
    """
    payload = {
        "description": "Test workout history for user isolation.",
        "users": {
            "user_a": {
                "name": "Alex",
                "profile": "Alex profile should never appear in user_b analysis.",
                "workouts": [
                    {
                        "date": "2026-03-01",
                        "exercise": "Dragon Lift",
                        "sets": [
                            {"reps": 10, "weight": 100, "unit": "kg"},
                            {"reps": 8, "weight": 105, "unit": "kg"},
                        ],
                    }
                ],
            },
            "user_b": {
                "name": "Binh",
                "profile": "Binh profile should never appear in user_a analysis.",
                "workouts": [
                    {
                        "date": "2026-03-01",
                        "exercise": "Bench Press",
                        "sets": [
                            {"reps": 10, "weight": 50, "unit": "kg"},
                            {"reps": 8, "weight": 55, "unit": "kg"},
                        ],
                    },
                    {
                        "date": "2026-03-15",
                        "exercise": "Bench Press",
                        "sets": [
                            {"reps": 10, "weight": 55, "unit": "kg"},
                            {"reps": 8, "weight": 60, "unit": "kg"},
                        ],
                    },
                ],
            },
        },
    }

    path = tmp_path / "workout-history.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_user_history_only_returns_requested_user(tmp_path, monkeypatch):
    workout_path = write_test_workout_history(tmp_path)
    monkeypatch.setattr(settings, "WORKOUT_HISTORY_PATH", str(workout_path))

    user_name, user_profile, workouts, warnings = load_user_history_from_file("user_b")

    assert warnings == []
    assert user_name == "Binh"
    assert user_profile == "Binh profile should never appear in user_a analysis."
    assert len(workouts) == 2

    exercises = {workout.exercise for workout in workouts}

    assert "Bench Press" in exercises
    assert "Dragon Lift" not in exercises


def test_analyze_workout_history_does_not_leak_other_user_into_evidence_or_prompt(
    tmp_path,
    monkeypatch,
):
    workout_path = write_test_workout_history(tmp_path)
    monkeypatch.setattr(settings, "WORKOUT_HISTORY_PATH", str(workout_path))

    captured_prompts = []

    def fake_generate_text(system_prompt: str, user_prompt: str, **kwargs):
        captured_prompts.append(user_prompt)
        return "Mocked answer for user_b only."

    monkeypatch.setattr("app.workout.analyzer.generate_text", fake_generate_text)

    response = analyze_workout_history(
        user_id="user_b",
        question="What is my bench press trend?",
        history=None,
    )

    assert response.user_id == "user_b"
    assert response.user_name == "Binh"
    assert response.user_profile == "Binh profile should never appear in user_a analysis."
    assert response.refusal is False
    assert response.answer == "Mocked answer for user_b only."

    evidence_text = json.dumps(response.evidence)
    prompt_text = "\n".join(captured_prompts)

    # user_b data should exist
    assert "Binh" in evidence_text
    assert "Bench Press" in evidence_text
    assert "Binh" in prompt_text
    assert "Bench Press" in prompt_text

    # user_a data must not leak into evidence or LLM prompt
    assert "Alex" not in evidence_text
    assert "Dragon Lift" not in evidence_text
    assert "Alex" not in prompt_text
    assert "Dragon Lift" not in prompt_text


def test_workout_analyze_endpoint_does_not_leak_other_user(
    tmp_path,
    monkeypatch,
):
    workout_path = write_test_workout_history(tmp_path)
    monkeypatch.setattr(settings, "WORKOUT_HISTORY_PATH", str(workout_path))

    captured_prompts = []

    def fake_generate_text(system_prompt: str, user_prompt: str, **kwargs):
        captured_prompts.append(user_prompt)
        return "Endpoint mocked answer for user_b only."

    monkeypatch.setattr("app.workout.analyzer.generate_text", fake_generate_text)

    client = TestClient(app)

    response = client.post(
        "/workout/analyze",
        json={
            "user_id": "user_b",
            "question": "What is my bench press trend?",
        },
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload["user_id"] == "user_b"
    assert payload["user_name"] == "Binh"
    assert payload["answer"] == "Endpoint mocked answer for user_b only."
    assert payload["refusal"] is False

    payload_text = json.dumps(payload)
    prompt_text = "\n".join(captured_prompts)

    assert "Bench Press" in payload_text
    assert "Binh" in payload_text

    assert "Dragon Lift" not in payload_text
    assert "Alex" not in payload_text
    assert "Dragon Lift" not in prompt_text
    assert "Alex" not in prompt_text


def test_missing_user_does_not_return_any_workout_history(tmp_path, monkeypatch):
    workout_path = write_test_workout_history(tmp_path)
    monkeypatch.setattr(settings, "WORKOUT_HISTORY_PATH", str(workout_path))

    response = analyze_workout_history(
        user_id="user_c",
        question="What is my training trend?",
        history=None,
    )

    assert response.user_id == "user_c"
    assert response.insufficient_data is True
    assert response.evidence["history_status"] == "empty"

    evidence_text = json.dumps(response.evidence)
    answer_text = response.answer

    assert "Dragon Lift" not in evidence_text
    assert "Bench Press" not in evidence_text
    assert "Alex profile" not in evidence_text
    assert "Binh profile" not in evidence_text

    assert "Dragon Lift" not in answer_text
    assert "Bench Press" not in answer_text