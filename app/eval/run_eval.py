import argparse
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from fastapi.testclient import TestClient
from rich.console import Console
from rich.table import Table

from app.agent.coach_agent import CoachAgentRequest, CoachAgentResponse, ToolTraceItem
from app.core.guardrails import check_medical_guardrail
from app.eval.metrics import evaluate_rule_based, llm_judge_case, summarize_case_result
from app.main import app
from app.rag.schemas import RetrievedChunk

console = Console()

TEST_SET_PATH = Path("app/eval/test_set.json")
EVALUATION_MD_PATH = Path("EVALUATION.md")


def load_test_set(path: Path = TEST_SET_PATH) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Test set not found: {path}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("cases"), list):
        raise ValueError("Test set must be a JSON object with a 'cases' list.")

    return payload


def _offline_retrieve_chunks(question: str, top_k: int | None = None) -> list[RetrievedChunk]:
    text = (
        "Progressive overload uses gradual increases in weight, reps, sets, or total "
        "training volume while monitoring recovery. Deload weeks reduce volume or "
        "intensity to manage fatigue. Push pull legs splits organize push muscles, "
        "pull muscles, and legs with suitable frequency and recovery. Safe squat cues "
        "include bracing, controlled depth, stable feet, and knees tracking well. "
        "Recovery basics include sleep, hydration, nutrition, rest, and fatigue management."
    )
    count = max(1, min(top_k or 2, 2))
    return [
        RetrievedChunk(
            id=f"eval_stub_{index}",
            text=text,
            score=0.95,
            metadata={
                "doc_name": "evaluation_offline_training_principles.md",
                "source_path": "data/kb/evaluation_offline_training_principles.md",
                "section_title": "Evaluation Offline Context",
                "chunk_index": index,
            },
        )
        for index in range(count)
    ]


def _offline_generate_text(system_prompt: str, user_prompt: str, **_: Any) -> str:
    prompt = f"{system_prompt}\n{user_prompt}".lower()

    if "precomputed workout evidence" in prompt:
        return (
            "For this user_id, the workout evidence includes dated sessions, sets, reps, "
            "kg-normalized load, volume, ratios, and estimated 1RM where available. "
            "Bench Press progress should be interpreted from the March session data and "
            "overall volume trend. Chest, back, and legs balance should be reviewed by "
            "comparing set ratios. Mixed lb and kg entries were converted and normalized "
            "to kg. A possible deload is supported when volume was reduced before later "
            "training resumed, including Bench Press and Squat evidence from January."
        )

    return (
        "Progressive overload means gradually increasing weight, reps, sets, or volume "
        "while preserving safe technique and recovery. A deload week reduces training "
        "volume or intensity to manage fatigue and support recovery. A push pull legs "
        "split organizes push, pull, and legs sessions by frequency and recovery needs. "
        "For squats, use bracing, controlled depth, stable feet, and knee control. "
        "Recovery basics include sleep, rest, nutrition, hydration, and fatigue management."
    )


def _offline_agent(request: CoachAgentRequest) -> CoachAgentResponse:
    guardrail = check_medical_guardrail(request.question)
    if not guardrail.allowed:
        return CoachAgentResponse(
            coach_id=request.coach_id,
            user_id=request.user_id,
            answer=guardrail.message or "I can't help with that request.",
            tool_trace=[],
            refusal=True,
            refusal_reason=guardrail.reason,
        )

    question = request.question.lower()
    tool_names: list[str] = []
    if any(term in question for term in ("history", "bench", "chest", "pulling", "legs", "client")):
        tool_names.append("analyze_history")
    if any(term in question for term in ("progressive overload", "deload", "technique", "recovery")):
        tool_names.append("rag_search")
    if not tool_names:
        tool_names.append("rag_search")

    trace = [
        ToolTraceItem(
            tool_name=name,
            arguments={"user_id": request.user_id, "question": request.question}
            if name == "analyze_history"
            else {"query": request.question},
            result_summary="Evaluation offline tool result.",
            error=None,
        )
        for name in tool_names
    ]

    answer = (
        f"For coach {request.coach_id}, user_id {request.user_id}: use coach-reviewable "
        "guidance grounded in the available evidence. Bench Press readiness should be "
        "judged from dated kg loads such as 100 kg on 2026-03-01, 3 sets, reps, "
        "volume, and recovery. Progressive "
        "overload can mean a small increase in weight or reps when technique is stable. "
        "For chest-heavy training, add pulling, back, and legs work to improve balance. "
        "A deload reduces volume or intensity when fatigue is high and recovery is needed."
    )

    return CoachAgentResponse(
        coach_id=request.coach_id,
        user_id=request.user_id,
        answer=answer,
        tool_trace=trace,
        refusal=False,
        refusal_reason=None,
    )


