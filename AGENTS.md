# AGENTS.md — Serious Sam Classics: directional 3D audio for SuperProject

You are joining a research and reverse-engineering project cold. Read this whole file before doing anything. Your job in this phase is **analysis and documentation only**. You do not write patch code yet.

Project root: `PROJECT_ROOT`

---

## 1. Ultimate goal (context, not your task)

Add an **opt-in, directional 3D audio mode** to *Serious Sam Classics* (The First Encounter / The Second Encounter, Steam builds) through **SuperProject** (the fan-made "Serious Sam Classics Patch", GPL-2.0). The mode should reproduce what an unreleased **TSE 1.50 beta** build did: per-sound positional audio through DirectSound3D (DS3D), where the Steam release only does stereo panning and volume.

Hard constraints:

- **Do not replace `Engine.dll`.** SuperProject deliberately leaves the stock engine untouched and patches engine functions at runtime. Vanilla behavior must stay the default and must still work alongside the patch.
- Everything new must live behind an opt-in switch (planned: a cvar such as `snd_bDS3DSpatial`, default off).
- Only hook functions that the engine exports by name, unless there is no alternative. Version-matching across game versions depends on that.

The planned implementation (so you know what your findings feed into):

1. SuperProject's `Core` already replaces `CSoundObject::Update3DEffects` and `CSoundLibrary::Listen` with its own reimplementations of the 1.10 source logic *(reported, not verified — see task S3)*.
2. Extend those replacements so each playing mono 3D sound also gets a **"shadow" DS3D buffer**: created at `Play_internal`, positioned/velocity-updated in `Update3DEffects`, released at `Stop_internal`. The engine's own software mix for that sound is muted so only the shadow buffer is audible. The engine stays authoritative for playing/finished state.
3. Observe the result with **DSOAL** (DirectSound → OpenAL Soft wrapper), whose call log is how the beta's behavior was captured.

Your findings decide the exact parameters and the lifecycle details of step 2.

---

## 2. Your role and scope

You are the reverse engineer / source archaeologist. Produce **verified, evidence-backed findings** about:

- **A. The beta:** exactly how the TSE 1.50 beta drives DirectSound3D, so it can be reproduced.
- **B. The Steam build:** which functions can be hooked, how they behave, and whether the planned "shadow buffer + muted software mix" design is viable.
- **C. SuperProject's patch mechanism:** how its function patches work and where the sound patches live.

Not in scope until the user says so: writing or modifying hook code, building any project, modifying any binary, running the game executables. If you think running something is necessary, **ask the user first** and say why.

---

## 3. Folder layout (all inputs are read-only)

| Folder | What it is |
|---|---|
| `SE1-StaticLibrariesForGames` | Compiled static libraries (and possibly headers) of the engine for various game versions, including the 1.50 beta generation. Use for symbol names, signatures and class layouts. |
| `Serious-Engine` | Open-source Serious Engine **1.10** source (GPL). Reference for the classic sound code: `Engine/Sound/*` (SoundLibrary, SoundObject, SoundData, SoundMixer). |
| `SS_TSE_Beta_Bin` | Binaries of the TSE 1.50 beta. **Primary subject of task group A.** |
| `SS_TSE_Steam_Bin` | Binaries of the Steam release. **Primary subject of task group B.** |
| `SuperProject` | The patch (solution with Core, game libs, etc.). Subject of task group C. |
| `XGizmo` | Helper library used by the patch, including the function-patching facility (`CPatch` / patcher). |

Rules for the folders:

