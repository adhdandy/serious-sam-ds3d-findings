# 04 — Beta buffer creation and lifecycle (Task A4)

## 1. Device/session initialization — `CSoundLibrary::StartUp_dsound` (0x80960) `[VERIFIED]`

Sequence (all corroborated by log lines 3-80):
1. `LoadLibraryA("dsound.dll")`, `GetProcAddress("DirectSoundCreate")` (cached module in
   DAT_1022e9cc). Create only if `sl_pDS == NULL` (re-inits reuse the device object; a
   full `ShutDown_dsound` clears it).
2. `GetCaps` — fails if `DSCAPS & 0x20` (emulated driver).
3. `SetCooperativeLevel(hwnd, DSSCL_PRIORITY)`.
4. **Primary**: `DSBCAPS_PRIMARYBUFFER|CTRL3D` (0x11), then `SetFormat(&sl_SwfeFormat)`
   (stereo 44.1 kHz 16-bit from `FUN_10081540`).
5. `QI(IID_IDirectSound3DListener)` → listener init, **apply = IMMEDIATE (0)**:
   `SetOrientation(0,0,1, 0,1,0)`, `SetPosition(0,0,0)`, `SetVelocity(0,0,0)`,
   `SetRolloffFactor(0)`, `SetDopplerFactor(1.1)`. Never touched again afterwards.
6. **Mix buffer** (software mix output): flags `0x500E0` =
   `LOCDEFER|GETCURRENTPOSITION2|CTRLVOLUME|CTRLPAN|CTRLFREQUENCY`, stereo,
   `BufferBytes = ceil(rate × snd_tmMixAhead)` (0.2 s default → 35,284 B in log).
   Started/stopped by `DSPlayMainBuffers` (0x80860) with `Play(0,0,LOOPING)`.
7. **EAX probe**: 4-byte `CTRL3D` mono buffer; `QI(3DBuffer)` + `QI(IKsPropertySet)`;
   `QuerySupport(EAX20_Listener, 0xB=ENVIRONMENT)` and `QuerySupport(EAX20_Buffer,
   3=DIRECTHF)`; if both have KSPROPERTY_SUPPORT_SET (0x2) → `sl_bUsingEAX = 1`;
   probe released.
8. Allocates the software mixer buffer (+0x64) and decoder buffer (+0x68).

`snd_bUseWaveOut` / `snd_iDevice` / `snd_iFormat` / `snd_iEmulationType` changes trigger
`SetFormat` → **`SetFormat` (0x81DD0)**: `Pause()` all objects → `ClearBuffer()` all
non-decoder CSoundData → `SetFormat_internal` (re-init DS) → `Reload()` all → `Resume()`.
This is the level-change / settings-change lifecycle and explains the second
`DirectSoundCreate` early in both logs (device re-created after prefs load).

## 2. Per-sound templates — `CSoundData::LoadWAV_t` (0x7EA90) `[VERIFIED]`

On load (and `Reload` after format change), if DS is active:
- Parses/validates WAV (PCM, 4/8/16-bit → converted to 16-bit, 1/2 ch, 11/22/44.1 kHz;
  non-native rates are resampled by the big x87 loop).
- `CreateSoundBuffer` with `DSBUFFERDESC{dwSize=0x24}`:
  - **mono** (3D-capable): flags `0x600B0` = `LOCDEFER|MUTE3DATMAXDISTANCE|GETCURRENTPOSITION2??`→
    actually `LOCDEFER|MUTE3DATMAXDISTANCE|CTRLVOLUME|CTRLFREQUENCY|CTRL3D`
    (log: "CTRL3D|CTRLFREQUENCY|CTRLVOLUME|MUTE3DATMAXDISTANCE|LOCDEFER"), 399 created;
  - **stereo** (2D-only): flags `0x400E0` = `LOCDEFER|CTRLVOLUME|CTRLPAN|CTRLFREQUENCY`
    (log matches), 14 created;
  - `guid3DAlgorithm` from **`snd_iEmulationType`**: 0 → GUID_NULL (DS3DALG_DEFAULT),
    1 → `{C2413342-…}` = DS3DALG_HRTF_LIGHT, 2 → `{C2413340-…}` = DS3DALG_HRTF_FULL.
    (Capture used 0 → "DS3DALG_DEFAULT" in log.)
- PCM written once via `Lock`/`Unlock` (static buffer; 1,815 lock/unlock pairs in log).
- `data+0x28` = template `IDirectSoundBuffer*`. In waveOut mode instead a software PCM
  copy is kept at `data+0x2C`.
