from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.core.config import settings
from app.rag.retriever import ask_rag
from app.rag.schemas import RagAskRequest, RagAskResponse

from app.workout.analyzer import analyze_workout_history
from app.workout.schemas import WorkoutAnalyzeRequest, WorkoutAnalysisResponse

from app.agent.coach_agent import CoachAgentRequest, CoachAgentResponse, run_coach_agent

app = FastAPI(
    title="Everfit AI Workout Coach",
    description="AI Workout Coach API with RAG, workout history analysis, coach agent, and evaluation.",
    version="0.1.0",
)


@app.get("/")
def root():
    return {
        "service": "Everfit AI Workout Coach",
        "status": "running",
        "version": "0.1.0",
        "ui": "/ui",
        "docs": "/docs",
    }


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "app_env": settings.APP_ENV,
        "debug_mode": settings.DEBUG_MODE,
    }


@app.get("/ready")
def readiness_check():
    missing = []

    if not settings.OPENAI_API_KEY:
        missing.append("OPENAI_API_KEY")

    if not settings.OPENAI_MODEL:
        missing.append("OPENAI_MODEL")

    if not settings.OPENAI_EMBEDDING_MODEL:
        missing.append("OPENAI_EMBEDDING_MODEL")

    if missing:
        return {
            "status": "not_ready",
            "missing_env": missing,
        }

    return {
        "status": "ready",
        "model": settings.OPENAI_MODEL,
        "embedding_model": settings.OPENAI_EMBEDDING_MODEL,
        "chroma_dir": settings.CHROMA_DIR,
        "collection": settings.CHROMA_COLLECTION_NAME,
    }


@app.post("/rag/ask", response_model=RagAskResponse)
def rag_ask(request: RagAskRequest):
    return ask_rag(
        question=request.question,
        top_k=request.top_k,
    )

@app.post("/workout/analyze", response_model=WorkoutAnalysisResponse)
def workout_analyze(request: WorkoutAnalyzeRequest):
    return analyze_workout_history(
        user_id=request.user_id,
        question=request.question,
        history=request.history,
    )

@app.post("/agent/coach", response_model=CoachAgentResponse)
def coach_agent(request: CoachAgentRequest):
    return run_coach_agent(request)

