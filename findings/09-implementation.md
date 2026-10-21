# Architecture: per-sound DirectSound3D for Serious Sam TSE 1.07

This document explains, at a high level, how the **shadow-buffer DS3D mode** was implemented.
It is written for someone who knows what a game sound is, but not how this
particular engine (or this patch) is organized. Exact numeric details, edge cases and
evidence live in `findings/08-design.md`, `findings/07-implementation-notes.md` and
`findings/99-summary-and-open-questions.md`.

---

## 1. What the project is

The game is the Steam release of **Serious Sam: The Second Encounter 1.07**, which uses a
2002-era **Serious Engine** build. The stock engine has a software mixer: it computes the
3D effect of every sound itself and mixes all sounds into two mono streams (a left "ear"
and a right "ear") before handing those two streams to DirectSound.

A later version of the engine (the TSE 1.50 "beta", used here as a behavioral reference)
instead gave every 3D sound its own **DirectSound3D** buffer, so the audio driver could do
per-sound 3D processing (distance, panning, doppler, HRTF, EAX).

This project adds that capability back to 1.07 **without replacing `Engine.dll`**. It is a
runtime patch:

- `SuperProject/` builds a separate `ClassicsCore.dll`.
- At startup, the patch hooks a small number of engine functions.
- The feature is off by default (`snd_bDS3DSpatial 0`). With the cvar off, the game should
  behave like the unmodified Steam build.

The new implementation lives in `SuperProject/Core/Patches/SoundDS3D.h` and
`SoundDS3D.cpp`; the hook bodies that replace engine methods live in
`SuperProject/Core/Patches/SoundLibrary.cpp`; the hooks are registered in
`SuperProject/Core/API/EnginePatches.cpp`.

The mode deliberately does **not**:

- replace `Engine.dll` or any game assets;
- spatialize music, streamed/encoded sounds, or stereo sounds (they stay in the stock
  software path);
- add new EAX environments (it exports the engine's existing per-sound high-frequency
  filter as EAX `DirectHF`);
- change gameplay sound logic. It changes **how** eligible sounds are rendered, not when,
  where, or why the game plays them.

---

## 2. The stock audio path

The stock engine has two relevant kinds of objects:

- **`CSoundData`** — the loaded sound asset (PCM samples, sample rate, channel count).
- **`CSoundObject`** — one playing instance of that asset (position, volume, pitch,
  flags, playback cursor).

Every frame, roughly this happens:

```text
 CSoundObject A ─┐
 CSoundObject B ─┤   CSoundObject::Update3DEffects()
 CSoundObject C ─┘   computes volume/pan/filter/delay for each 3D sound
                          │
                          ▼
                 so_spNew  (the "next frame" mixing parameters)
                          │
                 CSoundLibrary::UpdateSounds()
                 copies so_spNew -> so_sp, prepares sounds
                          │
                          ▼
        timer/audio thread: MixSounds() -> MixSound() per object
                 sums every sound into the software mixer
                          │
                          ▼
              sl_pDSSourceLeft / sl_pDSSourceRight
              (two mono DirectSound3D buffers, fixed at the ears)
                          │
                          ▼
                    DirectSound / driver
```

The important consequence: by the time DirectSound sees audio, it only sees **two mixed
streams**. It cannot apply per-sound HRTF, per-sound occlusion/EAX filtering, or per-sound
doppler, because the sounds have already been merged.

The engine's mixer is also where a sound is *advanced* and eventually *finished*: it moves
the playback offsets, wraps looping sounds, and clears `SOF_PLAY` when a non-looping sound
ends. Any design that hides a sound from the mixer must therefore take over those jobs.

---

## 3. The idea: a shadow buffer beside each sound

For every eligible sound, the patch creates a **shadow**:

- a small bookkeeping record (`DS3DShadow`) keyed by the engine's `CSoundObject*`, and
- a real DirectSound buffer, duplicated from a cached 3D template, with its own
  `IDirectSound3DBuffer` interface.