- **Never modify, rename or delete** anything in these folders. Copy to a scratch directory if a tool needs write access.
- All your output goes to `PROJECT_ROOT\findings\` (create it).
- The user holds a **DSOAL call log of the beta** (their ground truth). If it is not in the project folder, ask the user for it before starting task group A. Do not proceed with unverified recollections of its contents.

---

## 4. Tooling

- REA (MCP server) with a native-analysis backend (Ghidra expected). Use it for decompilation, xrefs, strings, imports, exports.
- Shell tools as available (`dumpbin`, `llvm-nm`/`llvm-objdump`, Python with `pefile` or `lief`, `grep`/`rg`). For the static libs, try `dumpbin /symbols` or `llvm-nm`; Ghidra's COFF-archive handling can be unreliable, so do not rely on it alone.
- The target binaries are **32-bit x86 Windows PE** DLLs. Member functions use `__thiscall` (the `QAE` in mangled names).

---

## 5. Working rules (important)

1. **Evidence or it did not happen.** Every claim needs: binary + version, function address (RVA or image-base-relative VA, state which), and the instruction or decompiler excerpt that supports it. If you cannot cite it, label it `HYPOTHESIS`.
2. **Label confidence** on every finding: `VERIFIED` (seen in disassembly and/or matched against log/source), `LIKELY`, `HYPOTHESIS`.
3. **Check names against the log.** The log is ground truth for *what the beta calls*. The disassembly explains *why* and *how the arguments are computed*. When they disagree, report it; do not smooth it over.
4. **Do not invent semantics from function names.** Names in this engine are informative but the beta differs from 1.10. Confirm by reading the code.
5. **Keep notes as you go** in `findings\WORKLOG.md` (what you tried, dead ends included). Decompiler output is imperfect; note when you suspect it is wrong.
6. **Facts below are tagged by origin.** `[LOG]` = from the user's DSOAL beta capture as relayed to this project. `[EXPORTS]` = from `dumpbin /exports` of the Steam `Engine.dll` supplied by the user. `[UNVERIFIED]` = claimed by an AI assistant or recalled from memory; verify before relying on it. Treat `[UNVERIFIED]` items as leads.
7. If you get stuck or the data contradicts this brief, **stop and report** rather than working around it. Earlier in this project, one export dump and one search gave wrong negative results (a function was reported "not found" that was exported). Distrust any single negative result; recheck it with a second method.

---

## 6. Known facts

### 6.1 Beta behavior from the DSOAL log `[LOG]`

(Numbers as relayed; re-derive them from the real log in task A1.)

- `Buffer3D::SetMode`: about 206 calls with `(1, 0)` and 21 with `(2, 0)`. Mode values should be `DS3DMODE_HEADRELATIVE` = 1 and `DS3DMODE_DISABLE` = 2; no `NORMAL` (0). The second argument is `dwApply` (0 = `DS3D_IMMEDIATE`).
- `Listener3D::SetRolloffFactor(0.0, 0)`: DS3D distance attenuation is off.
- `Listener3D::SetDopplerFactor(1.1, 0)`.
- Listener: `SetPosition (0,0,0)` and `SetOrientation (0,0,1, 0,1,0)`; stays fixed.
- `Buffer3D::SetPosition(x, y, z, dwApply)`: mostly vectors of length ≈ 0.9–1.0, e.g. `(-0.107, 0.486, 0.815)` (length ≈ 0.955 — **not** exactly unit). One outlier `(22.794806, -21.245279, -47.589603, 1)` with length ≈ 57.6. The trailing `1` is most likely `dwApply = DS3D_DEFERRED` rather than a fourth component `[UNVERIFIED]`.
- `Buffer3D::SetVelocity`: values such as `(-0.000, -0.0655, -1.833)`.
- `Buffer::SetVolume`: centibel values such as -538, -1522, -2157, -10000 (-10000 = silent). The engine appears to compute volume itself.
- `Buffer::SetFrequency`: always `0` (= `DSBFREQUENCY_ORIGINAL`).
- **No** calls to `SetMinDistance`, `SetMaxDistance`, or cone setters were found. Whether `SetAllParameters` or `CommitDeferredSettings` appear is **unknown**; check.
- On the order of 370 buffers created with `DSBCAPS_CTRL3D`.

### 6.2 Steam `Engine.dll` sound exports `[EXPORTS]`

RVAs from the supplied dumpbin output (stock Steam TSE `Engine.dll`):

```
CSoundObject:
  ?Update3DEffects@CSoundObject@@QAEXXZ              0007E870
  ?Play@CSoundObject@@QAEXPAVCSoundData@@J@Z          0007E480
  ?Play_internal@CSoundObject@@QAEXPAVCSoundData@@J@Z 0007E500
  ?Play_t@CSoundObject@@QAEXABVCTFileName@@J@Z        0007F060
  ?Stop@CSoundObject@@QAEXXZ                          0007E750
  ?Stop_internal@CSoundObject@@QAEXXZ                 0007E810
  ?PrepareSound@CSoundObject@@QAEXXZ                  0007F010
  ?Set3DParameters@CSoundObject@@QAEXMMMM@Z           0007E2B0
  ?SetVolume@CSoundObject@@QAEXMM@Z                   00019E00
  ?SetFilter@CSoundObject@@QAEXMM@Z                   00019E20
  ?SetPitch@CSoundObject@@QAEXM@Z                     00019E60
  ?SetPhase@CSoundObject@@QAEXM@Z                     00019E70
  ?SetDelay@CSoundObject@@QAEXM@Z                     00019E80
  ?SetOwner@CSoundObject@@QAEXPAVCEntity@@@Z          00019E90
  ?SetOffset@CSoundObject@@QAEXM@Z                    0007E6B0
  ?Pause / ?Resume / ?IsPaused / ?IsPlaying / ?IsHooked   (00019DB0, 00019DC0, 00019DE0, 00019DD0, 00019DF0)
  ?Copy@CSoundObject@@QAEXAAV1@@Z                     0007E1F0
  ??4CSoundObject@@QAEAAV0@ABV0@@Z  (operator=)       00019F40
  ?GetPredictionTail@CSoundObject@@QAEPAV1@KK@Z       0007E310
