# 07 — Implementation notes (Phase 2, Task 1: G1–G10 resolved)

Answers each gap question from the AGENTS-phase2-addendum §3. Sources: 1.10 source
(`Serious-Engine\Sources\Engine\...` — identical to the Steam binary per findings 05 §1.2
"no divergences") and the Steam binary itself (`SS_TSE_Steam_Bin\Engine.dll`, ImageBase
0x600C0000; `findings\scratch\steam-*.txt`). Confidence tagged per §5 rules.
Everything below feeds the design in `08-design.md`.

**Headline result (changes the mute mechanism):** the planned mute primitive — zeroing
`so_spNew` L/R volumes so the software mixer skips the object — **kills non-looping
sounds after ONE mix block** in the Steam binary (G7). Phase 1's verdict in 99 §3
("finishes on schedule") was wrong for non-looping sounds and has been corrected there
and in 05 §2.2/§2.3. The corrected mechanism intercepts the static mixer function
`MixSound` directly (beta-parity: "state lives in the DS buffer", findings 04 §6).
This is a **documented deviation** from the addendum §3 G7 "expected fix"
(zero `so_sp`/`so_spNew` L/R in `P_Play_internal`), per the deviation rule in addendum §1.

---

## G7 — Mute path, instruction level (and the correction)

### 7.1 Complete write map of `so_sp`(+0x34) vs `so_spNew`(+0x50) `[VERIFIED]`

| Site | Writes | Gate |
|---|---|---|
| `CSoundObject::CSoundObject` (SoundObject.cpp:94) | `so_sp = so_spNew` (ctor defaults) | — |
| `CSoundObject::Play_internal` (SoundObject.cpp:273; Steam 0x7E615 `rep movsl`×7) | `so_sp = so_spNew` | every play/re-play |
| `CSoundObject::Read_t` (SoundObject.cpp:663) | `so_sp = so_spNew` | savegame load |
| `CSoundLibrary::UpdateSounds` (SoundLibrary.cpp:1060) | **`so_sp = so_spNew` — the per-frame copy** | `SOF_PLAY` set only; **not skipped under any flag** (SOF_PREPARE only gates `PrepareSound`, L1062-1064) |
| `CSoundObject::Update3DEffects` (via inline `SetVolume/SetFilter/SetPitch/SetPhase/SetDelay`, SoundObject.h:136-160) | writes **`so_spNew` only** | every frame, 3D sounds |
| game code / `Play_t` etc. (`SetVolume`, `Set3DParameters`…) | `so_spNew` only | any time |
| `MixSound` (SoundMixer.cpp:648, 805) | `so_sp.sp_fDelay = 0` (on finish) | mixer thread |

So: **UpdateSounds is the per-frame `spNew→sp` copy** (confirming 05 §2.3; 05 §1.2 only
documented the Play_internal copy). Mixer consumes `so_sp`; game-side writes land in
`so_spNew`. Both the copy (SoundLibrary.cpp:1001 lock, Steam 0x60139765) and the mixer
(05 §2.1) run under `sl_csSound`.

### 7.2 THE CORRECTION — zero-volume non-looping sounds stop after one block `[VERIFIED]`

`SoundMixer.cpp:624-660` (skip path), confirmed in the Steam binary instruction-level
(`scratch/steam-MixSound.txt`):

```
6013b1db: movl 0x10(%esi), %eax      ; so_slFlags
6013b1de: testb $0x1, %al            ; SOF_LOOP
6013b1e0: je 0x6013b29e              ; NOT looping -> jump straight to:
6013b29e: andl $0x7fffffff, %eax     ; clear SOF_PLAY
6013b2a3: movl %eax, 0x10(%esi)
6013b2a6: movl $0, 0x14(%esi)        ; so_fDelayed = 0
6013b2ab: movl $0, 0x4c(%esi)        ; so_sp.sp_fDelay = 0
```

There is **no end-of-buffer comparison** guarding the clear — the non-looping branch
jumps directly to it (the 0x7B1E6-0x7B29C region is only the looping wrap while-loops).
Source matches: `SoundMixer.cpp:637-649` — looping → wrap offsets; **else →
`so_slFlags &= ~SOF_PLAY` unconditionally**. The offsets were advanced by one block
first (L630-632, `fOfsDelta = fStep × mixerRate × secs`), then the sound is finished.

- Looping sounds: offsets advance + wrap — the 05 §2.2/§2.3 claim holds.
- **Non-looping sounds: a muted (all four volumes < 0.001) non-looping sound has
  `SOF_PLAY` cleared on the first skip-path block (~11-23 ms after muting).** 05's
  "finished, on schedule" and 99 §3 condition 1 are corrected accordingly.
- Consequence for the planned design: **zero-volume muting cannot drive non-looping
  sounds** — they would be killed almost immediately and never heard through the shadow.
- Corollary (stock-behavior note): in stock Steam, any *parked* (out-of-falloff,
  zero-volume) non-looping 3D sound already dies this way — SetVolume(0,0) from
  Update3DEffects (SoundObject.cpp:575) feeds the same path. This is existing engine
  behavior, not introduced by us.

### 7.3 Other skip-path facts (verified, relevant to any mute scheme)

- `fStep = sd_wfeFormat.nSamplesPerSec × so_sp.sp_fPitchShift / mixerRate`
  (SoundMixer.cpp:601-602) — **the skip-path offset advance includes the engine pitch**
  (doppler baked by Update3DEffects changes finish time of muted sounds).
- Delay is consumed *before* the volume gate (L591-597): `so_fDelayed += secs`;
  `if (so_fDelayed < so_sp.sp_fDelay) return;` then sentinel `so_fDelayed = 9999.9999`
  ("no more delays").
- Encoded (`SDF_ENCODED`) objects in the skip path: no advance, no finish (L628 gate) —
  they hang in `SOF_PLAY` forever while inaudible (99 §3 condition A re-confirmed at
  source level).
- The audible path's volume interpolation: `fLeftVolume` = `so_fLastLeftVolume` (already
  master-scaled when stored), `fNewLeftVolume` = `so_sp.sp_fLeftVolume × master`
  (L616-622: SOF_MUSIC → `snd_fMusicVolume`, else `snd_fSoundVolume`); interpolated
  across the block; `so_fLastLeftVolume = fNew…` on exit (L817). So **master volume is
  applied per mix block inside MixSound** (and once per play in `PrepareSound`,
  SoundObject.cpp:598-607).

### 7.4 Corrected mute mechanism — intercept static `MixSound` (chosen for 08) `[VERIFIED feasibility]`

Instead of poisoning `so_spNew`/`so_sp` volumes, hook the static mixer entry
`MixSound` (Steam **RVA 0x7AF80**, VA 0x6013AF80, `__cdecl void MixSound(CSoundObject*)`):

- **Single call site in the entire binary**: `0x6013a02c` inside `MixSounds`' object loop
  (grep over `scratch/steam-engine-disasm.txt`: exactly one `calll 0x6013af80`).
- Raw-address hook, exactly like `ADDR_RENDERLENSFLARES` (GameSpecific.h:119, used via
  `StructPtr` at EnginePatches.cpp:329 — 06 §4b): resolve at init as
  `ADDR_ENGINE + 0x7AF80`, `CreatePatch(pMixSound, &P_MixSound, "MixSound(...)")`.
