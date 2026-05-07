# AI_WORKFLOW.md

## 1. Overview

This project was developed with AI assistance, but the implementation decisions were reviewed and corrected manually. I used AI tools mainly for scaffolding, code review, test generation, documentation drafting, and risk analysis. I did not treat AI output as final without checking it against the assignment requirements, especially around guardrails, user data isolation, and evaluation design.

The assignment is health-adjacent, so I intentionally kept the AI system conservative around medical advice while still allowing normal fitness coaching questions.

---

## 2. AI Tools Used

| Stage | Tool | Purpose | Human Review Applied |
|---|---|---|---|
| Requirement analysis | ChatGPT | Break down the take-home exercise into implementation milestones and time estimates | Verified against the original assignment PDF |
| Project planning | ChatGPT | Draft architecture, endpoint list, module boundaries, and implementation order | Simplified the scope to avoid overengineering |
| Coding | Codex | Generate initial FastAPI modules, Pydantic schemas, service classes, and tests | Reviewed code for correctness, privacy risks, and assignment fit |
| RAG implementation | Codex | Draft markdown loader, chunking, embedding, Chroma persistence, and retrieval logic | Adjusted metadata fields and retrieval response format to guarantee source attribution |
| Workout analysis | Codex | Draft deterministic preprocessing for workout history before LLM generation | Ensured raw JSON was not passed directly into the LLM prompt |
| Guardrails | ChatGPT / Codex | Brainstorm refusal triggers and adversarial examples | Narrowed the refusal logic to avoid blocking legitimate fitness questions |
| Evaluation | ChatGPT / Codex | Draft test set, metric functions, and LLM-as-judge rubric | Added rule-based checks for source references, numeric evidence, and data isolation |
| Documentation | ChatGPT / Codex | Draft README, AI workflow notes, and evaluation report | Rewrote sections to reflect actual implementation tradeoffs and failures |

---

## 3. Prompting Strategy

I used a staged prompting strategy instead of asking AI to generate the entire project in one prompt.

### 3.1 Initial planning prompts

At the beginning, I gave the assignment requirements and asked for:

- a step-by-step implementation plan,
- a time estimate,
- recommended architecture,
- required deliverables,
- and risks that should not be missed.

This helped identify that the assignment is not only about coding. It also evaluates evaluation rigor, guardrail thinking, production readiness, and AI-assisted workflow evidence.

### 3.2 Smaller implementation prompts

For coding, I split work into smaller prompts:

1. Create project structure and dependencies.
2. Implement configuration loading.
3. Implement RAG ingestion.
4. Implement RAG answer generation.
5. Implement workout preprocessing.
6. Implement coach agent tool-calling.
7. Implement evaluation metrics.
8. Add tests and documentation.

This reduced the chance of AI generating a large, hard-to-review codebase.

### 3.3 Review prompts

After generating code, I used review-style prompts such as:

```text
Review this module for assignment compliance, privacy leakage, hidden state, overbroad guardrails, missing source citations, and poor error handling.
```

This was useful because many issues in this assignment are not syntax issues. They are product and safety issues.

---

## 4. Examples Where AI Output Was Wrong or Suboptimal

> Note: This section should be updated with the exact Codex outputs observed during implementation. The examples below describe the kinds of corrections made during development and should be replaced or expanded with concrete commits before final submission.

### Example 1 — AI suggested passing raw workout JSON into the LLM

**What the AI suggested**

An early implementation approach generated a prompt that included the user's raw workout history JSON directly inside the LLM prompt.

**Why it was wrong or suboptimal**

The assignment explicitly requires workout data to be parsed and analyzed before being passed to the LLM. Passing raw JSON would increase token usage, reduce reliability, and make it harder to guarantee data-backed responses.

**Correction**

I implemented a deterministic preprocessing layer before the LLM call. It computes:

- exercise frequency,
- total sets,
- total volume,
- estimated 1RM where applicable,
- push/pull and muscle-group balance,
- recent gaps,
- date ranges,
- and insufficient-data flags.

Only this compact analysis summary is passed to the LLM.

---