The engine object remains the owner and the authority for the sound's lifetime. The shadow
is a helper that mirrors its audible state. It is called a "shadow" because it follows the
engine object around: when the object plays, pauses, stops, changes volume or dies, the
shadow follows.

```text
                              game thread, once per frame
                     ┌──────────────────────────────────────┐
                     │                                      ▼
 CSoundObject ──> P_Update3DEffects() ──> DS3DShadow ──> per-sound 3D buffer ───┐
   (owner)          store-only snapshot       (record)      (DirectSound)       │
                                                                                │
 CSoundObject ──> not eligible ──────────> stock software mixer ──> ear pair ───┤
   (music/2D)                                                                   │
                                                                                ▼
                                                                       DirectSound / DSOAL
```

Two separate things make this work:

1. **The shadow gets its own audio.** The template cache (`DS3DTemplate`) stores one PCM
   copy per `CSoundData`. Each play makes a `DuplicateSoundBuffer` of that template. The
   duplicate shares the sample memory but has its own play cursor and 3D state. This is
   cheap and matches what the later engine did.

2. **The stock mixer is told to skip that object.** The patch hooks the static function
   `MixSound(CSoundObject*)` in the audio timer thread. If the object is in the shadow
   table **and** flagged to use the shadow path, the hook returns immediately. The object
   is not mixed, not advanced, and not finished in software.

Only one path may own a sound at a time:

- shadow path: the DirectSound buffer plays it, software skips it;
- software path: the stock mixer plays it, no shadow buffer exists for it.

The flag that selects the path is `bBypass` in `DS3DShadow`.

### Why not just set the engine volume to zero?

That was the first idea, and it does not work. The stock mixer's "silent" path still
advances the sound and then clears `SOF_PLAY` on the **first mix block** for non-looping
sounds. A gunshot muted that way would be killed almost immediately. Intercepting
`MixSound` avoids touching engine state at all. It is the central design decision of the
project.

---

## 4. Which sounds get a shadow?

The decision is made when the engine starts a sound (`CSoundObject::Play_internal`), from
the sound data and play flags:

| Eligible for a DS3D shadow | Stays in the software mixer |
| --- | --- |
| `SOF_3D` set | non-3D / 2D sounds |
| not `SOF_MUSIC` | music |
| not `SDF_ENCODED` (no streaming decoder) | encoded/streamed sounds |
| mono | stereo |
| 16-bit | other sample formats |

Volumetric 3D sounds are included. Decoder sounds are important to exclude: the software
mixer is what feeds their decoder, so hiding them from it would leave them stuck.

Eligibility is checked from the `Play_internal` arguments, **before** the original function
runs. This closes a race: the object is registered (and reserved for the shadow path)
before it can be mixed for the first time, so the stock mixer cannot double-play it while
the buffer is still being created. The original is then called through a trampoline, and
the shadow continues lazily — the actual buffer is created by the next driver pass,
usually the same frame's `UpdateSounds` tail.

---

## 5. The patch surface: what is hooked and why

The patch installs wrappers around engine functions. A wrapper either:

- calls the original through a **trampoline** and then does extra work, or
- fully replaces a function whose original behavior is already reimplemented in the patch.

```text
Engine.dll function
      │  (first bytes rewritten to a jump)
      ▼
patch wrapper  ──> optional: call original through trampoline
      │
      └────────> shadow bookkeeping / DirectSound calls
```

| Hooked function | Role in the DS3D mode |
| --- | --- |
| `CSoundObject::Play_internal` | Register an eligible sound; on re-play, detach the old buffer. |
| `CSoundObject::Stop_internal` | Remove the shadow and detach its buffer when the game stops the sound. |
| `CSoundObject::~CSoundObject` | Remove the shadow before the engine object disappears. |
| `CSoundObject::Update3DEffects` | Existing 1.10 spatial math, extended with a **store-only** snapshot of position, velocity, volume and filter. No DirectSound calls here. |
| `CSoundLibrary::UpdateSounds` | Original first (fills the snapshots), then the per-frame **driver tail** that talks to DirectSound. |
| `CSoundLibrary::SetFormat` | Device re-initialization: save positions, rebuild templates/buffers on the new device, re-apply listener settings. |
| `CSoundLibrary::Mute` | Stop shadow buffers during the engine's blocking mute window. |
| `CSoundData::ClearBuffer` | Invalidate the cached template and hold/release the shadows that use that sound data. |
| static `MixSound` | Skip the stock mixer for shadowed objects. This is a raw-address hook, not an exported symbol. |

