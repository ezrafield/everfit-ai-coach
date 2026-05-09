## Usage Metering Layer

I would add usage metering as a middleware/service layer around every AI endpoint: `/rag/ask`, `/workout/analyze`, and `/agent/coach`. Each request would create a usage event with `coach_id`, `client_id`, endpoint, model, input tokens, output tokens, embedding tokens, tool calls, latency, success/failure status, and estimated cost. 
For agent calls, each internal tool/model call should be metered separately, then linked under one parent request ID.
Limits should be enforced before expensive execution starts. The API should check the coach workspace’s quota, remaining budget, and per-request maximum token allowance before calling the LLM or embedding model. For long agent sessions, the system should reserve an estimated token budget and reconcile actual usage after completion.
If a coach hits their limit mid-session, the agent should stop before the next paid model call, return a clear quota message, preserve partial results, and suggest upgrading, waiting for quota reset, or retrying with a smaller request.
In my evaluation run, 3 evaluation runs used about 61,143 OpenAI API tokens, so token-level metering is necessary for predictable billing.