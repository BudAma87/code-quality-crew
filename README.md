# Code Quality Crew — A Claude Managed Agents Learning Project

A small, hands-on project for learning **Claude Managed Agents**. You build it in
three stages, each one adding a single new concept, so by the end you understand
the whole picture: a *coordinator* agent that delegates a code review to two
*specialist* agents that work in a shared sandbox.

> **Heads-up:** Claude Managed Agents is in **public beta**. The exact method
> names and flags can still change. When something here doesn't match reality,
> the official docs are the source of truth:
> <https://platform.claude.com/docs/en/managed-agents/overview>

---

## TL;DR — just review my code (the plugin)

If you don't want to read the tutorial and just want the crew to review files in
**your own repo**, this project ships a ready-to-use **Claude Code plugin**.
Install it once, then run `/crew-review <file>` on any source file — the crew
reviews it and drops a generated `test_<name>.py` next to it.

```text
# in Claude Code, from any repo:
/plugin marketplace add budama87/code-quality-crew
/plugin install code-quality-crew@code-quality-crew
/crew-review src/auth.py
```

Full walkthrough below in **[Use it in your own repo (the plugin)](#use-it-in-your-own-repo-the-plugin)**.
The rest of this README is the learning tutorial that the plugin is built on.

---

## What you'll learn

| Stage | You build | New concept |
|-------|-----------|-------------|
| 1 | A single "hello world" agent | agent + environment + session + streaming |
| 2 | The same agent, but with real tools | built-in tools, sandbox file I/O |
| 3 | A coordinator + 2 specialists | multi-agent orchestration |

By the end you'll understand the four core building blocks and how one agent can
delegate work to others.

---

## The mental model

Managed Agents splits an agent into pieces that Anthropic hosts for you. Four
objects matter:

- **Agent** — a *configuration* (model, system prompt, tools, MCP servers,
  skills). It is a blueprint, not a running process. Create it once, reference
  it by ID forever.
- **Environment** — the sandbox template: which packages are pre-installed and
  what network access is allowed.
- **Session** — a running conversation that ties one agent to one environment.
  It is stateful: it keeps the filesystem and conversation history, and survives
  network drops.
- **Event** — a message in or out of a session (`user.message`, `agent.message`,
  `agent.tool_use`, `session.status_idle`, etc.). You send events and stream
  events back.

In stage 3, multiple agents run inside **one** session. Each gets its own
isolated context thread, but they **share the same sandbox, filesystem, and
credentials**. That shared filesystem is how a reviewer agent and a test-writer
agent collaborate on the same code.

---

## Prerequisites

1. An **Anthropic Console account** and an **API key** — get one at
   <https://console.anthropic.com>.
2. **Python 3.10+** (this guide uses Python; a TypeScript SDK exists too).
3. Optionally, the **`ant` CLI** — Anthropic's command-line client, handy for
   poking at agents and sessions without writing code.

### Install

```bash
# Python SDK (make sure it's a recent version with beta agent support)
pip install --upgrade anthropic

# Optional: the ant CLI
#   macOS (Homebrew):
brew install anthropics/tap/ant
#   or via npm:
npm install -g @anthropic-ai/ant
```

### Configure your key

```bash
export ANTHROPIC_API_KEY="your-api-key-here"
```

Verify the CLI if you installed it:

```bash
ant --version
```

> **The beta header.** Every Managed Agents request needs the header
> `anthropic-beta: managed-agents-2026-04-01`. **The SDK sets this
> automatically** — you only add it by hand if you call the raw HTTP API with
> `curl`. A missing/wrong header is the single most common cause of `400`
> errors, so if you hit one early, check this first.

---

## Project structure

```
code-quality-crew/
├── README.md              # this file
├── .env                   # ANTHROPIC_API_KEY (never commit this)
├── .env.example           # template to copy to .env
├── requirements.txt       # anthropic + pytest
├── stage1_hello.py        # single agent
├── stage2_tools.py        # agent that reads/writes files in the sandbox
├── stage3_crew.py         # coordinator + reviewer + test-writer
├── uploader.py            # helpers to get a local file into the sandbox
├── sample/
│   ├── auth.py            # buggy code for the crew to review
│   └── test_auth.py       # example tests for it
├── .claude-plugin/
│   └── marketplace.json   # makes this repo an installable plugin marketplace
└── plugin/                # the Claude Code plugin (see "Use it in your own repo")
    ├── .claude-plugin/plugin.json
    ├── commands/crew-review.md
    ├── scripts/crew_review.py
    └── README.md
```

Create the sample file the crew will review:

```python
# sample/auth.py  — intentionally sloppy, so the crew has something to find
def login(users, name, password):
    for u in users:
        if u["name"] == name and u["password"] == password:
            return u
    # no return if not found -> implicit None, no logging, plaintext passwords
```

---

## Stage 1 — Your first agent

The whole loop in one file: create an agent, create an environment, open a
session, send one message, stream the reply.

```python
# stage1_hello.py
from anthropic import Anthropic

client = Anthropic()  # reads ANTHROPIC_API_KEY from the environment

# 1. Agent = a blueprint (model + instructions)
agent = client.beta.agents.create(
    name="hello-agent",
    model="claude-opus-4-8",
    system_prompt="You are a friendly assistant. Keep answers short.",
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
```

Run it:

```bash
python stage1_hello.py
```

**What happened:** when you sent the message, Managed Agents provisioned a
sandbox, ran the agent loop, streamed events back, and emitted
`session.status_idle` when the agent had nothing more to do.

> **Save the IDs.** `agent.id` and `environment.id` are reusable. In a real
> project you'd create them once (or via the `ant` CLI) and reference them
> everywhere. For learning, recreating them each run is fine.

---

## Stage 2 — Give the agent tools

A blueprint with no tools can only talk. Add the built-in toolset and the agent
can run bash, read/write files, search the web, and execute code — all inside
the sandbox. The tool type is `agent_toolset_20260401`.

```python
# stage2_tools.py
from anthropic import Anthropic

client = Anthropic()

agent = client.beta.agents.create(
    name="coding-agent",
    model="claude-opus-4-8",
    system_prompt="You are a careful coding assistant. Write clean code.",
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
```

Watch the `[tool: ...]` lines — that's the agent actually writing the file with
`write` and running it with `bash`, not just describing what it would do.

> **Tip — start broad, then scope down.** For a first run, leave the full
> toolset on so you can see what the agent chooses. Later you can give each agent
> a narrower set of tools (e.g. read-only for a reviewer).

> **Networking tip.** If your agent only touches its own files, use
> `"networking": {"type": "limited"}` instead of `unrestricted` — safer and
> usually enough. You can also pre-install packages in the environment config
> (e.g. `packages: {pip: [pandas, numpy]}`).

---

## Stage 3 — The multi-agent crew

Now the payoff. You create **two specialist agents** and **one coordinator**
that delegates to them. The coordinator gets the `agent_toolset` tool (so it's
*able* to delegate) plus a `multiagent` block listing its roster.

```
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
```

```python
# stage3_crew.py
from anthropic import Anthropic

client = Anthropic()

# --- 1. Specialist agents ---------------------------------------------------
reviewer = client.beta.agents.create(
    name="reviewer",
    model="claude-opus-4-8",
    system_prompt=(
        "You are a senior code reviewer. Read the given file and report bugs, "
        "security issues (e.g. plaintext passwords), and missing error handling. "
        "Be concise and specific. Do not modify files."
    ),
    tools=[{"type": "agent_toolset_20260401"}],
)

test_writer = client.beta.agents.create(
    name="test-writer",
    model="claude-sonnet-4-6",   # cheaper model — narrower job
    system_prompt=(
        "You write thorough pytest unit tests for the given file. "
        "Save tests next to the source as test_<name>.py."
    ),
    tools=[{"type": "agent_toolset_20260401"}],
)

# --- 2. Coordinator with a roster ------------------------------------------
coordinator = client.beta.agents.create(
    name="lead",
    model="claude-opus-4-8",
    system_prompt=(
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

# NOTE: in a real run you'd upload sample/auth.py into the sandbox first
# (see the docs on uploading files). For learning, you can instead paste the
# code into the prompt and ask the crew to work from that.

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
```

### What to notice

- **You only talk to the coordinator.** It spawns the specialists; you never
  call them directly.
- **The stream you watch is the primary thread** — a *condensed* view. You see
  when each specialist starts and finishes, but not their full internal chatter.
  To inspect a single agent's every step, use the Console (see below).
- **Each agent keeps its own config.** The reviewer can run on Opus with
  read-only intent while the test-writer runs on a cheaper Sonnet model. Tools,
  context, and MCP servers are *not* shared between them — only the filesystem is.
- **Three reasons this pattern exists:** parallelization (fan out independent
  subtasks), specialization (focused prompts/tools per agent), and escalation
  (send the hard parts to a stronger model). Up to **25 concurrent threads** are
  supported.

> **Access note.** Multi-agent orchestration has moved through research preview
> into beta during this period. If `multiagent` isn't recognized for your org,
> check whether it needs enabling in the Console and read the current page:
> <https://platform.claude.com/docs/en/managed-agents/multi-agent>

---

## Use it in your own repo (the plugin)

The tutorial creates the crew from scratch each time. Once you understand it, you
probably just want to point the crew at real files in your project. That's what
the bundled **Claude Code plugin** is for: it wraps the same coordinator +
reviewer + test-writer crew behind a single `/crew-review` command.

```
code-quality-crew/
├── .claude-plugin/marketplace.json   # makes this repo an installable marketplace
└── plugin/
    ├── .claude-plugin/plugin.json
    ├── commands/crew-review.md        # the /crew-review slash command
    ├── scripts/crew_review.py         # wrapper around the Managed Agents crew
    └── README.md
```

### 1. Prerequisites

- **Claude Code** installed.
- **Python 3.10+** with the SDK: `pip install "anthropic>=0.40.0"`.
- An **`ANTHROPIC_API_KEY`** — set as an environment variable, or in a `.env`
  file in the repo you run it from. The plugin loads `.env` for you.

### 2. Install the plugin

From inside Claude Code (works in any repo, once installed):

```
/plugin marketplace add budama87/code-quality-crew
/plugin install code-quality-crew@code-quality-crew
```

`marketplace add` points Claude Code at this GitHub repo; `install` pulls in the
`code-quality-crew` plugin it advertises. You only do this once per machine.

### 3. Review a file

In the repo you want to review, run:

```
/crew-review src/auth.py
```

What happens:

1. The crew (coordinator → reviewer + test-writer) is created **once** and its
   IDs are cached at `~/.code-quality-crew/crew.json`, so later runs are faster.
2. Your file is staged into a fresh sandbox and reviewed.
3. You get a **severity-grouped review** printed back, and a generated
   **`test_<name>.py` is written next to your source file**.

Flags:

| Flag | Effect |
|------|--------|
| `--no-tests` | Print the review only; don't write any test file. |
| `--fresh` | Ignore the cached agents and recreate the crew. |

```
/crew-review src/auth.py --no-tests
```

### 4. Run it without Claude Code (optional)

The wrapper is a normal script, so it also works straight from a terminal — handy
for quick checks or wiring into your own tooling:

```bash
python plugin/scripts/crew_review.py src/auth.py
python plugin/scripts/crew_review.py src/auth.py --no-tests
```

> **Heads-up.** Each `/crew-review` opens a Managed Agents session (3 agents) and
> uses tokens; the session is deleted automatically when the run finishes. See
> **[Cost](#cost-so-you-dont-get-surprised)** below. The first run is slower
> because it creates the agents; subsequent runs reuse the cached crew.

See `plugin/README.md` for the plugin-only quickstart.

---

## The `ant` CLI alternative (optional)

Instead of Python, you can define agents as YAML and create them from the shell —
nice for version-controlling configs in git.

```yaml
# reviewer.agent.yaml
name: reviewer
model: claude-opus-4-8
system: |
  You are a senior code reviewer. Report bugs and security issues. Be concise.
tools:
  - type: agent_toolset_20260401
```

```bash
# Create from the YAML file
ant beta:agents create < reviewer.agent.yaml

# Create an environment
ant beta:environments create \
  --name "crew-env" \
  --config '{type: cloud, networking: {type: limited}}'

# Send a message and stream the reply
ant beta:sessions:events send \
  --session-id "$SESSION_ID" \
  --type user.message --content-type text \
  --content-text "Review sample/auth.py"
ant beta:sessions stream --session-id "$SESSION_ID"
```

---

## Observing and debugging

Open the **Claude Console** to see a full timeline of every session: which agent
did what, in what order, and why, plus the raw payload of each step. This is the
best way to understand what your crew actually did — especially the parts the
condensed primary stream hides.

Common first-run problems:

- **`400` errors right away** → almost always the beta header (raw HTTP only) or
  an outdated SDK. Upgrade the SDK; it sets the header for you.
- **`429` errors** → rate limits. Create endpoints are limited (around 60
  requests/min) and read endpoints higher (around 600/min), with your org tier
  on top. Back off with jitter; don't hammer retries.
- **Agent loops on tools but never finishes** → check the Console traces for a
  step waiting on a response that never came.

---

## Cost (so you don't get surprised)

- **Tokens:** standard Claude API token rates for whatever models your agents use.
- **Runtime:** about **$0.08 per session-hour** of *active* runtime. **Idle time
  is free** — while the agent waits on you or a tool, the clock isn't running.
- **Web search:** roughly **$10 per 1,000 searches** when an agent uses it.

For learning, costs are tiny, but **clean up** when you're done (next section),
and run cost projections before any high-volume use.

---

## Cleanup

Sessions are stateful and stored server-side, so tidy up after experiments:

```python
# Delete a session when you're finished with it
client.beta.sessions.delete(session.id)
```

You can also archive/delete environments via the API or `ant` CLI. Deleting a
session removes its stored state; files you uploaded are deleted separately.

> **Data note.** Because Managed Agents stores session state server-side, it is
> **not currently eligible for Zero Data Retention or HIPAA BAA** coverage. You
> can delete sessions and uploaded files at any time. Don't put regulated or
> highly sensitive data through it while learning.

---

## Where to go next

- Quickstart: <https://platform.claude.com/docs/en/managed-agents/quickstart>
- Multi-agent sessions: <https://platform.claude.com/docs/en/managed-agents/multi-agent>
- Environments: <https://platform.claude.com/docs/en/managed-agents/environments>
- Overview & data retention: <https://platform.claude.com/docs/en/managed-agents/overview>
- Engineering deep-dive ("Decoupling the brain from the hands"):
  <https://www.anthropic.com/engineering/managed-agents>

Ideas to extend the crew once it runs:

1. Add a third specialist (a **security agent**) to the roster and watch the
   coordinator split work three ways.
2. Give the reviewer a read-only toolset and the test-writer a write-enabled one.
3. Have the coordinator run multiple **copies** of the same research agent in
   parallel over different files, then synthesize.
4. Connect an MCP server (e.g. a docs source) to one agent so it can pull
   external context.

Happy building — start at Stage 1, get one message streaming back, and only then
move on. Each stage adds exactly one idea.
