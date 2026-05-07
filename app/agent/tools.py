import json
from typing import Any

from app.rag.retriever import ask_rag
from app.workout.analyzer import analyze_workout_history


def rag_search(query: str) -> dict[str, Any]:
    """
    Tool wrapper around Feature 1 RAG.
    Returns a serializable dict for the agent.
    """
    result = ask_rag(question=query)

    return {
        "tool": "rag_search",
        "query": query,
        "answer": result.answer,
        "sources": [source.model_dump() for source in result.sources],
        "refusal": result.refusal,
        "refusal_reason": result.refusal_reason,
    }


def analyze_history(user_id: str, question: str) -> dict[str, Any]:
    """
    Tool wrapper around Feature 2 workout history analysis.
    Loads the user's history from data/workout-history.json.
    """
    result = analyze_workout_history(
        user_id=user_id,
        question=question,
        history=None,
    )

    return {
        "tool": "analyze_history",
        "user_id": result.user_id,
        "user_name": result.user_name,
        "user_profile": result.user_profile,
        "answer": result.answer,
        "insufficient_data": result.insufficient_data,
        "warnings": result.warnings,
        "evidence": result.evidence,
        "refusal": result.refusal,
        "refusal_reason": result.refusal_reason,
    }


def execute_agent_tool(
    tool_name: str,
    arguments: dict[str, Any],
    default_user_id: str,
) -> dict[str, Any]:
    """
    Execute one allowed agent tool.

    default_user_id is injected by the server-side request context so the model
    cannot accidentally analyze another user unless the API request explicitly
    routes to that user.
    """
    if tool_name == "rag_search":
        query = str(arguments.get("query", "")).strip()

        if not query:
            return {
                "tool": tool_name,
                "error": "Missing required argument: query",
            }

        return rag_search(query=query)

    if tool_name == "analyze_history":
        question = str(arguments.get("question", "")).strip()
        requested_user_id = str(arguments.get("user_id", default_user_id)).strip()

        # Safety boundary:
        # For this assignment, the authenticated/requested user_id from the API request wins.
        # This prevents the LLM from switching users via tool arguments.
        if requested_user_id != default_user_id:
            return {
                "tool": tool_name,
                "error": "User mismatch. The agent can only analyze the user_id from the API request.",
                "requested_user_id": requested_user_id,
                "allowed_user_id": default_user_id,
            }

        if not question:
            return {
                "tool": tool_name,
                "error": "Missing required argument: question",
            }

        return analyze_history(
            user_id=default_user_id,
            question=question,
        )

    return {
        "tool": tool_name,
        "error": f"Unknown tool: {tool_name}",
    }


def tool_result_to_text(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2, default=str)


AGENT_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "rag_search",
            "description": (
                "Search the fitness knowledge base for grounded information about exercise technique, "
                "progressive overload, workout programming, recovery, nutrition basics, periodization, "
                "deloads, and training principles."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The fitness knowledge question to search for.",
                    }
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_history",
            "description": (
                "Analyze a specific client's workout history using precomputed statistics such as "
                "volume, exercise trends, muscle balance, movement patterns, and neglected exercises."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": (
                            "The client user ID. Must match the user_id from the API request."
                        ),
                    },
                    "question": {
                        "type": "string",
                        "description": "The workout-history analysis question.",
                    },
                },
                "required": ["user_id", "question"],
                "additionalProperties": False,
            },
        },
    },
]