### Example 2 — AI guardrails were initially too broad

**What the AI suggested**

The initial guardrail logic treated many pain-related queries as full refusals, including normal fitness questions such as:

```text
My shoulders feel tight after bench press. How should I adjust my warm-up?
```

**Why it was wrong or suboptimal**

This would block legitimate coaching and general training education. The system should refuse diagnosis, treatment, and injury rehabilitation without professional assessment, but it should still allow general safety-oriented fitness guidance.

**Correction**

I narrowed the refusal logic:

- Refuse: diagnosis, medical treatment, injury rehab plans, eating disorder-risk requests, extreme weight loss, and requests to train through serious symptoms.
- Allow with caution: general warm-up, technique, load management, deloading, and advice to consult a professional when pain is persistent or severe.

---

## 5. Example Where I Rejected an AI Suggestion Entirely

> Replace this with the exact rejected suggestion from Codex once implementation is complete.

### Rejected suggestion — Using a heavy agent framework

**What the AI suggested**

The AI suggested using a full agent framework such as LangGraph or CrewAI for the coach-assist agent.

**Why I rejected it**

The assignment explicitly says a full agentic framework is not required and that clean function/tool-calling via the LLM API is sufficient. For a 6–8 hour take-home exercise, adding a full framework would increase complexity without improving the core evaluation signal.

**What I did instead**

I implemented a small tool-calling loop using the OpenAI API. The agent receives the coach question, decides whether to call `rag_search`, `analyze_history`, or both, then synthesizes a final response with citations and data references.

This keeps the design easy to inspect, test, and extend.

---

## 6. Guardrails Reflection

AI tools were helpful for brainstorming possible unsafe categories, but they needed correction. The first version of the refusal logic was too keyword-driven and risked blocking normal fitness questions. For example, any mention of "pain" or "tightness" could trigger refusal, even when the user only wanted general training advice.

I adjusted the guardrail strategy to focus on intent rather than keywords alone.

### Refusal triggers

The system refuses or redirects when the user asks for:

- medical diagnosis,
- injury rehabilitation without professional assessment,
- treatment plans for pain or medical conditions,
- eating disorder-risk behavior,
- extreme weight-loss instructions,
- or advice to ignore serious symptoms.

### Allowed with caution

The system allows general fitness guidance when the request is about:

- technique,
- warm-up,
- programming,
- progressive overload,
- recovery basics,
- nutrition basics,
- and general load management.

When relevant, the answer includes a safety note recommending a qualified professional for persistent pain, injury, or medical concerns.

---

## 7. How AI Changed the Development Process

AI accelerated the first draft of the system architecture and boilerplate code. The biggest value was not raw code generation, but rapid iteration:

- turning assignment requirements into a checklist,
- identifying missing edge cases,
- generating initial tests,
- reviewing for privacy and safety risks,
- and improving documentation quality.

However, AI output still required strong human review. The most important decisions were manual:

- keeping the architecture small,
- avoiding unnecessary frameworks,
- enforcing data isolation,
- designing refusal boundaries,
- and writing honest failure analysis.

---

## 8. Commit History Approach

I used iterative commits rather than one large final commit. The intended commit sequence is:

```text
1. Initialize FastAPI project structure
2. Add OpenAI configuration and environment template
3. Add markdown ingestion and vector store
4. Implement grounded RAG endpoint
5. Add guardrails and refusal strategy
6. Add workout preprocessing and analysis endpoint
7. Add user data isolation tests
8. Implement coach-assist tool-calling agent
9. Add evaluation test set and metrics
10. Document architecture, evaluation, and AI workflow
11. Add Docker setup and final cleanup
```

Each commit is intended to describe both what changed and why it was changed.

---

## 9. Final Reflection

The main lesson from using AI on this project is that AI is useful for speed, but the senior engineering value comes from judgment:

- choosing simple architecture over unnecessary abstractions,
- validating AI-generated code against requirements,
- correcting safety boundaries,
- testing data isolation,
- and being honest about failure modes.

For this assignment, AI helped produce a faster first draft, but human review determined what was safe, correct, and production-relevant.
