"""Stage 3 — The multi-agent crew.

You create two specialist agents and one coordinator that delegates to them.
The coordinator gets the ``agent_toolset`` tool (so it's *able* to delegate)
plus a ``multiagent`` block listing its roster.

            ┌──────────────┐
   you ───▶ │ coordinator  │  (lead — delegates & synthesizes)
            └──────┬───────┘
            ┌──────┴───────┐
            ▼              ▼
     ┌────────────┐  ┌──────────────┐
     │  reviewer  │  │ test-writer  │   (specialists, own context each)
     └─────┬──────┘  └──────┬───────┘
           └──────┬─────────┘
                  ▼
         ┌──────────────────┐
         │  shared sandbox  │   (one filesystem, used by all)
         └──────────────────┘

Run it:
    python stage3_crew.py
"""

from anthropic import Anthropic

from uploader import upload_file

client = Anthropic()


def main() -> None:
    # --- 1. Specialist agents ---------------------------------------------------
    reviewer = client.beta.agents.create(
        name="reviewer",
        model="claude-opus-4-8",
        system=(
            "You are a senior code reviewer. Read the given file and report bugs, "
            "security issues (e.g. plaintext passwords), and missing error handling. "
            "Be concise and specific. Do not modify files."
        ),
        tools=[{"type": "agent_toolset_20260401"}],
    )

    test_writer = client.beta.agents.create(
        name="test-writer",
        model="claude-sonnet-4-6",   # cheaper model — narrower job
        system=(
            "You write thorough pytest unit tests for the given file. "
            "Save tests next to the source as test_<name>.py."
        ),
        tools=[{"type": "agent_toolset_20260401"}],
    )

    # --- 2. Coordinator with a roster ------------------------------------------
    coordinator = client.beta.agents.create(
        name="lead",
        model="claude-opus-4-8",
        system=(
            "You coordinate a code-quality review of sample/auth.py. "
            "Delegate the review to the reviewer agent and the test writing to the "
            "test-writer agent. They share your sandbox filesystem. When both are "
            "done, summarize their findings for the user."
        ),
        tools=[{"type": "agent_toolset_20260401"}],
        multiagent={
            "type": "coordinator",
            "agents": [
                {"type": "agent", "id": reviewer.id},
                {"type": "agent", "id": test_writer.id},
            ],
        },
    )

    # --- 3. One session, pointed at the coordinator ----------------------------
    environment = client.beta.environments.create(
        name="crew-env",
        config={"type": "cloud", "networking": {"type": "limited"}},
    )
    session = client.beta.sessions.create(
        agent=coordinator.id, environment_id=environment.id, title="Code review crew",
    )

    # Stage the file the crew reviews into the (empty) sandbox first. If your SDK
    # lacks the native upload API, uploader falls back to writing it via bash.
    # For a zero-setup alternative, drop this and paste uploader.inline_file(...)
    # into the message text below instead.
    upload_file(client, session.id, "sample/auth.py")

    with client.beta.sessions.events.stream(session.id) as stream:
        client.beta.sessions.events.send(
            session.id,
            events=[{
                "type": "user.message",
                "content": [{
                    "type": "text",
                    "text": "Review sample/auth.py and write unit tests for it.",
                }],
            }],
        )
        for event in stream:
            if event.type == "agent.message":
                for block in event.content:
                    print(block.text, end="")
            elif event.type == "agent.tool_use":
                print(f"\n[lead tool: {event.name}]")
            elif event.type == "session.status_idle":
                print("\n[crew done]")
                break


if __name__ == "__main__":
    main()