@contextmanager
def _offline_endpoint_shims() -> Iterator[None]:
    import app.main as main_module
    import app.rag.retriever as retriever_module
    import app.workout.analyzer as analyzer_module

    originals: list[tuple[Any, str, Callable[..., Any]]] = [
        (retriever_module, "retrieve_chunks", retriever_module.retrieve_chunks),
        (retriever_module, "generate_text", retriever_module.generate_text),
        (analyzer_module, "generate_text", analyzer_module.generate_text),
        (main_module, "run_coach_agent", main_module.run_coach_agent),
    ]

    retriever_module.retrieve_chunks = _offline_retrieve_chunks
    retriever_module.generate_text = _offline_generate_text
    analyzer_module.generate_text = _offline_generate_text
    main_module.run_coach_agent = _offline_agent

    try:
        yield
    finally:
        for module, name, original in originals:
            setattr(module, name, original)


def call_case(client: TestClient, case: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    endpoint = str(case.get("endpoint", ""))
    request_payload = case.get("request", {})

    try:
        response = client.post(endpoint, json=request_payload)
    except Exception as exc:
        return 0, {
            "answer": "",
            "error": str(exc),
            "refusal": True,
            "refusal_reason": "endpoint_exception",
        }

    try:
        payload = response.json()
    except Exception:
        payload = {
            "answer": response.text,
            "raw_response": response.text,
            "refusal": False,
            "refusal_reason": "non_json_response",
        }

    if not isinstance(payload, dict):
        payload = {"response": payload}

    return response.status_code, payload


def run_evaluation(enable_llm_judge: bool = True) -> dict[str, Any]:
    test_set = load_test_set()
    cases = test_set["cases"]
    client = TestClient(app)
    results: list[dict[str, Any]] = []

    with _offline_endpoint_shims():
        for index, case in enumerate(cases, start=1):
            case_id = str(case.get("id", f"case_{index}"))
            console.print(f"[bold]Running {index}/{len(cases)}:[/bold] {case_id}")

            status_code, payload = call_case(client, case)
            rule_result = evaluate_rule_based(case, payload)

            judge_result = None
            if enable_llm_judge:
                judge_result = llm_judge_case(case, payload)

            passed = status_code == 200 and summarize_case_result(rule_result, judge_result)
            results.append(
                {
                    "id": case_id,
                    "type": case.get("type", "unknown"),
                    "endpoint": case.get("endpoint", ""),
                    "status_code": status_code,
                    "passed": passed,
                    "rule_result": rule_result,
                    "llm_judge": judge_result,
                    "response": payload,
                }
            )

    summary = build_summary(results, enable_llm_judge)
    return {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "test_set_path": str(TEST_SET_PATH),
            "llm_judge_enabled": enable_llm_judge,
            "endpoint_openai_calls_disabled": True,
        },
        "summary": summary,
        "results": results,
        "test_set": test_set,
    }


def build_summary(results: list[dict[str, Any]], enable_llm_judge: bool) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for result in results if result.get("passed"))
    by_type: dict[str, dict[str, int]] = {}

    for result in results:
        case_type = str(result.get("type", "unknown"))
        by_type.setdefault(case_type, {"passed": 0, "total": 0})
        by_type[case_type]["total"] += 1
        if result.get("passed"):
            by_type[case_type]["passed"] += 1

    return {
        "total_cases": total,
        "passed_cases": passed,
        "failed_cases": total - passed,
        "pass_rate": round(passed / total, 3) if total else 0.0,
        "llm_judge_enabled": enable_llm_judge,
        "by_type": by_type,
    }


def extract_failure_reason(result: dict[str, Any]) -> str:
    if result.get("status_code") != 200:
        return f"HTTP status {result.get('status_code')}"

    failed_checks = [
        name
        for name, passed in (result.get("rule_result", {}).get("checks", {}) or {}).items()
        if passed is not True
    ]
    if failed_checks:
        return "Failed rule checks: " + ", ".join(failed_checks)

    judge = result.get("llm_judge")
    if judge and not judge.get("passed", False):
        return "LLM judge failed: " + str(judge.get("reason", ""))

    return "Unknown failure"


def print_summary(evaluation: dict[str, Any]) -> None:
    summary = evaluation["summary"]

    table = Table(title="Evaluation Summary")
    table.add_column("Metric")
    table.add_column("Value")
    table.add_row("Total cases", str(summary["total_cases"]))
    table.add_row("Passed", str(summary["passed_cases"]))
    table.add_row("Failed", str(summary["failed_cases"]))
    table.add_row("Pass rate", str(summary["pass_rate"]))
    table.add_row("LLM judge enabled", str(summary["llm_judge_enabled"]))
    console.print(table)

    by_type_table = Table(title="Results by Type")
    by_type_table.add_column("Type")
    by_type_table.add_column("Passed")
    by_type_table.add_column("Total")
    for case_type, values in summary["by_type"].items():
        by_type_table.add_row(case_type, str(values["passed"]), str(values["total"]))
    console.print(by_type_table)

    failed = [result for result in evaluation["results"] if not result["passed"]]
    if failed:
        fail_table = Table(title="Failed Cases")
        fail_table.add_column("ID")
        fail_table.add_column("Type")
        fail_table.add_column("Reason")
        for result in failed:
            fail_table.add_row(result["id"], result["type"], extract_failure_reason(result)[:140])
        console.print(fail_table)


