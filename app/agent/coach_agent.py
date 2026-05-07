import json
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field

from app.agent.tools import (
    AGENT_TOOL_DEFINITIONS,
    execute_agent_tool,
    tool_result_to_text,
)
from app.core.config import settings
from app.core.guardrails import check_medical_guardrail
from app.core.llm import get_openai_client


class CoachAgentRequest(BaseModel):
    coach_id: str = Field(..., min_length=1)
    user_id: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)


class ToolTraceItem(BaseModel):
    tool_name: str
    arguments: dict[str, Any]
    result_summary: str | None = None
    error: str | None = None


class CoachAgentResponse(BaseModel):
    coach_id: str
    user_id: str
    answer: str
    tool_trace: list[ToolTraceItem] = []
    refusal: bool = False
    refusal_reason: str | None = None


AGENT_SYSTEM_PROMPT = """
You are a Coach Assist Agent for Everfit, a fitness coaching platform.

Your job:
- Help a coach answer multi-step client questions.
- Decide which tools to call and in what order.
- Do not hardcode tool order. Use the tools only when they are useful.
- Use analyze_history when the question depends on the client's workout data.
- Use rag_search when the question needs training principles, technique guidance, progressive overload, recovery, deloads, or programming knowledge.
- Use both tools when the answer needs both client-specific evidence and general training principles.
- If one tool returns insufficient data, still answer using the available evidence and clearly state what is missing.
- Do not diagnose injuries, prescribe injury rehabilitation, or provide medical treatment.
- For pain, injury, or medical symptoms, redirect to a qualified professional while offering general non-medical training principles when safe.
- Keep the coach's judgment at the center. Phrase recommendations as coach-reviewable guidance.

Final answer requirements:
- Produce one coherent answer.
- Mention specific workout data when analyze_history was used.
- Mention source document names or sections when rag_search was used.
- Be concise but useful.
""".strip()


def safe_parse_json_arguments(raw_arguments: str | None) -> dict[str, Any]:
    if not raw_arguments:
        return {}

    try:
        parsed = json.loads(raw_arguments)
    except json.JSONDecodeError:
        return {}

    if isinstance(parsed, dict):
        return parsed

    return {}


def assistant_message_to_dict(message) -> dict[str, Any]:
    """
    Convert OpenAI assistant message object into a serializable message dict.
    """
    result: dict[str, Any] = {
        "role": "assistant",
        "content": message.content,
    }

    if message.tool_calls:
        result["tool_calls"] = [
            {
                "id": tool_call.id,
                "type": tool_call.type,
                "function": {
                    "name": tool_call.function.name,
                    "arguments": tool_call.function.arguments,
                },
            }
            for tool_call in message.tool_calls
        ]

    return result


def summarize_tool_result_for_trace(result: dict[str, Any]) -> str:
    if "error" in result:
        return str(result["error"])

    tool = result.get("tool")

    if tool == "rag_search":
        sources = result.get("sources", [])
        return (
            f"RAG returned refusal={result.get('refusal')}, "
            f"sources={len(sources)}."
        )

    if tool == "analyze_history":
        evidence = result.get("evidence", {})
        return (
            f"History analysis returned refusal={result.get('refusal')}, "
            f"insufficient_data={result.get('insufficient_data')}, "
            f"date_range={evidence.get('date_range')}."
        )

    return "Tool executed."


def build_initial_messages(request: CoachAgentRequest) -> list[dict[str, Any]]:
    return [
        {
            "role": "system",
            "content": AGENT_SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": (
                f"Coach ID: {request.coach_id}\n"
                f"Client user_id: {request.user_id}\n"
                f"Coach question: {request.question}\n\n"
                "Answer the coach's question. Decide whether you need workout history analysis, "
                "fitness knowledge base search, or both."
            ),
        },
    ]


def run_coach_agent(request: CoachAgentRequest) -> CoachAgentResponse:
    guardrail_result = check_medical_guardrail(request.question)

    if not guardrail_result.allowed:
        return CoachAgentResponse(
            coach_id=request.coach_id,
            user_id=request.user_id,
            answer=guardrail_result.message or "I can’t answer that request.",
            tool_trace=[],
            refusal=True,
            refusal_reason=guardrail_result.reason,
        )

    client = get_openai_client()
    messages = build_initial_messages(request)
    tool_trace: list[ToolTraceItem] = []

    max_tool_rounds = 4

    for _ in range(max_tool_rounds):
        response = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=messages,
            tools=AGENT_TOOL_DEFINITIONS,
            tool_choice="auto",
            temperature=settings.OPENAI_TEMPERATURE,
            max_tokens=settings.OPENAI_MAX_TOKENS,
        )

        assistant_message = response.choices[0].message
        messages.append(assistant_message_to_dict(assistant_message))

        if not assistant_message.tool_calls:
            final_answer = assistant_message.content or ""

            return CoachAgentResponse(
                coach_id=request.coach_id,
                user_id=request.user_id,
                answer=final_answer,
                tool_trace=tool_trace,
                refusal=False,
                refusal_reason=None,
            )

        for tool_call in assistant_message.tool_calls:
            tool_name = tool_call.function.name
            arguments = safe_parse_json_arguments(tool_call.function.arguments)

            try:
                result = execute_agent_tool(
                    tool_name=tool_name,
                    arguments=arguments,
                    default_user_id=request.user_id,
                )
            except Exception as exc:
                logger.exception(f"Agent tool failed: {tool_name}")
                result = {
                    "tool": tool_name,
                    "error": str(exc),
                }

            tool_trace.append(
                ToolTraceItem(
                    tool_name=tool_name,
                    arguments=arguments,
                    result_summary=summarize_tool_result_for_trace(result),
                    error=result.get("error"),
                )
            )

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_result_to_text(result),
                }
            )

    # Fallback if the model keeps calling tools and never finalizes.
    fallback_response = client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            *messages,
            {
                "role": "user",
                "content": (
                    "Stop calling tools now. Produce the best final coach-facing answer using the tool results already provided."
                ),
            },
        ],
        temperature=settings.OPENAI_TEMPERATURE,
        max_tokens=settings.OPENAI_MAX_TOKENS,
    )

    final_answer = fallback_response.choices[0].message.content or (
        "I gathered tool results but could not produce a final response."
    )

    return CoachAgentResponse(
        coach_id=request.coach_id,
        user_id=request.user_id,
        answer=final_answer,
        tool_trace=tool_trace,
        refusal=False,
        refusal_reason=None,
    )