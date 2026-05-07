import re


EXERCISE_ALIASES = {
    "bench": "Bench Press",
    "bench press": "Bench Press",
    "barbell bench press": "Bench Press",

    "db bench press": "Dumbbell Bench Press",
    "dumbbell bench press": "Dumbbell Bench Press",

    "incline bench": "Incline Bench Press",
    "incline bench press": "Incline Bench Press",
    "incline dumbbell press": "Incline Dumbbell Press",
    "incline db press": "Incline Dumbbell Press",

    "push up": "Push Up",
    "pushup": "Push Up",
    "push ups": "Push Up",
    "pushups": "Push Up",

    "squat": "Back Squat",
    "back squat": "Back Squat",
    "front squat": "Front Squat",
    "leg press": "Leg Press",
    "lunge": "Lunge",
    "lunges": "Lunge",

    "deadlift": "Deadlift",
    "conventional deadlift": "Deadlift",
    "romanian deadlift": "Romanian Deadlift",
    "rdl": "Romanian Deadlift",

    "pull up": "Pull Up",
    "pullup": "Pull Up",
    "pull ups": "Pull Up",
    "pullups": "Pull Up",
    "pull-up": "Pull Up",
    "pull-ups": "Pull Up",

    "lat pulldown": "Lat Pulldown",
    "lat pull down": "Lat Pulldown",

    "row": "Row",
    "barbell row": "Barbell Row",
    "cable row": "Cable Row",
    "seated row": "Cable Row",
    "dumbbell row": "Dumbbell Row",

    "face pull": "Face Pull",
    "face pulls": "Face Pull",

    "overhead press": "Overhead Press",
    "ohp": "Overhead Press",
    "shoulder press": "Shoulder Press",
    "lateral raise": "Lateral Raise",
    "lat raise": "Lateral Raise",

    "bicep curl": "Bicep Curl",
    "biceps curl": "Bicep Curl",
    "curl": "Bicep Curl",
    "tricep pushdown": "Tricep Pushdown",
    "triceps pushdown": "Tricep Pushdown",

    "plank": "Plank",
    "crunch": "Crunch",
    "sit up": "Sit Up",
    "situp": "Sit Up",
}