- `P_MixSound(pso)`: if `pso` is in the shadow table → return (skip mixing, **advance
  nothing, finish nothing** — the DS shadow buffer owns playback state, exactly the
  beta's model, findings 04 §6: "not mixed, not advanced in software — their state lives
  in the DS buffer"); else → call original via trampoline.
- This removes *all* engine-state poisoning: `so_spNew`, `so_sp`, `so_fLast*Volume`
  keep real values at all times. Consequences:
  - No savegame/world-file leakage (moot anyway — see §12.2: nothing serializes
    `CSoundObject` in TSE game code; but real values are strictly cleaner).
  - **First-block case solved by construction**: `P_Play_internal` can register the
    object *before* calling the original (eligibility is decidable from the arguments:
    `slFlags & SOF_3D`, `pCsdLink->sd_ulFlags & SDF_ENCODED`, `nChannels==1`,
    `wBitsPerSample==16`); the whole call runs under `Play`'s `sl_csSound`
    (SoundObject.cpp:212), so no mixer tick can slip between registration and the
    original — zero window for an unmuted software block.
  - Engine-offset drift (G4b) dissolves: shadowed sounds never advance engine offsets;
    finish comes from the shadow's `GetStatus` (beta model, 04 §4), and we clear
    `SOF_PLAY` from the game thread under the lock.
  - `P_Stop_internal` ordering: call original first, then remove from table + release —
    a mixer tick in between sees (in-table, `!SOF_PLAY`) and skips safely;
    `MixSounds`' outer gate (05 §2.1) skips non-`SOF_PLAY` objects anyway.
- Residual costs: one map lookup per playing object per timer tick (timer thread, under
  `MixSounds`' lock); the profile counter `PCI_SOUNDSSKIPPED` is not incremented for
  shadowed objects (cosmetic only).

**Deviation note (per addendum §1):** the addendum's G7 "expected fix" (zero
`so_sp`+`so_spNew` L/R in `P_Play_internal`) is superseded — 7.2 shows it would kill
every non-looping 3D sound within one mix block. Reason recorded here first, design in 08.

---

## G1 — Template creation `[VERIFIED]`

From 1.10 `SoundData.cpp/h` (= Steam per 05 §1.1 empirical layout):

- `CSoundData::Read_t` (SoundData.cpp:131-181):
  - encoded (.ogg/.mp3): `SDF_ENCODED|SDF_STREAMING`, format from decoder, no PCM buffer;
  - WAV: `sd_wfeFormat` = file's native format, then **L160-162: desired rate =
    `min(fileRate, _pSound->sl_SwfeFormat.nSamplesPerSec)`** (downsample to the mixer
    rate if the mixer is slower; expansion impossible — zero-filled, Wave.cpp:268-278),
    **L164: bits forced to 16**, channels stay native (1 or 2).
  - `sd_slBufferSampleSize` = **samples** (per-channel frames), allocation
    `samples × channels × 2` bytes **+ 8 bytes** whose first 4 hold a copy of the first
    sample (linear interpolation guard, L171-175).
  - PCM loaded only `if (_pSound->IsActive())` (L167) — no buffer when the library is off.
  - `Read_t` takes `sl_csSound` (L134); `AddSoundAware` at the end.
- **Template `DSBUFFERDESC` inputs**: `nSamplesPerSec` = `sd_wfeFormat.nSamplesPerSec`,
  `nChannels` (must be 1 for the 3D template), 16 bits, `dwBufferBytes =
  sd_slBufferSampleSize × nChannels × 2` (exclude the +8 pad), PCM copied once via
  `Lock`/`Unlock` from `sd_pswBuffer` (beta parity: 04 §2). Eligibility must also
  require `wBitsPerSample==16` (the mixer gate, SoundMixer.cpp:586, rejects anything
  else — such sounds are dead in stock anyway).
- **Lifetime/free points**:
  - `CSoundData::ClearBuffer` (SoundData.cpp:98-104): `FreeMemory(sd_pswBuffer)`, NULL —
    **the single invalidation point** for our template cache.
  - Called from `Clear` (L219; also `~CSoundData` path; `Clear` takes the lock, L213) and
    from `CSerial::Reload` (inherited — SoundData.h:23; invoked by
    `CSoundLibrary::SetFormat`, SoundLibrary.cpp:974, for every non-encoded
    `CSoundData` after a format/device re-init).
  - **Design**: hook exported `?ClearBuffer@CSoundData@@QAEXXZ` (0x76200, def L982):
    release the cached template for that `CSoundData` and force-recommit (drop shadows
    playing it — next frame's bookkeeping re-creates from the fresh PCM).
- Note: `Reload` only happens on `SetFormat`; there is **no per-frame format dependency**
  — `sd_pswBuffer` is independent of the current output format (the mixer resamples).

---

## G2 — Interface gate `[VERIFIED]`

- `sl_pDSListener`@+0x48 and the `CTRL3D` primary exist only when `snd_iInterface==2`
  (05 §1.1a; StartUp_dsound reads `snd_iInterface` @ VA 0x602a4128).
- **`snd_iInterface` CAN change at runtime, and the engine reacts with a full re-init**:
  it is declared `post:SndPostFunc` (SoundLibrary.cpp:772) along with `snd_tmMixAhead`,
  `snd_iDevice`, `snd_iFormat` (L771-774). `SndPostFunc` (L173-186) clamps the values,
  compares against `_iLastAPI/_iLastFormat/_iLastDevice/_tmLastMixAhead` and calls
  `_pSound->SetFormat(snd_iFormat, TRUE)` on any change → full DS re-init on the next
  console change. `SetFormat` re-reads `snd_iInterface` in `StartUp_dsound` (via
  `SetFormat_internal`).
- **Design consequence**: the gate must be tested as `sl_pDSListener != NULL` (state),
  not `snd_iInterface == 2` (intention), and re-evaluated after every `SetFormat`
  (device generation change): if the listener is gone after re-init, disable the mode
  with a console notice and drop shadows (sounds continue in software — no state was
  poisoned, so they are audible immediately).

---

## G3 — Commit placement `[VERIFIED]`

- The engine's own `CommitDeferredSettings` sites (Steam log's "×3 total" explained):
  1. `StartUp_dsound` (once per device init; 05 §1.1a, 0x78CF6);
  2. `UpdateSounds` EAX-panning path (SoundLibrary.cpp:1030-1043): only when
     `sl_bUsingEAX && _fLastPanning != snd_fEAXPanning` — sets both source positions
     (`DS3D_DEFERRED`) and commits. **Not per-frame**; fires only when the user changes
     `snd_fEAXPanning`.
- Both engine commits merely flush deferred state early; neither conflicts with a
  per-frame wrapper commit (the beta committed per frame — 46,444×, findings 02 §6).
  `CommitDeferredSettings` on the listener flushes deferred settings of **all** 3D
  buffers and the listener (no per-buffer commit exists in DS3D — 02 §6; also implied
  by the engine committing right after setting only the two source buffers).
- **Design consequence (as decided)**: `P_UpdateSounds` = original first → shadow
  bookkeeping → **one** commit; commit while paused is harmless (settings are parked
  values anyway). Note the ordering: if the engine's panning commit fires inside the
  original, it flushes *last frame's* shadow deferreds — the wrapper's own commit at the
  end re-flushes the current frame's. No bad interleave.
- The engine's panning `SetPosition` calls on `sl_pDSSourceLeft/Right` use
  `DS3D_DEFERRED` (L1039-1040) — they rely on some commit happening; stock gets away
  with the rare panning-change commit. Our per-frame commit also keeps them fresh
  (harmless bonus).

---

## G4 — Position and drift

### (a) Units and conversions `[VERIFIED]`

- `so_fLeft/RightOffset` count **source samples** at the sound's (possibly downsampled)
  rate — `SoundMixer.cpp:630-632`, L814-815; `SetOffset` (dead code, SoundObject.cpp:333)
  converts seconds → samples via `nSamplesPerSec`.
- `IDirectSoundBuffer::SetCurrentPosition` takes **bytes** from the buffer start
  (DSOUND.H; DS3D buffers are the same buffers). Conversion for a mono 16-bit shadow:
  `bytes = so_fLeftOffset × 1 channel × 2` (general: `offset × nChannels ×
  wBitsPerSample/8`).
- Under the corrected mechanism (7.4) engine offsets are **frozen** for shadowed sounds
  (the mixer never advances them), so the conversion is needed only at shadow
  (re)creation: fresh commit → `SetCurrentPosition(0)` (beta parity: 04 §4, fresh =
  `SetCurrentPosition(0)`); resume-after-`SOF_PAUSED` recommit and savegame-load replay
  (`SOF_LOADED`, SoundObject.cpp:651-653+666-668) → `SetCurrentPosition(bytes(so_fLeftOffset))`.
- **`SOF_LOOP` wrap: not our concern** — the DS buffer loops itself (`DSBPLAY_LOOPING`);
  engine offsets never advance for shadowed sounds. `sp_fDelay`: honored by the shadow
  bookkeeping (start `Play` only after the delay elapses; read the real
  `so_spNew.sp_fDelay` each frame — unpoisoned).
- Packed sentinel: `sp_fDelay` values are serialized (dead) and read per block by the
  (bypassed) mixer — no poisoning happens, so nothing to restore.

### (b) Doppler and drift `[VERIFIED premise; DISSOLVED under the corrected mechanism]`

- Premise confirmed: 1.10 `Update3DEffects` bakes software doppler into the pitch —
  SoundObject.cpp:471-480 (`fPitchShift = (c+listenerRadial)/(c+objectRadial)`,
  c = `snd_fDopplerSoundSpeed`), L562 (`× so_sp3.sp3_fPitch`), L587 `SetPitch` →
  `so_spNew.sp_fPitchShift`; the (bypassed) skip path would advance offsets at that
  pitched rate (7.3).
- Under 7.4, engine offsets never advance for shadowed sounds; the **shadow's DS buffer
  is the playback authority** (beta model), finish detected via `GetStatus`. There is
  no engine/shadow finish-time drift to manage, and no software doppler is applied to
  any consumed value. DS3D doppler (`SetVelocity` + `DopplerFactor 1.1`) is the only
  doppler (99 #12 single-application confirmed; the beta's own software-doppler branch is
  only for waveOut/decoder sounds — 03 §4).
- The engine-side `so_spNew.sp_fPitchShift` keeps its real 1.10 value (including
  doppler) — dead end under 7.4 (mixer bypassed, no serializer — §12.2). No change to
  `P_Update3DEffects`'s existing 1.10 math is required for correctness.

### (c) Shadow created mid-play — complete enumeration `[VERIFIED]`

| Case | Origin | Shadow action |
|---|---|---|
| fresh play | `Play`→`Play_internal` (prediction tail) | create; `SetCurrentPosition(0)`; delay honored |
| re-play of a playing object | `Play_internal` (inlined `Stop_internal`, 05 §1.3; offsets reset to 0 unless `SOF_LOADED`, SoundObject.cpp:276-281) | release old (orphan semantics, 99 #17), create fresh at `bytes(so_fLeftOffset)` (= 0 unless LOADED); `so_fDelayed` is reset by the original itself (§12.7) |
| prediction copy | `CSoundObject::Copy` (SoundObject.cpp:121-131) / `operator=` — both call **public `Play`** when the source was playing | goes through `P_Play_internal` → normal create; copy has `so_penEntity=NULL` → parked (02 §1) |
| savegame load replay | `Read_t` (L666-668) → `Play_t(…|SOF_LOADED)` | create at restored `bytes(so_fLeftOffset)` |
| resume from `SOF_PAUSED` | `Pause`/`Resume` are bare flag flips (SoundObject.h:120-122); shadow released on pause (99 #18) **via `ReleaseForRecommit` (G4d/§13 item 14 — sync + entry kept + `bBypass` stays true; corrected 2026-10-15: offsets are frozen under 7.4, so a plain release would restart at 0; corrected again 2026-10-16: the beta's own recommit always restarts at 0 — its offset computation is dead, 04 §5 / 07 §14.3 item 1 — so our synced offset is an improvement, not parity)** | recreate at `bytes(so_fLeftOffset)` = the synced DS cursor |
| voice steal (ours) | our budget bookkeeping (99 #15) | victim: `ReleaseForRecommit` + **`bBypass=false`** (audible software fallback, §13 item 19) — software resumes from the steal-time synced offset and keeps advancing; re-commit when budget frees at the then-live `bytes(so_fLeftOffset)` (**improvement over the beta's fresh-at-0 recommit**, 04 §3/§4; corrected 2026-10-15) |
| un-park | listener back in falloff range | nothing special — position/volume resume; buffer was never released (parked ≠ paused: parked buffers keep playing at −10000, 02 §1/§4) |
| `SOF_SMOOTHCHANGE` continue | `Play_internal` bContinue (offsets still reset unless LOADED) | same as re-play row |

Also verified: **`CSoundObject::SetOffset` is a no-op in 1.10/Steam** — early `return`
at SoundObject.cpp:329 with dead code after it ("don't set offset for real — might be
source for some bugs!"). The mid-play offset-jump desync risk from AGENTS §8 does not
exist on this build.

### (d) Position-preserving release — `ReleaseKeepingPosition()` (added 2026-10-15, user review item A)

**Bug corrected:** under 7.4 the mixer never advances a shadowed object's
`so_fLeft/RightOffset`, so they stay at their play-start value (0 for fresh plays).
The G4c resume/steal rows and the G6 wrapper as drafted re-committed at
`bytes(so_fLeftOffset)` — i.e. every pause, steal and `SetFormat` would restart the
sound from 0, while the beta's own recommit also restarts at 0 (04 §5: the recommit
offset computation is dead in the beta — constant 0 at 0x10082BFB with the
`GetElapsedTime(0)` result discarded — and in LC, 07 §14.3 item 1). Only the old
G9 drop path (now `DropToSoftware`, §13 item 14) synced the cursor back. **Our
synced-offset release is deliberately not beta parity — it is an improvement
(2026-10-16 correction of the earlier "beta resumes from its elapsed timer" claim).**

**Helper** (game thread, `sl_csSound` held):

```
ReleaseKeepingPosition(shadow):
  if (shadow.bStarted) {                    // a delay-pending sound has no DS position
    GetPosition(&dwPlay)                    // play cursor, bytes from buffer start
    pso->so_fLeftOffset = pso->so_fRightOffset
        = dwPlay / shadow.iBytesPerFrame   // bytes -> source samples
    pso->so_fDelayed = 9999.9999            // past-delay sentinel (SoundMixer.cpp:597);
                                           // bStarted implies the delay already elapsed
  }
  buffer->Stop(); buffer->Release(); release 3D/KS ifaces; clear shadow pointers
```

Wrapped in two primitives (§13 item 14 — the overloaded "release" was itself a
third-review finding). **`ReleaseForRecommit`** = position sync via the helper body
above + release buffer/3D/KS ifaces + `bStarted = false` + `bSpatialValid = false`
(the recommit routes through the Play-latency guard instead of reissuing `Play`
against stale state) + `bBypass` unchanged (true) + **keep the table entry**. Applied
at: **SOF_PAUSED release** (driver step 1), **voice steal** (step 2 — plus
`bBypass = false`, §13 item 19), **`SetFormat` pre-release** (G6 — the one that
matters most: the entry survives the device re-init and recommits at the synced
offset), **`ClearBuffer` owner-alive** (G1; `Reload` re-reads the PCM and the
recommit refreshes the cached format from `so_pCsdLink`, §13 item 17).
**`DropToSoftware`** = position sync via the helper body + release + **remove the
table entry** (software resumes audibly from the synced offset; the sync is
intentionally inert when the buffer is already gone — e.g. `DropToSoftware` after
`ReleaseForRecommit` in the listener-lost path). Applied at: **G9 failures**
(G9.5), **forced mode disable** (listener loss — the only mass `DropToSoftware`;
cvar-off keeps drain semantics, 08 §6), **listener missing after `SetFormat`**.
Sites that are *neither* primitive stay plain releases: `Stop_internal`/dtor
(orphan semantics keep the buffer playing anyway), driver finish (step 8), the
`!SOF_PLAY` validation drops. NOT applied where no resume exists or the data is
gone: game-pause and `Mute` windows (buffer **kept**; DS `Stop` preserves the
cursor — 99 #20), the destruction path of `ClearBuffer` (`sd_pswBuffer` freed,
owner being torn down), and never for `!bStarted` shadows.

**Rejected alternatives:** (1) mirroring the cursor into the engine offsets every
frame — adds a per-sound `GetCurrentPosition` call the beta never makes and breaks
the acceptance row's per-frame call order; (2) converting offsets across a
mixer-rate change during `SetFormat` (`Read_t` re-downsamples, so sample positions
shift) — stock has the same imprecision resuming its own mixer; **parity kept**, no
conversion.

---

## G5 — Side effects on the engine's ear pair `[LIKELY → design-safe; log/listening check pending]`

Facts (verified):
- The ear pair `sl_pDSSourceLeft/Right` are `IDirectSound3DBuffer` ifaces of the two mono
  mix buffers (+0x4C/+0x50, 05 §1.1a), initialized with `SetMinDistance(1.0)` /
  `SetMaxDistance(9.0)` (source 506-519 → 05 §1.1a) and positioned at ±1 (panning path,
  L1033-1041; default `snd_fEAXPanning` → −1/+1, matching the Steam log).
- Their **velocity is never set** (engine never calls `SetVelocity` on them) → DS3D
  doppler factor has nothing to act on (doppler shift is a function of relative
  *velocity*).
- DS3D distance attenuation applies only beyond `MinDistance`: the pair sits at
  distance 1.0 == `MinDistance` 1.0 → attenuation 0 dB **regardless of the rolloff
  factor** (rolloff 0.0 vs 1.0 indistinguishable at the minimum point; the beta relies on
  exactly this for its mix buffer, which sits at the same distance — 04 §1 step 6 has
  no per-source min distance override either).
- Listener orientation/position changes (none — we set the same values the engine
  already sets) and `SetRolloffFactor(0.0)`/`SetDopplerFactor(1.1)` therefore do not
  change the ear pair's rendering. `[LIKELY — from DS3D semantics; to be confirmed by
  the DSOAL log diff + listening test per addendum §6 row "Ear pair unchanged".]`

---

## G6 — Re-init (`SetFormat`) `[VERIFIED]`

- Triggers for `SetFormat` in stock: `SndPostFunc` (cvar changes, G2), the
  `UpdateSounds` window watchdog (`sl_bUsingDirectSound && _hwndCurrent != _hwndMain`,
  SoundLibrary.cpp:992-995 — **runs before the lock, calls `SetFormat` directly at
  0x60139734**, i.e. our hook sees it), and level-load/session code paths.
- 1.10 `SetFormat` (SoundLibrary.cpp:949-984): takes `tm_csHooks` + `sl_csSound`
  (L952-954; recursive OPTEX makes our wrapper's own lock takes safe — §8), then
  `PausePlayingObjects` for all `CSoundData` → `SetFormat_internal` (re-runs
  `StartUp_dsound`: **all engine DS objects re-created; listener re-initialized with
  STOCK params — rolloff 1.0, no doppler**; 05 §1.1a) → `sd.Reload()` for non-encoded
  data (re-reads PCM, G1) → `ResumePlayingObjects`.
- Everything the shadow subsystem owns dies with the device: shadow buffers, 3D ifaces,
  KsPropertySet ifaces, **and the templates** (they are DS buffers on the dead device);
  listener params revert to stock.
- **Wrapper spec (for 08)**: `P_SetFormat` = [own `sl_csSound` lock] free templates
  + orphan list (mark generation; calling `Release` on the dying interfaces before the
  original is safe and cleaner) → release ALL shadows via **`ReleaseForRecommit`**
  (G4d/§13 item 14 — `bStarted`-guarded sync; entries **kept**, `bStarted`/
  `bSpatialValid` reset, `bBypass` stays true; `!bStarted` entries take the same
  primitive, sync inert) → call original via trampoline → re-check gate: if
  `sl_pDSListener != NULL` (still interface 2) re-apply **beta listener params**
  (`SetPosition(0,0,0)`, `SetOrientation(0,0,1, 0,1,0)`, `SetVelocity(0,0,0)`,
  `SetRolloffFactor(0.0)`, `SetDopplerFactor(1.1)`, all IMMEDIATE — 99 #1) — and the
  next `P_UpdateSounds` tail **recommits the kept entries at their synced offsets
  (RECREATE — §13 item 15; one silent frame per sound accepted)**; else
  `DropToSoftware` every entry + forced mode disable + console notice (§13 item 14;
  cvar-off drain semantics unaffected). This is the beta's "Pause all → re-init →
  Reload → Resume all" lifecycle translated to our ownership model (04 §1) — with
  the buffer returning after the re-init, as the beta's channels also returned
  (04 §5).
- `snd_iEmulationType` (guid3DAlgorithm) is a **beta cvar, absent from Steam**
  (binary grep §12.3) — the patch must declare it; template rebuild requires
  `SetFormat` when it changes (declare it `post:` a patch-local reinit function that
  just releases templates + calls `SetFormat(sl_EsfFormat)`; addendum Task 3 step 6).
  Because re-init **recreates** shadow buffers (§13 item 15), toggling it takes
  effect on **running** sounds — 99 §4 #6 resolved by mechanism (runtime test
  pending, 08 §11 step 6).

---

## G7 companion — `SOF_PAUSED`/pause gates under the corrected mechanism

Unchanged from the addendum's decisions (gates become *more* important because DS
buffers keep playing when the engine loop stops):

- `SOF_PAUSED` (engine `Pause`/`Resume`, `PausePlayingObjects` on `SetFormat`):
  release the shadow via `ReleaseForRecommit` (99 #18, G4d/§13 item 14 — sync +
  entry kept; `bBypass` **stays true** — else the resumed-but-unbuffered entry would
  be mixed for one block when the bare flag flip resumes it; corrected 2026-10-15:
  a plain release would recommit at the frozen play-start offset, i.e. 0);
  recommit on resume at the synced offset.
- Game pause for non-`SOF_NONGAME` sounds and `_bMuted`: `SetVolume(-10000)` +
  `Stop()` on the DS buffer, **buffer kept** (99 #20); DS `Stop` preserves the play
  cursor → resume = `Play` continues from DS position.
- **`_bMuted` specifics (verified)**: `CSoundLibrary::Mute()` (exported, def L2075,
  0x782B0; body SoundLibrary.cpp:915-939) sets `_bMuted=TRUE`, zeroes the secondary mix
  buffers, and is called from GfxLibrary (video re-init ×4) and Network (session/level
  transitions ×8) — all paths where the game loop is about to block, i.e. **no
  `UpdateSounds` runs to clear `_bMuted` (L996) until the operation finishes**.
  Meanwhile DS keeps mixing — shadows would stay audible. ⇒ **hook `Mute()`**
  (`P_Mute`: original, then `SetVolume(-10000)+Stop` on all playing shadows, buffers
  kept); first `UpdateSounds` after the window resumes them from DS-preserved
  positions. (Reading `_bMuted` in the wrapper tail is useless — the original just
  cleared it at L996.)

---

## G8 — Threading `[VERIFIED]`

- **`UpdateSounds` takes `sl_csSound`** — SoundLibrary.cpp:1001, binary
  0x60139765 (`call ??0CTSingleLock@@QAE@PAVCTCriticalSection@@H@Z`), after the
  pre-lock `SetFormat` watchdog (0x60139734). Full verified lock map of the paths we
  touch:

| Path | Lock | Where |
|---|---|---|
| `Play` / `Stop` (public) | `sl_csSound` | SoundObject.cpp:212/343 |
| `Play_internal` / `Stop_internal` | (called inside the above, lock held) | — |
| `UpdateSounds` (→ `Update3DEffects`, `PrepareSound`, cleanup) | `sl_csSound` | SoundLibrary.cpp:1001 |
| `MixSounds` (→ `MixSound`) | `sl_csSound` | 05 §2.1 |
| `SetFormat` | `tm_csHooks` + `sl_csSound` | SoundLibrary.cpp:952-954 |
| `CSoundData::Read_t` / `Clear` | `sl_csSound` | SoundData.cpp:134/213 |
| `CSoundLibrary::Mute` | `sl_csSound` | SoundLibrary.cpp:922 |
| `~CSoundLibrary` | `tm_csHooks` + `sl_csSound` | SoundLibrary.cpp:153-155 |

- `sl_csSound` is a `CTCriticalSection` = **OPTEX** (Synchronization.cpp:202-224) with
  same-thread recursion (`lRecurseCount++`, Synchronization.cpp:86-89) — wrapper hooks
  may safely re-take it (needed for the `P_UpdateSounds` tail and `P_SetFormat`
  pre/post sections).
- **Field-touch model (all shadow state only from game-thread hooks under `sl_csSound`;
  the timer thread never writes shadow state)**:

| Data | Written by (thread) | Read by |
|---|---|---|
| shadow table (`CSoundObject*`→state), template cache, orphan list, channel/budget bookkeeping | game thread (all hooks), under `sl_csSound` | game thread (bookkeeping); **timer thread: `P_MixSound` membership test only** (runs under `MixSounds`' lock → serialized against game-thread mutations) |
| DS interfaces (Play/Stop/Set*/GetStatus/QI/Duplicate) | game thread only | game thread |
| `so_slFlags` (SOF_PLAY clear at shadow-finish) | game thread, under lock | timer thread (mixer gates — same as stock mixer writes) |
| `so_fLeft/RightOffset`, `so_fDelayed` (sync + finish write-back, G4d/G9.5/§13 items 14+16; tail delay-advance for `bBypass` shadows, §13 item 16) | game thread, under lock | timer thread (advances only fallback entries — the same fields stock already writes) |
| cvars (`snd_bDS3DSpatial` etc.) | game thread (shell) | **game-thread hooks only, never the timer thread** (addendum §4 rule holds; `P_MixSound` reads no cvars) |

- `Pause`/`Resume` inline flag flips (SoundObject.h:120-122) are lock-free in stock —
  our per-frame bookkeeping reads `SOF_PAUSED` under our lock; worst case one frame of
  lag (same as stock's own consumption pattern in `MixSounds`).

---

## G9 — Runtime failure detection `[VERIFIED mechanics; rule FINALIZED 2026-10-14]`

- The beta's own failure policy is minimal (`DSFail` console + re-init path,
  SoundLibrary.cpp:1042 analog); there is no beta precedent for per-buffer failure
  recovery — the rule below is ours, built on the beta's bookkeeping primitives.
- Rule (FINALIZED 2026-10-14, user-approved; supersedes the draft rule 4):
  1. **Creation failure** (template `CreateSoundBuffer`, `DuplicateSoundBuffer`,
     `QI(3DBuffer)`, `Lock/Unlock`, `SetMode`, `SetCurrentPosition`): no shadow; the
     pre-registered entry is removed via `DropToSoftware` (§13 item 14 — sync inert,
     nothing was poisoned) and the sound continues in software from the next mixer
     tick (≤ one silent frame between registration and the first tail's failed
     commit — accepted, same class as the `SetFormat` gap). Console notice once per
     session per cause.
  2. **Runtime HRESULT failure** on `Play`/`SetVolume`/`SetFrequency`/`SetPosition`/
     `SetVelocity` (any non-DS_OK): drop the shadow immediately (procedure below).
  3. **`GetStatus` returns `DSBSTATUS_BUFFERLOST`**: `Restore()` once; if still lost
     next frame → drop. `DSBSTATUS_TERMINATED` → drop.
  4. **Not-playing anomaly rule DELETED 2026-10-14**: DS/DSOAL play-cursor behavior
     after a natural non-looping stop is undocumented — a cursor-based finish/anomaly
     split cannot reliably distinguish finish from failure. Replaced by the **pure beta
     finish rule**: `bStarted && GetStatus(not-playing) && !SOF_LOOP && no gates`
     → *finished* (not a failure). Trade-off accepted (matches the beta, 04 §4): a
     buffer that dies silently truncates instead of resuming in software. A sanity
     counter was considered and rejected (user decision 2026-10-14).
  5. **`DropToSoftware` primitive** (G4d/§13 item 14; never silent in both paths):
     game thread, under `sl_csSound`: position sync (`bStarted`-guarded — a
     delay-pending drop keeps its delay and start offset intact), release, then
     remove from table. The software mixer resumes the sound from the synced offset
     on its next tick — volumes in `so_spNew`/`so_sp` are real (7.4), so it is
     instantly audible (one ~1-block fade from `so_fLastLeftVolume`,
     SoundMixer.cpp:671-677 — acceptable).
- With the beta model the finish detection is the beta's own (04 §4 `GetStatus` per
  frame) — one code path, gated by `bStarted` and the frame's gate snapshot.

---

## G10 — Volume inputs

### (a) `snd_bLinearVolume` `[VERIFIED absent]`

- Absent from 1.10 source (no declaration among the sound cvars, SoundLibrary.cpp:757-778
  is the complete list) and **absent from the Steam binary** (byte-grep of
  `SS_TSE_Steam_Bin\Engine.dll` for the string: not found — §12.3).
- Decision per addendum: **hardcode the linear branch** (beta default 1):
  `v ≤ 0.005 → −10000; else cB = ftol(3000 × (v(v−1) + (1−v)·log10(v)))` (99 #10,
  03 §2). Do not add a cvar.

### (b) Master volume application points `[VERIFIED]`

- `snd_fSoundVolume` (VA 0x602a40f8) / `snd_fMusicVolume` (0x602a40fc) are applied
  **inside `MixSound` per block** (SoundMixer.cpp:616-622) and once per play in
  `PrepareSound` (SoundObject.cpp:598-607). A muted/bypassed object skips both — the
  shadow path must apply the master factor itself, per frame.
- Since `SOF_MUSIC` is excluded from eligibility, only `snd_fSoundVolume` is needed.
  (The beta's music factor `snd_fMusicVolume × 0.5` — 03 §1 — never applies.)
- Beta parity: the beta multiplies the master into `so+0x64` per frame in `Update`
  (03 §1) — our per-frame `v = vol_spatial × snd_fSoundVolume` matches.

### (c) Mapping Steam inputs to the 99 #8 curve `[VERIFIED formulas]`

- Beta/Steam input mapping: beta `so.curVolume(+0x38)` ↔ 1.10/Steam
  `so_sp3.sp3_fMaxVolume` (the per-object requested volume; 1.10's `SetVolume` L/R
  values are overwritten every frame by `Update3DEffects` for 3D sounds and never
  survive as the base). Listener volume: beta `L.vol_float` ↔ `sli.sli_fVolume`.
- Shadow volume (per frame, per 02 §2 + 03 §1, computed in `P_Update3DEffects` from the
  same listener walk):

```
w      = 1 if dist ≤ hotspot else (falloff − dist)/(falloff − hotspot)   # per listener; dist > falloff → listener skipped
vol    = clamp01( Σ_listeners( sli_fVolume × sp3_fMaxVolume × w² ) / Σ w )
volume = vol × snd_fSoundVolume          # master
# beta crossfade (Fade()) deliberately NOT reproduced — 99 §4 unknown #2: skip
#   (1.10 game code has no crossfade API; parity of positional behavior unaffected)
# budget (snd_iMaxSameSounds, ours, default 5): per-CSoundData running sum; over → volume = 0
cB     = volume ≤ 0.005 ? −10000 : ftol(3000 × (v(v−1) + (1−v)·log10 v))   # 99 #10, linear branch
DS3D:  Buffer::SetVolume(cB, IMMEDIATE)                                   # 99 #6
```

- Frequency: `sp3_fPitch == 1.0 → SetFrequency(0)` else
  `ftol(sd_wfeFormat.nSamplesPerSec × sp3_fPitch)` (99 #11, 03 §3) — pitch variation
  only, no doppler.
- EAX DirectHF: if `SOF_3D && playing && sl_bUsingEAX && snd_bUseEnvironmentFX`:
  `val = clamp(round(−100 × hfFactor), −10000, 0)` via
  `KsPropertySet::Set(EAX20_Buffer, 0x80000003, …, DEFERRED)` (99 #13, 03 §5).
  `hfFactor` = weighted average of listener filter ints
  (`acc.filter/Σw`, 02 §2), skipped for sounds with `SOF_LOCAL|SOF_MUSIC|SOF_2D`
  (mask 0x58, 03 §5). `snd_bUseEnvironmentFX` is a **beta cvar absent from Steam**
  (§12.3) — declare it (default 1) for beta console parity.
- Listener gate for the shadow's spatial walk: reuse the existing `P_Update3DEffects`
  listener gates *including* the `[Cecil]` predicted-listener fix (06 §2) — a deliberate
  one-line deviation from the beta's stock gate (02 §2) so the shadow and any software
  3D remnants agree on the listener set; to be noted in 08.

---

## 12. Additional verified facts (not in any gap)

### 12.1 `~CSoundObject` inlines `Stop_internal` — destructor hook required `[VERIFIED]`

`??1CSoundObject@@QAE@XZ` (def L384, VA 0x6013e150) inlines the full `Stop_internal`
body — flags clear (`andl $0x2fffffff`), decoder delete, `RemoveObjectLink`+
`RemReference` — with **no call to 0x7E810** (scratch/steam-engine-disasm.txt:187221ff).
So a shadowed object being destroyed never passes through the `Stop_internal` hook:
without a destructor hook, the shadow table would hold a dangling `CSoundObject*` and
the DS buffer would leak (and keep playing). ⇒ hook the exported destructor
(`P_dtor`: release shadow first — force, not orphan — then call original). Game
entities live in `EntitiesMP.dll`; cross-module destruction calls the imported (hooked)
dtor, and inlining across the module boundary is impossible. All non-destructive stops
are still caught generically by the per-frame `SOF_PLAY` check in bookkeeping (the
Stop hooks are the explicit path, not the only safety net).

### 12.2 `CSoundObject::Read_t/Write_t` are dead in TSE `[VERIFIED within available sources]`

No caller of `WriteSoundObject_t`/`ReadSoundObject_t` exists anywhere in the 1.10 tree
(only their definitions, Engine\Base\ReplaceFile.cpp:922-935), no entity in
`EntitiesMP` embeds a `CSoundObject` member, and nothing else calls
`CSoundObject::Read_t/Write_t`. ⇒ TSE savegames/worlds never serialize sound objects;
engine-state poisoning would not leak into files. (Residual risk: Steam `EntitiesMP.dll`
could differ from the 1.10 open-source tree — [LIKELY] not; and the corrected mechanism
doesn't poison anything anyway.)

### 12.3 Cvar string presence in the Steam binary `[VERIFIED byte-greps]`

| String | Present in `Engine.dll` | Consequence |
|---|---|---|
| `snd_iInterface`, `snd_fEAXPanning`, `snd_iMaxExtraChannels` | yes | engine cvars; read via `CSymbolPtr` |
| `snd_bLinearVolume` | **no** | hardcode linear curve (G10a) |
| `snd_iEmulationType` | **no** | patch declares it (guid3DAlgorithm, G6) |
| `snd_iMaxVoices`, `snd_iMaxSameSounds` | **no** | patch declares both (99 #15/#9 budget) |
| `snd_bUseEnvironmentFX`, `snd_bUseHeadphones` | **no** | declare the former (EAX DirectHF gate); skip the latter (beta-only, unused by our sheet) |
| `snd_bDS3DSpatial` | **no** | no name collision with the new cvar |

### 12.4 Cvar declaration + re-init pattern `[VERIFIED]`

Engine cvars are declared in one block (SoundLibrary.cpp:757-778) with
`_pShell->DeclareSymbol("persistent user … post:SndPostFunc;", &var)`; the patch's own
cvars follow the `_EnginePatches` member pattern (06 §5,
`EnginePatches.cpp:333-337`). New patch cvars (`snd_bDS3DSpatial`, `snd_iEmulationType`,
`snd_iMaxVoices`, `snd_iMaxSameSounds`, `snd_bUseEnvironmentFX`) get declared in
`ICorePatches::SoundLibrary()` (or the new category) the same way; `snd_iEmulationType`
additionally needs a `post:` handler that releases templates + triggers `SetFormat`
(only the algorithm GUID depends on it — 99 #14).

### 12.5 `SndPostFunc` is itself reachable `[VERIFIED]`

`SndPostFunc` is a shell-declared function (`"void SndPostFunc(INDEX);"`, L757) bound
via `post:` tags — the engine's own mechanism for cvar-change re-init. Our
`P_SetFormat` wrapper therefore also sees console-driven re-inits (G2/G6).

### 12.6 Constructor defaults (first-block context) `[VERIFIED]`

`CSoundObject` ctor (SoundObject.cpp:78-110): `spNew` volumes 1.0, filters 0x7FFF,
pitch 1.0, delay 0; `so_sp = so_spNew`; offsets 0; last volumes 1.0. Under 7.4 none of
this is mixed for shadowed objects (bypassed), it only sets the initial `sp` snapshot.

### 12.7 `Play_internal` resets `so_fDelayed` on every non-SOF_LOADED play `[VERIFIED disasm]`

Sliced `Play_internal` (0x7E500–0x7E6B0, `scratch/steam-engine-disasm.txt`): the
`so_sp = so_spNew` copy (`rep movsl`×7, `0x6013e615-0x6013e61c`) is followed by the
mixer-var init block, gated by the *play request's* `SOF_LOADED` bit (arg2):
`6013e61e: testl $0x20000000, %eax` / `6013e624: jne …+0x194` (skipped for savegame
replays — offsets restored). Inside the block, `6013e62b: xorl %eax,%eax` then
`movl %eax,` **`0x24`** (`so_fLeftOffset`), **`0x28`** (`so_fRightOffset`), `0x2c`,
and **`0x14` = `so_fDelayed = 0`** (`6013e635/63e/641/644`); last L/R volumes are
initialized from `so_sp` L/R (`flds (%edx)` / `flds 0x38(%ebx)` → `fsts/fstps
0x18/0x1c`), master-scaled on the smooth-continue path (`0x6013e665-0x6013e691`:
`testb $0x40` SOF_MUSIC → `snd_fMusicVolume`@0x602a40fc else
`snd_fSoundVolume`@0x602a40f8 — matches G10b's once-per-play scaling); last samples
zeroed on the non-smooth path (`6013e649/64d`, `0x20/0x22`).

Consequence (§13 item 16): **no `P_Play_internal` post-original `so_fDelayed` reset
is needed** — the original zeroes it on every fresh play and every re-play (re-play
routes through `Play_internal` too), and the savegame path correctly preserves the
restored delay. Our finish-path reset (`so_fDelayed = 0`) mirrors the stock mixer's
finish (`0x6013b2a6`).

---

## 13. Consequences carried into `08-design.md`

1. Mute primitive = `MixSound` raw-address hook (RVA 0x7AF80), not volume zeroing
   (G7.2/7.4). No engine state is poisoned, ever.
2. Shadow lifecycle = beta bookkeeping: per-frame `GetStatus`, finish → clear
   `SOF_PLAY` (ours, under lock) + forced release; engine `Stop_internal` → orphan
   play-out (99 #17); destructor → forced release (12.1 — needs the extra dtor hook).
3. Hook set (all exported except MixSound): `Play_internal`, `Stop_internal`,
   `Update3DEffects` (existing replacement, extended), `UpdateSounds` (wrapper),
   `SetFormat` (wrapper), `Mute` (wrapper), `ClearBuffer` (wrapper, template cache),
   `~CSoundObject` (release-first), + static `MixSound` (raw address).
4. Gates: interface (listener-present, re-checked after every `SetFormat`),
   `SOF_PAUSED` (release/recommit), game-pause + `Mute()` window (buffer-kept park),
   budget (volume −10000 at live position), parked (position sentinel + volume −10000,
   buffer keeps playing).
5. Volume/frequency/EAX per 99 #8–#13 with the G10 input mapping; master
   `snd_fSoundVolume` applied by the shadow per frame.
6. All new cvars declared patch-side (12.3/12.4); `snd_iEmulationType` re-init via
   `post:` → `SetFormat`.

**Amendments 2026-10-14 (user review of 08, approved):**

7. **Driver relocated**: the per-frame DS driver moves out of `P_Update3DEffects`
   (which becomes store-only: 1.10 math + write pos/vel/vol/hf/gates into
   `DS3DShadow`) into the `P_UpdateSounds` tail, running over the table **sorted
   by `fLastVolume`** (beta `PlayBuffers` per-frame sort, 04 §3/§4 — required for
   voice stealing). Threading model unchanged (same thread, same `sl_csSound`).
8. **Finish rule**: `bStarted && not-playing && !SOF_LOOP && no gates` → finished
   (G9 item 4); no play-cursor reads anywhere in finish/failure logic.
9. **Offline prologue check (all 9 hook targets; faithful simulation of
   `CPatch::CanRewriteInstructionSet`, patcher.cpp:28-224, against the actual Steam
   `Engine.dll` bytes) [VERIFIED]**:
   - OK: `Play_internal` 0x7E500 (rewriteLen 5), `~CSoundObject` **0x7E150** (5),
     `Update3DEffects` 0x7E870 (9), `UpdateSounds` 0x796F0 (5), `SetFormat`
     **0x784A0** (5), `Mute` 0x782B0 (5), `ClearBuffer` 0x76200 (6), static
     `MixSound` **0x7AF80** (6).
   - **FAIL: `Stop_internal` 0x7E810** — prologue `56 8b f1 57 8b 4e 10`; the decoder
     has no pattern for `mov ecx,[esi+d8]` (`8b 4e`) at +4. `P_Stop_internal` must
     call `FuncPatch_ForceRewrite(7)` (7 = 1+2+1+3, an instruction boundary; within
     the `VirtualProtect(...,10)` window).
   - Two RVAs in the 08 draft were wrong, corrected above: dtor 0x72E50 → 0x7E150
     (§12.1 VA 0x6013e150 is the correct source), `SetFormat` 0x78180 → 0x784A0
     (export dump). Both hooks resolve by name in code — doc-only fixes.
   - The raw-address `MixSound` hook must additionally byte-compare the first five
     bytes (`55 8b ec 83 ec`) + verify module identity before patching, refusing the
     mode on mismatch (patch-creation failure is fatal at startup, 06 §3 / IPatches.cpp:102).
10. `Play_internal` has exactly one caller in the Steam engine binary — `Play` at
    0x6013e4d1 (full-disasm grep, steam-engine-disasm.txt:187561) — so pre-registration
    under `Play`'s `sl_csSound` closes the first-block window [VERIFIED].

**Amendments 2026-10-15 (second user review, verified then applied):**

11. **Position-preserving release** (item A): engine offsets are frozen under 7.4, so
    every release of a *live* shadow must sync the DS play cursor back first
    (`ReleaseKeepingPosition()`, §G4d) — `SOF_PAUSED`, voice steal, `SetFormat`
    pre-release, `ClearBuffer` forced drop, G9 drop. Guards: `bStarted` only
    (delay-pending sounds keep delay + start offset); no sync for buffer-kept parks
    (game pause / `Mute` window) or the destruction path. Rejected: per-frame cursor
     mirroring (breaks the acceptance row's call order); mixer-rate offset conversion
     across `SetFormat` (stock-parity imprecision kept). (The sites listed above are
     now the two release primitives of item 14; the sync itself is unchanged.)
12. **`psdData` becomes an opaque key after commit** (item B): a `CSoundData` can be
    freed at `FreeUnusedStock` level/session transitions (Network.cpp:643, called at
    1079/1187/1277/1339/1744/2387) while the shadow table or budget sums still hold
    its pointer; `~CSoundData`→`Clear`→`ClearBuffer` (SoundData.cpp:91-106, hooked)
    normally invalidates first, but the driver must not rely on dereferencing
    `psdKey`. The shadow caches `nSamplesPerSec`/channels/bytes-per-frame at commit
    (`SetFrequency`, offset conversion use the copies); `psdKey` is used only as a map
    key (budget sums, template cache) and never dereferenced after commit; re-play with
    different data updates key + cached fields in `P_Play_internal`. The orphan list
    already holds only `IDirectSoundBuffer` pointers (08 §8) — safe by construction.
13. **Template-cache entry validation**: entries store (`sd_pswBuffer`, byte size, rate,
    channels) captured at creation; lookup compares them against the live
    `CSoundData` and rebuilds on mismatch — cheap guard against `CSoundData*` address
    reuse if any `ClearBuffer` path is ever missed. **Assumption to runtime-test
    (DSOAL):** a duplicate keeps playing (shared memory) after its template is
    `Release`d — DS documents the contract, DSOAL behavior unverified. Test: stop a
    long one-shot (orphan playing out) and force its data's `ClearBuffer` (level
    change) under DSOAL; also the §11 pause/resume mid-one-shot check.

**Amendments 2026-10-15 (third user review — `SetFormat` recreate, release
primitives, delay counter, guards; Task-3 design final):**

14. **Release primitive split** (replaces the overloaded "release" everywhere):
    - **`ReleaseForRecommit`**: position sync (`ReleaseKeepingPosition` body,
      `bStarted`-guarded) + release buffer/3D/KS ifaces + `bStarted = false` +
      `bSpatialValid = false` + **keep the table entry** (`bBypass` stays true).
      Sites: `SOF_PAUSED` release (driver step 1), voice steal (step 2 — the tail
      additionally sets `bBypass = false`, item 19), `P_SetFormat` pre-release,
      `P_ClearBuffer` when the owner is alive. The `bStarted=false` reset routes
      the recommit through the `bSpatialValid` Play-latency guard (item 18) instead
      of reissuing `Play` against stale state.
    - **`DropToSoftware`**: position sync (same guard — intentionally inert when the
      buffer is already gone, e.g. after a `ReleaseForRecommit`) + release +
      **remove the table entry**; software resumes audibly from the synced offset.
      Sites: G9 failures, forced mode disable (listener loss — the **only mass
      `DropToSoftware`**; user cvar-off keeps drain semantics), listener missing
      after `SetFormat`.
    - Sites that are *neither* primitive stay plain releases: `Stop_internal`/dtor
      (orphan/force), driver finish (step 8), the `!SOF_PLAY` validation drops.
15. **Recreate after `SetFormat`** (reverses the earlier "not recreated" wording in
    G6 — user decision): still-playing shadows are **recommitted at their synced
    offsets** by the next `P_UpdateSounds` tail; one frame of silence per sound is
    accepted (entry bypassed in software, no buffer yet). Rationale: ambient loops
    never re-enter `Play_internal`, so "finish in software" would de-spatialize a
    loop for the rest of the level — and `SetFormat` fires from the `UpdateSounds`
    window watchdog (pre-lock call at 0x60139734), not only device/format changes;
    and recreate is the only option under which toggling `snd_iEmulationType`
    affects running sounds (99 §4 #6 — mechanism in place, runtime test pending).
    The mass recommit is budget-gated: over-budget survivors take the item-19
    software fallback, not silence.
16. **Delay counter = engine field `so_fDelayed`** (user decision): the
    `P_UpdateSounds` tail advances `so_fDelayed` each frame for `bDelayPending`,
    **`bBypass=true`** shadows only (never fallback entries — their delay the stock
    mixer consumes itself; no double-advance), exactly as `MixSound` would
    (`so_fDelayed += frameSecs`; elapsed = `so_fDelayed >= so_sp.sp_fDelay` —
    `so_sp`, which is what the mixer compares against, SoundMixer.cpp:595).
    Sentinel interplay: a *started* sound's sync writes 9999.9999 (past-delay), which
    survives the `bStarted=false` reset — the recommit passes the delay test
    immediately; a *pending* sound keeps its partial `so_fDelayed` across re-init.
    Consequence: any mid-delay drop (failure, mode disable, `ReleaseForRecommit`)
    resumes software mid-delay for free — no per-site writeback discipline.
    Finish path (driver step 8) sets `so_fDelayed = 0` — mixer parity (§7.2).
    `Play_internal` itself resets it on every non-SOF_LOADED play (§12.7) — **no
    `P_Play_internal` post-original reset needed**.
17. **Format-cache refresh at (re)commit**: `Reload` may have re-downsampled
    (`Read_t`: `min(fileRate, mixerRate)`), so `shadow.iRate`/`iBytesPerFrame` can
    be stale at recommit. Required ordering: driver validation (`!SOF_PLAY` → drop)
    → read `pso->so_pCsdLink` (**live while `SOF_PLAY`** — playing implies the
    `AddObjectLink` reference) → refresh `psdKey` + `iRate`/`iChannels`/
    `iBytesPerFrame`. `psdKey` itself stays an opaque key (item 12). The ordering +
    the "never dereference `psdKey`" rule go side by side as a comment in
    `SoundDS3D.h` (08 §8).
18. **`bSpatialValid` Play-latency guard**: store-less table entries can exist
    (another thread's `Play` acquires `sl_csSound` between the `P_UpdateSounds`
    original's lock release and the tail's re-take; and the recommit paths
    themselves). `BOOL bSpatialValid`, initial **FALSE**, set by the
    `P_Update3DEffects` store. Commit may happen while false; **`Play` waits**
    until true. Cost: ≤ one frame of start latency; loses no audio. Backstop:
    stored spatial fields initialize to parked (pos (0,0,+10000), vol 0, vel 0,
    hf 0). Rejected: play-while-parked — consumes a frame of content inaudibly
    and clips the attack of short one-shots (gunshots).
19. **`bBypass` — software fallback for uncommitted entries** (fixes the
    finish-authority hole found in this review): a registered-but-never-committed
    entry is `P_MixSound`-bypassed, so nothing ever clears its `SOF_PLAY` (finish
    needs `bStarted`/a buffer) — a silent zombie with `IsPlaying()` true; the beta
    had no such hole because its per-object timers ran independent of channel
    state (04 §5). Rejected fixes: **virtual advancement** (reimplements the stock
    skip path — pitch-scaled step, wrap, finish, delay: §7.2/§7.3 — duplicated
    subtle logic) and **`DropToSoftware`-on-overflow** (permanently de-spatializes
    looping ambients that lose a transient budget race). Chosen: bypass only while
    the entry is in the shadow path — `bBypass` is **TRUE at registration**
    (first-block proof intact) and stays **TRUE after `ReleaseForRecommit`** (incl.
    the pause release — else a resumed-but-unbuffered entry would be mixed for one
    block); the tail sets it **FALSE only when it denies a commit** (voice budget,
    or a steal victim). `P_MixSound` skips only when `bBypass` is set → the stock
    mixer plays/advances/wraps/finishes fallback entries with real `so_spNew`
    values on its own schedule; the `!SOF_PLAY` validation drops them; each tail
    retries the commit, and on success `bBypass` goes back to TRUE with the buffer
    created at `bytes(so_fLeftOffset)` — offsets are live now, accurate to one mix
    block. **DEVIATION from 99 #15** ("uncommitted, silent this frame"):
    budget-denied voices become audible non-spatial software sounds (graceful
    degradation; honors "never silent in both paths"); recorded here per
    addendum §1 before the 08 edit.
20. **`bGateStopped`** (step-7 precision): set when the driver Stops a playing
    buffer in the pause/mute gate (step 6); step 7 re-Play condition = buffer
    exists && !playing && !gated && !delayPending && `bSpatialValid` &&
    (`!bStarted` || `bGateStopped`); cleared when `Play` is issued. An explicit
    flag instead of inferring "gate lifted this frame"; covers non-looping
    mid-buffer resume (a gated `Stop` also needs a `Play`) and removes the spurious
    per-finish `Play` of the old condition. A looping buffer that stops without a
    gate is not re-Played (beta parity — the beta's fresh → Play → GetStatus →
    finished rule has no loop-resurrect either); failures route through G9.

**Amendments 2026-10-16 (LC cross-check + design change D8 — silent sounds are not
committed; user decision 2026-10-16; evidence and provenance in §14):**

21. **D8 silence test** = stored spatial volume **after `snd_fSoundVolume`,
    before the same-sounds budget**, `< 0.005` (beta const 0x101b95cc). Deliberate
    difference from the beta, whose gate reads the **post-budget** current volume
    (beta 0x10082ad3 reads so+0x64, which `Update` zeroes when over the sound-mass
    budget; 07 §14.2): following the beta would let budget-silenced sounds fall
    into the `bBypass=false` software fallback audibly and defeat
    `snd_iMaxSameSounds`. Deviation flagged to the user (§14.5).
22. **Not held + silent** → **no commit attempt, no voice slot, no DS calls at
    all** (beta 0x10082b99-0x10082bc9: commit gate `!bInPlayBuffer && !bIsSilent
    && !SOF_PAUSED`; a still-uncommitted entry hits the `chan < 0 → next sound`
    skip before any positioning), and the tail sets `bBypass = false` so the stock
    mixer owns the entry (software is silent too — out-of-range `so_sp` volumes
    are ~0; stock already kills parked non-looping sounds after one block, §7.2
    corollary, and loops keep advancing silently). Accepted side effect: a sound
    just under 0.005 can be faintly audible (≤ −46 dB, the curve knee)
    non-spatially in software.
23. **Silent → audible**: normal commit at the live `bytes(so_fLeftOffset)`
    (offsets are live — the stock mixer advanced the fallback entry),
    `bBypass = true` (item 19 mechanism unchanged).
24. **Held + silent (parked)**: keep the buffer parked (position `(0,0,−10000)`
    + `SetVolume(−10000)` as today) and run a silent-since timer on the beta's
    clock (game tick; real time for `SOF_NONGAME` — beta `ResetTimer`/`GetElapsedTime`
    0x100892f0/0x10089370, LC SoundObject.cpp:821-856 paraphrase). Audible again
    within 10 s → timer cleared (beta 0x10082b1a-0x10082b21). Silent > 10 s
    (beta 0x10082b46, const 0x101b95c8 = 10.0) → **`ReleaseForRecommit` +
    `bBypass = false`**: synced offset, software continues silently, recommit at
    the live offset when audible again. The beta's release is non-forced (orphan
    plays out at −10000); ours syncs the cursor instead — same inaudible result,
    no orphan dependency.
25. **Silent entries do not count toward `snd_iMaxVoices`** (beta: the voice
    countdown decrements only on commit — 0x10082be3; silent entries never reach
    it).
26. **Budget interaction (deliberate deviation)**: over-same-sounds-budget sounds
    keep the current 08 behavior — committed, volume 0 at live position, counted
    as voices. The beta lets the budget zeroing feed the silence gate → no commit
    / 10 s release; rejected for us because the `bBypass=false` fallback would
    play them audibly in software (item 21 rationale).
27. **First-block proof unchanged**: registration sets `bBypass = true`; the
    first tail after the spatial store sets it false if the sound is silent and
    uncommitted (item 22).
28. **`DS3DShadow` gains a silent-since timestamp** (DOUBLE timer value on the
    item-24 clock; equivalently flag + tick). Acceptance row "Parked sounds"
    tightened: `(0,0,−10000)` + `SetVolume(−10000)` appear **only while a buffer
    is held** (≤ 10 s of silence); never-committed sounds produce no DS calls.
29. *(Not adopted, recorded for completeness — 07 §14.5)*: the beta's own finish
    backstop is a single compare in `Update()`: non-looping, non-decoder,
    `elapsed > sd_tmLength + 1 s` → clear `SOF_PLAYING`, ignoring pitch (beta
    0x10087693-0x100876eb; LC SoundObject.cpp:547-551 paraphrase). `bBypass`
    (item 19) already closes the same hole with audible fallback; the backstop is
    the alternative, not the implementation.

---

## 14. LC cross-check (2026-10-16)

**Provenance and rules.** New read-only input: the Last Chaos (LC) client engine
source, user-trimmed to `lastchaos-source-client\Engine\Sound` (SoundLibrary.cpp/.h,
SoundObject.cpp/.h, SoundData.cpp/.h, SoundMixer.cpp, SoundDecoder.cpp/.h, eax.h,
al_functions.h, ov_functions.h). LC is a later game on the 1.50-era engine — a
**cross-check, not ground truth**; the beta binary wins on any conflict. The LC
code is **leaked proprietary source** and this project is GPL, so the following
rules are binding: verification only — no LC code is copied or ported, and **no LC
snippets are pasted into any findings file**; the citations below are locators
(`file:lines`) plus behavioral paraphrase only; nothing derived from LC goes into
the public findings repo (`adhdandy/serious-sam-ds3d-findings`). Every claim below
was verified against the LC source at the cited locators during this session, and
each beta-binary check from the handoff was run read-only against
`scratch/beta-engine-disasm.txt` (function slices: `scratch/lcx-beta-{commitplayingbuffer,playbuffers,update}.txt`).

**Known LC-vs-beta differences (all re-verified this session; beta wins):**
`snd_iMaxVoices` default 20 (LC SoundLibrary.cpp:73) vs 30 (beta .data 0x1020f80c);
`snd_iEmulationType` range 0–3 including NO_VIRTUALIZATION=1 (LC SoundData.cpp:567-571)
vs beta 0/1/2 with out-of-range values remapped to 1 by a write-back at LoadWAV_t
(0x1007f063) and no NO_VIRTUALIZATION; LC QIs `IID_IDirectSound3DBuffer8`
(LC SoundLibrary.cpp:1363) vs beta `IID_IDirectSound3DBuffer` (0x100826d3); LC voice
clamp bounds 5–50 (`SND_MINBUFFERS`/`SND_MAXBUFFERS`, LC SoundLibrary.h:50-51) vs beta
4–64 (04 §7). None affect the spec (we declare our own cvars with the beta's values).

### 14.1 Beta-binary checks (all six PASS — no disagreement with LC)

| # | Check | Result |
|---|---|---|
| 1 | PlayBuffers pause path (0x82CEA–0x82D71) | **No `SetVolume(−10000)`/`SetFrequency(0)`** — when `bShouldPause` (game paused && !SOF_NONGAME, computed 0x10082c5f-0x10082c7f) the volume+frequency sets are skipped entirely (`jne 0x10082d5c` at 0x10082c9a); a playing buffer only gets `SOF_WAITING` set (0x10082d64) + `Stop()` (0x10082d71). The log's −10000 volumes come solely from the 0.005 silence gate (`DSBVOLUME_MIN` preloaded at 0x10082ca3). ⇒ 04 §4's old "mute path" line and 99 #20 corrected. |
| 2 | Silence gate, 10 s release, WAITING finish rule | Commit gate `!bInPlayBuffer && !bIsSilent && !SOF_PAUSED` (0x10082b99-0x10082bbc) with `bIsSilent = so+0x64 < 0.005` (0x10082ad3-0x10082ae8) — so+0x64 is post-budget, i.e. **the beta tests after the same-sounds budget**. Held+silent > 10.0 s (0x10082b46, const 0x101b95c8 = 10.0) → `ReleasePlayingBuffer(chan, 0)` **non-forced** (orphan plays out) + next sound (0x10082b53-0x10082b6e). Finish rule 0x10082d78-0x10082dcf: `!playing && !pauseGated && !loop && (!SOF_WAITING(0x10000000) \|\| elapsed(0) > so_pCsdLink+0x30 (sd_tmLength))` → `Stop(1)` (0x10082da7), else `Play(0,0,loop?)` (0x10082dc7); `SOF_WAITING` cleared after both (0x10082dcf); set at commit (0x10082722) and at pause-stop (0x10082d64). |
| 3 | `SetCurrentPosition` at 0x10082BFB | Argument is the **constant 0** (`ebx`, held 0 from 0x10082bea); the `GetElapsedTime(0)` call (0x10082bed) has its result **discarded** (`fstp %st(0)` at 0x10082bf2). Beta recommits always restart at 0 — the same dead computation as LC's shadowed local (§14.3 item 1). |
| 4 | Update backstop | `!SOF_PAUSED && so_pCsdLink && !decoder(so+0x9C) && !SOF_LOOP && GetElapsedTime(0) > so_pCsdLink+0x30 + 1.0` (const 0x101b8cd0 = 1.0) → clear `SOF_PLAYING` + return (0x10087693-0x100876eb). Ignores pitch. |
| 5 | `snd_iMaxVoices` / `snd_iEmulationType` | Default **30** (.data 0x1020f80c). `snd_iEmulationType`: 0 → DEFAULT, 2 → GUID@0x101b9398 (HRTF_FULL), anything else → GUID@0x101b93a8 (HRTF_LIGHT) **and 1 is written back to the cvar** (LoadWAV_t 0x1007f063) — range 0/1/2, invalid → 1, no NO_VIRTUALIZATION (LC differs, see header). It is `post:` — SetFormat on change (Init 0x10081b80 compares `_iLastEmulType`; SetFormat snapshots it at 0x10081e92). |
| 6 | SetMode only on the mono path | The QI(3DBuffer)/QI(KsPropertySet)/`SetMode` block sits inside the `bMono` branch of CommitPlayingBuffer (`movl -0x1c; testl; je 0x1008271f` at 0x1008269d-0x100826a2 skips it for stereo) — **stereo duplicates never get `SetMode`**; the 21 `DISABLE` calls are mono non-3D or `SOF_VOICE` sounds. The 227 vs 228 SetMode/duplicate residual stays open. |

### 14.2 Confirmed by LC (no change to the findings; tag "LC-confirmed" applied where cited)

- Listener init: orientation/position/velocity/rolloff 0.0/doppler 1.1, all IMMEDIATE
  (LC SoundLibrary.cpp:491-499) — 04 §1, 99 #1.
- z-negated DEFERRED `SetPosition`/`SetVelocity` (LC SoundLibrary.cpp:1571-1577) — 02 §5, 99 #3/#4.
- One `CommitDeferredSettings` immediately after `PlayBuffers` in `UpdateSounds`
  (LC SoundLibrary.cpp:1143-1149) — 02 §6, 99 #6.
- Volume curve: 0.005 gate; linear branch 3000×(v(v−1)+(1−v)log10 v); log branch
  3000×log10 (LC SoundLibrary.cpp:1586-1606) — 03 §2, 99 #10.
- `SetFrequency` = rate × pitch or 0 (LC SoundLibrary.cpp:1603-1606) — 03 §3, 99 #11.
- Steal rule: commit denied unless `new − lowest ≥ 0.333` (LC SoundLibrary.cpp:1326-1340;
  beta 0x10082620-0x10082638, polarity re-verified) — 04 §3, 99 #15.
- Duplicate → QI(3D) → (QI(KS) if 3D&&EAX) → `SetMode` → `SetCurrentPosition`
  (LC SoundLibrary.cpp:1346-1373 + 1557-1569) — 04 §3, 99 #16.
- Decoder sounds skipped by `PlayBuffers` (LC SoundLibrary.cpp:1495) — 04 §6.
- Pending list sorted by current volume desc, then distance (LC SoundLibrary.cpp:1018-1042) — 04 §4.
- EAX DirectHF = clamp(round(−100 × filter), −10000, 0), DEFERRED — and the `Set`
  is issued **also when `snd_bUseEnvironmentFX == 0`** (value 0; LC SoundLibrary.cpp:1636-1643;
  beta 0x10082def `je 0x10082e2a` skips only the computation, the `Set` at 0x10082e44 is
  unconditional) — 03 §5, 99 #13.
- Software doppler c = 300 only on the non-DS3D/decoder path (LC SoundObject.cpp:439-450:
  the function returns above the doppler block when DS3D && !decoder) — 03 §4, 99 #12.
- Volume weight w²: spatial volume accumulates `so_vol × sli_vol × w²` (position and
  velocity use w¹) (LC SoundObject.cpp:415-425) — 02 §2, 99 #8.
- `sd_fSoundMass` reset per `UpdateSounds` (pre-pass over the pending list), accumulating
  the master-scaled volume in list order; over budget → volume 0 for that object
  (LC SoundLibrary.cpp:1098-1105 + SoundObject.cpp:605-615) — 03 §1, 99 #9.

### 14.3 Corrections applied (each verified in LC and, where listed, in the beta binary)

1. **Beta recommit offset**: LC computes a resume offset from the play timer but
   redeclares the local inside its `if`, so the outer 0 is always passed to
   `SetCurrentPosition` (LC SoundLibrary.cpp:1557-1569); the beta binary behaves the
   same — the timer call is made and its result discarded (§14.1 check 3). Matches the
   log (228 × `0`). **Beta recommits always restart at 0; our synced-offset release is
   an improvement, not parity.** Applied: 07 §G4c/G4d, 99 #18, 04 §5.
2. **Flag names** (beta bit values with LC's names, LC SoundObject.h:14-25):
   **0x40 = `SOF_VOICE`** (attenuate other sounds; excludes the sound from 3D mode),
   not "SOF_2D"; **0x10000000 = `SOF_WAITING`** ("paused automatically by engine" —
   set at commit and at pause-stop, consumed by the finish rule), not "has hw buffer";
   **0x40000000 = `SOF_LOADED`** ("sound just loaded"), not SMOOTHCHANGE; 0x20000000 =
   SOF_PAUSED (manual); mask 0x58 = `SOF_LOCAL|SOF_MUSIC|SOF_VOICE`. Steam 1.10 has no
   voice flag — nothing to map. Applied: 01 §4, 02 §2, 03 §5, 04 §3.
3. **SetMode only inside the mono path** (§14.1 check 6). Applied: 04 §2/§3, 99 #7,
   00 §4.4.
4. **Pause path**: no `SetVolume(−10000)`/`SetFrequency(0)` — the sets are skipped;
   WAITING + Stop only (§14.1 check 1). Applied: 04 §4, 99 #20, 08 §4 step 6
   (acceptance-log-order only).
5. **DirectHF `Set` with value 0 when the cvar is off** (§14.2, EAX bullet). Applied:
   03 §5, 99 #13 (cvar-off only, low priority — our gate skips it).
6. **Master volume factors**: music = `snd_fMusicVolume / 2`; `_bMuteVolume` → 0;
   `_bAttenuateVolume` → 0.5 except `SOF_VOICE` sounds (set by `UpdateSounds` when a
   `SOF_VOICE` sound with current volume > 0.2 is pending — LC SoundLibrary.cpp:1098-1102).
   The "menu-state factors" `DAT_1022e9d8/DAT_1022e9d4` are exactly these two (beta
   Update head 0x100875e6-0x1008761a: mute → 0.0, attenuate && !SOF_VOICE → 0.5, const
   0x101b8c68). Steam has neither → N/A for the mode. Applied: 03 §1.

### 14.4 Closed unknowns (99 §4 #1/#2)

- **#1 volumetric blend**: angle = `ACos(dot(normalize(dir), (0,0,−1))) × bias`;
  `bias = min((dist − hotspot)/(falloff − hotspot) × 3, 1)`; bias = 0 (inside hotspot)
  → position `(0,0,−1)`, speed 0; 0 < bias < 1 → axis-lerp construction around the
  (0,0,−1) basis; bias ≥ 1 → plain rotated delta (LC SoundObject.cpp:384-412
  paraphrase). The `_DAT_101b8ca8 = 0.0` "angle scale" was a **Ghidra misread** (it is
  the volumetric-bias default 0.0, not a multiply in the acos path). Applied: 02 §3,
  99 sheet row #5 → VERIFIED.
- **#2 `Fade()`**: volume = lerp(spatialVolume, fadeTarget, t); a fade completing at
  target 0 stops the sound (clears `SOF_PLAYING`) (LC SoundObject.cpp:553-570, 583
  paraphrase). Not applicable on Steam (no Fade API) — stays skipped.

### 14.5 Design change D8 — silent sounds are not committed (user decision 2026-10-16)

Reason recorded before the 08 edit (addendum §1 deviation rule): 08 §4/§6 as drafted
commit every eligible playing sound and never release parked ones, which would let
out-of-range ambients exhaust `snd_iMaxVoices` and push audible sounds into the
software fallback; the beta's own behavior (LC SoundLibrary.cpp:1514-1532 + §14.1
check 2) keeps silent sounds out of the channel system entirely. Spec: §13 items
21-28 above; 08 §0 (D8 row) / §4 (steps 2-3, closing paragraph) / §6 / §8 / §10 /
§11 step 5 amended. Deliberate deviation: the silence test runs **before** the
same-sounds budget (items 21/26) — flagged to the user with this entry. The beta's
own finish backstop was considered and not adopted (item 29; alternative only).
