# Everfit AI Workout Coach

An AI Workout Coach API for the Everfit AI Engineer take-home assignment.

The system answers fitness knowledge questions using RAG, analyzes workout history with deterministic preprocessing before LLM generation, assists coaches with multi-step questions through a tool-calling agent, and applies health-adjacent guardrails for medical and unsafe nutrition boundaries.

---

## 1. Features

### Feature 1 — Fitness Knowledge RAG

- Ingests markdown knowledge base files from `data/kb`
- Chunks documents with source metadata
- Stores embeddings in local ChromaDB
- Answers fitness questions through `POST /rag/ask`
- Returns source references for retrieved chunks
- Handles out-of-scope questions gracefully
- Refuses medical diagnosis, injury rehab prescription, and unsafe eating-disorder-risk requests

### Feature 2 — Workout History Analysis

- Loads sample workout data from `data/workout-history.json`
- Supports multi-user workout histories
- Analyzes only the requested `user_id`
- Computes deterministic evidence before calling the LLM:
  - total sets
  - total reps
  - volume
  - estimated 1RM
  - exercise trends
  - push/pull balance
  - chest/back/leg balance
  - neglected muscle groups
  - deload-like volume drops
  - mixed-unit normalization
- Sends only compact evidence summaries to the LLM, not raw workout JSON
- Includes tests for user data isolation

### Feature 3 — Coach Assist Agent

- Provides a simple OpenAI tool-calling agent
- Tools:
  - `rag_search(query)`
  - `analyze_history(user_id, question)`
- Lets the model decide which tool to call and in what order
- Produces a single coach-facing answer
- Includes tool trace for debugging and evaluation
- Prevents the model from switching to a different user ID during tool execution

### Feature 4 — Evaluation Pipeline

- Includes 15 test cases:
  - 5 RAG cases
  - 5 workout analysis cases
  - 3 agent cases
  - 2 adversarial guardrail cases
- Includes rule-based metrics
- Includes optional LLM-as-judge metric
- Generates `EVALUATION.md`

---

## 2. Architecture

```text
User / Coach
    |
    v
FastAPI
    |
    +-- /rag/ask
    |      |
    |      +-- Guardrails
    |      +-- Query embedding
    |      +-- Chroma retrieval
    |      +-- LLM grounded answer
    |
    +-- /workout/analyze
    |      |
    |      +-- Load workout-history.json by user_id
    |      +-- Deterministic preprocessing
    |      +-- Data isolation boundary
    |      +-- LLM insight generation
    |
    +-- /agent/coach
           |
           +-- OpenAI tool calling
           +-- Tool: rag_search
           +-- Tool: analyze_history
           +-- Final coach-facing synthesi
```

## 3. Usage Metering Layer

I would add usage metering as a middleware/service layer around every AI endpoint: `/rag/ask`, `/workout/analyze`, and `/agent/coach`. Each request would create a usage event with `coach_id`, `client_id`, endpoint, model, input tokens, output tokens, embedding tokens, tool calls, latency, success/failure status, and estimated cost. For agent calls, each internal tool/model call should be metered separately, then linked under one parent request ID.

Limits should be enforced before expensive execution starts. The API should check the coach workspace’s quota, remaining budget, and per-request maximum token allowance before calling the LLM or embedding model. For long agent sessions, the system should reserve an estimated token budget and reconcile actual usage after completion.

If a coach hits their limit mid-session, the agent should stop before the next paid model call, return a clear quota message, preserve partial results, and suggest upgrading, waiting for quota reset, or retrying with a smaller request.

In my evaluation run, 3 evaluation runs used about 61,143 OpenAI API tokens (about 0.17$), so token-level metering is necessary for predictable billing.