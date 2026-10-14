# AGENTS.md — Phase 2 addendum: implementation (rev 2)

**Status:** Phase 1 (analysis) is complete. Findings `00`–`06` and `99` in `findings\` are the
**spec of record**. This addendum supersedes the "analysis and documentation only" rule in §2 of
the original AGENTS.md. Everything else in AGENTS.md (working rules §5, evidence/confidence tags,
folder rules, "stop and report") stays in force.

Goal unchanged: opt-in DS3D shadow-buffer mode (`snd_bDS3DSpatial`, default 0) in SuperProject
for the Steam TSE build (TSE107, stock `Engine.dll`, never replaced). Vanilla behavior must be
unchanged when the mode is off.

---

## 1. Changed rules

| Topic | Rule |
|---|---|
| Source of truth | `findings\99` §1 (parameter sheet) and §3 (viability conditions A/B). Code comments cite sheet rows (`// 99 §1.2 #10`). |
| Where code goes | A **working copy** of SuperProject at `PROJECT_ROOT\work\SuperProject` (git branch `ds3d-spatial`). The original `SuperProject` folder stays read-only. |
| Allowed without asking | Reading anything, editing the working copy, scripts in `findings\scripts\`, log analysis, static disassembly. |
| **Ask the user first** | Building (state toolchain/config), running any game EXE, copying DLLs into any game folder, anything touching `SS_TSE_*_Bin`. Say what you will do and what you expect to see. |
| Documentation | Every session: append to `WORKLOG.md`. New engine facts go into a findings file with a confidence tag, not only into code comments. |
| Deviation from the spec | Write the reason in `findings\07-implementation-notes.md` first, then change the code. |

## 2. Task 0 — API submodule (do first, small; blocks Task 2)

The user is adding `https://github.com/SamClassicPatch/API` to the project folder. Once present:

1. Read `API\include\classicspatch_api.h` and neighbors. Record the real signatures of
   `CreatePatch`, `HFuncPatch`, the `CLASSICSPATCH_*` macros, and the numeric values of
   `SE1_VER` / `SE1_105/107/110/150` (they may live in `Includes` instead; report which).
2. Update `06` (open questions 1 and 2) and `99` §4 unknown #7 → resolved, with file:line cites.
3. Confirm the **call-the-original-via-trampoline pattern for member functions** (precedent:
   `CControlsPatch::P_Load`, 06 §2) works for `Play_internal`/`Stop_internal`/`UpdateSounds`/
   `SetFormat`, and whether `CreatePatch` can be called after `CorePatches()` init (plugin path, 06 §8).

Task 2 (design) must not be finalized before Task 0 is done; Task 1 can run in parallel.

## 3. Task 1 — close the gaps (output: `findings\07-implementation-notes.md`)

Answer each from the Steam binary and/or 1.10 source, tag it, and cite addresses.