`MixSound` is special. It is a private static function at a fixed address in the Steam
`Engine.dll`, so the patch cannot resolve it by name. Before hooking it, the patch checks:

- that the address really lies inside the loaded `Engine.dll`, and
- that the first bytes match the expected function prologue.

If either check fails, the mode is refused (with a console message) instead of patching an
unknown function. This matters because a bad hook at startup is fatal in a release build.

All 1.07-specific code is compiled only for the release Steam 1.07 configuration:

```c
#if SE1_VER == SE1_107 && defined(NDEBUG) && _PATCHCONFIG_ENGINEPATCHES
```

Other builds compile the subsystem to nothing.

---

## 6. One frame in the DS3D mode

The per-frame work is split deliberately:

- `Update3DEffects` runs inside the engine's normal sound update loop. It computes and
  **stores** the spatial values for each registered shadow. It does not call DirectSound.
- The **driver tail** runs after the original `UpdateSounds` returns. It performs the
  per-frame DirectSound work, under the engine's sound lock. (The lifecycle hooks also
  change the table and call DirectSound when a sound starts, stops, or the device
  changes.)

```text
 Game thread
 ─────────────────────────────────────────────────────────────────────────────
 CSoundLibrary::P_UpdateSounds()
 │
 ├─ original UpdateSounds()
 │    ├─ for each sound: Update3DEffects()
 │    │     └─ DS3D_StoreSpatial(): pos, vel, volume, filter, delay flag
 │    ├─ so_sp = so_spNew            (stock frame copy)
 │    └─ prepare sounds / remove dead objects
 │
  └─ DS3D_DriverTail()
       ├─ sort entries by volume (loudest first)
       ├─ for each entry, in that order:
       │     validate table (!SOF_PLAY -> drop)
       │     SOF_PAUSED -> release buffer for later recommit
       │     advance pending start delays
       │     silence gate (volume * master < 0.005)
       │     ensure a buffer exists (voice budget / steal)
       │     drive steps 4-9:
       │       SetPosition (deferred)
       │       SetVelocity (deferred)
       │       GetStatus
       │       SetVolume / SetFrequency (immediate)
       │       Play (when allowed)
       │       detect natural finish
       │       EAX DirectHF (deferred)
       ├─ scan detached "orphan" buffers, release finished ones
       └─ one CommitDeferredSettings()
 ─────────────────────────────────────────────────────────────────────────────
 Timer thread (may run between game updates)
      MixSounds() -> MixSound() for each object
                    └─ P_MixSound(): shadowed + bBypass -> return
```

### Why this order?

- **Position and velocity are deferred.** They are only flushed by the one
  `CommitDeferredSettings` at the end of the frame. This matches the later engine's
  behavior and avoids many small driver commits.
- **Volume and frequency are immediate.** They should take effect even if a deferred
  commit is delayed.
- **The table is sorted by stored volume.** This is what makes voice stealing sensible:
  the quietest live channel is the first candidate to be released.
- **One commit per frame.** All deferred 3D state for all shadow buffers is applied in one
  go.

### The spatial math, briefly

The patch reuses the engine's listener list and the later engine's formulas:

- Distance factor `w` is 1 inside the hot spot and falls linearly to 0 at the falloff
  radius.
- Position is the weighted average of the sound's position relative to each listener,
  rotated into listener space. The sound is not normalized to unit length: distance is
  meaningful to DirectSound.
- Velocity is the relative velocity, rotated the same way.
- Volume is `clamp01(Σ(listener volume × object volume × w²) / Σw)`, then multiplied by
  the master `snd_fSoundVolume`.
