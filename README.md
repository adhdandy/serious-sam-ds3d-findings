# Serious Sam Classics — DS3D spatial audio research

Reverse-engineering notes and an implementation design for restoring the
unreleased **TSE 1.50 beta's** per-sound **DirectSound3D** positional audio in
the Steam builds of *Serious Sam Classic* (TSE), via runtime function
patches in [SuperProject](https://github.com/SamClassicPatch) — without
replacing the stock `Engine.dll`.

An opt-in cvar (`snd_bDS3DSpatial`, default off) will enable a "shadow buffer"
mode: each playing mono 3D sound gets its own DS3D buffer driven by the same
math the beta used, while a hook on the software mixer ensures that sound is
not also mixed in software. The DS shadow buffer owns playback state (the
beta's model); the engine's `SOF_PLAY` bit is cleared by the mode when the
shadow reports a natural stop.

## Status

- **Analysis:** complete (beta engine, Steam engine, patch framework).
- **Design:** complete and reviewed (`findings/08-design.md`, `findings/07-implementation-notes.md`).
- **Implementation:** not started. Nothing has been built or run in-game yet;
  everything here is static analysis plus DSOAL log evidence.
- **Pending runtime tests** (need a build): pause/resume mid-one-shot, DSOAL
  behavior of a duplicate outliving its released template, `snd_iEmulationType`
  toggle on running sounds, ear-pair unchanged check.

## Key results

- **Architectures differ.** The beta drives one DS3D buffer per sound
  (template → `DuplicateSoundBuffer` per play, position/velocity deferred,
  volume/frequency immediate, one `CommitDeferredSettings` per frame). The Steam
  build (TSE 1.07 ≙ Serious Engine 1.10 source) software-mixes everything into
  two mono DS3D buffers at ±1 and makes no per-sound DS calls.
- **Beta parameters** are fully recovered and log-validated: listener-space
  position (true distance, z negated), rolloff 0.0 / Doppler 1.1, centibel curve
  `3000·(v(v−1)+(1−v)·log10 v)` (−538 at v = 0.8), `SetFrequency` = rate × pitch,
  EAX DirectHF = round(−100·hf). See `findings/99-summary-and-open-questions.md`.
- **Steam `Engine.dll` matches the 1.10 headers** for every sound function and
  structure examined, so the open-source headers are safe to build against.
- **Zero-volume muting does not work as the mute mechanism.** In the Steam mixer a
  muted *non-looping* sound has `SOF_PLAY` cleared after one mix block. The design
  instead hooks the static `MixSound` (RVA 0x7AF80, single call site) so shadowed
  objects are never mixed, advanced or finished in software. No engine state is
  poisoned.
- **Hook caveats:** `Play_internal` and `~CSoundObject` inline `Stop_internal`, so
  both need their own hooks; `Stop_internal`'s prologue defeats the patcher's
  instruction decoder and needs `FuncPatch_ForceRewrite(7)`.

## Reading order

| File | What it is |
| --- | --- |
| [AGENTS.md](AGENTS.md) | Project brief: goals, constraints, tooling, Stage-1 tasks |
| [AGENTS-phase2-addendum.md](AGENTS-phase2-addendum.md) | Phase 2: implementation plan, gap list (G1–G10), acceptance tests |
| [findings/00-orientation.md](findings/00-orientation.md) | Module inventory, export diff, DSOAL log structure, API version |
| [findings/01-beta-dsound-callsites.md](findings/01-beta-dsound-callsites.md) | All DS3D call sites in the beta engine |
| [findings/02-beta-position-velocity.md](findings/02-beta-position-velocity.md) | How the beta builds `SetPosition` / `SetVelocity` arguments |
| [findings/03-beta-volume-pitch.md](findings/03-beta-volume-pitch.md) | Volume (centibel) curve, pitch, Doppler handling |
| [findings/04-beta-buffer-lifecycle.md](findings/04-beta-buffer-lifecycle.md) | Buffer creation, flags, pooling, pause/stop/level lifecycle |
| [findings/05-steam-hook-surface.md](findings/05-steam-hook-surface.md) | Steam `Engine.dll` hook surface; mixer behavior with muted objects |
| [findings/06-core-patch-mechanism.md](findings/06-core-patch-mechanism.md) | SuperProject / XGizmo patch mechanism and existing sound patches |
| [findings/07-implementation-notes.md](findings/07-implementation-notes.md) | Gap resolutions G1–G10, deviations, design amendments |
| [findings/08-design.md](findings/08-design.md) | Module design: files, hooks, eligibility, gates, failure policy |
| [findings/99-summary-and-open-questions.md](findings/99-summary-and-open-questions.md) | One-page parameter sheet, mapping table, open questions |
| [findings/WORKLOG.md](findings/WORKLOG.md) | Running analysis log (what worked, dead ends) |

If you only read two files: `99` (what the beta does) and `08` (what the patch will do).

Some early statements were later corrected; corrections are marked inline
(`[CORRECTED …]` / `[SUPERSEDED …]`), and `07` is authoritative where files disagree.

[`findings/scripts/`](findings/scripts) contains the log-analysis and PE helpers
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
| --- | --- |
| TSE 1.50 beta `Engine.dll` | Subject of the beta RE (task group A) |
| Steam TSE 1.07 `Engine.dll` | Subject of the hook-surface analysis (task group B) |
| DSOAL call logs (beta + Steam) | Ground truth for DS3D call sequences issued by each engine |
| [Serious Engine 1.10](https://github.com/Croteam-official/Serious-Engine) source | GPL reference for the classic sound code |
| [Last Chaos Client Source](https://github.com/openlastchaos/lastchaos-source-client/) | Shares an Engine with TSE 1.50 |
| [SamClassicPatch/API](https://github.com/SamClassicPatch/API), [SuperProject](https://github.com/SamClassicPatch/SuperProject), [XGizmo](https://github.com/SamClassicPatch/XGizmo) | Patch framework under study / extension target |

## Methodology and AI assistance

This is my first reverse-engineering project, and AI tools played a central role throughout the investigation — assisting with disassembly analysis, interpreting engine behavior, comparing the beta and Steam builds, developing hypotheses, and exploring the implementation architecture.

Because AI-assisted analysis can produce confident-sounding but incorrect conclusions, every claim in the findings is tagged by evidence strength (see *Confidence tags* below) and cited to specific disassembly addresses, source lines, or DSOAL log evidence. Early conclusions that were later overturned are marked inline (`[CORRECTED …]` / `[SUPERSEDED …]`) rather than silently edited. Some conclusions remain hypotheses, and the proposed implementation has not yet been validated in-game.

This repository is intended to document the investigation and provide a technical starting point for further verification, discussion, and implementation. Feedback and corrections from experienced reverse engineers and developers are very welcome.

## Related projects

- [SamClassicPatch](https://github.com/SamClassicPatch) — "Serious Sam
  Classics Patch" (GPL-2.0); this design extends it.
- [DSOAL](https://github.com/kcat/dsoal) — DirectSound → OpenAL Soft wrapper
  used to capture the call logs that document the beta's behavior.

## License

- Documentation: [CC BY 4.0](LICENSE).
- Helper scripts in `findings/scripts/`: [MIT](findings/scripts/LICENSE).
- Short excerpts of GPL-licensed code (Serious Engine, SuperProject) and short
  disassembly/decompiler excerpts of the game binaries appear only as cited
  evidence for commentary and analysis.

Serious Sam is a trademark of Croteam. This is unofficial fan research; not
affiliated with or endorsed by Croteam.