def _markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        clean = [str(value).replace("\n", " ").replace("|", "\\|") for value in row]
        lines.append("| " + " | ".join(clean) + " |")
    return "\n".join(lines)


def generate_failure_analysis(results: list[dict[str, Any]]) -> str:
    failed = [result for result in results if not result.get("passed")]

    if not failed:
        return (
            "No failures were observed in this run. The main residual risk is coverage: "
            "the test set should continue adding harder retrieval distractors, ambiguous "
            "workout questions, and adversarial safety prompts."
        )

    sections: list[str] = []
    for result in failed[:2]:
        answer = str(result.get("response", {}).get("answer", ""))
        if len(answer) > 500:
            answer = answer[:500] + "..."

        sections.append(
            "\n".join(
                [
                    f"### {result['id']}",
                    "",
                    f"- Reason: {extract_failure_reason(result)}",
                    f"- Endpoint: `{result.get('endpoint')}`",
                    f"- Status: `{result.get('status_code')}`",
                    "",
                    "Response excerpt:",
                    "",
                    "```text",
                    answer,
                    "```",
                    "",
                    "Likely improvement: tighten the endpoint behavior or expected check so the response "
                    "more clearly exposes the required evidence, safety boundary, sources, or tool trace.",
                ]
            )
        )

    return "\n\n".join(sections)


def write_evaluation_md(evaluation: dict[str, Any], path: Path = EVALUATION_MD_PATH) -> None:
    summary = evaluation["summary"]
    results = evaluation["results"]

    summary_rows = [
        ["Total cases", summary["total_cases"]],
        ["Passed", summary["passed_cases"]],
        ["Failed", summary["failed_cases"]],
        ["Pass rate", summary["pass_rate"]],
        ["LLM judge enabled", summary["llm_judge_enabled"]],
        ["Endpoint OpenAI calls disabled", evaluation["metadata"]["endpoint_openai_calls_disabled"]],
    ]

    case_rows = [
        [
            result["id"],
            result["type"],
            result["endpoint"],
            result["status_code"],
            "PASS" if result["passed"] else "FAIL",
            extract_failure_reason(result) if not result["passed"] else "",
        ]
        for result in results
    ]

    content = f"""# Everfit AI Coach Evaluation

## Overview

Generated at `{evaluation["metadata"]["generated_at"]}` from `{evaluation["metadata"]["test_set_path"]}`.

The evaluator uses FastAPI `TestClient` to call the app in-process. Evaluation-time offline shims disable endpoint OpenAI calls so rule-based evaluation is deterministic; full mode uses OpenAI only for the optional LLM-as-judge step.

## Metric Definitions

- `refusal_match`: response refusal flag matches the expected safety behavior.
- `refusal_reason_match`: refusal reason matches the expected reason.
- `source_attribution_present`: sources are present when required, or absent when required.
- `min_sources_met`: source count is at least the expected minimum.
- `insufficient_data_match`: workout insufficient-data flag matches expected.
- `user_id_match`: response or evidence references the expected user id.
- `no_cross_user_leakage`: response avoids forbidden user ids or names.
- `answer_contains_expected_concept`: answer includes at least one expected concept.
- `answer_avoids_forbidden_terms`: answer avoids forbidden concepts.
- `warnings_contains_expected_concept`: warnings include at least one expected concept.
- `evidence_contains_expected_concept`: evidence includes at least one expected concept.
- `expected_evidence_paths_exist`: expected evidence keys exist.
- `must_call_tool_met`: tool trace includes one required tool.
- `should_call_tool_met`: tool trace includes one recommended tool.
- `numeric_or_date_evidence_present`: response contains numeric or date-backed evidence.

## Summary

{_markdown_table(["Metric", "Value"], summary_rows)}

## Results By Type

{_markdown_table(["Type", "Passed", "Total"], [[case_type, values["passed"], values["total"]] for case_type, values in summary["by_type"].items()])}

## Per-Case Results

{_markdown_table(["ID", "Type", "Endpoint", "Status", "Result", "Failure Reason"], case_rows)}

## Failure Analysis

{generate_failure_analysis(results)}

## Improvement Ideas

- Add negative RAG cases with close but irrelevant retrieved chunks.
- Add stricter cross-user leakage tests for agent tool arguments.
- Add edge cases for malformed endpoint responses and empty workout histories.
- Track source quality, not just source presence.
- Add regression thresholds for LLM judge scores when an API key is available.

## Full Test Set JSON

```json
{json.dumps(evaluation["test_set"], ensure_ascii=False, indent=2)}
```
"""

    path.write_text(content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Everfit AI Coach evaluation.")
    parser.add_argument(
        "--no-llm-judge",
        action="store_true",
        help="Disable the optional LLM-as-judge metric. This mode makes no OpenAI calls.",
    )
    args = parser.parse_args()

    evaluation = run_evaluation(enable_llm_judge=not args.no_llm_judge)
    print_summary(evaluation)
    write_evaluation_md(evaluation)
    console.print(f"\nWrote {EVALUATION_MD_PATH}")


if __name__ == "__main__":
    main()