@app.get("/ui", response_class=HTMLResponse)
def test_ui():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Everfit AI Coach Test UI</title>
  <style>
    body {
      font-family: Arial, sans-serif;
      background: #f7f8fa;
      color: #1f2937;
      margin: 0;
      padding: 32px;
    }

    .container {
      max-width: 1100px;
      margin: 0 auto;
    }

    h1 {
      margin-bottom: 4px;
    }

    .subtitle {
      color: #6b7280;
      margin-bottom: 24px;
    }

    .card {
      background: white;
      border: 1px solid #e5e7eb;
      border-radius: 12px;
      padding: 20px;
      margin-bottom: 20px;
      box-shadow: 0 1px 2px rgba(0,0,0,0.04);
    }

    label {
      display: block;
      font-weight: 600;
      margin-bottom: 8px;
    }

    input, textarea, select {
      width: 100%;
      box-sizing: border-box;
      padding: 10px;
      border: 1px solid #d1d5db;
      border-radius: 8px;
      font-size: 14px;
      margin-bottom: 12px;
      font-family: Consolas, monospace;
    }

    textarea {
      min-height: 160px;
      resize: vertical;
    }

    button {
      background: #111827;
      color: white;
      border: none;
      border-radius: 8px;
      padding: 10px 14px;
      cursor: pointer;
      font-weight: 600;
      margin-right: 8px;
      margin-bottom: 8px;
    }

    button.secondary {
      background: #4b5563;
    }

    button.warning {
      background: #b45309;
    }

    button.danger {
      background: #b91c1c;
    }

    button:hover {
      opacity: 0.9;
    }

    pre {
      background: #0f172a;
      color: #e5e7eb;
      padding: 16px;
      border-radius: 10px;
      overflow-x: auto;
      min-height: 160px;
      white-space: pre-wrap;
    }

    .row {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 20px;
    }

    .small {
      font-size: 13px;
      color: #6b7280;
    }

    .badge {
      display: inline-block;
      background: #eef2ff;
      color: #3730a3;
      padding: 4px 8px;
      border-radius: 999px;
      font-size: 12px;
      margin-left: 8px;
    }

    @media (max-width: 900px) {
      .row {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>

<body>
  <div class="container">
    <h1>Everfit AI Coach Test UI <span class="badge">Local Dev</span></h1>
    <div class="subtitle">
      Use this page to quickly test health, readiness, RAG, guardrails, and future endpoints.
    </div>

    <div class="card">
      <h2>Quick Checks</h2>
      <button onclick="callGet('/health')">GET /health</button>
      <button onclick="callGet('/ready')">GET /ready</button>
      <button onclick="window.open('/docs', '_blank')" class="secondary">Open Swagger /docs</button>
    </div>

    <div class="row">
      <div class="card">
        <h2>RAG Test</h2>

        <label>Question</label>
        <textarea id="ragQuestion">What is progressive overload and how should a beginner apply it?</textarea>

        <label>Top K</label>
        <input id="ragTopK" type="number" value="5" min="1" max="10" />

        <button onclick="askRag()">Ask RAG</button>
        <button class="secondary" onclick="loadRagSample()">Sample: Progressive Overload</button>
        <button class="warning" onclick="loadOutOfScopeSample()">Sample: Out of Scope</button>
        <button class="danger" onclick="loadMedicalRiskSample()">Sample: Medical Refusal</button>

        <p class="small">
          This calls <code>POST /rag/ask</code>. Make sure you already ran RAG ingestion first.
        </p>
      </div>

      <div class="card">
        <h2>Generic API Tester</h2>

        <label>Endpoint</label>
        <input id="customEndpoint" value="/rag/ask" />

        <label>JSON Body</label>
        <textarea id="customBody">{
  "question": "What is progressive overload?",
  "top_k": 5
}</textarea>

        <button onclick="callCustomPost()">POST</button>
        <button class="secondary" onclick="loadWorkoutPlaceholder()">Load Workout Placeholder</button>
        <button class="secondary" onclick="loadAgentPlaceholder()">Load Agent Placeholder</button>

        <p class="small">
          This generic tester will be useful after we add <code>/workout/analyze</code> and <code>/agent/coach</code>.
        </p>
      </div>
    </div>

    <div class="card">
      <h2>Response</h2>
      <pre id="responseBox">No request yet.</pre>
    </div>
  </div>

<script>
  function showResponse(data, status = null) {
    const box = document.getElementById("responseBox");
    const prefix = status ? `HTTP ${status}\\n\\n` : "";
    box.textContent = prefix + JSON.stringify(data, null, 2);
  }

  function showError(error) {
    const box = document.getElementById("responseBox");
    box.textContent = "ERROR:\\n" + error;
  }

  async function callGet(endpoint) {
    try {
      const res = await fetch(endpoint);
      const data = await res.json();
      showResponse(data, res.status);
    } catch (err) {
      showError(err.toString());
    }
  }

  async function askRag() {
    const question = document.getElementById("ragQuestion").value;
    const topK = Number(document.getElementById("ragTopK").value || 5);

    try {
      const res = await fetch("/rag/ask", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          question: question,
          top_k: topK
        })
      });

      const data = await res.json();
      showResponse(data, res.status);
    } catch (err) {
      showError(err.toString());
    }
  }

  async function callCustomPost() {
    const endpoint = document.getElementById("customEndpoint").value;
    const rawBody = document.getElementById("customBody").value;

    let body;

    try {
      body = JSON.parse(rawBody);
    } catch (err) {
      showError("Invalid JSON body:\\n" + err.toString());
      return;
    }

    try {
      const res = await fetch(endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify(body)
      });

      const data = await res.json();
      showResponse(data, res.status);
    } catch (err) {
      showError(err.toString());
    }
  }

  function loadRagSample() {
    document.getElementById("ragQuestion").value =
      "What is progressive overload and how should a beginner apply it?";
  }

  function loadOutOfScopeSample() {
    document.getElementById("ragQuestion").value =
      "What is the weather today?";
  }

  function loadMedicalRiskSample() {
    document.getElementById("ragQuestion").value =
      "I have sharp knee pain. Diagnose it and give me a rehab plan.";
  }

  function loadWorkoutPlaceholder() {
    document.getElementById("customEndpoint").value = "/workout/analyze";
    document.getElementById("customBody").value = JSON.stringify({
      user_id: "user_a",
      question: "What is my bench press trend over the last month?"
    }, null, 2);
  }
  
  function loadAgentPlaceholder() {
    document.getElementById("customEndpoint").value = "/agent/coach";
    document.getElementById("customBody").value = JSON.stringify({
      coach_id: "coach_1",
      user_id: "user_a",
      question: "Based on Alex's recent workout history, is he ready to increase bench press weight? What does proper progressive overload look like for his current level?"
    }, null, 2);
  }
</script>
</body>
</html>
    """