| # | Question | Why it matters |
|---|---|---|
| **G7** | **Mute path, instruction level.** `MixSound` reads `so_sp`@+0x34. Trace every write to `so_sp` vs `so_spNew` across `Play_internal`, `Update3DEffects`, `PrepareSound` (0x7F010), `UpdateSounds`, `MixSound`. Which function copies `spNew → sp` each frame (05 §2.3 says "UpdateSounds copies"; 05 §1.2 only documents the `Play_internal` copy)? Is the copy skipped under any flag (`SOF_PREPARE`, smooth change)? | Mute = zero `so_spNew` L/R **inside `P_Update3DEffects` after the normal computation** (a game-side `SetVolume(0,0)` is overwritten every frame). Must be proven to reach `so_sp` before `MixSound` reads it. |
| | *Same task, first-block case:* `Play_internal` copies the caller's volumes into `so_sp` before the first `Update3DEffects` runs. Can `MixSound` (timer thread) mix one unmuted block alongside the new shadow? | Expected fix: `P_Play_internal` zeroes `so_sp`+`so_spNew` L/R for eligible sounds right after the original returns. Confirm it is sufficient. |
| **G1** | **Template creation.** Steam has no per-sound DS templates. What is in `CSoundData` for a loaded WAV (`sd_pswBuffer`@+0x40, size@+0x44, `sd_wfeFormat`@+0x2C): sample rate (resampled to mixer rate?), channels, bits? Where is it freed (`ClearBuffer` 0x76200, destructor, `Reload` after `SetFormat`)? | Patch builds `DSBUFFERDESC` (flags per `99` #14) from this and owns the template lifetime. |
| **G2** | **Interface gate.** `sl_pDSListener`@+0x48 and a `CTRL3D` primary exist only when `snd_iInterface==2` (05 §1.1a). **Decided:** mode refuses to enable otherwise, with a console notice. Remaining question: can `snd_iInterface` change at runtime, and how does the engine react? | Avoids an inert mode that looks like a bug. |
| **G3** | **Commit placement.** Steam log: `CommitDeferredSettings` ×3 total (00 §5) → no per-frame commit. **Decided:** wrapper on exported `UpdateSounds`: call original first (it runs `Update3DEffects` for all objects), then update shadow bookkeeping, then **one** commit; also while paused (harmless). Verify engine's own commit sites don't interleave badly. | Deferred position/velocity are inert without it (`99` #6). |
| **G4** | **Position and drift.** (a) Units: `so_fLeftOffset` counts source samples (advance = `fStep × mixRate × secs` per block, 05 §2.2); `SetCurrentPosition` takes bytes = samples × channels × bytes/sample. State the exact conversion incl. `SOF_LOOP` wrap and `sp_fDelay`. (b) **Doppler:** Steam's `Update3DEffects` (1.10) bakes software doppler into the engine pitch. If the shadow uses DS3D doppler (`99` #12) the engine and shadow advance at different rates → finish time drifts. Design: no software doppler on the engine-side pitch in shadow mode; **engine stays authoritative** — when `SOF_PLAY` clears, stop+release the shadow. (c) Cases creating a shadow mid-play: voice steal, un-park, resume, re-`Play` with `SOF_SMOOTHCHANGE`. | Lifecycle `99` #16/#18 assumes restart at 0; Steam has real offsets. |
| **G5** | **Side effects on the engine's ear pair.** Applying rolloff 0.0 / doppler 1.1 to the shared listener also affects `sl_pDSSourceLeft/Right` (carry software mix of non-3D, music, decoder sounds). Reasoning `[LIKELY]`: the pair sits at ±1 with `MinDistance` 1.0 → attenuation `min/dist = 1` regardless of rolloff; velocity 0 → doppler no-op; panning comes from position. Confirm against DS3D semantics, and mark for a log/listening check. | "Vanilla alongside" constraint. |
| **G6** | **Re-init.** `SetFormat` re-runs `StartUp_dsound`: all shadows/templates die with the device and listener params revert. Define a `SetFormat` wrapper: release shadows before the original, re-apply beta listener params after. | `99` §5 caveat; 04 §1. |
| **G8** | **Threading.** Verify `UpdateSounds` takes `sl_csSound` (05 verified this only for `Play`, `Stop`, `MixSounds`). List every field the shadow subsystem touches and from which thread. Intended model: all shadow state is touched only from game-thread hooks under `sl_csSound`; the WINMM mixer thread never touches it. | Prevents races without inventing new locks. |
| **G9** | **Runtime failure detection.** Define the rule that un-mutes and drops a shadow: any DS HRESULT failure on `Play`/`SetVolume`/`SetPosition`, `DSBSTATUS_BUFFERLOST`, or `GetStatus` showing not-playing while the engine says playing and the expected end is not reached, for N frames. | Enforces "never silent in both paths" at runtime, not only at creation. |
| **G10** | **Volume inputs.** (a) `snd_bLinearVolume` (03 §2) probably does not exist in Steam (1.10 has no such curve): check; if absent, hardcode the linear branch (beta default 1) and do not add a cvar unless useful. (b) Master volume (`snd_fSoundVolume`@VA 0x602a40f8, `snd_fMusicVolume`@0x602a40fc) is applied inside `MixSound`/`Play_internal` in Steam, which a muted object skips → the shadow path applies it itself. (c) Map Steam inputs (`sp3_fMaxVolume`, accumulated L/R) to `99` #8. | Correct loudness; no double or missing master scaling. |

## 4. Task 2 — module design (write after Task 0; output `findings\08-design.md`, 1–2 pages)

Must contain:

- **Files:** new `Core\Patches\SoundDS3D.cpp/.h` (channel table ≤64, template cache, per-sound
  state); cvar declared in `ICorePatches::SoundLibrary()`; no changes to unrelated patches.
- **Hooks** (all exported, hooked like `Listen`, 05 §1.3 / 06 §7):
  - `P_Play_internal` — call original first (trampoline), then create/refresh the shadow and zero
    `so_sp`/`so_spNew` L/R for eligible sounds (G7). Covers the inlined `Stop_internal` on re-Play.
  - `P_Stop_internal` — release the shadow (explicit `Stop` path).
  - `P_Update3DEffects` — existing full replacement; extend with the DS3D computation
    (`99` #2–#5, #8–#13), apply to the shadow, then zero `so_spNew` L/R (mute); no software
    doppler on engine pitch for shadowed sounds (G4b).
  - `UpdateSounds` wrapper — original, then shadow bookkeeping, voice budget/steal (`99` #15),
    one `CommitDeferredSettings` (G3).
  - `SetFormat` wrapper (G6); `ClearBuffer` if G1 requires it.
- **Eligibility (Steam terms):** `SOF_3D` set, `sd_wfeFormat.nChannels==1`, `!SDF_ENCODED`,
  `so_psdcDecoder==NULL`, `!SOF_MUSIC`. `SOF_VOLUMETRIC` sounds **are** shadowed (beta does).
  Everything else stays in the ordinary software mix, untouched (`99` §3 condition A).
- **Gates, one behavior each** (condition B):
  - `SOF_PAUSED` (engine `Pause`) → **release** the shadow; recommit on resume (`99` #18).
  - Game pause for non-`SOF_NONGAME` sounds, and `_bMuted` (VA 0x602c97f0, focus loss) →
    `SetVolume(-10000)` + `Stop()`, buffer kept (`99` #20); resume continues from DS position.
- **Parked state:** position `(0,0,-10000)` **and** `SetVolume(-10000)` always together (`99` §4 #3),
  because some drivers may ignore `MUTE3DATMAXDISTANCE`.
- **Toggle semantics:** cvar-on → only **newly played** eligible sounds get shadows; already-playing
  sounds stay in software until they end. cvar-off → existing shadows drain on their natural stop;
  new sounds go to software. No mid-flight conversion, no hook/unhook at runtime (06 open question 5).
- **Interface gate:** refuse to enable unless `snd_iInterface==2` / `sl_pDSListener != NULL`, with a console notice (G2).
- **Failure policy:** creation failures and runtime failures (G9) → drop the shadow, restore engine volume.
- **Cvar access:** `snd_bDS3DSpatial` is read only from game-thread hook bodies (never from the timer thread).
- **Version gating:** build only for the TSE107 config via `#if` on `SE1_VER` / the game macro
  (exact condition after Task 0; `CHOOSE_FOR_*` is value selection, not feature gating) plus
  `_PATCHCONFIG_ENGINEPATCHES` as for the existing sound patches. Other builds compile the feature out.

Stop and show the user the design before Task 3.

## 5. Task 3 — implementation order

1. Cvar + empty shadow subsystem, hooks installed, mode off → verify vanilla behavior unchanged (§6).
2. Listener param application + template cache + create/release lifecycle for **one** sound
   class (e.g. a looping ambient), no muting yet (double audio is expected and fine for this test).
3. Position/velocity/volume/frequency/EAX HF per `99`, one commit per frame.
4. Muting of the engine mix (G7 design) + gates + failure policy.
5. Voice budget/steal, `snd_iMaxSameSounds` budget (include — `99` §4 #5).
6. `SetFormat` re-init robustness; `snd_iEmulationType` toggle.

Each step ends with a WORKLOG entry and, where applicable, a user-approved runtime test.

## 6. Acceptance tests (DSOAL log comparison)

Reuse `findings\scripts\logstats.py`. The user runs the game with DSOAL logging; the agent only
analyzes the log. **"Matches in structure"** = for a chosen set of sampled 3D sounds, the per-frame
call sequence and apply modes equal the beta's, and aggregate counts per call type are in the same
proportions (not equal totals; the sessions differ).

| Check | Expected (beta reference) |
|---|---|
| Listener init | `SetRolloffFactor(0.0)`, `SetDopplerFactor(1.1)` after every device init (incl. after `SetFormat`) |
| Buffers | duplicates from per-sound templates; `SetMode(1)` for shadowed mono sounds |
| Per-frame order (sampled sound) | `SetPosition` → `SetVelocity` → `GetStatus` → `SetVolume` → `SetFrequency` → EAX `Set(0x80000003)`; **one** `CommitDeferredSettings` per frame |
| Apply modes | position/velocity/DirectHF = 1 (deferred); volume/frequency = 0 |
| Volume values | centibels follow the `99` #10 curve (−538 at v=0.8 with default master, −10000 at ≤0.005) |
| Parked sounds | `SetPosition(0,0,-10000)` together with `SetVolume(-10000)` |
| Decoder/music sounds | no shadow buffers; still audible via software mix |
| Ear pair | unchanged: two mono mix buffers at (−1,0,0)/(1,0,0), same call pattern as `dsoal_Steam_log.txt` (G5) |
| Mode off | log structurally identical to `dsoal_Steam_log.txt` (zero per-sound DS activity) |

Subjective check (user): directional audio with headphones, no doubled sounds (watch the first
block of each new sound), sounds end on time, pause/resume and level change behave.

## 7. Reporting

Report to the user after Task 0, after Task 1+2 (design for approval), and after each Task 3 step
that needs a runtime test. Five lines or fewer in chat, details in `findings\`.