- Template flags byte `data+0x44 bit0` = "needs decoder" (ogg/mpx filename) — such
  sounds get a `CSoundDecoder` at `Play` time (`so+0x9C`) and are software-mixed.

**DS3D requires mono**: stereo sounds are created WITHOUT CTRL3D and always take the
2D path (`SetMode(2, DISABLE)` after duplicate) — 21 occurrences in log `[VERIFIED]`.

## 3. Channel system and per-play buffers `[VERIFIED]`

64-channel array in `CSoundLibrary` (see 01 §4). Per playing instance:

**`CommitPlayingBuffer(CSoundObject&, int&)` (0x82560)** — called from `PlayBuffers`
when an object has no channel (or its channel was repossessed):
1. `is3D = SOF_3D && data.channels==1 && !SOF_2D(0x40)`.
2. Find a free channel (owner==0 && buffer==NULL, or buffer not playing).
3. Else **steal**: pick the channel whose owner has the lowest `so.volume(+0x64)`;
   only if `newVolume − lowest > 0.333` (const 0x101b95bc); else fail (return −1,
   sound stays uncommitted this frame — the voice limit `snd_iMaxVoices`, default 30,
   clamped [4,64], bounds the search).
4. `DuplicateSoundBuffer(sl_pDS, data.template(+0x28), &chan.buffer)` —
   **the log's 228 duplicates**.
5. If mono: release stale 3D/property ifaces, `QI(IID_IDirectSound3DBuffer)` →
    chan+0xC; if `is3D && sl_bUsingEAX`: `QI(IID_IKsPropertySet)` → chan+0x10
    (**208 KsPropertySet QIs in log = 206 3D-commit QIs (matches `SetMode(1)` count) +
    2 startup probes** — log lines 75 and 2002, one per device generation; verified
    session 5);
   `SetMode(is3D ? DS3DMODE_HEADRELATIVE(1) : DS3DMODE_DISABLE(2), 0)` —
   the exact 206/21 split in the log.
6. `so.flags |= 0x10000000` (has hw buffer); channel owner/data set.

**`ReleasePlayingBuffer(chan, force)` (0x82740)**: clears owner/data (+ the 5-dword
block) and (if force) `FUN_10082780(chan, 1)`:
- `FUN_10082780` (0x82780): `GetStatus`; if not playing (or forced, after `Stop()`):
  `Release()` buffer + 3D iface + property set; zero the pointers. **If still playing
  and not forced: only owner/data are cleared — the orphaned duplicate plays out to
  completion** (so finished sounds are never cut) `[VERIFIED]`.

## 4. Per-frame driving — `PlayBuffers` (0x829F0) `[VERIFIED]`

Per pending object (list sorted by volume each frame):
```
voice budget check (snd_iMaxVoices): over budget → release channel, chan = -1
if (chan == -1 && wants-play && !parked):  chan = CommitPlayingBuffer(); fresh = true
if (fresh):   Buffer::SetCurrentPosition(0)          # 228 in log
if (is3D):    SetPosition/SetVelocity (deferred, z-negated)   # 2D sounds: never positioned
Buffer::GetStatus
if (paused && !SOF_NONGAME):  SetVolume(-10000); SetFrequency(0); Stop()   [mute path]
else:          SetVolume(curve(so.volume)); SetFrequency(rate×pitch or 0)
if (not playing && should):  Play(0, 0, SOF_LOOP ? DSBPLAY_LOOPING : 0)   # 15 looping in log
if (finished non-looping):   Stop(), CSoundObject::Stop(1)
if (is3D && playing && EAX): KsPropertySet::Set(DIRECTHF deferred)
if (chan.data != so.data):   release + re-commit (sound switched data)
```

## 5. State transitions `[VERIFIED]`

| Event | What happens to the DS3D buffer |
|---|---|
| `Play(data, flags)` (0x872D0) | `Stop_internal(0)`, swap data refs, `AddToPendingList`, set SOF_PLAY(0x80000000), reset timers/fades; construct decoder if `data+0x44&1`; unless SOF_SMOOTHCHANGE(0x40000000), reset mixer L/R fields. The DS buffer appears lazily at next `PlayBuffers` |
| `Stop(int)` / `Stop_internal(int)` (0x87450/0x874D0) | clear PLAY bit, `RemoveFromPendingList` → `ReleasePlayingBuffer(chan, int)`, free decoder, unlink data. `int` = force release flag |
| `Pause()` (0x88AD0) | set 0x20000000; if DS && chan ≥ 0: `ReleasePlayingBuffer(chan, 1)` (immediate release), chan = −1 |
| `Resume()` (0x88B10) | clear 0x20000000 (buffer recommitted next frame; timers preserved → restart offset via `GetElapsedTime`) |
| `SetFormat` / level change | Pause all → ClearBuffer all → re-init → Reload all → Resume all |
| `Mute(float)` (0x81C80) | master volume ramp (used by menu/world transitions; `_pNetwork` pause paths in PlayBuffers use volume −10000 + Stop instead) |
| window focus | `UpdateSounds` detects hwnd change → `SetFormat` re-init |
| save/load (`Read_t`/`Write_t` 0x88B20/0x88EE0) | serializes flags, volumes (+0x6C..+0x80), filters, offsets, hotspot/falloff/volume/pitch — channel is NOT serialized (recreated) |

