# Conversational RAG Copilot

- **Context:** A useful knowledge assistant needs conversation, grounded answers, controlled actions, and a reusable backend.
- **Goal:** Deliver a small, controlled RAG Agent that is exposed through an API and runs locally in containers.
- **Session 6:** Add recent conversation state, resolve follow-ups, keep grounded sources, define one read-only tool, and implement a bounded loop that chooses between history, retrieval, a tool, or clarification.
- **Session 7:** Make tool execution robust, add explicit stop conditions and a high-level trace, expose `/health`, `/chat`, `/search`, and `/sessions/reset` through FastAPI, and connect Streamlit through HTTP.
- **Session 8:** Containerize the UI and API, pass secrets at runtime, add a container health check and an end-to-end smoke test, and document architecture, execution, and limitations.
- **Scope boundary:** No PydanticAI, MCP, multi-agent orchestration, autonomous planning, or long-term memory. Cloud deployment and a deep benchmark are optional extensions.