EXERCISE_METADATA = {
    "Bench Press": {
        "primary_muscle": "chest",
        "secondary_muscles": ["triceps", "front_delts"],
        "movement_pattern": "horizontal_push",
    },
    "Dumbbell Bench Press": {
        "primary_muscle": "chest",
        "secondary_muscles": ["triceps", "front_delts"],
        "movement_pattern": "horizontal_push",
    },
    "Incline Bench Press": {
        "primary_muscle": "upper_chest",
        "secondary_muscles": ["triceps", "front_delts"],
        "movement_pattern": "horizontal_push",
    },
    "Incline Dumbbell Press": {
        "primary_muscle": "upper_chest",
        "secondary_muscles": ["triceps", "front_delts"],
        "movement_pattern": "horizontal_push",
    },
    "Push Up": {
        "primary_muscle": "chest",
        "secondary_muscles": ["triceps", "front_delts", "core"],
        "movement_pattern": "horizontal_push",
    },

    "Back Squat": {
        "primary_muscle": "quads",
        "secondary_muscles": ["glutes", "hamstrings", "core"],
        "movement_pattern": "squat",
    },
    "Front Squat": {
        "primary_muscle": "quads",
        "secondary_muscles": ["glutes", "core"],
        "movement_pattern": "squat",
    },
    "Leg Press": {
        "primary_muscle": "quads",
        "secondary_muscles": ["glutes", "hamstrings"],
        "movement_pattern": "squat",
    },
    "Lunge": {
        "primary_muscle": "quads",
        "secondary_muscles": ["glutes", "hamstrings"],
        "movement_pattern": "single_leg",
    },

    "Deadlift": {
        "primary_muscle": "posterior_chain",
        "secondary_muscles": ["glutes", "hamstrings", "back"],
        "movement_pattern": "hinge",
    },
    "Romanian Deadlift": {
        "primary_muscle": "hamstrings",
        "secondary_muscles": ["glutes", "back"],
        "movement_pattern": "hinge",
    },

    "Pull Up": {
        "primary_muscle": "back",
        "secondary_muscles": ["biceps"],
        "movement_pattern": "vertical_pull",
        "is_bodyweight": True,
    },
    "Lat Pulldown": {
        "primary_muscle": "back",
        "secondary_muscles": ["biceps"],
        "movement_pattern": "vertical_pull",
    },
    "Row": {
        "primary_muscle": "back",
        "secondary_muscles": ["biceps", "rear_delts"],
        "movement_pattern": "horizontal_pull",
    },
    "Barbell Row": {
        "primary_muscle": "back",
        "secondary_muscles": ["biceps", "rear_delts"],
        "movement_pattern": "horizontal_pull",
    },
    "Cable Row": {
        "primary_muscle": "back",
        "secondary_muscles": ["biceps", "rear_delts"],
        "movement_pattern": "horizontal_pull",
    },
    "Dumbbell Row": {
        "primary_muscle": "back",
        "secondary_muscles": ["biceps", "rear_delts"],
        "movement_pattern": "horizontal_pull",
    },
    "Face Pull": {
        "primary_muscle": "rear_delts",
        "secondary_muscles": ["upper_back"],
        "movement_pattern": "horizontal_pull",
    },

    "Overhead Press": {
        "primary_muscle": "shoulders",
        "secondary_muscles": ["triceps", "upper_chest"],
        "movement_pattern": "vertical_push",
    },
    "Shoulder Press": {
        "primary_muscle": "shoulders",
        "secondary_muscles": ["triceps"],
        "movement_pattern": "vertical_push",
    },
    "Lateral Raise": {
        "primary_muscle": "side_delts",
        "secondary_muscles": [],
        "movement_pattern": "shoulder_isolation",
    },

    "Bicep Curl": {
        "primary_muscle": "biceps",
        "secondary_muscles": [],
        "movement_pattern": "elbow_flexion",
    },
    "Tricep Pushdown": {
        "primary_muscle": "triceps",
        "secondary_muscles": [],
        "movement_pattern": "elbow_extension",
    },

    "Plank": {
        "primary_muscle": "core",
        "secondary_muscles": [],
        "movement_pattern": "core_stability",
    },
    "Crunch": {
        "primary_muscle": "core",
        "secondary_muscles": [],
        "movement_pattern": "core_flexion",
    },
    "Sit Up": {
        "primary_muscle": "core",
        "secondary_muscles": [],
        "movement_pattern": "core_flexion",
    },
}


def normalize_text(text: str) -> str:
    text = text.lower().strip()
    text = text.replace("-", " ")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def title_case_unknown_exercise(exercise: str) -> str:
    return " ".join(word.capitalize() for word in normalize_text(exercise).split())


def normalize_exercise_name(exercise: str) -> str:
    normalized = normalize_text(exercise)

    if normalized in EXERCISE_ALIASES:
        return EXERCISE_ALIASES[normalized]

    possible_title = title_case_unknown_exercise(exercise)

    if possible_title in EXERCISE_METADATA:
        return possible_title

    return possible_title or exercise.strip()


def get_exercise_metadata(exercise: str) -> dict:
    canonical = normalize_exercise_name(exercise)

    metadata = EXERCISE_METADATA.get(
        canonical,
        {
            "primary_muscle": "unknown",
            "secondary_muscles": [],
            "movement_pattern": "unknown",
            "is_bodyweight": False,
        },
    )

    return {
        "canonical_name": canonical,
        "is_bodyweight": metadata.get("is_bodyweight", False),
        **metadata,
    }


def detect_exercise_from_question(question: str, known_exercises: list[str]) -> str | None:
    normalized_question = normalize_text(question)

    candidates = set(known_exercises)

    for alias, canonical in EXERCISE_ALIASES.items():
        candidates.add(canonical)
        if normalize_text(alias) in normalized_question:
            return canonical

    sorted_candidates = sorted(candidates, key=len, reverse=True)

    for exercise in sorted_candidates:
        if normalize_text(exercise) in normalized_question:
            return exercise

    return None