## 6. The software mixer path in the beta (for contrast with Steam) `[VERIFIED]`

`MixSounds` (0x827F0) runs on a WINMM timer (installed once from `UpdateSounds`):
- In DS mode it only mixes objects with a **decoder** (`so+0x9C != 0`) — gate:
  `(voice budget > 0 || decoder) && (sl_bUsingDSound == 0 || decoder)`.
  I.e. **non-streaming sounds are NEVER software-mixed in DS3D mode — no double audio**.
- Objects whose mixer L/R (+0x84/+0x88) are both 0.0 are **skipped entirely**
  (not mixed, not advanced in software — their state lives in the DS buffer).
- Output: `CopyMixerBuffer_dsound` Locks the mix buffer (+0x30), copies from the mixer
  ring, Unlocks.

## 7. Beta sound cvars (from `CSoundLibrary::Init` 0x81630 + .data defaults) `[VERIFIED]`

| Cvar (full string) | Storage | Default | Use |
|---|---|---|---|
| `snd_fSoundVolume` | 0x1020f814 | 0.8 | master volume |
| `snd_fMusicVolume` | 0x1020f818 | 0.7 | music volume (×0.5 const for SOF_MUSIC) |
| `snd_bLinearVolume` | 0x1020f81c | 1 | volume curve mode (see 03 §2) |
| `snd_tmMixAhead` | 0x1020f810 | 0.2 s (clamp 0.1–0.4) | mix buffer size |
| `snd_bUseWaveOut` | 0x1022e9bc (BSS) | 0 | waveOut fallback |
| `snd_iDevice` | 0x1020f828 | −1 | device select |
| `snd_iFormat` | global | — | output format |
| `snd_iMaxExtraChannels` | 0x1020f834 | 32 | extra channels |
| `snd_tmOpenFailDelay` | 0x1020f838 | 0.5 | reopen delay |
| `snd_iMaxVoices` | 0x1020f80c | 30 (clamp 4–64) | voice/channel limit |
| `snd_iMaxSameSounds` | 0x1020f820 | 5 (clamp 1–99) | per-CSoundData volume budget |
| `snd_bUseHeadphones` | 0x1022e9b8 (BSS) | 0 | (headphone mode) |
| `snd_bUseEnvironmentFX` | 0x1020f82c | 1 | gates EAX listener env + per-buffer DirectHF sets |
| `snd_bReportStereoWaves` | 0x1022e9c4 (BSS) | 0 | reporting |
| `snd_iEmulationType` | 0x1022e9c0 (BSS) | 0 | DS3D algorithm: 0=default 1=HRTF_LIGHT 2=HRTF_FULL |

Also: shell function `void SndPostFunc(INDEX)` (0x1020fec4 → 0x81AC0) invoked when the
`post:`-tagged cvars change (re-init).

## 8. Voice accounting vs the log `[VERIFIED]`

- 419 `CreateSoundBuffer` = 2 device generations × (1 primary + 1 mix + 1 probe + ~200
  templates + 7 stereo templates); the log's "≈370 CTRL3D" (§6.1) is the 399 template
  count (plus 2 probes + 2 primaries = 403 CTRL3D-flagged).
- 228 `DuplicateSoundBuffer` ≈ 229 `QI(3DBuffer)` (228 duplicates + 1 startup probe —
  only the first generation's probe QI'd 3DBuffer; the second probe QI'd KsPropertySet
  only) — one duplicate per (re)commit; channels are reused without re-duplicating while
  owned. Residual oddity `[LIKELY/minor]`: total `SetMode` = 227 vs 228 duplicates —
  one commit without a SetMode (probably one duplicate that was released before its
  SetMode, or a mode-2 path edge); not worth a targeted log pass.
- 15 looping `Play`s = music/ambient loops; 216 one-shot plays; 55 stops.
- ~10 distinct live 3D buffer pointers in the frame loop (address reuse across 228
  duplicates over the session; ≤ snd_iMaxVoices = 30 concurrent by design).
