"""Stage 1 — Your first agent.

The whole loop in one file: create an agent, create an environment, open a
session, send one message, stream the reply.

Run it:
    python stage1_hello.py
"""

from anthropic import Anthropic

client = Anthropic()  # reads ANTHROPIC_API_KEY from the environment


def main() -> None:
    # 1. Agent = a blueprint (model + instructions)
    agent = client.beta.agents.create(
        name="hello-agent",
        model="claude-opus-4-8",
        system="You are a friendly assistant. Keep answers short.",
    )

    # 2. Environment = the sandbox template
    environment = client.beta.environments.create(
        name="learning-env",
        config={"type": "cloud", "networking": {"type": "unrestricted"}},
    )

    # 3. Session = agent + environment, running
    session = client.beta.sessions.create(
        agent=agent.id,
        environment_id=environment.id,
        title="Hello session",
    )
    print("Session:", session.id)

    # 4. Stream events while sending a message
    with client.beta.sessions.events.stream(session.id) as stream:
        client.beta.sessions.events.send(
            session.id,
            events=[{
                "type": "user.message",
                "content": [{"type": "text", "text": "Say hi and tell me one fun fact."}],
            }],
        )
        for event in stream:
            if event.type == "agent.message":
                for block in event.content:
                    print(block.text, end="")
            elif event.type == "session.status_idle":
                print("\n[done]")
                break


if __name__ == "__main__":
    main()