- The filter value becomes EAX `DirectHF`, a per-buffer high-frequency attenuation.
- Volumetric sounds blend their direction toward "straight ahead" when very close, matching
  the reference behavior.

DirectSound works in a left-handed coordinate system with a different Z direction, so the
stored engine Z is negated when sent to DirectSound. The buffers use
`DS3DMODE_HEADRELATIVE`: positions are already listener-relative, and the listener itself is
kept at the origin.

"No listener in range" or "no entity" is represented by a **parked** sound: position
`(0, 0, +10000)` in engine space (sent as `(0, 0, -10000)`) and volume `-10000`. This is
the reference engine's "far away and inaudible" sentinel.

### Volume conversion and the gain trim

DirectSound volume is in hundredths of a decibel. The patch uses the reference engine's
linear-volume curve:

```text
v <= 0.005  -> -10000 (silence)
otherwise   -> cB = 3000 * (v*(v-1) + (1-v)*log10(v))
```

After the curve, an optional flat user trim is added:

```text
cB = clamp(cB + round(snd_fDS3DGain * 100), -10000, 0)
```

`snd_fDS3DGain` defaults to `-6.0` dB. This is a deliberate, user-tuned deviation from the
reference engine: shadow-buffer sounds were louder than the software-mixed sounds, and the
trim balances the two paths. It does not change the silence test or either budget.

---

## 7. Lifecycle: how a shadow follows its owner

The shadow is a state machine. The important fields are:

| Field | Meaning |
| --- | --- |
| `pBuffer` | DirectSound buffer, or `NULL` while uncommitted/released. |
| `bStarted` | We issued `Play` on the current buffer. |
| `bSpatialValid` | A fresh spatial snapshot exists; the driver may start the sound. |
| `bBypass` | `MixSound` must skip this object (shadow owns it). |
| `bGateStopped` | A pause/mute gate stopped the buffer; the next ungated frame must `Play` it again. |
| `bDelayPending` | The sound's start delay has not elapsed yet. |
| `bLooping` | The current play is looping. |
| `tmSilentSince` | How long a held buffer has been silent (for the 10-second released rule). |

```text
                  Play_internal (eligible)
                           │
                           ▼
                 registered, no buffer
                 bBypass = true
                           │
             next tail: not silent, voice available
                           │
                           ▼
                    buffer committed
                           │
              Play (once bSpatialValid and delay elapsed)
                           │
                           ▼
                        playing
        ┌──────────────────┼─────────────────────┐
        │                  │                     │
     paused            game paused /          natural end
        │              Mute window                 │
        │                  │                     ▼
        ▼                  ▼              clear SOF_PLAY,
 release for         Stop, keep buffer    remove entry
 recommit            (bGateStopped)
        │                  │
        └──── resume ──────┘
```

### Special cases in the lifecycle

- **Re-play of a playing object.** The engine's `Play_internal` internally stops the old
  play. A non-looping old shadow buffer is detached and allowed to **play out** (an
  "orphan") because the reference engine's stop is non-forced. A looping buffer is
  force-released: otherwise an orphaned loop would never end.
- **Explicit `Stop`.** The engine stops the object and the shadow is removed. A playing
  non-looping buffer becomes an orphan; a looping one is force-released.
- **Destructor.** The destructor inlines the stop logic, so an extra hook is needed to
  remove the shadow *before* the object is gone.
- **`ClearBuffer` (sound data freed or reloaded).** The cached template is dropped. If the
  owner is still playing, its shadow is released but kept in the table, to be recommitted
  when the new PCM is available.
- **`SetFormat` (device re-init, window change, quality/device change).** All DirectSound
  buffers die with the old device. Every shadow is position-synced and released, templates
  are freed, the engine re-creates its device, the listener settings are re-applied, and
  the next frame recommits each still-playing, audible shadow at its saved offset. One
  silent frame per sound is accepted.
- **`snd_iEmulationType` changed.** HRTF algorithms are baked into the buffer at creation,
  so changing the cvar forces a `SetFormat` re-init. The recommit then uses the new
  algorithm; this makes the toggle audible on already-running sounds.
