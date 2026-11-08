# The New Guy in Town

An AI helper for people moving to a new city. The first product is the AI Relocation Agent for IT employees moving to Hyderabad.

This repository has the plan and build prompts only. It has no app code yet.

## What is here

| Path | What it contains |
| --- | --- |
| `docs/PRD.md` | Full product requirements and roadmap |
| `docs/prompts/` | Prompts for your coding agent, one file each |
| `.env.example` | Environment variable names, without real values |

## Before you start

1. Check whether the Buildathon allows code written before 20 November 2026.
2. Install Git, Node.js, Python 3.11 or newer, and Docker Desktop.
3. Copy `.env.example` to `.env`, and add your own keys only to `.env`.

## How to build

```bash
git clone https://github.com/Tarak-Ram/TheNewGuyInTheTown.git
cd TheNewGuyInTheTown
code .
```

Open your coding agent in VS Code, then work one step at a time:

1. Start a new agent chat.
2. Paste `docs/prompts/prompt-00.md` and `docs/prompts/prompt-01.md`.
3. Run the app and tests, and read the main changes.
4. Commit the working result.
5. Start a new chat with `prompt-00.md` and the next prompt.

Think of Prompt 0 as the site rules given to every new worker. Each later prompt is that worker's job for the day.

## Do not run these yet

- `prompt-09.md`: real phone calls need the compliance gate in the PRD to be complete.
- `prompt-11.md`: use it only after the Buildathon demo and the earlier roadmap phase pass.
