"""Exercise 1 — Ask another team's agent to act, through A2A.

The confirmations of batch 10:12 reached settlement late and must be resent. Your team has no tool for that:
settlement's systems belong to the settlement team. Their agent, the "Settlement Agent", speaks A2A (Agent2Agent).
The on-call already approved the resend (a2a.request has the approval reference).

resend(a2a) talks to the Settlement Agent and returns the final Task.

The client below works, but it is naive: it sends one message, and because settlement is slow, it sends it again.
Run it and look at the result. Then write a client that holds up.

What a good client must do:
- read the Agent Card first: what the skill needs, and how to authenticate;
- send the request once, with what the skill asks for;
- answer the agent inside the same task if it needs more from you (TASK_STATE_INPUT_REQUIRED);
- wait for a long task by asking for its state (GetTask), never by sending the request again;
- check the result before returning it.

What you can use (lab/a2a.py has the details): a2a.card(), await a2a.send_message(message, token),
await a2a.get_task(task_id, token), a2a.token, a2a.request, await a2a.wait(seconds), a2a.note(text).
A message (A2A v1.0): {"role": "ROLE_USER", "parts": [{"text": "..."}, {"data": {...}}], "taskId"?: "...", "contextId"?: "..."}

Hints:
- Read every field of the skill's description in the card. One sentence in it is the whole exercise.
- TASK_STATE_WORKING is not TASK_STATE_FAILED. What is the difference between sending again and asking again?
- A task that asks you a question is still the same task.
"""

from __future__ import annotations


async def resend(a2a) -> dict:
    card = a2a.card()
    skill = next((item for item in card.get("skills", []) if item.get("id") == "resend-confirmations"), None)
    if skill is None:
        raise RuntimeError("The Settlement Agent card does not advertise resend-confirmations.")

    requirements = card.get("securityRequirements", [])
    if not any("bearer" in requirement.get("schemes", {}) for requirement in requirements):
        raise RuntimeError("The Settlement Agent card does not require the supported bearer authentication.")

    token = a2a.token
    request = a2a.request
    batch = request["batch"]
    incident = request["incident"]
    approval_ref = request["approval_ref"]
    idempotency_key = f"resend-confirmations:{incident}:{batch}"
    text = f"Please resend {batch} for incident {incident}. Approval: {approval_ref}."
    parts = [
        {"text": text},
        {"data": {
            "batch": batch,
            "incident": incident,
            "approval_ref": approval_ref,
            "idempotency_key": idempotency_key,
        }},
    ]

    task = await a2a.send_message({"role": "ROLE_USER", "parts": parts}, token)
    replied_to_input = False
    while True:
        if "error" in task:
            raise RuntimeError(f"Settlement Agent request failed: {task['error']}")

        status = task.get("status", {})
        state = status.get("state")
        task_id = task.get("id")

        if state == "TASK_STATE_COMPLETED":
            receipt = next(
                (artifact for artifact in task.get("artifacts", []) if artifact.get("name") == "resend-receipt"),
                None,
            )
            receipt_data = next(
                (
                    part["data"]
                    for part in (receipt or {}).get("parts", [])
                    if isinstance(part.get("data"), dict)
                ),
                {},
            )
            if receipt_data.get("batch") != batch or receipt_data.get("outcome") not in {"completed", "already_done"}:
                raise RuntimeError("Settlement Agent completed the task without a valid resend receipt.")
            a2a.note(f"Verified the resend receipt for {batch}.")
            return task

        if state == "TASK_STATE_INPUT_REQUIRED":
            if replied_to_input:
                raise RuntimeError("Settlement Agent still requires input after the request was answered.")
            if not task_id:
                raise RuntimeError("Settlement Agent requested input without providing a task id.")
            replied_to_input = True
            task = await a2a.send_message(
                {
                    "role": "ROLE_USER",
                    "parts": parts,
                    "taskId": task_id,
                    "contextId": task.get("contextId"),
                },
                token,
            )
            continue

        if state in {"TASK_STATE_SUBMITTED", "TASK_STATE_WORKING"}:
            if not task_id:
                raise RuntimeError(f"Settlement Agent returned {state} without providing a task id.")
            await a2a.wait(1)
            task = await a2a.get_task(task_id, token)
            continue

        raise RuntimeError(f"Settlement Agent ended the task in unexpected state {state!r}.")
