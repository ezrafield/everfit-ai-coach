from dataclasses import dataclass


@dataclass(frozen=True)
class GuardrailResult:
    allowed: bool
    reason: str | None = None
    message: str | None = None


MEDICAL_RISK_TERMS = [
    "diagnose",
    "diagnosis",
    "medical condition",
    "torn acl",
    "acl tear",
    "meniscus tear",
    "fracture",
    "stress fracture",
    "hernia",
    "chest pain",
    "fainting",
    "dizziness",
    "numbness",
    "severe pain",
    "sharp pain",
    "rehab my injury",
    "rehabilitate my injury",
    "injury rehab",
    "physical therapy plan",
    "treat my injury",
    "fix my injury",
]

EATING_DISORDER_RISK_TERMS = [
    "starve",
    "starving",
    "purge",
    "vomit after eating",
    "laxative",
    "laxatives",
    "eating disorder",
    "anorexia",
    "bulimia",
    "binge and purge",
    "lose 5kg in 5 days",
    "lose 10kg in a week",
    "extreme calorie deficit",
]

OBVIOUS_OUT_OF_SCOPE_TERMS = [
    "weather",
    "stock price",
    "crypto",
    "bitcoin",
    "politics",
    "election",
    "movie recommendation",
    "travel itinerary",
    "write a poem",
    "software bug",
]


def normalize_query(query: str) -> str:
    return " ".join(query.lower().strip().split())


def check_medical_guardrail(query: str) -> GuardrailResult:
    normalized = normalize_query(query)

    for term in MEDICAL_RISK_TERMS:
        if term in normalized:
            return GuardrailResult(
                allowed=False,
                reason="medical_advice_risk",
                message=(
                    "I can’t diagnose, treat, or prescribe rehabilitation for injuries or medical "
                    "conditions. Please consult a qualified medical professional. I can still share "
                    "general training principles or suggest questions to discuss with your coach or clinician."
                ),
            )

    for term in EATING_DISORDER_RISK_TERMS:
        if term in normalized:
            return GuardrailResult(
                allowed=False,
                reason="eating_disorder_risk",
                message=(
                    "I can’t help with unsafe weight-loss methods, disordered eating behaviors, "
                    "or extreme restriction. Please consider speaking with a qualified healthcare "
                    "professional. I can help with general, balanced fitness and nutrition habits."
                ),
            )

    return GuardrailResult(allowed=True)


def check_obvious_out_of_scope(query: str) -> GuardrailResult:
    normalized = normalize_query(query)

    for term in OBVIOUS_OUT_OF_SCOPE_TERMS:
        if term in normalized:
            return GuardrailResult(
                allowed=False,
                reason="out_of_scope",
                message=(
                    "I can help with fitness, exercise technique, training principles, recovery, "
                    "nutrition basics, and workout programming. This question appears to be outside that scope."
                ),
            )

    return GuardrailResult(allowed=True)


def check_rag_guardrails(query: str) -> GuardrailResult:
    medical_result = check_medical_guardrail(query)
    if not medical_result.allowed:
        return medical_result

    scope_result = check_obvious_out_of_scope(query)
    if not scope_result.allowed:
        return scope_result

    return GuardrailResult(allowed=True)