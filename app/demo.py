from __future__ import annotations

from typing import Any

from app.auth import create_user
from app.jobs import enqueue_ingest
from app.spaces import add_member, load_demo_docs

DEMO_PASSWORD = "demo1234"
PACKS = {"HR": "hr", "Engineering": "engineering", "Finance": "finance"}
DEMO_PEOPLE = (
    {
        "email": "maya@northstar.demo",
        "name": "Maya Chen",
        "space": "HR",
        "role": "viewer",
        "tier": "free",
    },
    {
        "email": "jordan@northstar.demo",
        "name": "Jordan Hale",
        "space": "Engineering",
        "role": "editor",
        "tier": "free",
    },
    {
        "email": "priya@northstar.demo",
        "name": "Priya Shah",
        "space": "Finance",
        "role": "viewer",
        "tier": "free",
    },
)


def seed_space_docs(spaces: list[dict[str, Any]]) -> None:
    for space in spaces:
        pack = PACKS.get(space["name"])
        load_demo_docs(space["id"], pack=pack)
        enqueue_ingest(space["id"])


def seed_demo_users(spaces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_name = {s["name"]: s["id"] for s in spaces}
    created: list[dict[str, Any]] = []
    for person in DEMO_PEOPLE:
        try:
            user = create_user(
                person["email"],
                person["name"],
                DEMO_PASSWORD,
                org_role="member",
                tier=person["tier"],
            )
        except Exception:
            continue
        space_id = by_name.get(person["space"])
        if space_id:
            add_member(space_id, user["id"], person["role"])
        created.append(user)
    return created
