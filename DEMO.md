# Demo guide

A three-minute run of the AI Relocation Agent, in English, with a reset command so every run starts clean.

## Before you start

One-time setup:

1. In `.env`, set `DEMO_MODE=true`. This turns on the demo sign-in and the labelled commute estimates. Never set it in staging or production.
2. Start everything: `docker compose up -d --build`
3. Check it is healthy: `python scripts/check_health.py` (all four lines say `OK`).

Before **every** run (and after every rehearsal):

```bash
python scripts/reset_demo.py                 # clean slate
python scripts/reset_demo.py --sample-calls  # clean slate + 3 pre-recorded calls (backup)
```

The reset only runs while `DEMO_MODE=true`. It touches only the demo account and the fake sample PGs, so it cannot affect a real user. It also gives back any PG that "opted out" during a rehearsal.

## What is real and what is demo

| Part | In the demo |
| --- | --- |
| Sign-in | Demo account (one click). Real Google sign-in works once `GOOGLE_CLIENT_ID` is set. |
| Office address | One of 7 known offices (Wipro Circle, Cyber Towers, Mindspace, Microsoft, Financial District, Kondapur, Madhapur). With a real `MAPS_API_KEY`, any Hyderabad address works. |
| Commute times | **Estimates** from straight-line distance, labelled "Demo data, not live Google Maps" on screen. With a real `MAPS_API_KEY` they come from the Routes API. |
| Rents | Placeholder sample figures, labelled as unreviewed. |
| PGs | 12 fake PGs. No real PG owner is ever contacted. |
| Voice call | **Real** Gemini Live call in the browser, with a teammate playing the owner. Needs `GOOGLE_API_KEY` and a working `GEMINI_LIVE_MODEL`. |
| Comparison table | Real: facts are read from the call transcript and checked against the owner's words. |
| Agreement check | Real, on fake sample agreements. Without an AI key it uses the basic keyword check, which is enough for the samples. |

Say this out loud on stage where it matters: "These commute times are demo estimates; the live product uses Google Maps." The honest version is also the safer one.

## The three minutes

| Time | Screen | Say | Do |
| --- | --- | --- | --- |
| 0:00 to 0:30 | Home page | "Moving to a new city means choosing a home without knowing the city." Then one real quote from a mover: **[TO FILL after interviews]** | Click **Get started**, then **Use the demo account**. |
| 0:30 to 1:00 | Step 2, then step 3 | "I enter my office and budget." "Each area shows commute, rent and a reason. The score is calculated in code; the AI only explains it." | Office: `Wipro Circle`. Click **Check address**. Budget 8000 to 14000. **Find areas.** Point at the commute and rent source on one card. |
| 1:00 to 1:50 | Step 4 | "I choose PGs that agreed to AI calls and approve the calls. Nothing is called without my approval." | Pick 2 PGs, **Review**, **Approve calls**, **Start demo call**. The teammate (the "owner") answers in English. Show the box: *This is a demo owner.* Let the agent say it is an AI. |
| 1:50 to 2:20 | Step 5 | "Only what the owner clearly said is shown. Anything unclear says Not confirmed." | Open the comparison. Hover a value to show the owner's exact words. Point at a **Not confirmed**. |
| 2:20 to 2:45 | Step 6 | "I upload the agreement. Every risk quotes the exact clause, and it says this is not legal advice." | Upload `evals/agreements/pdf/g_multi.pdf`. Open one risk. Point at the notice. |
| 2:45 to 3:00 | Home | "Companies pay per relocating employee. Rides, storage and local help come later." | Stop on the home page. |

Optional moments if you have time:

- **Stop request.** In a call, the owner says "please stop calling me". The call ends at once, and that PG disappears from every user's list.
- **Prompt injection.** Upload `evals/agreements/pdf/e_injection.pdf`. The page warns that the document tries to instruct an AI, and the real lock-in risk is still reported.

## Backup plan

The PRD's rule is to assume something will fail. In order:

1. **Voice call will not start** (key, quota, network): run `python scripts/reset_demo.py --sample-calls`, sign in, and go straight to step 5. The three pre-recorded calls are labelled *Pre-recorded sample* on screen, and you must say so. Their facts go through the same checks as a live call.
2. **Event Wi-Fi is down:** use a phone hotspot. Everything except the voice call runs on your laptop.
3. **Everything fails:** play the recorded video of the full demo.

## Before you go on stage

- [ ] `DEMO_MODE=true`, stack healthy, `reset_demo.py` run within the last hour
- [ ] Microphone and headset tested (a headset avoids echo between the agent and the owner)
- [ ] The teammate knows the script: answer rent, deposit and food clearly, and say one thing unsure ("around, maybe") so a **Not confirmed** appears
- [ ] A recorded video of the full demo is open in another window
- [ ] Phone hotspot ready, laptop and phone charged
- [ ] Sample PDFs open in a file picker: `evals/agreements/pdf/`

## If something looks wrong

| Problem | Fix |
| --- | --- |
| "Use the demo account" button is missing | `DEMO_MODE` is not `true` in `.env`. Fix it and run `docker compose up -d`. |
| "Address not found" | In demo mode only the 7 known offices work. Use one of them, or set a real `MAPS_API_KEY`. |
| "Commute times are unavailable" | Run `python scripts/check_health.py`. In demo mode this should not happen; it means the API is down. |
| A PG is missing from the list | It opted out in an earlier run. `python scripts/reset_demo.py` brings it back. |
| Call link "already used" | Each call link works once. Go back and click **Start demo call** again. |
| Table says "Checking what the owners said" for long | Click **Check this call again** on that row. |
