# Back to basics: cleanup plan

Status: phase 1 file changes done on `cleanup/back-to-basics`. Nothing is deleted.
Every retired doc moved to `docs/archive/`. The GitHub issue changes wait for approval.

## The new direction

1. The Pi watches the feeder with the camera and decides one thing: bird or no bird.
2. Every capture with a bird goes to the gaming PC (RTX 5080) for classification.
   That is today's Tier 2 inference server.
3. Tier 3 (Claude or another frontier model) stays in the code, off by default.
4. Tier 1 (TFLite species classification on the Pi) stops being the first stop.
   Removing it is a code change, so it waits for phase 2.

## Phase 1: process and docs

All file changes go on one branch, `cleanup/back-to-basics`, as one pull request.
You review the diff before anything merges.

### Files

| File | Lines | Action | Why |
|---|---|---|---|
| `README.md` | new | Create, about 60 lines | The repo has no root README. It holds what Peck Deck is, how to run it, what is built, and the short "Next" list below. |
| `FLEDGE_ROADMAP.md` | 476 | Archive | Phases 0 to 8 are done. A short "What is built" section in the README replaces it. |
| `OUTDOOR_DEPLOYMENT.md` | 1,233 | Archive | Spokane outdoor build, power, squirrels, enclosures. None of it matters for a windowsill. |
| `HARDWARE_TEST_PLAN.md` | 395 | Archive | Bring-up logs from July. |
| `docs/handbook.html` | | Archive | A styled copy of the planning docs above. |
| `docs/research/perch-switch-selection-and-wiring.md` | | Archive | The perch switch is gone from the plan. |
| `docs/research/picamera2-focus-and-exposure.md` | | Keep | Real API notes for the camera you will use. |
| `AGENTS.md` | 111 | Archive | It mostly mirrors the writing rules. |
| `docs/agents/` (4 files) | 225 | Archive | Config for the Matt Pocock skills, plus the repo copy of the writing rules. |
| `CLAUDE.md` | 240 | Shrink to 144 lines, and commit it again. The full old version goes to `docs/archive/CLAUDE-full.md` | Keep the stack facts, code conventions, security notes and subsystem traps. Remove the Writing section, the Agent skills section and the roadmap pointer. Remove the `.gitignore` line that hides it. |
| `CONTRIBUTING.md` | 87 | Small edit | Keep the new GPU server instructions. Remove the Writing section and the `AGENTS.md` paragraph. |
| `PRD.md` | 373 | Edit sections 5.1, 5.2 and 9 | Describe the new direction: the Pi detects, the gaming PC classifies. |
| `SETUP.md` | 224 | Small edit | Fix the stale `TRIGGER_TYPE` line. Mark the Tier 2 section as the main path. |
| `docs/live-updates-sse.md`, `docs/operations.md`, `docs/pwa-and-web-push.md`, `docs/simulator-and-demo-mode.md` | 233 | Keep | Short docs about code that exists. If phase 2 removes a feature, its doc goes with it. |
| `household-agent-server.html` | 1,327 | Your call | It is untracked and looks unrelated to Peck Deck. I'd move it out of this repo. |

The writing rules then live in one place: your global `~/.claude/CLAUDE.md`.

Net effect: about 2,600 lines of planning and agent config move to `docs/archive/`,
and one 60-line README is added.

### The short list (goes in the README under "Next")

1. Replace the `pir` and `ir_beam` triggers with a camera trigger. Use a cheap
   motion check first, then a small detector (YOLO nano or similar) to confirm a bird.
2. Send every bird capture straight to Tier 2 on the gaming PC.
3. Leave Tier 3 in the code, off by default.
4. Put the Pi at the window with a feeder outside. Look at real sightings in the app.
5. Tune the detector thresholds and focus from what step 4 shows.

### GitHub issues: preview

I post each comment below, then close the issue. Nothing happens on GitHub until
you approve this list.

| Issue | Closing comment |
|---|---|
| [Wayfinder: Phase 4, bench to windowsill](https://github.com/dnorris823/Peck_Deck/issues/35) | Closing. The plan grew bigger than the work. The next steps now live in `README.md` under "Next". |
| [Provision a working device token on the Pi](https://github.com/dnorris823/Peck_Deck/issues/47) | Closing as done. [Provision the Pi's device token unattended](https://github.com/dnorris823/Peck_Deck/pull/57) merged this. |
| [Collect Stage 0 feeder footage through the glass](https://github.com/dnorris823/Peck_Deck/issues/53) | Closing. This is step 4 of the new list in `README.md`. |
| [Pick the detector and the trigger thresholds](https://github.com/dnorris823/Peck_Deck/issues/54) | Closing. Steps 1 and 5 of the new list cover it. Start with defaults and tune on real footage. |
| [What counts as one visit on a vision trigger](https://github.com/dnorris823/Peck_Deck/issues/55) | Closing. Start with "first detection after a 15 s quiet gap" and change it if real visits disagree. |
| [Pick the AF and exposure numbers at the glass](https://github.com/dnorris823/Peck_Deck/issues/45) | Closing. Pick these from real captures at the window. `docs/research/picamera2-focus-and-exposure.md` keeps the API notes. |
| [Thermal telemetry in the device heartbeat](https://github.com/dnorris823/Peck_Deck/issues/41) | Closing. Not needed for a first bird. Reopen if the Pi throttles at the window. |
| [Detector health and silent-failure detection](https://github.com/dnorris823/Peck_Deck/issues/56) | Closing. Revisit once the feeder runs unattended. |
| [Should the ablation gain a through-glass variant?](https://github.com/dnorris823/Peck_Deck/issues/58) | Closing. Accuracy work waits until real sightings exist. |
| [How code reaches the Pi](https://github.com/dnorris823/Peck_Deck/issues/59) | Closing. `git pull` on the Pi is enough for now. |

After that, I delete the five `wayfinder:*` labels. The 15 closed wayfinder issues
stay closed and keep their text. Deleting the labels only strips the tag.

### Order of work

1. You review this file and change anything you want.
2. I make the file changes on the branch and open a draft pull request.
3. You review the diff.
4. After you approve, I close the 10 issues with the comments above and delete
   the labels.
5. You merge.

## Phase 2: code (later, after your review)

Not part of this pass. These are the candidates I'd look at:

- Delete `trigger/pir_trigger.py` and `trigger/ir_beam_trigger.py` once the camera
  trigger exists.
- Remove Tier 1 TFLite from the default chain, and maybe from the repo.
- Ask whether demo mode, the simulator, web push, SSE and the analytics dashboard
  each still earn their keep. Each one adds its own doc and its own traps in
  `CLAUDE.md`.

## Questions for you

1. `household-agent-server.html`: move it out, delete it, or leave it?
2. Answered: archive everything, delete nothing.
