"""Stage 2 — Give the agent tools.

A blueprint with no tools can only talk. Add the built-in toolset and the agent
can run bash, read/write files, search the web, and execute code — all inside
the sandbox. The tool type is ``agent_toolset_20260401``.

Run it:
    python stage2_tools.py
"""

from anthropic import Anthropic

client = Anthropic()


def main() -> None:
    agent = client.beta.agents.create(
        name="coding-agent",
        model="claude-opus-4-8",
        system="You are a careful coding assistant. Write clean code.",
        tools=[{"type": "agent_toolset_20260401"}],   # <-- the new part
    )

    environment = client.beta.environments.create(
        name="learning-env-tools",
        config={"type": "cloud", "networking": {"type": "unrestricted"}},
    )

    session = client.beta.sessions.create(
        agent=agent.id, environment_id=environment.id, title="Tools session",
    )

    with client.beta.sessions.events.stream(session.id) as stream:
        client.beta.sessions.events.send(
            session.id,
            events=[{
                "type": "user.message",
                "content": [{
                    "type": "text",
                    "text": "Write a Python script that prints the first 20 "
                            "Fibonacci numbers, save it as fib.py, run it, and "
                            "show me the output.",
                }],
            }],
        )
        for event in stream:
            if event.type == "agent.message":
                for block in event.content:
                    print(block.text, end="")
            elif event.type == "agent.tool_use":
                print(f"\n[tool: {event.name}]")
            elif event.type == "session.status_idle":
                print("\n[done]")
                break


if __name__ == "__main__":
    main()
