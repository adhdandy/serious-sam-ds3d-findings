# 08 — SoundDS3D module design (Phase 2, Task 2)

Design of the opt-in DS3D shadow-buffer mode. Parameter values come from `99 §1`
(spec of record, cited as `99 #n`); mechanism facts from `07` (cited as `07 §n`);
hook mechanics from `06` (cited as `06 §n`). **Deviations from the addendum §4 sketch
are listed first** (per the addendum §1 deviation rule — reasons are in 07).

## 0. Deviations from the addendum's §4 sketch (all evidence-based)

| # | Addendum sketch | Design here | Reason (07) |
|---|---|---|---|
| D1 | Mute = zero `so_sp`/`so_spNew` L/R in `P_Play_internal`/`P_Update3DEffects` | **No engine-state poisoning at all.** Shadowed objects are intercepted at static `MixSound` (RVA 0x7AF80, raw-address hook, single call site 0x6013a02c in `MixSounds`) and never mixed/advanced/finished in software | Zero-volume non-looping sounds are killed after one mix block (07 §7.2, binary 0x6013b1e0→0x6013b29e); the beta's own mixer never touches non-decoder DS sounds (04 §6) |
| D2 | (implicit) `Stop_internal` hook suffices for release | Additional hooks: `~CSoundObject` (inlines Stop_internal, def L384), `Mute` (def L2075; DS keeps playing during muted windows), `ClearBuffer` (def L982; template cache lifetime) | 07 §12.1, §7 companion, §G1 |
| D3 | "no software doppler on the engine-side pitch" as an active change | No change needed: the engine pitch of shadowed sounds is a dead value under D1 (mixer bypassed, nothing serializes — 07 §7.4, §12.2). 1.10 math in `P_Update3DEffects` stays untouched | 07 §G4b |
| D4 | `P_Update3DEffects`: "…then zero `so_spNew` L/R (mute)" | Replaced by: keep real values (they are the correct software-fallback state — `DropToSoftware` and budget fallback are seamless) | 07 §7.4, §G9.5 |
| D5 | Driver runs per-object inside `P_Update3DEffects`, engine list order | `P_Update3DEffects` is **store-only**; the DS driver runs in the `P_UpdateSounds` tail over the **volume-sorted** table (beta `PlayBuffers` structure; enables the beta's per-frame sort for voice stealing) | 04 §3/§4; user-approved 2026-10-14, 07 §13 item 7 |
| D6 | Finish = not-playing + play-cursor-at-end (cursor-based) | `bStarted`-based pure beta finish rule; failures = HRESULT / BUFFERLOST / TERMINATED only; G9 rule 4 deleted | user-approved 2026-10-14, 07 §G9 item 4 |
| D7 | Voice-budget overflow = "uncommitted, silent this frame" (99 #15, addendum §4 sketch defers to it) | Budget-denied voices fall back to **audible software** via the `bBypass` flag (§4 step 2, §6) | Finish-authority hole: a never-committed entry is mixer-bypassed so nothing clears its `SOF_PLAY` (silent zombie, `IsPlaying()` true); beta silence would require virtual advancement — reimplementing the stock skip path — rejected; 07 §13 item 19 |
| D8 | (implicit) every eligible playing sound is committed; parked buffers never released | **Silent sounds are not committed**: pre-budget spatial volume < 0.005 and no buffer → no commit attempt, no voice slot, no DS calls (`bBypass=false`, software-silent fallback); held + silent > 10 s → `ReleaseForRecommit` + `bBypass=false`; silent → audible → normal commit at the live offset | Without it, out-of-range ambients exhaust `snd_iMaxVoices` and push audible sounds into software fallback; beta PlayBuffers 0x10082b99-0x10082b6e (silence gate + 10 s non-forced release, verified 2026-10-16); user decision 2026-10-16 — 07 §14.5 / §13 items 21-28 |

## 1. Files and build gating

- New: `Core\Patches\SoundDS3D.h` / `SoundDS3D.cpp` (subsystem: state tables, driver,
  DS helpers) + extend `Core\Patches\SoundLibrary.h/.cpp` (hook bodies live with the
  existing patch classes; `SoundDS3D.cpp` holds everything else). No other patch touched.
- Registered from `ICorePatches::SoundLibrary()` (`EnginePatches.cpp:393-401`), which
  already runs post-init, game-client only (06 §1).
- Feature gate: `#if SE1_VER == SE1_107 && defined(NDEBUG) && _PATCHCONFIG_ENGINEPATCHES`
  — value `107` is unique to the TSE107 configs (06 §10.4); `defined(NDEBUG)` because the
  raw `MixSound` address (RVA 0x7AF80) is a *release* `Engine.dll` address
  (Debug_TSE107 loads `EngineD.dll`; precedent for the NDEBUG pairing:
  `EnginePatches.cpp:346` Ska). Everything compiles to no-op in other builds.

## 2. Console variables (declared once, in the new registration; pattern 06 §5)

| Cvar | Type/default | Notes |
|---|---|---|
| `snd_bDS3DSpatial` | persistent user INDEX, **0** | the mode switch; read only in game-thread hooks |
| `snd_iEmulationType` | persistent user INDEX, 0 | `guid3DAlgorithm` 0/1/2 = DEFAULT/HRTF_LIGHT/HRTF_FULL (99 #14); beta name (absent in Steam — 07 §12.3); declared `post:` a helper that frees templates + calls `SetFormat(sl_EsfFormat)` (G6) |
| `snd_iMaxVoices` | persistent user INDEX, 30 (clamp 4..64) | voice budget (99 #15) |
| `snd_iMaxSameSounds` | persistent user INDEX, 5 (clamp 1..99) | per-CSoundData volume budget (99 #9) |
| `snd_bUseEnvironmentFX` | persistent user INDEX, 1 | EAX DirectHF gate (99 #13) |

Existing engine cvars read via `CSymbolPtr`: `snd_fSoundVolume` (0x602a40f8),
`snd_iInterface`, `snd_fEAXPanning`. `snd_bLinearVolume` does not exist — linear curve
hardcoded (07 §G10a).

## 3. Hooks

| Hook | Target | Type | Body |
|---|---|---|---|
| `P_Play_internal` | export 0x7E500 | wrapper, trampoline | (1) decide eligibility from args (`slFlags&SOF_3D`, `!SOF_MUSIC`, `pCsdLink`: `!SDF_ENCODED`, `nChannels==1`, `wBitsPerSample==16`); if eligible && cvar && gate: **pre-register** object in table (no buffer yet) — caller (`Play`) holds `sl_csSound` (single call site verified: `0x6013e4d1` in `Play`, full-disasm grep), so no mixer tick can mix an unregistered block (07 §7.4 first-block proof); (2) call original; (3) if re-play of an already-shadowed object: detach its old buffer to the **orphan list** (non-forced → plays out, 99 #17). Buffer creation is lazy (next driver pass — beta: "appears lazily at next PlayBuffers", 04 §5); the entry starts `bBypass=true` (§4 step 2). No post-original `so_fDelayed` reset — the original zeroes it on every non-SOF_LOADED play (07 §12.7) |
| `P_Stop_internal` | export 0x7E810 | wrapper, trampoline, **`FuncPatch_ForceRewrite(7)`** | call original; then remove from table; detach buffer → orphan list (99 #17 non-forced). **Prologue `56 8b f1 57 8b 4e 10` fails `CanRewriteInstructionSet` at +4 (`mov ecx,[esi+d8]` not in decoder table, patcher.cpp:28-224)**; 7 bytes ends on an instruction boundary and fits the `VirtualProtect(...,10)` window (offline check, findings §12) |
| `P_dtor` | export `??1CSoundObject@@QAE@XZ` **RVA 0x7E150** (07 §12.1 VA 0x6013e150; 08 earlier draft had a 0x72E50 typo) | wrapper, trampoline | **release shadow (force, no orphan) BEFORE original** — the dtor inlines Stop_internal (07 §12.1) |
| `P_Update3DEffects` | export 0x7E870 (existing full replacement) | replacement (extended) | existing 1.10 math kept verbatim (real spNew values = correct fallback state, D4); then, if object in table: **store-only** — write `pos`, `vel`, `vol`, `hf`, `bDelayPending`, gates snapshot into `DS3DShadow`; **no COM calls** (driver moved to `P_UpdateSounds` tail, §4), and set `bSpatialValid = TRUE` (§4 step 7 gate — 07 §13 item 18) |
| `P_UpdateSounds` | export 0x796F0 | wrapper, trampoline | original first (its loop calls `P_Update3DEffects` per object → shadow fields filled, `bSpatialValid` set); then under own `sl_csSound` (OPTEX-recursive, 07 §G8): **table validation** (drop entries with `!SOF_PLAY` — generic safety net for any unhooked stop; this is also where the stock mixer finishes `bBypass=false` fallback entries); **advance `so_fDelayed`** for `bDelayPending`, `bBypass=true` shadows only (07 §13 item 16); **sort the table by `fLastVolume` (beta per-frame sort, 04 §4) and run the per-frame driver (§4 steps 1-9, all DS calls, beta order; step 2 retries commits for fallback entries each pass — 07 §13 item 19)**; orphan scan (`GetStatus` → done → `Release`), **one** `CommitDeferredSettings` if listener present (G3/99 #6) |
| `P_SetFormat` | export **RVA 0x784A0** (export dump; earlier draft's 0x78180 points mid-instruction) | wrapper, trampoline | pre-original (own lock): free templates + orphan list (mark generation), then release ALL shadows via **`ReleaseForRecommit`** (07 §G4d/§13 item 14 — `bStarted`-guarded sync; entries **kept**, `bStarted`/`bSpatialValid` reset, `bBypass` stays true; `!bStarted` entries take the same primitive, sync inert); post-original: if `sl_pDSListener != NULL` re-apply beta listener params (99 #1: pos 0, orient 0,0,1/0,1,0, vel 0, rolloff 0.0, doppler 1.1, all IMMEDIATE) — **the next `P_UpdateSounds` tail recommits the kept entries at their synced offsets (RECREATE — one silent frame accepted; 07 §13 item 15; makes the `snd_iEmulationType` toggle observable on running sounds)**; else `DropToSoftware` every entry + forced mode disable + console notice (G2/G6 — cvar-off drain semantics unaffected) |
| `P_Mute` | export 0x782B0 | wrapper, trampoline | original (zeroes mix buffers, sets `_bMuted`); then `SetVolume(-10000)`+`Stop()` on all playing shadow buffers and **set `bGateStopped`** (§4 step 7), **buffers kept** (DS preserves play cursor; first `UpdateSounds` resumes them — 07 §G7 companion) |
| `P_ClearBuffer` | export 0x76200 | wrapper, trampoline | original (frees `sd_pswBuffer`); then release the cached template for that `CSoundData` (G1; covers `Reload` after `SetFormat`, `Clear`, destruction). Shadows of that data: owner still playing → **`ReleaseForRecommit`** (07 §G4d/§13 item 14 — `bStarted`-guarded sync, entry kept; `Reload` re-reads the PCM and the recommit refreshes `psdKey` + cached format from `so_pCsdLink`, §4 step 2); destruction path (owner dead) → plain release (defensive; the dtor hook already removed the entry) |
| `P_MixSound` | **static RVA 0x7AF80** (`ADDR_ENGINE + 0x7AF80`, raw-address like `ADDR_RENDERLENSFLARES`, 06 §4b) | wrapper, trampoline | **byte-compare `55 8b ec 83 ec` at the target address + module identity check before patching; mismatch → refuse the mode + console notice, never patch** (patch-creation failure is fatal in release, 06 §3 / IPatches.cpp:102). If patched: `pso` in table **and entry `bBypass`** → return (skip; no DS calls, no cvars); else call original (fallback entries — `bBypass=false`, 07 §13 item 19 — are mixed by the stock mixer; that is the design) |

`P_Listen` and the engine's ear pair are untouched (99 §2 note). `ForceRewrite`
(06 §10.1) is needed **only** for `P_Stop_internal` (7 bytes); all other eight
prologues pass `CanRewriteInstructionSet` in the offline byte-level simulation
against the Steam binary (2026-10-14, details 07 §13 item 9): rewriteLen 5 = dtor/
Play_internal/UpdateSounds/SetFormat/Mute, 9 = Update3DEffects, 6 = ClearBuffer,
6 = MixSound (raw-address hook additionally gated on the prologue byte-compare).

## 4. Per-frame driver (in the `P_UpdateSounds` tail, over the **volume-sorted** shadow table; = beta `PlayBuffers` order, 04 §4 / 99 §6 acceptance row)

**Restructured (approved 2026-10-14; amended 2026-10-15):** `P_Update3DEffects` only
computes and stores spatial values (no COM calls); the `P_UpdateSounds` tail runs the
table validation (`!SOF_PLAY` → drop) and the `so_fDelayed` advance for
`bDelayPending`, `bBypass=true` shadows (07 §13 item 16) **before** the sort; it sorts
the table by `fLastVolume` (beta per-frame sort — required for voice stealing,
04 §3/§4) and performs all DS calls in beta order, retrying commits for fallback
(`bBypass=false`) entries (07 §13 item 19), then commits once. All game-thread under
the original `UpdateSounds`' `sl_csSound`. All DS calls on the shadow only. Order per
sound (matches the beta's per-frame call sequence for the acceptance log):

1. **`SOF_PAUSED` gate** → `ReleaseForRecommit` (07 §13 item 14 — `bStarted`-guarded
   sync into `so_fLeft/RightOffset` + past-delay sentinel, entry kept, `bBypass`
   stays true); skip (recommit on resume at
   `SetCurrentPosition(bytes(so_fLeftOffset))` = the synced offset — 99 #18).
2. **silence gate (D8, 07 §13 items 21-25)**: `silent = storedVol ×
   snd_fSoundVolume < 0.005` — the test runs **after** the master, **before** the
   same-sounds budget (deliberate deviation from the beta's post-budget gate, 07
   §14.5; the stored `vol` of step 3 is pre-master/pre-budget, the master is applied
   here for the test only). **No buffer && silent** → no commit attempt, no voice
   slot, **no DS calls at all** (beta 0x10082b99-0x10082bc9), `bBypass = false`
   (stock mixer owns the entry; software is silent too — out-of-range `so_sp`
   volumes are ~0; accepted ≤ −46 dB edge, 07 §13 item 22). **Buffer held &&
   silent** → keep parked (steps 4-9 as-is: sentinel position + `SetVolume(−10000)`,
   buffer keeps playing) + run the silent-since timer (game tick, real time for
   `SOF_NONGAME`): audible again within 10 s → timer cleared; silent > 10 s →
   `ReleaseForRecommit` + `bBypass = false` (synced offset, software continues
   silently, recommit at the live offset once audible — beta 0x10082b46, const
   10.0). **Silent entries never count toward `snd_iMaxVoices`** (beta parity:
   the countdown decrements only on commit).
3. **ensure committed** (only when not silent per step 2, after the `!SOF_PLAY`
   validation and the format refresh: read `pso->so_pCsdLink` → refresh `psdKey` +
   `iRate`/`iChannels`/`iBytesPerFrame` — never dereference `psdKey`; 07 §13 item 17):
   no buffer → voice budget + steal check (commit only if
   `newVol − lowestLiveVol > 0.333`, 99 #15):
   `DuplicateSoundBuffer(template)` → `QI(3DBuffer)` → (`QI(KsPropertySet)` if EAX) →
   `SetMode(1 /*HEADRELATIVE*/, 0)` → `SetCurrentPosition(bytes(so_fLeftOffset))`
   (= 0 fresh; synced on resume/reload-recommit; **live** mixer-advanced for fallback
   and silent→audible recommits — 07 §13 item 23). Commit failure → `DropToSoftware`
   (§6). **Over voice budget (or steal victim) → `bBypass = false`**: audible
   software fallback this frame, retried every tail, back to `bBypass=true` at the
   live offset on success (07 §13 item 19 — deviation from 99 #15 silence); over
   **same-sounds** budget → committed but volume 0 at live position (99 #9, beta
   parity; deliberately **not** routed through the silence gate — 07 §13 item 26).
   Steal victims: `ReleaseForRecommit` + `bBypass=false` — sync first, software
   continues from the synced offset, recommit later at the live offset
   (improvement over the beta's fresh-at-0 recommit, 07 §G4d).

   *(Not a step — spatial values are already computed and **stored** per object by
   `P_Update3DEffects` — beta formulas, own listener loop reusing the `[Cecil]` gate,
   07 §G10c):* `w`, `pos = Σ(rotateΔ·w)/Σw`, `vel`, `vol = clamp01(Σ(sli_vol·sp3_max·w²)/Σw)`
   (**pre-master, pre-budget** — the D8 step-2 test and the step-6 curve consume it
   from there), `hf = Σ(listenerFilterInt·w)/Σw`; parked case (no entity or no
   listener in falloff): `pos=(0,0,+10000)` sentinel, `vol=0` (02 §1/§4). The store
   also sets `bSpatialValid = TRUE` (step 7 gate — 07 §13 item 18); stored fields
   initialize to parked (pos (0,0,+10000), vol 0, vel 0, hf 0) as the backstop.
4. `SetPosition(pos.x, pos.y, −pos.z, DS3D_DEFERRED)` — parked logs as (0,0,−10000);
   `SetVelocity(vel.x, vel.y, −vel.z, DS3D_DEFERRED)` (99 #3/#4, z-negation 02 §5).
5. `GetStatus` (buffer exists).
6. **Pause/mute gates**: `(gamePaused && !SOF_NONGAME) || muteWindow` → `Stop()`
   **and set `bGateStopped`** (step 7 re-Play condition — 07 §13 item 20; buffer
   kept; resume from DS position — 99 #20). **No `SetVolume(−10000)` /
   `SetFrequency(0)` on gated frames — corrected 2026-10-16:** the beta skips the
   volume/frequency sets entirely when pause-gated (07 §14.1 check 1; the old
   "mute path" was a misreading — the log's −10000 values come from the 0.005
   silence gate only); volume/frequency resume on the first ungated frame, before
   step 7's re-`Play` (beta order). `P_Mute`'s one-time `SetVolume(−10000)` at
   `Mute()`-call time stays (07 §G7 companion). Ungated → `SetVolume(cB, 0)` with
   `cB` from 99 #10 linear curve on `vol × snd_fSoundVolume` (07 §G10b/c) and
   `SetFrequency(rate×pitch or 0, 0)` (99 #11; rate = the shadow-cached `iRate`,
   never `psdKey` — 07 §13 item 12).
7. buffer && `!playing` && `!gated` && `!delayPending` && **`bSpatialValid`** &&
   (`!bStarted` || **`bGateStopped`**) → `Play(0,0, SOF_LOOP?DSBPLAY_LOOPING:0)`:
   sets `bStarted`, clears `bGateStopped` (07 §13 items 18/20 — removes the spurious
   `Play` per finished sound and covers non-looping mid-buffer resume). Delay honored
   from real `so_sp.sp_fDelay` (stored `bDelayPending`; the tail advances
   `so_fDelayed` until elapsed — 07 §13 item 16).
8. **finish (pure beta rule — replaces cursor-based detection, approved 2026-10-14):**
   `bStarted && GetStatus == not-playing && !SOF_LOOP && no gates active` → force-release
   buffer, clear `SOF_PLAY` (ours, under lock — engine cleanup unlinks next `UpdateSounds`,
   SoundLibrary.cpp:1067-1070), remove from table, and set `so_fDelayed = 0` (mixer
   parity — 07 §7.2/§13 item 16; the original resets it on re-play too, 07 §12.7).
   **No play-cursor read, no position-at-end comparison** — DirectSound/DSOAL cursor
   behavior after a natural non-looping stop is undocumented/unreliable; "we issued
   Play, nothing gates it, DS says not playing" is the beta's own rule (04 §4:
   `fresh → Play → GetStatus → finished`).
9. EAX: `SOF_3D && playing && sl_bUsingEAX && snd_bUseEnvironmentFX` →
   `KsPropertySet::Set(EAX20_Buffer, 0x80000003, clamp(round(−100·hf), −10000, 0), DEFERRED)`
   (99 #13).

Parked sounds (held + silent, D8 step 2) keep playing at −10000 **only while the
10 s silent window runs** — after > 10 s silent the buffer is released via
`ReleaseForRecommit` and the entry falls to software (`bBypass=false`, silent);
never-committed silent sounds produce **no DS calls at all** (beta 0x10082bc9:
silent uncommitted entries are skipped before any positioning). Parked ≠ paused
(paused entries release via step 1); one-shots parked mid-play still finish via
step 8 while held (beta behavior). Fallback entries (`bBypass=false`) have no
buffer — steps 4-9 skip them (no DS calls; this includes silent-uncommitted and
10 s-released entries); the stock mixer owns them (advance/wrap/finish — 07 §13
item 19), the `!SOF_PLAY` validation drops them, and each tail retries their
commit (steps 2-3: audible entries re-commit at the live offset, silent ones only
once audible again).

## 5. Eligibility (registration-time, `P_Play_internal`)

`SOF_3D` set && `!SOF_MUSIC` && `sd_ulFlags & SDF_ENCODED == 0` && `nChannels == 1` &&
`wBitsPerSample == 16` && `so_psdcDecoder == NULL` (post-original it is NULL for
non-encoded; args already guarantee it). `SOF_VOLUMETRIC` **are** shadowed (beta parity,
02 §3). Everything else stays in the ordinary software mix untouched (99 §3 condition A —
decoder sounds are never muted, never shadowed: bypassed only via table membership).

## 6. Toggle semantics, gate, failure policy

- **cvar on → off**: new plays stay software; existing shadows drain naturally
  (driver keeps running for table members until they finish/stop). No hook/unhook.
- **cvar off → on**: only newly played eligible sounds register (mid-flight sounds stay
  software until they end). No mid-flight conversion.
- **Interface gate** (G2): registration requires `sl_pDSListener != NULL` (state, not
  `snd_iInterface`); re-checked after every `SetFormat`; loss of the listener →
  forced mode disable + console notice + `DropToSoftware` all (the only mass
  `DropToSoftware` — 07 §13 item 14). **Forced disable ≠ cvar-off**: cvar-off keeps
  the drain semantics above; the gate is re-evaluated at every registration, so a
  later `SetFormat` that restores the listener re-enables without user action while
  the cvar is 1.
- **`DropToSoftware` primitive** (creation failure at commit, runtime HRESULT failure,
  `BUFFERLOST` after one `Restore()`, `DSBSTATUS_TERMINATED` — 07 §G9/§13 item 14):
  `bStarted`-guarded position sync (a delay-pending drop keeps its delay and start
  offset intact; inert when the buffer is already gone) + release + remove from
  table. Software resumes audibly from the synced offset on the next mixer tick
  (real spNew/sp values — one ~1-block fade at most). Console notice once per cause
  per session. Post-condition: entry gone, software owns the sound.
- **Position sync on every release of a live shadow** (07 §G4d/§13 item 14): all
  `ReleaseForRecommit` sites (`SOF_PAUSED`, `SetFormat` pre-release, `ClearBuffer`
  owner-alive) and all `DropToSoftware` sites (G9, forced disable, listener loss)
  write the DS play cursor back to `so_fLeft/RightOffset` (plus the `so_fDelayed`
  sentinel) first, so software or re-commit never restarts at 0. Post-conditions:
  `ReleaseForRecommit` → entry kept, recommit via the `bSpatialValid` guard at the
  synced offset; `DropToSoftware` → entry gone, software resumes at the synced
  offset. Steal victims sync at steal time, then go `bBypass=false` (software
  advances the synced offsets live from there). No sync for buffer-kept parks
  (game pause, `Mute` window), for `!bStarted` shadows (sync would cancel a pending
  delay), or on the destruction path (data gone). No mixer-rate offset conversion
  across `SetFormat` (stock-parity imprecision accepted — 07 §G4d).
- **Budget is not failure**: over **same-sounds** budget → committed + volume 0 at
  live position (beta parity, 99 #9; deliberately **not** routed through the D8
  silence gate — releasing budget-silenced entries to software would defeat
  `snd_iMaxSameSounds`, 07 §13 items 21/26); over **voice** budget → **audible
  software fallback** (`bBypass=false`, §4 step 2 — deviation from 99 #15 silence,
  07 §13 item 19), retried each tail, back to spatial at the live offset. Neither
  is a drop.

## 7. Threading (07 §G8 model, verified lock map)

- Game thread only: all DS calls, all table mutations, all cvar reads — under
  `sl_csSound` (inherited from the hook's caller or taken explicitly in
  `P_UpdateSounds`/`P_SetFormat` tails; OPTEX is recursive, Synchronization.cpp:86-89).
- Timer thread: `P_MixSound` does one table lookup (membership && `bBypass`) and
  returns; it runs under `MixSounds`' `sl_csSound`, so it is serialized against all
  game-thread mutations; `bBypass` is written only from the game-thread tail under
  the same lock.
- Engine fields written by us: `SOF_PLAY` clear (finish), `so_fLeft/RightOffset`,
  `so_fDelayed` (sync/finish write-back + tail delay-advance — 07 §13 items 14/16) —
  game thread, under lock; the stock mixer already writes the same fields under the
  same lock (and keeps advancing them for fallback entries).
- `Mute()` callers (Gfx/Network, 07 §G7 companion) run on the game thread.

## 8. Data structures (`SoundDS3D.h`)

- `struct DS3DShadow { CSoundObject *psoOwner; CSoundData *psdKey; LPDIRECTSOUNDBUFFER pBuffer;
   LPDIRECTSOUND3DBUFFER pBuffer3D; LPKSPROPERTYSET pKsProps; BOOL bLooping, bStarted, bDelayPending,
   bSpatialValid, bBypass, bGateStopped;
   FLOAT fLastVolume; INDEX iRate, iChannels, iBytesPerFrame; INDEX iFailFrames;
   DOUBLE tmSilentSince; … }`
   — ≤64 live (channel table = the live-shadow list itself; steal scans it).
   `tmSilentSince` = the D8 silent-since timer value on the beta's clock (game
   tick; real time for `SOF_NONGAME` — 07 §13 item 24; 0/not-set when audible;
   drives the 10 s release of step 2).
  **`psdKey` is an opaque map key only** — never dereferenced after commit (07 §13
  item 12); if a live pointer is needed, the only source is `pso->so_pCsdLink`
  (valid while `SOF_PLAY`), refreshed at every (re)commit AFTER the `!SOF_PLAY`
  validation (07 §13 item 17 — keep this note and the "never dereference" rule
  together in the header comment). `iRate`/`iChannels`/`iBytesPerFrame` are cached
  from the play arguments at registration and drive `SetFrequency` and the
  bytes↔samples conversion (`ReleaseKeepingPosition`); re-play with different data
  updates key + cached fields in `P_Play_internal`, and every recommit re-reads them
  from `so_pCsdLink`. Flag semantics: `bSpatialValid` — set by the
  `P_Update3DEffects` store; `Play` waits for it (07 §13 item 18; stored fields init
  to parked). `bBypass` — `P_MixSound` skips only when it is set (07 §13 item 19;
  true at registration and after `ReleaseForRecommit`, false on tail commit
  denial). `bGateStopped` — set by the step-6 gate `Stop`, consumed by step 7
  (07 §13 item 20).
- `se1::map<CSoundObject*, DS3DShadow*>` registration table (the `P_MixSound` membership
  test; XGizmo `se1::map` precedent: IPatches.cpp:78).
- `se1::map<CSoundData*, {LPDIRECTSOUNDBUFFER pbuf; UBYTE *pswPCM; INDEX iBytes, iRate, iChannels}>`
  template cache (built lazily from `sd_pswBuffer` via `Lock`/`Unlock`, flags per
  99 #14 + `guid3DAlgorithm` from `snd_iEmulationType`; invalidated by
  `P_ClearBuffer` and freed on `P_SetFormat`). **Lookup validates (`pswPCM`,
  `iBytes`, `iRate`, `iChannels`) against the live `CSoundData` and rebuilds on
  mismatch** — guard against `CSoundData*` address reuse if any `ClearBuffer` path is
  ever missed (07 §13 item 13).
- Orphan list (**detached buffers only — no `CSoundData*`, no owner pointer**; play
  out; scanned per frame in `P_UpdateSounds` tail). Assumption to runtime-test under
  DSOAL: a duplicate keeps playing (shared memory) after its template is `Release`d
  — DS documents the contract, DSOAL unverified (07 §13 item 13).
- Per-frame budget sums: `se1::map<CSoundData*, FLOAT>` (reset each frame, 99 #9).

## 9. Device/listener init

On mode-enable confirm + after every `SetFormat`: apply 99 #1 listener params
(IMMEDIATE). Beta values: rolloff 0.0, doppler 1.1 — the stock engine's own init
(rolloff 1.0, no doppler) is always overwritten by our re-application; the ear pair is
unaffected (07 §G5: distance == MinDistance → no attenuation change; zero velocity → no
doppler) — verify via acceptance row "Ear pair unchanged".

## 10. Acceptance mapping (addendum §6)

| Row | Mechanism |
|---|---|
| Listener init | §9 (re-applied after every init incl. `SetFormat`) |
| Buffers = duplicates, `SetMode(1)` | driver step 2 in `P_UpdateSounds` tail (99 #16: duplicate + QI + SetMode + SetCurrentPosition) |
| Per-frame order pos→vel→GetStatus→vol→freq→EAX; one commit | `P_UpdateSounds` tail driver (steps 4-9, sorted) + one tail commit |
| Apply modes 1/1/0/0 | driver steps 4 (deferred), 6 (immediate), 9 (deferred) |
| Volume curve | 99 #10 linear branch × master (07 §G10) |
| Parked = (0,0,−10000)+vol −10000 | driver steps 2/4/6 — **only while a buffer is held** (held + silent, ≤ 10 s, D8); never-committed silent sounds produce **no DS calls**; after > 10 s silent: release + software-silent fallback (07 §13 items 22/24/28) |
| Decoder/music = no shadow, still software-audible | eligibility (§5) + D1 (nothing poisoned) |
| Ear pair unchanged | no touch; G5 reasoning; log/listening check |
| Mode off = structurally stock log | hooks installed but table empty when cvar 0: `P_MixSound` always trampolines, drivers no-op — only the (stock-identical) listener init commits differ |

## 11. Implementation order (Task 3, adjusted for D1-D8)

1. Cvars + empty subsystem + all hooks installed, mode off → vanilla behavior unchanged
   (acceptance row "Mode off"); WORKLOG entry.
2. Listener params + template cache + create/commit/release for one looping ambient
   class, **`P_MixSound` NOT yet skipping** (double audio expected and fine — proves the
   shadow audibly).
3. Enable the `P_MixSound` skip (single-line activation of D1) + driver steps 4-9 +
   one-commit → full positional mode.
4. Gates (`SOF_PAUSED`, game-pause, `Mute` window → `bGateStopped`), release
   primitives (`ReleaseForRecommit`/`DropToSoftware`, 07 §13 item 14), `bSpatialValid`
   guard, tail delay-advance + finish reset `so_fDelayed = 0` (item 16), failure
   policy, destructor hook. **Runtime test: pause/resume mid-play of a long one-shot
   — a restart from 0 exposes a missing sync (07 §G4d).**
5. Budget/steal (`snd_iMaxVoices`, `snd_iMaxSameSounds`), **`bBypass` software
   fallback + per-tail commit retry** (07 §13 item 19), orphan play-out, **D8
   silence gate + 10 s parked release** (driver step 2, 07 §13 items 21-28).
   **Runtime test (D8): an out-of-range ambient must not consume a voice** — in
   the DSOAL log it produces no per-sound DS calls while silent (and its
   pre-existing held buffer, if any, disappears ~10 s after it goes silent:
   release in the log, no further calls for it).
6. `SetFormat`/`snd_iEmulationType` re-init robustness — **recreate: still-playing
   shadows recommit at synced offsets (one silent frame accepted — 07 §13 item 15)**.
   Runtime tests: (a) toggle `snd_iEmulationType` mid-play of a long ambient under
   DSOAL — expect device re-init, template rebuild with the new GUID, re-duplicate +
   `SetMode` + `SetCurrentPosition(nonzero)` ≈ synced offset + `Play`; ambient stays
   spatialized, no restart from 0 (99 §4 #6); (b) orphan-plays-past-template-release
   under DSOAL; final DSOAL log comparison.

Each step ends with a WORKLOG entry; runtime tests (user-run) after steps 1, 3, 4, 6.
