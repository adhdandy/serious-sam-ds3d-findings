# Serious Sam Classics — DS3D spatial audio research

Reverse-engineering notes and an implementation design for restoring the
unreleased **TSE 1.50 beta's** per-sound **DirectSound3D** positional audio in
the Steam builds of *Serious Sam Classic* (TSE), via runtime function
patches in [SuperProject](https://github.com/SamClassicPatch) — without
replacing the stock `Engine.dll`.

An opt-in cvar (`snd_bDS3DSpatial`, default off) will enable a “shadow buffer”
mode: each playing mono 3D sound gets its own DS3D buffer driven by the same math the beta used, while a hook on the software mixer ensures that sound is not also mixed in software.
The DS shadow buffer owns playback state (the beta's model); the engine's SOF_PLAY bit is cleared by the mode when the shadow reports a natural stop.

## Reading order

| File | What it is |
|---|---|
| File | What it is |
|---|---|
| [AGENTS.md](AGENTS.md) | Project brief: goals, constraints, tooling, Stage-1 tasks |
| [AGENTS-phase2-addendum.md](AGENTS-phase2-addendum.md) | Phase 2: implementation plan, gap list (G1–G10), acceptance tests |
| [findings/00-orientation.md](findings/00-orientation.md) | Module inventory, export diff, DSOAL log structure, API version |
| [findings/01-beta-dsound-callsites.md](findings/01-beta-dsound-callsites.md) | All DS3D call sites in the beta engine |
| [findings/02-beta-position-velocity.md](findings/02-beta-position-velocity.md) | How the beta builds `SetPosition` / `SetVelocity` arguments |
| [findings/03-beta-volume-pitch.md](findings/03-beta-volume-pitch.md) | Volume (centibel) curve, pitch, Doppler handling |
| [findings/04-beta-buffer-lifecycle.md](findings/04-beta-buffer-lifecycle.md) | Buffer creation, flags, pooling, pause/stop/level lifecycle |
| [findings/05-steam-hook-surface.md](findings/05-steam-hook-surface.md) | Steam `Engine.dll` hook surface; mixer behavior with muted objects |
| [findings/06-core-patch-mechanism.md](findings/06-core-patch-mechanism.md) | SuperProject / XGizmo patch mechanism and existing sound patches |
| [findings/07-implementation-notes.md](findings/07-implementation-notes.md) | Implementation-session notes (gap resolutions, deviations) |
| [findings/08-design.md](findings/08-design.md) | Module design: files, hooks, eligibility, gates, failure policy |
| [findings/99-summary-and-open-questions.md](findings/99-summary-and-open-questions.md) | One-page parameter sheet, mapping table, open questions |
| [WORKLOG.md](findings/WORKLOG.md) | Running analysis log (what worked, dead ends) |

[`findings/scripts/`](findings/scripts/) contains the log-analysis and PE helpers
used during the research (`logstats.py`, `condense.py`, `exportdiff.py`,
`readpe.py`, `slicefunc.py`, plus a Ghidra script).

## Confidence tags

Every claim in the findings is labeled:

- **VERIFIED** — seen in disassembly and/or matched against a DSOAL log or source
- **LIKELY** — strongly supported but not fully cross-checked
- **HYPOTHESIS** — plausible, needs confirmation

Addresses are RVAs into the named binary unless stated otherwise.

## Inputs (not included here)

This repo contains only original documentation and helper scripts. It does
**not** include game binaries, DSOAL call logs, engine source, or
SuperProject/XGizmo code. Those stay in the private analysis workspace:

| Input | Role |
|---|---|
| TSE 1.50 beta `Engine.dll` | Subject of the beta RE (task group A) |
| Steam TSE 1.07 `Engine.dll` | Subject of the hook-surface analysis (task group B) |
| DSOAL call logs (beta + Steam) | Ground truth for DS3D call sequences issued by each engine |
| [Serious Engine 1.10](https://github.com/Croteam-official/Serious-Engine) source | GPL reference for the classic sound code |
| [SamClassicPatch/API](https://github.com/SamClassicPatch/API), SuperProject, XGizmo | Patch framework under study / extension target |

## Related projects

- [SamClassicPatch](https://github.com/SamClassicPatch) — “Serious Sam
  Classics Patch” (GPL-2.0); this design extends it.
- [DSOAL](https://github.com/kcat/dsoal) — DirectSound → OpenAL Soft wrapper
  used to capture the call logs that document the beta's behavior.

## License

Documentation and scripts in this repository:
[CC BY 4.0](LICENSE). Short excerpts of GPL-licensed code (Serious Engine,
SuperProject) appear only as cited evidence for commentary/analysis.

Serious Sam is a trademark of Croteam. This is unofficial fan research; not
affiliated with or endorsed by Croteam.
