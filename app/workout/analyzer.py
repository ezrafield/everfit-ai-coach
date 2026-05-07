import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from loguru import logger

from app.core.config import settings
from app.core.guardrails import check_medical_guardrail
from app.core.llm import generate_text
from app.workout.exercise_map import detect_exercise_from_question, get_exercise_metadata
from app.workout.schemas import WorkoutAnalysisResponse, WorkoutEntry


WORKOUT_ANALYSIS_SYSTEM_PROMPT = """
You are an AI workout analysis assistant for a fitness coaching platform.

You must:
- Use only the provided precomputed workout evidence.
- Reference specific numbers, dates, exercises, sets, volume, or estimated 1RM when relevant.
- Be practical and coach-friendly.
- Avoid pretending certainty when data is limited.
- Do not diagnose injuries, prescribe injury rehabilitation, or provide medical advice.
- If suggesting next steps, frame them as general training guidance that a coach can review.
""".strip()


def load_user_history_from_file(user_id: str) -> tuple[str | None, str | None, list[WorkoutEntry], list[str]]:
    path = Path(settings.WORKOUT_HISTORY_PATH)
    warnings: list[str] = []

    if not path.exists():
        return None, None, [], [f"Workout history file not found: {settings.WORKOUT_HISTORY_PATH}"]

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, None, [], [f"Workout history file is not valid JSON: {exc}"]

    users = payload.get("users", {})

    if user_id not in users:
        available_users = sorted(users.keys())
        return (
            None,
            None,
            [],
            [
                f"User '{user_id}' was not found in workout history file.",
                f"Available users: {available_users}",
            ],
        )

    user_payload = users[user_id]
    user_name = user_payload.get("name")
    user_profile = user_payload.get("profile")
    raw_workouts = user_payload.get("workouts", [])

    parsed_workouts: list[WorkoutEntry] = []

    for index, item in enumerate(raw_workouts):
        try:
            parsed_workouts.append(WorkoutEntry.model_validate(item))
        except Exception as exc:
            warnings.append(f"Skipped invalid workout entry at index {index}: {exc}")

    return user_name, user_profile, parsed_workouts, warnings


def convert_weight_to_kg(weight: float, unit: str) -> float:
    if unit == "kg":
        return float(weight)

    if unit == "lb":
        return float(weight) * 0.45359237

    return float(weight)


def estimate_one_rep_max_kg(weight_kg: float, reps: int) -> float | None:
    """
    Epley estimate:
    estimated 1RM = weight * (1 + reps / 30)

    For bodyweight rows with external load = 0, this returns None instead of 0
    because 0kg is not a useful strength estimate.
    """
    if weight_kg <= 0:
        return None

    return weight_kg * (1 + reps / 30)


def round_number(value: float | None, digits: int = 1) -> float | None:
    if value is None:
        return None

    return round(float(value), digits)