- **Pause (`SOF_PAUSED`).** The buffer is released; `bBypass` is left unchanged (true for a
  shadow-owned entry), so the software mixer does not take over. On resume, the buffer is
  re-created at the saved cursor.
- **Game pause / `Mute` window.** The buffer is stopped but **kept**. DirectSound preserves
  the play cursor across `Stop`, so the sound resumes where it was.
- **Silent/parked sounds.** A silent sound with no buffer is not committed at all; it stays
  in software (also silent) and does not consume a voice. A held buffer that stays silent
  for more than 10 seconds is released to software-silent state. This prevents distant
  ambients from exhausting the voice budget.

### The release paths

Not every release should resume the sound from the same place. The implementation has
these explicit paths:

| Path | What it does | Used for |
| --- | --- | --- |
| plain release | Stop and release the buffer; remove the table entry if needed. | natural finish, destructor, validation drops. |
| `ReleaseForRecommit` | Read the DirectSound play cursor, write it back into the engine's offsets, release the buffer, **keep the table entry**. | pause, voice steal, `SetFormat`, `ClearBuffer` while the owner lives, the 10-second silent release. |
| `DropToSoftware` | Same position sync, release, **remove the table entry**. | creation/runtime failure, listener loss. |
| orphan detach | Hand the buffer to a small list that lets it finish naturally; release it later. | non-looping stop/re-play; looping buffers are force-released instead. |

The position sync exists because, under this design, the engine's playback offsets are
**frozen** for shadowed sounds: the stock mixer no longer advances them. The DirectSound
cursor is the real position. When control goes back to software, that cursor must be
written into `so_fLeftOffset`/`so_fRightOffset`, or the sound would restart from zero.

---

## 8. Failures and graceful degradation

The mode must never make a sound both silent and immortal, and must never crash the audio
system. The rules are:

- **Hook install failure / unknown binary:** refuse the mode and print a notice. Do not
  patch.
- **Could not create a buffer** (template, duplicate, 3D interface, mode, position): drop
  that shadow to software and continue. Console notice once per cause.
- **Runtime DirectSound call fails:** drop that shadow to software immediately.
- **Buffer lost:** try `Restore()` once; if it is still lost on the next frame, drop it.
- **Buffer terminated:** drop it.
- **Over the voice budget:** if the new sound is clearly louder than the quietest live
  shadow, release the quietest one (position-synced) and give the voice to the new sound.
  Otherwise the new sound falls back to audible software mixing and is retried every frame.
- **Over the same-sound budget** (`snd_iMaxSameSounds`): the sound keeps its buffer but is
  set to volume zero. This preserves the reference engine's behavior of limiting how many
  copies of one sample can stack up.
- **Listener disappears** (device re-init without a 3D listener): all shadows are dropped
  to software and the mode is disabled until a later re-init restores the listener.
- **Natural finish:** a started non-looping shadow that DirectSound reports as not playing
  is considered finished. The patch clears `SOF_PLAY`, removes the entry, and the engine
  cleans the object up on its next update. Failures are not used to guess "finished"; only
  DirectSound status and the gate state are used.

---

## 9. Threading model

There are two relevant threads:

- the **game thread**, which runs `Play`/`Stop`, `UpdateSounds`, `SetFormat`, `Mute`, and
  object destruction;
- the **audio timer thread**, which runs `MixSounds` and calls `MixSound` for each object.

The rule is simple:

- all shadow table changes and all DirectSound calls happen on the **game thread**;
- both sides hold the engine's `sl_csSound` critical section (the audio thread takes it in
  `MixSounds`, the patch takes it explicitly where needed; the lock is recursive);
- the audio thread only does **one table lookup and reads `bBypass`**. It does not read
  cvars, touch DirectSound, or modify the table.

```text
 Game thread                                  Audio timer thread
 ───────────                                  ──────────────────
 Play / Stop / dtor                           MixSounds()
 UpdateSounds -> driver tail                    └─ MixSound()
 SetFormat / Mute / ClearBuffer                     └─ P_MixSound()
       │                                                 │
       └──────────── both under sl_csSound ──────────────┘
```

