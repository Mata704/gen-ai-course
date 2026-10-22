"""Simulated ticket system (Jira-like) exposed as an MCP server."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from meridian.mcp_servers._base import ServerBuilder, settings_for
from meridian.tools import MeridianTools

DEFAULTS = {
    "version": "2.7.1",
    "publisher": "it-service-management",
    "instructions": "Meridian service desk. Projects: MRX (operations incidents and tasks), MEM (member support).",
    "scopes": ["tickets:read", "tickets:create", "tickets:comment", "tickets:link"],
}

PROJECTS = {
    "MRX": {"key": "MRX", "name": "Meridian Operations", "lead": "ops-lead", "issue_types": ["Incident", "Task", "Change", "Problem"]},
    "MEM": {"key": "MEM", "name": "Member Support", "lead": "member-support-lead", "issue_types": ["Complaint", "Question", "Access request"]},
}
USERS = ["rita.alves (on-call engineer)", "joao.matos (incident manager)", "member-support", "db-team", "network-team", "agent-first-line"]
COMPONENTS = ["order-gateway", "matching-engine", "market-data", "settlement", "reference-db"]
TRANSITIONS = ["Open", "In Progress", "Waiting", "Resolved", "Closed"]


def build(tools: MeridianTools, auth: Any = None) -> FastMCP:
    settings = settings_for(tools, "tickets", DEFAULTS)
    builder = ServerBuilder(tools, settings, auth)
    sim = tools.sim
    store = sim.tickets

    def search_issues(
        text: str | None = None,
        project: str | None = None,
        status: str | None = None,
        component: str | None = None,
        issue_type: str | None = None,
        max_results: int = 20,
    ) -> dict[str, Any]:
        found = store.search(text=text, status=status, component=component, project=project, issue_type=issue_type)
        return {"total": len(found), "max_results": max_results, "issues": [ticket.public(with_comments=False) for ticket in found[:max_results]]}

    def get_issue(key: str) -> dict[str, Any]:
        return store.get(key).public()

    def create_issue(project: str, issue_type: str, summary: str, description: str = "", component: str | None = None, priority: str = "Medium") -> dict[str, Any]:
        if project not in PROJECTS:
            raise KeyError(f"Unknown project: {project}")
        ticket = store.create(
            {"project": project, "issue_type": issue_type, "summary": summary, "description": description, "component": component, "priority": priority},
            tools.actor,
            sim.state.tick,
            sim.clock,
        )
        return {"key": ticket.key, "status": ticket.status, "created": ticket.created_at}

    def add_comment(key: str, body: str) -> dict[str, Any]:
        return {"key": key, "comment": store.comment(key, body, tools.actor, sim.state.tick, sim.clock)}

    def transition_issue(key: str, status: str) -> dict[str, Any]:
        ticket = store.transition(key, status, tools.actor)
        return {"key": ticket.key, "status": ticket.status}

    def link_issues(key: str, other_key: str, link_type: str = "relates to") -> dict[str, Any]:
        ticket = store.link(key, other_key, link_type, tools.actor)
        return {"key": ticket.key, "links": ticket.links}

    def assign_issue(key: str, assignee: str) -> dict[str, Any]:
        store.get(key)
        return {"key": key, "assignee": assignee}

    def add_watcher(key: str, user: str) -> dict[str, Any]:
        store.get(key)
        return {"key": key, "watcher": user}

    def list_projects() -> dict[str, Any]:
        return {"projects": [{"key": project["key"], "name": project["name"]} for project in PROJECTS.values()]}

    def get_project(key: str) -> dict[str, Any]:
        if key not in PROJECTS:
            raise KeyError(f"Unknown project: {key}")
        return PROJECTS[key]

    def list_transitions(key: str) -> dict[str, Any]:
        ticket = store.get(key)
        return {"key": key, "current": ticket.status, "transitions": [status for status in TRANSITIONS if status != ticket.status]}

    def list_users(query: str | None = None) -> dict[str, Any]:
        return {"users": [user for user in USERS if not query or query.lower() in user.lower()]}

    def list_components(project: str) -> dict[str, Any]:
        return {"project": project, "components": COMPONENTS}

    def get_issue_changelog(key: str) -> dict[str, Any]:
        ticket = store.get(key)
        entries = [{"created": ticket.created_at, "author": ticket.reporter, "change": "created"}]
        entries += [{"created": comment["created"], "author": comment["author"], "change": "comment added"} for comment in ticket.comments]
        return {"key": key, "changelog": entries}

    builder.add(
        search_issues,
        "Search issues across projects. Filters are combined with AND; `text` matches any word in the key, summary, "
        "description, component or labels. Returns issue summaries without comments; call get_issue for the full issue. "
        "Typical use: check whether an incident or complaint about the same problem is already open before creating a new one.",
        scope="tickets:read",
    )
    builder.add(get_issue, "Get one issue by key (e.g. MRX-2210), with description, comments and links.", scope="tickets:read")
    builder.add(
        create_issue,
        "Create a new issue. project: MRX (operations) or MEM (member support). issue_type: Incident, Task, Change, "
        "Problem, Complaint, Question. Returns the new key. Creating an issue notifies the project's on-call rota.",
        scope="tickets:create",
    )
    builder.add(add_comment, "Add a comment to an issue. Comments are visible to everyone who can see the issue, including members for MEM issues.", scope="tickets:comment")
    builder.add(transition_issue, "Move an issue to another status: Open, In Progress, Waiting, Resolved or Closed.", scope="tickets:transition")
    builder.add(
        link_issues,
        "Link two issues. link_type: 'relates to', 'duplicates', 'is caused by' or 'blocks'. Links are added to both issues.",
        scope="tickets:link",
    )
    builder.add(assign_issue, "Assign an issue to a user.", scope="tickets:assign")
    builder.add(add_watcher, "Add a watcher to an issue; watchers receive every update by email.", scope="tickets:comment")
    builder.add(list_projects, "List the projects visible to the caller.", scope="tickets:read")
    builder.add(get_project, "Get a project with its lead and issue types.", scope="tickets:read")
    builder.add(list_transitions, "List the statuses an issue can move to from its current status.", scope="tickets:read")
    builder.add(list_users, "Search users by name or role.", scope="tickets:read")
    builder.add(list_components, "List the components of a project.", scope="tickets:read")
    builder.add(get_issue_changelog, "Get the history of an issue: creation and comments, with author and time.", scope="tickets:read")
    return builder.server