CSoundLibrary:
  ?Listen@CSoundLibrary@@QAEXAAVCSoundListener@@@Z    0007A4B0
  ?MixSounds@CSoundLibrary@@QAEXXZ                    00079D70
  ?UpdateSounds@CSoundLibrary@@QAEXXZ                 000796F0
  ?Init / ?Clear / ?ClearLibrary / ?Mute / ?SetFormat / ?SetEnvironment / ?AddSoundAware / ?RemoveSoundAware
CSoundData:
  ?ClearBuffer@CSoundData@@QAEXXZ  00076200,  AddObjectLink 000760B0, RemoveObjectLink 000760D0,
  PausePlayingObjects 00076070, ResumePlayingObjects 00076090, Read_t 00076240
Data:
  ?_pSound@@3PAVCSoundLibrary@@A      002097D4   (sound library singleton)
  ?_pSoundStock@@3PAVCStock_CSoundData@@A  0020C2FC
```

(The full dump is in the user's possession; ask for it if you need it.) No `CommitPlayingBuffer` appears in this dump; it may be beta-only.

### 6.3 Leads `[UNVERIFIED]`

- The 1.10 engine **software-mixes** all sounds into one stereo stream (`MixSounds` and the mixer in `SoundMixer.cpp`); `Update3DEffects` computes per-sound left/right volume, phase and pitch for that mixer. The Steam DSOAL log shows only a couple of buffers (apparently placed at ±1 on x), which fits software mixing with DS3D used as a stereo output. The beta uses one DS3D buffer per sound. If this is right, the beta and Steam differ architecturally, and the "mute the software mix, play through a shadow buffer" plan depends on how the software mixer treats zero-volume objects (task S2).
- SuperProject's `Core` (`Core/API/EnginePatches.cpp`, `Core/Patches/SoundLibrary.cpp`, as relayed) registers patches for `CSoundLibrary::Listen` and `CSoundObject::Update3DEffects` via a `CreatePatch(...)` helper over XGizmo's `CPatch`. CoreLib was archived in March 2025, so the live code may sit under `SuperProject` instead.
- `IDirectSound3DBuffer` vtable slots (counting `IUnknown` as 0–2): `GetAllParameters` 3, `GetConeAngles` 4, `GetConeOrientation` 5, `GetConeOutsideVolume` 6, `GetMaxDistance` 7, `GetMinDistance` 8, `GetMode` 9, `GetPosition` 10, `GetVelocity` 11, `SetAllParameters` 12, `SetConeAngles` 13, `SetConeOrientation` 14, `SetConeOutsideVolume` 15, `SetMaxDistance` 16, `SetMinDistance` 17, `SetMode` 18, **`SetPosition` 19 (offset 0x4C)**, **`SetVelocity` 20 (0x50)**. `IDirectSound3DListener`: `SetDopplerFactor` 12, `SetOrientation` 13, `SetPosition` 14, `SetRolloffFactor` 15, `SetVelocity` 16, `CommitDeferredSettings` 17. `IDirectSoundBuffer`: `Lock` 11, `Play` 12, `SetCurrentPosition` 13, `SetVolume` 15, `SetFrequency` 17, `Stop` 18, `Unlock` 19. `IDirectSound`: `CreateSoundBuffer` 3. **Verify these against `dsound.h`** (find it in the Windows SDK or the SDK folders) before using them as search patterns.
- IIDs useful for xrefs: `IDirectSound3DListener` `{279AFA84-4981-11CE-A521-0020AF0BE560}`, `IDirectSoundBuffer` `{279AFA85-...}`, `IDirectSound3DBuffer` `{279AFA86-...}` (same tail). Verify.

---

## 7. Tasks

Work in the order below. Write each result to its own file in `findings\` (names given). Report to the user after **Stage 1 (orientation)** and again at the end.

### Stage 1 — Orientation (output: `findings\00-orientation.md`)

- Inventory each folder: which DLLs/EXEs, versions, PE timestamps, hashes. Identify which beta module contains the sound code (probably `Engine.dll`) and which Steam module (`Engine.dll`).
- **Export diff.** Dump the exports of the beta engine DLL and the Steam `Engine.dll`. Diff the sound-related symbols (`CSound*`, `Update3DEffects`, `Listen`, `CommitPlayingBuffer`, etc.). Cross-check against the static libraries' symbols. Report what exists in both, what exists only in the beta.
- Locate the user's DSOAL log; summarize its structure (call names, argument layout, which interfaces it covers). Re-derive the facts in 6.1 from the real log, with counts, and list every deviation.
- Identify the DirectSound API version the beta uses (`DirectSoundCreate` vs `DirectSoundCreate8`, which `IDirectSound*` interface).
- Confirm or correct the vtable slot table in 6.3 using `dsound.h`.

### Task group A — Beta reverse engineering

**A1. DS3D call sites** (`findings\01-beta-dsound-callsites.md`). Find all indirect calls through `IDirectSound3DBuffer`, `IDirectSound3DListener`, and `IDirectSoundBuffer` in the beta (xrefs from the IIDs, `QueryInterface`, and vtable-offset call patterns). Produce a table: call-site address, containing function, method called. Map the functions to engine names using exports, static-lib symbols, and 1.10 source as guides. Establish which function is the beta's equivalent of `CSoundObject::Update3DEffects`.

**A2. Position and velocity construction** (`findings\02-beta-position-velocity.md`). Trace how the `SetPosition` and `SetVelocity` arguments are computed: world → listener space transform, any normalization or scale factor (the observed length ≈ 0.955 implies scaling), the source of the `dwApply` value (immediate vs deferred), and the origin of large-magnitude cases like the 57.6 outlier. State the formula in pseudocode with the addresses it came from. Check whether `CommitDeferredSettings` is called, and where.

**A3. Volume and pitch** (`findings\03-beta-volume-pitch.md`). Trace the path from the engine's float volume (`so_sp3.sp3_fMaxVolume`, distance factor, listener volume, etc.) to the centibel value in `SetVolume`: formula, clamping, any lookup table. Determine how the pitch argument of `Set3DParameters` reaches the buffer (log shows `SetFrequency(0)` always: is pitch dropped, folded into something else, or applied by resampling?). Determine whether Doppler is done only by DS3D or also in software.

**A4. Buffer creation and lifecycle** (`findings\04-beta-buffer-lifecycle.md`). Document `DSBUFFERDESC` flags and `guid3DAlgorithm`, how PCM gets into the buffer (static / `Lock`+`Unlock` / streaming), looping, pooling or reuse of buffers (about 370 creations were logged), the voice limit, and what the beta does on `Pause`, `Resume`, `SetOffset`, `SetDelay`, `Stop`, and on level change/clear. Find where `SetMode` 1 vs 2 is chosen (what kind of sound gets `DISABLE`).

### Task group B — Steam build analysis

**S1. Hook surface** (`findings\05-steam-hook-surface.md`). For each export in 6.2: confirm its address matches the stock Steam `Engine.dll` (re-derive from the binary, do not trust the dump blindly), its calling convention, argument types, and what it does. Compare the Steam disassembly of `Update3DEffects` and `Listen` against the 1.10 source: do the structure offsets and logic match, so that 1.10 headers can be used safely against this binary? List any divergence.

**S2. Mixer behavior with muted objects** (same file). Read the mixing path (`MixSounds`, the mixer loop, how `so_spNew`/`so_sp` volumes are consumed). Answer: *if a sound object's left and right volume are zero, does the mixer still advance its playback position and report it finished at the correct time, or does it skip it?* This decides whether the shadow-buffer design is viable. Also find how the engine reaches a sound's PCM data (`CSoundData` buffer pointer, sample count, format, channel count) and where the engine's output DirectSound buffers are created.

**S3. Existing hooks** (`findings\06-core-patch-mechanism.md`). In `SuperProject` and `XGizmo`, find where `CSoundLibrary::Listen` and `CSoundObject::Update3DEffects` are patched, what the replacement bodies do, how patches are registered, how the trampoline/original-call works, how a console variable is declared, and how game-version selection (`SE1_VER`, `CHOOSE_FOR_ENGINE`, build checks) affects what is hooked. Quote file paths and line ranges. Determine whether `Play_internal` and `Stop_internal` can be hooked the same way, and whether the plugin API allows engine patching.

### Stage final — Consolidation (`findings\99-summary-and-open-questions.md`)

- One-page parameter sheet: everything the implementation needs (position formula, volume curve, pitch/Doppler handling, apply mode, buffer flags, lifecycle events), each tagged `VERIFIED`/`LIKELY`/`HYPOTHESIS`.
- Beta ↔ Steam function mapping table.
- Verdict on the viability of the shadow-buffer plan, with the S2 answer stated explicitly.
- Remaining unknowns, ranked by risk, each with a concrete suggested way to resolve it (including anything that requires running the game, which the user must approve).

---

## 8. Known risks to keep in mind while you work

- Shadow buffers and engine state can desynchronize on `Pause`/`Resume`, `SetOffset`, `SetDelay`, window focus loss (`Mute`), level changes, savegame loading (`Read_t`), and copied sound objects (`Copy`, `operator=`, prediction tails). Note every place the beta or engine handles these, as they define the lifecycle spec.
- DS3D requires **mono** buffers. Note how the beta treats stereo sounds (likely mode 2 / non-3D).
- If both the software mixer and a DS3D path apply Doppler, it is applied twice. Note exactly where the beta applies it.
- Streaming sounds (e.g. Ogg) may use a different path from static sound data.

## 9. Reporting style

Be concise and specific. Lead with the answer, then evidence. Use tables for address maps and parameter sheets. When you finish a stage, summarize in five lines or fewer in chat and point to the findings file.
