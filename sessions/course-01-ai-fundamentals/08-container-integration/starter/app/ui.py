"""Prepared Streamlit UI that talks to the Copilot API over HTTP."""

from __future__ import annotations

import os
import uuid

import httpx
import streamlit as st


API_URL = os.getenv("COPILOT_API_URL", "http://127.0.0.1:8000").rstrip("/")


def initialise_state() -> None:
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())
    if "messages" not in st.session_state:
        st.session_state.messages = []


def reset_conversation() -> None:
    try:
        httpx.post(
            f"{API_URL}/sessions/reset",
            json={"session_id": st.session_state.session_id},
            timeout=10.0,
        ).raise_for_status()
    except httpx.HTTPError as exc:
        st.error(f"Could not reset the API session: {exc}")
        return
    st.session_state.session_id = str(uuid.uuid4())
    st.session_state.messages = []


def ask_api(question: str) -> dict:
    response = httpx.post(
        f"{API_URL}/chat",
        json={"session_id": st.session_state.session_id, "question": question},
        timeout=60.0,
    )
    response.raise_for_status()
    return response.json()


def main() -> None:
    st.set_page_config(page_title="Apollo Mission Copilot", page_icon="🚀")
    initialise_state()

    with st.sidebar:
        st.caption(f"API: {API_URL}")
        st.caption(f"Session ID: {st.session_state.session_id}")
        if st.button("Check server history"):
            try:
                response = httpx.get(
                    f"{API_URL}/session-state/{st.session_state.session_id}", timeout=60.0
                )
                response.raise_for_status()
                st.json(response.json())
            except (httpx.HTTPError, ValueError) as exc:
                st.error(f"Could not inspect API state: {exc}")
        st.button("Reset conversation", on_click=reset_conversation)

    st.title("Apollo Mission Copilot")
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    question = st.chat_input("Ask about an Apollo mission")
    if not question:
        return

    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    try:
        result = ask_api(question)
        answer = result["answer"]
        trace = result.get("trace", [])
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        st.error(f"The API request failed: {exc}")
        return

    st.session_state.messages.append({"role": "assistant", "content": answer})
    with st.chat_message("assistant"):
        st.markdown(answer)
        if trace:
            st.caption(f"Trace: {trace}")
        st.caption(
            f"API runtime: {result.get('runtime_id')} | "
            f"History before this question: {result.get('history_messages_before')} messages"
        )


if __name__ == "__main__":
    main()