`bBypass` is written only by the game thread, so the audio thread's read is a simple flag
test inside the same lock. This is what keeps the hot mixer path cheap.

---

## 10. Configuration

All cvars are declared by the patch and are persistent user settings:

| Cvar | Default | Meaning |
| --- | --- | --- |
| `snd_bDS3DSpatial` | `0` | Master switch for the shadow-buffer mode. |
| `snd_iEmulationType` | `0` | HRTF algorithm: 0 = default, 1 = HRTF light, 2 = HRTF full. Changing it re-initializes the device. |
| `snd_iMaxVoices` | `30` | Maximum simultaneous shadow buffers (clamped 4–64). |
| `snd_iMaxSameSounds` | `5` | Per-sample volume budget (clamped 1–99). |
| `snd_bUseEnvironmentFX` | `1` | Enable per-buffer EAX DirectHF filtering. |
| `snd_fDS3DGain` | `-6.0` dB | Post-curve gain trim to balance shadow and software sounds (clamped -30–0). |

### What "off" means

- `snd_bDS3DSpatial 0`: no new sounds are registered. Hooks are still installed, but the
  shadow table is empty and `MixSound` calls the original for every object. Existing
  shadows from a previous on-state drain naturally until they finish or stop.
- Turning the cvar on only affects **newly played** eligible sounds. A sound already
  playing in software is not converted mid-flight.
- The engine's real software state (`so_sp`, `so_spNew`, volumes, engine offsets) is never
  zeroed or poisoned. This is what makes falling back to software safe.

---

## 11. Source map

| File | Contents |
| --- | --- |
| `SuperProject/Core/Patches/SoundDS3D.h` | Shadow/template data structures, hook-body declarations, cvar globals. |
| `SuperProject/Core/Patches/SoundDS3D.cpp` | Registration, spatial store, template cache, commit/release primitives, driver tail, failure policy. |
| `SuperProject/Core/Patches/SoundLibrary.cpp` | The actual trampoline wrappers for `Play_internal`, `Stop_internal`, destructor, `UpdateSounds`, `SetFormat`, `Mute`, `ClearBuffer`, and the raw `MixSound` wrapper. |
| `SuperProject/Core/API/EnginePatches.cpp` | `CreatePatch` registration and the `MixSound` address/prologue validation. |
| `findings/08-design.md` | The design of record: hooks, driver steps, eligibility, gates, failure policy. |
| `findings/07-implementation-notes.md` | Evidence and decisions behind the design (especially §13 items and §14–§16). |
| `findings/99-summary-and-open-questions.md` | One-page parameter sheet and reference-engine/Steam mapping. |

---

## 12. Glossary

- **Shadow** — the patch's per-sound record plus its DirectSound buffer; it mirrors an
  engine `CSoundObject`.
- **Template** — a cached DirectSound buffer containing one copy of a `CSoundData`'s PCM.
  Per-play buffers are duplicated from it.
- **Duplicate** — a DirectSound buffer sharing the template's sample memory, with its own
  play cursor and 3D properties.
- **Orphan** — a detached non-looping buffer that is allowed to finish naturally after its
  owner stopped or re-played; it is released when DirectSound reports it done.
- **Parked** — the reference engine's "silent and far away" state: sentinel position plus
  volume `-10000`.
- **`bBypass`** — the single flag that decides whether the stock mixer skips an object.
  `true` = shadow owns it; `false` = software owns it.
- **Voice** — one live shadow buffer. `snd_iMaxVoices` limits how many may exist at once.
- **Software mixer** — the engine's original per-block mixer (`MixSounds`/`MixSound`) that
  produces the left/right ear streams.
- **Deferred / immediate** — DirectSound's two apply modes. Deferred changes are flushed
  by `CommitDeferredSettings`; the driver uses one commit per frame.
- **DSOAL** — a DirectSound-to-OpenAL wrapper used for testing and for HRTF output; the
  patch works with it but targets the normal DirectSound API.
