# Code Quality Crew — Claude Code plugin

A `/crew-review` slash command that wraps the Claude **Managed Agents** crew: a
coordinator agent delegates a code review to a `reviewer` agent and unit-test
writing to a `test-writer` agent, then synthesizes the result and saves the
generated pytest file next to your source.

## Install

From the GitHub repo that contains this plugin:

```
/plugin marketplace add budama87/code-quality-crew
/plugin install code-quality-crew@code-quality-crew
```

## Prerequisites

- Python 3.10+ with the Anthropic SDK: `pip install "anthropic>=0.40.0"`
- An Anthropic API key, either as the `ANTHROPIC_API_KEY` environment variable
  or in a `.env` file in your working directory.

## Use

In Claude Code:

```
/crew-review src/auth.py
/crew-review src/auth.py --no-tests     # report only, write nothing
```

It prints a severity-grouped review and writes `test_<name>.py` next to the
reviewed file. The three agents are created once and cached in
`~/.code-quality-crew/crew.json`; pass `--fresh` to recreate them.

## Run without the plugin

The wrapper is a plain script, so it also works standalone:

```
python scripts/crew_review.py src/auth.py
```

## Cost / cleanup

Each run opens a Managed Agents session (3 agents). The session is deleted
automatically when the run finishes. Standard Claude API token rates apply plus
a small session-runtime charge; see the project README for details.
