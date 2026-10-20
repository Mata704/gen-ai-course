"""Print preparation and tool events without changing the Session 7 agent loop."""

import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "07-agent-api"))

from agent_service import (  # noqa: E402
    AgentService, OpenAI, TIMELINES_FILE, create_embeddings,
    load_documents, require_api_key, whole_document_chunks,
)


class ObservedAgentService(AgentService):
    def __init__(self) -> None:
        started = time.perf_counter()
        self.service_id = uuid.uuid4().hex[:8]
        require_api_key()
        self.client = OpenAI()
        print(f"[PREPARE {self.service_id}] Load documents", flush=True)
        self.chunks = whole_document_chunks(load_documents())
        print(
            f"[PREPARE {self.service_id}] Embed {len(self.chunks)} documents: one batch request",
            flush=True,
        )
        self.chunk_embeddings = create_embeddings(self.client, [c.text for c in self.chunks])
        self.timelines = json.loads(TIMELINES_FILE.read_text(encoding="utf-8"))
        self.sessions = {}
        self.preparation_seconds = time.perf_counter() - started
        print(f"[READY {self.service_id}] {self.preparation_seconds:.2f}s", flush=True)

    def search(self, question: str, top_k: int = 2) -> list:
        print(f"[REQUEST {self.service_id}] Embed the search question", flush=True)
        return super().search(question, top_k)

    def execute_tool_call(self, call):
        print(f"[TOOL {self.service_id}] {call.name}", flush=True)
        result = super().execute_tool_call(call)
        print(f"[TOOL {self.service_id}] ok={result.get('ok')}", flush=True)
        return result

    def chat(self, session_id: str, question: str, max_steps: int = 4):
        print(
            f"[CHAT {self.service_id}] history_messages={len(self.sessions.get(session_id, []))}",
            flush=True,
        )
        started = time.perf_counter()
        reply = super().chat(session_id, question, max_steps)
        print(f"[CHAT {self.service_id}] answer ready in {time.perf_counter() - started:.2f}s", flush=True)
        return reply
