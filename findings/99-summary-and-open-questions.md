# 99 — Summary and open questions (final stage)

One-page parameter sheet + beta↔Steam mapping + viability verdict, consolidating
findings 00–06. Every item tagged VERIFIED (binary+log/source cross-checked),
LIKELY, or HYPOTHESIS. Addresses: **beta VA − 0x10000000**, **Steam RVA** (ImageBase
0x600C0000). Ground truth for *what* the beta calls: `dsoal_log.txt`; for *why/how*:
beta Engine.dll disassembly (findings 01–04).

---

## 1. Implementation parameter sheet (what the DS3D mode must do)

### 1.1 Spatial parameters (per 3D mono sound, per frame)

| # | Parameter | Value / formula | Confidence | Source |
|---|---|---|---|---|
| 1 | Listener setup (once per device init) | `QI(3DListener)` on primary; `SetPosition(0,0,0)`, `SetOrientation(0,0,1, 0,1,0)`, `SetVelocity(0,0,0)`, **`SetRolloffFactor(0.0)`**, **`SetDopplerFactor(1.1)`**, all apply=IMMEDIATE. Listener never touched again. | VERIFIED | 02 §6, 04 §1 |
| 2 | Distance factor `w` | `1` if `dist ≤ hotspot`, else `(falloff−dist)/(falloff−hotspot)`; listener skipped entirely if `dist > falloff` | VERIFIED | 02 §2 |
| 3 | Position (DS3D args) | `SetPosition(Σ(rotate(worldΔ)·w)/Σw . x, .y, **−.z**, DS3D_DEFERRED)` — multi-listener weighted average of listener-space deltas; **length = true distance, NOT normalized**; if no entity or all listeners out of range: parked `(0,0,10000)` → logs as `(0,0,−10000)` | VERIFIED | 02 §2/§4/§7 |
| 4 | Velocity (DS3D args) | `SetVelocity(relVelRotated .x, .y, −.z, DS3D_DEFERRED)` where `relVel = entityVel − listenerVel` rotated by listener matrix, same weighting | VERIFIED | 02 §5 |
| 5 | Volumetric near-field | inside hotspot & (SOF_VOLUMETRIC or decoder): angle = `ACos(dot(normalize(dir), (0,0,−1))) × bias`, `bias = min((dist−hotspot)/(falloff−hotspot)×3, 1)`; bias=0 (inside hotspot) → position `(0,0,−1)`, speed 0; bias ≥ 1 → plain rotated delta; 0<bias<1 → axis-lerp blend toward the `(0,0,−1)` basis → ~unit vectors (the log's 101K `(0,0,1)` = `(0,0,−1)` z-negated) | VERIFIED (LC cross-check; the `_DAT_101b8ca8 = 0.0` "angle scale" was a Ghidra misread — it is the volumetric-bias default) | 02 §3, 07 §14.4 |
| 6 | Apply mode | `SetPosition`/`SetVelocity`/EAX DirectHF: **DEFERRED (1)**; `SetVolume`/`SetFrequency`: IMMEDIATE (0); `SetMode`: IMMEDIATE; **one `CommitDeferredSettings()` per frame after all sounds** | VERIFIED | 02 §6, 01 §3 |
| 7 | Buffer mode | `SetMode(DS3DMODE_HEADRELATIVE=1, 0)` for 3D mono sounds; **`DISABLE(2)` for mono non-3D / `SOF_VOICE` sounds** — `SetMode` is only called inside the mono commit path, **stereo sounds never get `SetMode`** (log 206×1 / 21×2; the 227-vs-228 SetMode/duplicate residual stays open) | VERIFIED (LC + beta 0x1008269d) | 04 §2/§3, 07 §14.1 check 6 |

### 1.2 Volume / filter / pitch

| # | Parameter | Value / formula | Confidence | Source |
|---|---|---|---|---|
| 8 | Engine volume (0..1 float) | `clamp01(Σ(L.vol × so.curVolume × w²)/Σw)`, then crossfade (`Fade()`), then master `× snd_fSoundVolume` (music: `× snd_fMusicVolume × 0.5`) | VERIFIED | 03 §1 |
| 9 | Per-CSoundData budget | `snd_iMaxSameSounds` (default 5): per-frame running sum; over-budget objects get volume 0 (silent, still playing) | VERIFIED | 03 §1 |
| 10 | **Centibel curve** | `v ≤ 0.005 → −10000`; else (`snd_bLinearVolume`=1, default): `cB = ftol(3000×(v(v−1)+(1−v)·log10 v))`; else `cB = ftol(3000×log10 v)` — predicts log's −538/−1436/−2157 exactly | VERIFIED | 03 §2 |
| 11 | `SetFrequency` | `pitch==1.0 → 0 (DSBFREQUENCY_ORIGINAL)`; else `ftol(data.nSamplesPerSec × pitch)`. NOT doppler. | VERIFIED | 03 §3 |
| 12 | Doppler | **once**: DS3D only (`SetVelocity` + DopplerFactor 1.1) on the DS3D path; software `c=300 m/s` formula only for waveOut/decoder sounds | VERIFIED | 03 §4 |
| 13 | EAX per-buffer | if 3D && playing && EAX: `DirectHF = clamp(round(−100 × hfFactor), −10000, 0)` via `KsPropertySet::Set(EAX20_Buffer, 0x80000003, …)` (DEFERRED) — **the `Set` is issued also when `snd_bUseEnvironmentFX == 0`, with value 0** (beta skips only the computation, not the call; our design gates it — cvar-off only, low priority) | VERIFIED | 03 §5, 07 §14.2 |
| 14 | Buffer flags | mono 3D template: `CTRL3D\|CTRLFREQUENCY\|CTRLVOLUME\|MUTE3DATMAXDISTANCE\|LOCDEFER`; stereo 2D: `CTRLFREQUENCY\|CTRLPAN\|CTRLVOLUME\|LOCDEFER`; `guid3DAlgorithm` from `snd_iEmulationType` (0/1/2 = DEFAULT/HRTF_LIGHT/HRTF_FULL); PCM written once via Lock/Unlock | VERIFIED | 04 §2 |

### 1.3 Lifecycle / channel management

| # | Event | Behavior | Confidence | Source |
|---|---|---|---|---|
| 15 | Voice budget | `snd_iMaxVoices` (default 30, clamp 4–64) channels; commit gate = `!held && !silent(<0.005, post-budget so+0x64) && !paused` — **silent sounds never commit and never consume a voice; held + silent > 10 s → non-forced release (orphan plays out)**; steal lowest-volume channel only if `newVol − lowest > 0.333`, else denied this frame; over-voice-budget held buffers are force-released (beta 0x10082aa2-0x10082ad1) (**our design deviates twice: budget-denied voices fall back to audible software via `bBypass`, 07 §13 item 19; and the D8 silence test runs pre-budget, 07 §13 items 21/26**) | VERIFIED | 04 §3, 07 §14.1 check 2 |
| 16 | Buffer instantiation | `DuplicateSoundBuffer(template)` per (re)commit + `QI(3DBuffer)` (+ `QI(KsPropertySet)` if 3D&EAX) + `SetMode` + `SetCurrentPosition(0)` | VERIFIED | 04 §3 |
| 17 | Stop/finish | `Stop` clears PLAY + releases channel (non-forced: owner cleared only; **orphaned buffer plays out**); finish rule (verified): `!playing && !pauseGated && !loop && (!SOF_WAITING(0x10000000) \|\| elapsed > sd_tmLength)` → `Stop(1)`, else `Play(0,0,loop?)`; `SOF_WAITING` cleared after both, set at commit and at pause-stop | VERIFIED | 04 §3/§4, 07 §14.1 check 2 |
| 18 | Pause | **releases buffer immediately** (`ReleasePlayingBuffer(force)`); Resume → recommitted next frame — **always at `SetCurrentPosition(0)`**: the recommit's offset computation is dead in the beta (constant 0 at 0x10082BFB; the `GetElapsedTime(0)` result is discarded — LC has the same shadowed-local bug, 07 §14.3 item 1); timers are preserved for the finish rule only. Our synced-offset recommit is an improvement, not parity | VERIFIED | 04 §5, 07 §14.1 check 3 |
| 19 | Format/level change, focus loss | `SetFormat`: Pause-all → ClearBuffer-all → re-init DS → Reload → Resume | VERIFIED | 04 §1 |
| 20 | Game pause (network) | per channel (not SOF_NONGAME): **no `SetVolume(−10000)`/`SetFrequency(0)` — the volume/frequency sets are skipped on gated frames entirely**; a playing buffer gets `SOF_WAITING` + `Stop()` only; sets resume on the first ungated frame before the re-`Play` (corrected 2026-10-16 — the old "mute path" was a misreading; the log's −10000 comes from the 0.005 silence gate) | VERIFIED | 04 §4, 07 §14.1 check 1 |
| 21 | Beta software mixer | In DS3D mode mixes **decoder sounds only** → no double audio | VERIFIED | 04 §6 |

---

## 2. Beta ↔ Steam function mapping

| Role | Beta (TSE150) | Steam (TSE107, = 1.10 source) | Note |
|---|---|---|---|
| Per-object spatial update | `CSoundObject::Update` (RVA 0x875E0) + static core 0x87970 | `CSoundObject::Update3DEffects` (RVA 0x7E870) | different struct layout (beta: channels/flags at 0x28/0x2C, DS pos cached at 0x48–0x68; 1.10 layout confirmed in 05 §1.1) — **do NOT port beta structs** |
| DS3D driver | `CSoundLibrary::PlayBuffers` (0x829F0) | *(none — Steam has no per-sound DS3D)* | must be written wholesale in the patch |
| Frame scheduler | `UpdateSounds` (0x81F40): sort by volume, budget, PlayBuffers, commit | `UpdateSounds` (RVA 0x796F0): Update3DEffects loop, Prepare, no DS3D | hook both `UpdateSounds`-per-object entry points via `Update3DEffects` (called directly at 0x79BA0) |
| Buffer commit/release | `CommitPlayingBuffer` (0x82560) / `ReleasePlayingBuffer` (0x82740), 64×0x14 channel array @ +0x74 | — | new subsystem in the patch |
| Mix buffer | stereo mix buffer, mixer gated to decoder sounds | two mono `sl_pDSSourceLeft/Right` @ ±1 (log-corroborated) | leave Steam's intact; shadow buffers are additive |
| Play/Stop | `Play(CSoundData*, ULONG)` 0x872D0, `Stop(int)` 0x87450, `Stop_internal(int)` 0x874D0 | `Play(CSoundData*, LONG)` 0x7E480, `Play_internal` 0x7E500, `Stop` 0x7E750, `Stop_internal` 0x7E810 | **Steam `Play_internal` inlines `Stop_internal`** (05 §1.3) — release shadow in the `Play_internal` wrapper |
| Listener registry | `sl_lhActiveListeners` @ +0x38 | same list @ CSoundLibrary+0x94 | `Listen` (Steam 0x7A4B0) = 1.10 source verbatim |

## 3. Verdict on the shadow-buffer design — VIABLE, with two conditions

1. **Muting works — CORRECTED (Phase 2 Task 1; findings/07 §7.2/§7.4)**: the original
   Phase-1 claim that a zero-volume object "advances offsets and clears SOF_PLAY **on
   schedule**" was right for **looping** sounds only. Instruction-level
   (`0x6013b1e0 je → 0x6013b29e`, no end-of-buffer check; = `SoundMixer.cpp:637-649`)
   a zero-volume **non-looping** sound has `SOF_PLAY` cleared after **one mix block**.
   ⇒ zero-volume muting cannot be the mode's mechanism (it would kill every one-shot).
   Corrected mechanism (design 08): intercept static `MixSound` (RVA 0x7AF80, single call
   site in `MixSounds`) so shadowed objects are never mixed/advanced/finished in
   software; the DS shadow buffer owns playback (beta model, 04 §6) and finish comes
   from `GetStatus` bookkeeping that clears `SOF_PLAY` itself. No engine state is
   poisoned (spNew/sp keep real values).
   **Condition A — decoder sounds**: `SDF_ENCODED` objects are never advanced by the mute
   path and would hang `SOF_PLAY` forever; they must **not** be muted — keep them in the
   ordinary software mix (beta did the same, findings 04 §6) and give them no shadow buffer
   (or route via mode-2 semantics).
   **Condition B — pause/mute gates**: `bGamePaused`(SOF_NONGAME), `SOF_PAUSED` and
   `_bMuted` are checked in `MixSounds` *before* `MixSound`; a shadow buffer must honor
   them itself (beta: Pause = release buffer immediately, 04 §5; game-pause = SetVolume(−10000)
   + Stop, 04 §4).
2. **Hooking works** `[VERIFIED]`: `Play_internal`/`Stop_internal` are exported
   (`TSE107\Engine.def` 2167/2817) and hook exactly like `Listen` (linked import stub +
   `CreatePatch`, findings 06 §4a/§7). Caveats: hook `Play_internal` (which subsumes the
   inlined `Stop_internal`) for lifecycle; per-frame shadow updates belong inside the
   existing `P_Update3DEffects` replacement (full replacement, no trampoline — 06 §2);
   `UpdateSounds` calls it directly, so one hook covers all call sites.
   `P_Listen` needs no change (beta listener handling is engine-side of the shadow design).
3. **No double audio / no double doppler** `[VERIFIED]`: see param sheet #12 and the
   mixer gating above.

## 4. Remaining unknowns (ranked by risk)

| # | Unknown | Risk | Suggested resolution |
|---|---|---|---|
| 1 | ~~Exact beta stereo-pair behavior of the **volumetric blend angle constants**~~ **RESOLVED (2026-10-16, LC cross-check — 07 §14.4)**: angle = `ACos(dot(dir,(0,0,−1))) × bias` with `bias = min((dist−hotspot)/(falloff−hotspot)×3, 1)`; bias=0 → `(0,0,−1)` + zero speed; bias ≥ 1 → plain rotated delta. `_DAT_101b8ca8 = 0.0` was a Ghidra misread (it is the volumetric-bias default). Sheet row #5 → VERIFIED. | ~~low-med~~ none | none — recorded |
| 2 | ~~Beta `Fade()`/crossfade semantics + menu-state volume factors~~ **RESOLVED (2026-10-16, LC cross-check — 07 §14.4)**: `Fade` lerps volume toward the fade target over the fade time; a fade completing at target 0 stops the sound. The menu-state factors `DAT_1022e9d8/d4` are `_bMuteVolume` (→ 0) and `_bAttenuateVolume` (→ 0.5 except `SOF_VOICE`; set when a voice sound > 0.2 is pending) — Steam has neither, N/A. Decision unchanged: not reproduced (no Steam Fade API). | ~~low~~ none | none — recorded |
| 3 | DSOAL behavior of `MUTE3DATMAXDISTANCE` + rolloff 0 + parked `SetPosition(0,0,−10000)` on **non-DSOAL** stacks (real Creative/Windows dsound, OpenAL Soft w/o wrapper) — parked buffers might still be faintly audible if a driver ignores flags | med for correctness on non-DSOAL hardware | runtime test (needs user approval to run the game with a test build); mitigation: also `SetVolume(−10000)` when parked (beta does exactly this — log shows parked = position(0,0,−10000) **and** volume −10000) — so reproduce both, which the sheet already specifies |
| 4 | `UpdateSounds`-side EAX listener env presets (`SetEnvironment` 0x81C20 / env table @ 0x1020f7c8) if the mode wants EAX listener parity | low (optional feature) | dump 17-dword table + Steam `SetEnvironment` (RVA 0x781B0, `(long,long,float)` signature differs) if pursued |
| 5 | Whether `snd_iMaxSameSounds` budget and `Fade` should ship in the Steam mode at all (they're beta features, not DS3D-specific) | low | product decision: recommend including budget (prevents same-sample pileup under HRTF) |
| 6 | Beta `SndPostFunc`/re-init trigger set for the new cvars (which changes require full DS re-init vs shadow-buffer recreate) | med (stability) | runtime test after implementation: toggling `snd_iEmulationType` must recreate templates/buffers; confirm DSOAL handles GUID change on live device or force `SetFormat` path. **Update (2026-10-15): mechanism in place — the design forces the `SetFormat` path (template release + `SetFormat(sl_EsfFormat)` post-handler) and recreates running shadows (07 §13 item 15); runtime test pending at 08 §11 step 6** |
| 7 | ~~`CreatePatch`/`HFuncPatch` exact signatures (off-disk, empty API submodule)~~ **RESOLVED (Phase 2 Task 0, 2026-10-13)**: API repo now cloned at project root (`API\`, SamClassicPatch/API @ main 8362c52); `CreatePatch` template + `HFuncPatch` + `CreateOpcodePatch`/`DestroyPatch`/`FuncPatch_ForceRewrite` quoted and verified in 06 §10.1; trampoline pattern confirmed for `Play_internal`/`Stop_internal`/`UpdateSounds`/`SetFormat` (06 §10.3); `SE1_VER` values recorded (`SE1_107=107`, `SS_TSE='S'` — 06 §10.4). Build note: populate the `SuperProject\API` submodule itself before compiling (06 §10 caveat). | ~~low~~ none | none — recorded |

### Explicitly resolved / no longer open
- `CreatePatch`/`HFuncPatch` signatures + trampoline applicability to the four new hooks +
  `SE1_VER` values `[VERIFIED — Phase 2 Task 0]` — 06 §10.
- Volumetric blend formula + `Fade()` semantics + menu-state factor identification
  `[VERIFIED — LC cross-check 2026-10-16]` — 07 §14.4.
- Beta flag names: 0x40 = `SOF_VOICE`, 0x10000000 = `SOF_WAITING`, 0x40000000 = `SOF_LOADED`
  (not SOF_2D / "has hw buffer" / SMOOTHCHANGE) `[VERIFIED — LC cross-check]` — 07 §14.3 item 2.
- Beta recommit offset is always 0 (dead computation in both beta and LC) — our synced
  release is an improvement, not parity `[VERIFIED]` — 07 §14.3 item 1.
- Beta pause path: no `SetVolume(−10000)`/`SetFrequency(0)` on gated frames (skip + WAITING +
  Stop) `[VERIFIED]` — 07 §14.1 check 1.
- `dwApply=1` = DEFERRED `[VERIFIED]`; CommitDeferredSettings present (46,444×) — 00 §4.1.
- No `SetAllParameters`, no cone/min/max distance setters — 00 §4.1, 03 §6.
- Steam mixer zero-volume behavior = S2 answer — 05 §2.
- DirectSound (not DS8), interfaces 3DListener/3DBuffer/KsPropertySet; vtable slots verified against DSOUND.H — 00 §3.
- Steam Engine.dll ≡ 1.10 source for every sound function examined — 05 §1.2.

## 5. Proposed patch skeleton (for the next phase, analysis only)

- cvar `snd_bDS3DSpatial` (persistent user INDEX, default 0) declared via `_pShell->DeclareSymbol`
  in a new `ICorePatches::SoundLibraryDS3D()` (or inside existing `SoundLibrary()`).
- New static subsystem (in `Core/Patches/`): channel table (≤64), created lazily by
  reusing the engine's `IDirectSound*` (`_pSound` @ Steam RVA 0x2097D4 →
  **`sl_pDS` @ CSoundLibrary+0x34** `[VERIFIED — RESOLVED session 4 by reading Steam
  StartUp_dsound @ RVA 0x78840; full DS-pointer map in 05 §1.1a: `sl_pKSProperty`@+0x38,
  `sl_pDSPrimary`@+0x3C, `sl_pDSSecondary(2)`@+0x40/+0x44, `sl_pDSListener`@+0x48,
  `sl_pDSSourceLeft/Right`@+0x4C/+0x50, `sl_bUsingEAX`@+0x1C, `_hInstDS`@RVA 0x2097E4]`],
  templates duplicated per play per sheet #16. Caveat from the same read: the engine's
  listener init = 1.10 source 506-519 (rolloff 1.0 DEFERRED, no doppler) — the DS3D mode
  must apply the BETA listener params (rolloff 0.0, doppler 1.1) itself and re-apply
  them after every engine `SetFormat` re-init.
- Hooks: keep `P_Listen`, `P_Update3DEffects` (extend: compute DS3D pos/vel/vol/freq
  per sheet, drive shadow buffers; **no volume zeroing — superseded, see §3 correction
  and 07 §7.4**), new `P_Play_internal` / `P_Stop_internal` wrappers for create/release
  (call original via trampoline first — unlike the existing full replacements), plus
  per 07 §13: `UpdateSounds`/`SetFormat`/`Mute`/`ClearBuffer` wrappers, `~CSoundObject`
  hook, and the static-`MixSound` intercept (RVA 0x7AF80) as the mute mechanism.