def flatten_history(history: list[WorkoutEntry]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for entry in history:
        metadata = get_exercise_metadata(entry.exercise)
        canonical_exercise = metadata["canonical_name"]

        for set_index, workout_set in enumerate(entry.sets, start=1):
            weight_kg = convert_weight_to_kg(workout_set.weight, workout_set.unit)
            volume_kg = weight_kg * workout_set.reps
            estimated_1rm_kg = estimate_one_rep_max_kg(weight_kg, workout_set.reps)

            rows.append(
                {
                    "date": entry.date,
                    "exercise_raw": entry.exercise,
                    "exercise": canonical_exercise,
                    "set_index": set_index,
                    "reps": workout_set.reps,
                    "weight": workout_set.weight,
                    "unit": workout_set.unit,
                    "weight_kg": weight_kg,
                    "volume_kg": volume_kg,
                    "estimated_1rm_kg": estimated_1rm_kg,
                    "primary_muscle": metadata["primary_muscle"],
                    "secondary_muscles": metadata["secondary_muscles"],
                    "movement_pattern": metadata["movement_pattern"],
                    "is_bodyweight": metadata.get("is_bodyweight", False),
                }
            )

    return sorted(rows, key=lambda row: (row["date"], row["exercise"], row["set_index"]))


def max_optional(values: list[float | None]) -> float | None:
    valid_values = [value for value in values if value is not None]
    return max(valid_values) if valid_values else None


def summarize_by_exercise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        grouped[row["exercise"]].append(row)

    summary: dict[str, Any] = {}

    for exercise, exercise_rows in grouped.items():
        dates = sorted({row["date"] for row in exercise_rows})
        total_sets = len(exercise_rows)
        total_reps = sum(row["reps"] for row in exercise_rows)
        total_volume = sum(row["volume_kg"] for row in exercise_rows)
        max_weight = max(row["weight_kg"] for row in exercise_rows)
        best_1rm = max_optional([row["estimated_1rm_kg"] for row in exercise_rows])

        first_date = dates[0]
        latest_date = dates[-1]

        first_day_rows = [row for row in exercise_rows if row["date"] == first_date]
        latest_day_rows = [row for row in exercise_rows if row["date"] == latest_date]

        first_best_1rm = max_optional([row["estimated_1rm_kg"] for row in first_day_rows])
        latest_best_1rm = max_optional([row["estimated_1rm_kg"] for row in latest_day_rows])
        first_volume = sum(row["volume_kg"] for row in first_day_rows)
        latest_volume = sum(row["volume_kg"] for row in latest_day_rows)

        estimated_1rm_change = None
        if first_best_1rm is not None and latest_best_1rm is not None:
            estimated_1rm_change = latest_best_1rm - first_best_1rm

        summary[exercise] = {
            "sessions": len(dates),
            "total_sets": total_sets,
            "total_reps": total_reps,
            "total_volume_kg": round_number(total_volume),
            "max_external_load_kg": round_number(max_weight),
            "best_estimated_1rm_kg": round_number(best_1rm),
            "first_session_date": first_date.isoformat(),
            "latest_session_date": latest_date.isoformat(),
            "first_session_best_estimated_1rm_kg": round_number(first_best_1rm),
            "latest_session_best_estimated_1rm_kg": round_number(latest_best_1rm),
            "estimated_1rm_change_kg": round_number(estimated_1rm_change),
            "first_session_volume_kg": round_number(first_volume),
            "latest_session_volume_kg": round_number(latest_volume),
            "session_volume_change_kg": round_number(latest_volume - first_volume),
        }

    return summary


def summarize_by_category(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        grouped[row[key]].append(row)

    summary: dict[str, Any] = {}

    for category, category_rows in grouped.items():
        dates = sorted({row["date"] for row in category_rows})
        summary[category] = {
            "sessions": len(dates),
            "total_sets": len(category_rows),
            "total_reps": sum(row["reps"] for row in category_rows),
            "total_volume_kg": round_number(sum(row["volume_kg"] for row in category_rows)),
            "latest_date": dates[-1].isoformat() if dates else None,
        }

    return summary


def build_balance_summary(
    muscle_summary: dict[str, Any],
    pattern_summary: dict[str, Any],
) -> dict[str, Any]:
    chest_sets = (
        muscle_summary.get("chest", {}).get("total_sets", 0)
        + muscle_summary.get("upper_chest", {}).get("total_sets", 0)
    )
    back_sets = (
        muscle_summary.get("back", {}).get("total_sets", 0)
        + muscle_summary.get("rear_delts", {}).get("total_sets", 0)
        + muscle_summary.get("upper_back", {}).get("total_sets", 0)
    )
    leg_sets = (
        muscle_summary.get("quads", {}).get("total_sets", 0)
        + muscle_summary.get("hamstrings", {}).get("total_sets", 0)
        + muscle_summary.get("posterior_chain", {}).get("total_sets", 0)
    )
    push_sets = (
        pattern_summary.get("horizontal_push", {}).get("total_sets", 0)
        + pattern_summary.get("vertical_push", {}).get("total_sets", 0)
    )
    pull_sets = (
        pattern_summary.get("horizontal_pull", {}).get("total_sets", 0)
        + pattern_summary.get("vertical_pull", {}).get("total_sets", 0)
    )

    return {
        "chest_sets": chest_sets,
        "back_sets": back_sets,
        "leg_sets": leg_sets,
        "push_sets": push_sets,
        "pull_sets": pull_sets,
        "chest_to_back_set_ratio": round_number(chest_sets / back_sets, 2) if back_sets else None,
        "push_to_pull_set_ratio": round_number(push_sets / pull_sets, 2) if pull_sets else None,
    }


def build_neglected_summary(rows: list[dict[str, Any]], reference_date: date) -> dict[str, Any]:
    important_muscles = [
        "chest",
        "upper_chest",
        "back",
        "rear_delts",
        "shoulders",
        "quads",
        "hamstrings",
        "posterior_chain",
    ]
    important_patterns = [
        "horizontal_push",
        "vertical_push",
        "horizontal_pull",
        "vertical_pull",
        "squat",
        "hinge",
    ]

    latest_by_muscle: dict[str, date] = {}
    latest_by_pattern: dict[str, date] = {}

    for row in rows:
        muscle = row["primary_muscle"]
        pattern = row["movement_pattern"]

        if muscle not in latest_by_muscle or row["date"] > latest_by_muscle[muscle]:
            latest_by_muscle[muscle] = row["date"]

        if pattern not in latest_by_pattern or row["date"] > latest_by_pattern[pattern]:
            latest_by_pattern[pattern] = row["date"]

    neglected_muscles = []
    for muscle in important_muscles:
        latest_date = latest_by_muscle.get(muscle)

        if latest_date is None:
            neglected_muscles.append(
                {
                    "muscle": muscle,
                    "latest_date": None,
                    "days_since": None,
                    "status": "never_trained_in_history",
                }
            )
            continue

        days_since = (reference_date - latest_date).days

        if days_since >= 21:
            neglected_muscles.append(
                {
                    "muscle": muscle,
                    "latest_date": latest_date.isoformat(),
                    "days_since": days_since,
                    "status": "not_trained_recently",
                }
            )

    neglected_patterns = []
    for pattern in important_patterns:
        latest_date = latest_by_pattern.get(pattern)

        if latest_date is None:
            neglected_patterns.append(
                {
                    "movement_pattern": pattern,
                    "latest_date": None,
                    "days_since": None,
                    "status": "never_trained_in_history",
                }
            )
            continue

        days_since = (reference_date - latest_date).days

        if days_since >= 21:
            neglected_patterns.append(
                {
                    "movement_pattern": pattern,
                    "latest_date": latest_date.isoformat(),
                    "days_since": days_since,
                    "status": "not_trained_recently",
                }
            )

    return {
        "neglected_muscles_21d": neglected_muscles,
        "neglected_movement_patterns_21d": neglected_patterns,
    }


def build_target_exercise_trend(
    rows: list[dict[str, Any]],
    target_exercise: str | None,
) -> dict[str, Any] | None:
    if not target_exercise:
        return None

    target_rows = [row for row in rows if row["exercise"] == target_exercise]

    if not target_rows:
        return None

    grouped_by_date: dict[date, list[dict[str, Any]]] = defaultdict(list)

    for row in target_rows:
        grouped_by_date[row["date"]].append(row)

    sessions = []

    for session_date, session_rows in sorted(grouped_by_date.items()):
        session_volume = sum(row["volume_kg"] for row in session_rows)
        best_1rm = max_optional([row["estimated_1rm_kg"] for row in session_rows])
        max_weight = max(row["weight_kg"] for row in session_rows)
        total_reps = sum(row["reps"] for row in session_rows)

        sessions.append(
            {
                "date": session_date.isoformat(),
                "sets": len(session_rows),
                "total_reps": total_reps,
                "session_volume_kg": round_number(session_volume),
                "max_external_load_kg": round_number(max_weight),
                "best_estimated_1rm_kg": round_number(best_1rm),
            }
        )

    first = sessions[0]
    latest = sessions[-1]

    best_1rm_change = None
    if first["best_estimated_1rm_kg"] is not None and latest["best_estimated_1rm_kg"] is not None:
        best_1rm_change = latest["best_estimated_1rm_kg"] - first["best_estimated_1rm_kg"]

    return {
        "exercise": target_exercise,
        "session_count": len(sessions),
        "sessions": sessions,
        "change_from_first_to_latest": {
            "session_volume_kg": round_number(latest["session_volume_kg"] - first["session_volume_kg"]),
            "max_external_load_kg": round_number(latest["max_external_load_kg"] - first["max_external_load_kg"]),
            "best_estimated_1rm_kg": round_number(best_1rm_change),
        },
    }


def detect_deload_patterns(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Simple deload detection:
    For each exercise, detect sessions where volume drops by >=30% from previous session,
    then later returns upward.
    """
    by_exercise_date: dict[str, dict[date, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))

    for row in rows:
        by_exercise_date[row["exercise"]][row["date"]].append(row)

    deloads: list[dict[str, Any]] = []

    for exercise, by_date in by_exercise_date.items():
        sessions = []

        for session_date, session_rows in sorted(by_date.items()):
            sessions.append(
                {
                    "date": session_date,
                    "volume_kg": sum(row["volume_kg"] for row in session_rows),
                    "sets": len(session_rows),
                }
            )

        for index in range(1, len(sessions)):
            previous = sessions[index - 1]
            current = sessions[index]

            if previous["volume_kg"] <= 0:
                continue

            drop_ratio = (previous["volume_kg"] - current["volume_kg"]) / previous["volume_kg"]

            if drop_ratio >= 0.3:
                deloads.append(
                    {
                        "exercise": exercise,
                        "date": current["date"].isoformat(),
                        "previous_date": previous["date"].isoformat(),
                        "previous_volume_kg": round_number(previous["volume_kg"]),
                        "current_volume_kg": round_number(current["volume_kg"]),
                        "drop_percent": round_number(drop_ratio * 100),
                    }
                )

    return deloads


def collect_warnings(rows: list[dict[str, Any]], file_warnings: list[str]) -> list[str]:
    warnings: list[str] = list(file_warnings)

    unknown_exercises = sorted({row["exercise_raw"] for row in rows if row["primary_muscle"] == "unknown"})

    if unknown_exercises:
        warnings.append(
            "Unknown exercise mapping for: "
            + ", ".join(unknown_exercises)
            + ". They were included in totals but excluded from muscle-balance confidence."
        )

    units = sorted({row["unit"] for row in rows})
    if len(units) > 1:
        warnings.append("Mixed weight units detected. All weights were normalized to kg for analysis.")

    bodyweight_exercises = sorted({row["exercise"] for row in rows if row["is_bodyweight"] and row["weight_kg"] == 0})
    if bodyweight_exercises:
        warnings.append(
            "Bodyweight exercises with 0 external load detected: "
            + ", ".join(bodyweight_exercises)
            + ". Volume uses external load only, so bodyweight work is better interpreted through reps and frequency."
        )

    return warnings


def build_precomputed_evidence(
    user_id: str,
    question: str,
    history: list[WorkoutEntry],
    user_name: str | None,
    user_profile: str | None,
    file_warnings: list[str],
) -> tuple[dict[str, Any], list[str], bool]:
    if not history:
        return (
            {
                "user_id": user_id,
                "user_name": user_name,
                "user_profile": user_profile,
                "question": question,
                "history_status": "empty",
            },
            file_warnings or ["Workout history is empty."],
            True,
        )

    rows = flatten_history(history)

    if not rows:
        return (
            {
                "user_id": user_id,
                "user_name": user_name,
                "user_profile": user_profile,
                "question": question,
                "history_status": "no_valid_sets",
            },
            file_warnings + ["No valid workout sets were found."],
            True,
        )

    dates = sorted({row["date"] for row in rows})
    known_exercises = sorted({row["exercise"] for row in rows})
    target_exercise = detect_exercise_from_question(question, known_exercises)

    exercise_summary = summarize_by_exercise(rows)
    muscle_summary = summarize_by_category(rows, "primary_muscle")
    pattern_summary = summarize_by_category(rows, "movement_pattern")
    balance_summary = build_balance_summary(muscle_summary, pattern_summary)
    neglected_summary = build_neglected_summary(rows, reference_date=dates[-1])
    target_trend = build_target_exercise_trend(rows, target_exercise)
    deload_patterns = detect_deload_patterns(rows)

    warnings = collect_warnings(rows, file_warnings)

    insufficient_data = False

    if len(dates) < 2:
        insufficient_data = True
        warnings.append("Only one training date is available, so trend analysis is limited.")

    if target_exercise and target_trend and target_trend["session_count"] < 2:
        insufficient_data = True
        warnings.append(f"Only one session found for {target_exercise}, so exercise-specific trend analysis is limited.")

    if not target_exercise and any(word in question.lower() for word in ["trend", "progress", "increase", "improve"]):
        warnings.append("No specific exercise was detected from the question; trend analysis is based on overall history.")

    evidence = {
        "user_id": user_id,
        "user_name": user_name,
        "user_profile": user_profile,
        "question": question,
        "history_status": "available",
        "date_range": {
            "start": dates[0].isoformat(),
            "end": dates[-1].isoformat(),
            "unique_training_days": len(dates),
        },
        "total_sets": len(rows),
        "total_reps": sum(row["reps"] for row in rows),
        "total_volume_kg": round_number(sum(row["volume_kg"] for row in rows)),
        "known_exercises": known_exercises,
        "target_exercise_detected": target_exercise,
        "exercise_summary": exercise_summary,
        "muscle_summary": muscle_summary,
        "movement_pattern_summary": pattern_summary,
        "balance_summary": balance_summary,
        "neglected_summary": neglected_summary,
        "target_exercise_trend": target_trend,
        "deload_patterns": deload_patterns,
    }

    return evidence, warnings, insufficient_data


def format_evidence_for_llm(evidence: dict[str, Any], warnings: list[str]) -> str:
    lines: list[str] = []

    lines.append(f"User ID: {evidence.get('user_id')}")
    lines.append(f"User name: {evidence.get('user_name')}")
    lines.append(f"User profile: {evidence.get('user_profile')}")
    lines.append(f"Question: {evidence.get('question')}")
    lines.append(f"History status: {evidence.get('history_status')}")

    if evidence.get("history_status") != "available":
        return "\n".join(lines)

    date_range = evidence["date_range"]
    lines.append(
        f"Date range: {date_range['start']} to {date_range['end']} "
        f"({date_range['unique_training_days']} training days)"
    )
    lines.append(f"Total sets: {evidence['total_sets']}")
    lines.append(f"Total reps: {evidence['total_reps']}")
    lines.append(f"Total external-load volume: {evidence['total_volume_kg']} kg")
    lines.append(f"Known exercises: {', '.join(evidence['known_exercises'])}")
    lines.append(f"Target exercise detected: {evidence.get('target_exercise_detected') or 'none'}")

    target_trend = evidence.get("target_exercise_trend")
    if target_trend:
        lines.append("")
        lines.append("Target exercise trend:")
        lines.append(f"- Exercise: {target_trend['exercise']}")
        lines.append(f"- Session count: {target_trend['session_count']}")

        for session in target_trend["sessions"]:
            lines.append(
                f"- {session['date']}: {session['sets']} sets, "
                f"{session['total_reps']} reps, "
                f"{session['session_volume_kg']} kg external-load volume, "
                f"max external load {session['max_external_load_kg']} kg, "
                f"best estimated 1RM {session['best_estimated_1rm_kg']} kg"
            )

        change = target_trend["change_from_first_to_latest"]
        lines.append(
            f"- Change first to latest: volume {change['session_volume_kg']} kg, "
            f"max external load {change['max_external_load_kg']} kg, "
            f"estimated 1RM {change['best_estimated_1rm_kg']} kg"
        )

    lines.append("")
    lines.append("Exercise summary:")
    for exercise, summary in evidence["exercise_summary"].items():
        lines.append(
            f"- {exercise}: {summary['sessions']} sessions, {summary['total_sets']} sets, "
            f"{summary['total_volume_kg']} kg total external-load volume, "
            f"best estimated 1RM {summary['best_estimated_1rm_kg']} kg, "
            f"latest session {summary['latest_session_date']}"
        )

    lines.append("")
    lines.append("Muscle summary:")
    for muscle, summary in evidence["muscle_summary"].items():
        lines.append(
            f"- {muscle}: {summary['total_sets']} sets, "
            f"{summary['total_volume_kg']} kg volume, latest date {summary['latest_date']}"
        )

    balance = evidence["balance_summary"]
    lines.append("")
    lines.append("Balance summary:")
    lines.append(f"- Chest sets: {balance['chest_sets']}")
    lines.append(f"- Back sets: {balance['back_sets']}")
    lines.append(f"- Leg sets: {balance['leg_sets']}")
    lines.append(f"- Push sets: {balance['push_sets']}")
    lines.append(f"- Pull sets: {balance['pull_sets']}")
    lines.append(f"- Chest/back set ratio: {balance['chest_to_back_set_ratio']}")
    lines.append(f"- Push/pull set ratio: {balance['push_to_pull_set_ratio']}")

    neglected = evidence["neglected_summary"]
    lines.append("")
    lines.append(f"Neglected muscles >=21 days: {neglected['neglected_muscles_21d']}")
    lines.append(f"Neglected movement patterns >=21 days: {neglected['neglected_movement_patterns_21d']}")

    if evidence.get("deload_patterns"):
        lines.append("")
        lines.append(f"Potential deload patterns: {evidence['deload_patterns']}")

    if warnings:
        lines.append("")
        lines.append("Warnings:")
        for warning in warnings:
            lines.append(f"- {warning}")

    return "\n".join(lines)


def build_user_prompt(evidence_text: str) -> str:
    return f"""
Precomputed workout evidence:
{evidence_text}

Write a useful answer to the user's question.

Rules:
- Do not mention raw JSON.
- Mention specific data points when relevant.
- If data is insufficient, say exactly what is missing.
- If suggesting a plan, make it conservative and coach-reviewable.
- Do not provide medical diagnosis or injury rehabilitation.
""".strip()


def analyze_workout_history(
    user_id: str,
    question: str,
    history: list[WorkoutEntry] | None = None,
) -> WorkoutAnalysisResponse:
    guardrail_result = check_medical_guardrail(question)

    if not guardrail_result.allowed:
        return WorkoutAnalysisResponse(
            user_id=user_id,
            user_name=None,
            user_profile=None,
            answer=guardrail_result.message or "I can’t answer that request.",
            insufficient_data=False,
            warnings=[],
            evidence={},
            refusal=True,
            refusal_reason=guardrail_result.reason,
        )

    user_name = None
    user_profile = None
    file_warnings: list[str] = []

    if history is None:
        user_name, user_profile, history, file_warnings = load_user_history_from_file(user_id)

    evidence, warnings, insufficient_data = build_precomputed_evidence(
        user_id=user_id,
        question=question,
        history=history,
        user_name=user_name,
        user_profile=user_profile,
        file_warnings=file_warnings,
    )

    if evidence.get("history_status") != "available":
        return WorkoutAnalysisResponse(
            user_id=user_id,
            user_name=user_name,
            user_profile=user_profile,
            answer=(
                "I do not have enough workout history to answer this. "
                "Please check that the user exists and has dated workout sessions with exercises, sets, reps, and weights."
            ),
            insufficient_data=True,
            warnings=warnings,
            evidence=evidence,
            refusal=False,
            refusal_reason=None,
        )

    evidence_text = format_evidence_for_llm(evidence, warnings)

    try:
        answer = generate_text(
            system_prompt=WORKOUT_ANALYSIS_SYSTEM_PROMPT,
            user_prompt=build_user_prompt(evidence_text),
        )
    except Exception:
        logger.exception("Workout analysis LLM generation failed")

        date_range = evidence.get("date_range", {})
        answer = (
            "I processed the workout history, but could not generate a full AI response right now. "
            "Key evidence: "
            f"{evidence.get('total_sets')} total sets, "
            f"{evidence.get('total_volume_kg')} kg external-load volume, "
            f"date range {date_range.get('start')} to {date_range.get('end')}."
        )

    return WorkoutAnalysisResponse(
        user_id=user_id,
        user_name=user_name,
        user_profile=user_profile,
        answer=answer,
        insufficient_data=insufficient_data,
        warnings=warnings,
        evidence=evidence,
        refusal=False,
        refusal_reason=None,
    )