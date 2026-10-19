# 01 — Beta DS3D call sites (Task A1)

All addresses are VAs in the beta `Engine.dll` (image base 0x10000000; RVA = VA − 0x10000000).
Evidence: Ghidra 12.1.4 headless decompilation (`findings/ghidra-out/sound-analysis.txt`),
raw disassembly (`findings/scratch/beta-engine-disasm.txt`), DSOAL log (`dsoal_log.txt`),
1.10 source cross-reference. Confidence tags per AGENTS.md.

## 1. Anchors (how the call sites were found) `[VERIFIED]`

| Anchor | VA | Used by |
|---|---|---|
| `IID_IDirectSound` | 0x101b9208 | (present, unused by sound path) |
| `IID_IDirectSound3DListener` | 0x101b9258 | `StartUp_dsound` @ 0x10080b29 |
| `IID_IDirectSoundBuffer` | 0x101b9228 | (present; no QI site found in seeds) |
| `IID_IDirectSound3DBuffer` | 0x101b9268 | `StartUp_dsound` @ 0x10080c79 (probe), `CommitPlayingBuffer` @ 0x100826d9 |
| `IID_IKsPropertySet` | 0x101b92b8 | `StartUp_dsound` @ 0x10080cb1, `CommitPlayingBuffer` @ 0x1008270a |
| `DSPROPSETID_EAX20_ListenerProperties` | 0x101b958c | `StartUp_dsound` @ 0x10080cc4, `SetEnvironment` @ 0x10081c72 |
| `DSPROPSETID_EAX20_BufferProperties` | 0x101b959c | `StartUp_dsound` @ 0x10080ce7, `PlayBuffers` @ 0x10082e3e |
| `"dsound.dll"` / `"DirectSoundCreate"` | 0x1020f8f8 / 0x1020f93c | `StartUp_dsound` (LoadLibraryA/GetProcAddress) |
| `_pSound` / `_pSoundStock` | 0x1022e9b4 / 0x10230ed4 | 60+ sites (completeness anchor) |

Vtable slots used (all verified against `Serious-Engine/Sources/Engine/Sound/DSOUND.H`):
IDirectSound: CreateSoundBuffer=3(0x0C), GetCaps=4(0x10), SetCooperativeLevel=6(0x18),
DuplicateSoundBuffer=5(0x14). IDirectSoundBuffer: Lock=11(0x2C), Play=12(0x30),
SetCurrentPosition=13(0x34), SetVolume=15(0x3C), SetFrequency=17(0x44), Stop=18(0x48),
Unlock=19(0x4C), QueryInterface=0. IDirectSound3DBuffer: SetMode=18(0x48),
SetPosition=19(0x4C), SetVelocity=20(0x50). IDirectSound3DListener: SetDopplerFactor=12(0x30),
SetOrientation=13(0x34), SetPosition=14(0x38), SetRolloffFactor=15(0x3C), SetVelocity=16(0x40),
CommitDeferredSettings=17(0x44). **IKsPropertySet in this header generation: Get=3, Set=4
(0x10), QuerySupport=5 (0x14)** — matches both binary and DSOAL log behavior `[VERIFIED]`
(note: some modern dsound.h order Get/QuerySupport/Set — do NOT use those for this project).

## 2. Master call-site table `[VERIFIED]`

| Call site (VA) | In function (RVA) | Method called | Log corroboration |
|---|---|---|---|
| 0x10080a12 | StartUp_dsound (0x80960) | `DirectSoundCreate` (via GetProcAddress) | log line 3 |
| 0x10080a3a | StartUp_dsound | IDirectSound::GetCaps | after create |
| 0x10080aaa | StartUp_dsound | IDirectSound::SetCooperativeLevel(hwnd, 2=DSSCL_PRIORITY) | log line 19 |
| 0x10080aee | StartUp_dsound | IDirectSound::CreateSoundBuffer (primary, flags 0x11) | log lines 20-25 |
| 0x10080b07 | StartUp_dsound | Primary::SetFormat(&sl_SwfeFormat) | log lines 28-35 |
| 0x10080b29 | StartUp_dsound | Primary::QueryInterface(IID_IDirectSound3DListener) | log line 36 |
| 0x10080b54 | StartUp_dsound | Listener3D::SetOrientation(0,0,1, 0,1,0, 0) | log line 38 |
| 0x10080b64 | StartUp_dsound | Listener3D::SetPosition(0,0,0, 0) | log line 39 |
| 0x10080b74 | StartUp_dsound | Listener3D::SetVelocity(0,0,0, 0) | log line 40 |
| 0x10080b80 | StartUp_dsound | Listener3D::SetRolloffFactor(0.0, 0) | log line 41 |
| 0x10080b8f | StartUp_dsound | Listener3D::SetDopplerFactor(1.1, 0) | log line 42 |
| 0x10080bf8 | StartUp_dsound | IDirectSound::CreateSoundBuffer (mix buffer, flags 0x500E0, bytes=ceil(rate×snd_tmMixAhead)) | log lines 43-56 (35284 B stereo) |
| 0x10080c5f | StartUp_dsound | IDirectSound::CreateSoundBuffer (EAX probe, flags 0x10, 4 B, mono fmt) | log lines 58-72 |
| 0x10080c79 | StartUp_dsound | Buffer::QueryInterface(IID_IDirectSound3DBuffer) on probe | log line 73 |
| 0x10080cb1 | StartUp_dsound | Buffer::QueryInterface(IID_IKsPropertySet) on probe | log line 75 |
| 0x10080cca | StartUp_dsound | KsPropertySet::QuerySupport(EAX20_Listener, 0xB) | log line 77 |
| 0x10080ce7 | StartUp_dsound | KsPropertySet::QuerySupport(EAX20_Buffer, 3=DIRECTHF) | log line 78; sets `sl_bUsingEAX` if SUPPORT_SET |
| 0x10080d14/0x10080d30 | StartUp_dsound | Buffer/Buffer3D::Release ×2 (probe) | log line 79-80 |
| 0x1007f080 | CSoundData::LoadWAV_t (0x7ea90) | IDirectSound::CreateSoundBuffer (**per-sound template**, mono 0x600B0 / stereo 0x400E0 flags) | 399+14 creations |
| 0x1007f09e | LoadWAV_t | Buffer::Lock(0, bytes, ...) | 1815 locks |
| 0x1007f0d7 | LoadWAV_t | Buffer::Unlock | 1815 unlocks |
| 0x100825ee | CSoundLibrary::CommitPlayingBuffer (0x82560) | Buffer::GetStatus (template check) | — |
| 0x1008268a | CommitPlayingBuffer | IDirectSound::DuplicateSoundBuffer(template→channel) | 228 dups, log line 6320 ff. |
| 0x100826d9 | CommitPlayingBuffer | Buffer::QueryInterface(IID_IDirectSound3DBuffer) | 229 QIs |
| 0x1008270a | CommitPlayingBuffer | Buffer::QueryInterface(IID_IKsPropertySet) (only if 3D && EAX) | 208 QIs = 206 3D commits + 2 startup probes (see 04 §3) |
| 0x1008271c | CommitPlayingBuffer | Buffer3D::SetMode(is3D ? 1=HEADRELATIVE : 2=DISABLE, 0) | 206×(1,0), 21×(2,0) |
| 0x10082bfb | CSoundLibrary::PlayBuffers (0x829f0) | Buffer::SetCurrentPosition(0) (on fresh commit) | 228×"0" |
| 0x10082c34 | PlayBuffers | Buffer3D::SetPosition(so.x, so.y, **−so.z**, 1=DEFERRED) | 218,313 calls |
| 0x10082c4f | PlayBuffers | Buffer3D::SetVelocity(so.x, so.y, **−so.z**, 1=DEFERRED) | 218,313 calls |
| 0x10082c5c | PlayBuffers | Buffer::GetStatus | per-frame, playing check |
| 0x10082d11 | PlayBuffers | Buffer::SetVolume(cB) | 255,926 calls |
| 0x10082d3f | PlayBuffers | Buffer::SetFrequency(rate×pitch or 0) | 255,926 calls |
| 0x10082d71 | PlayBuffers | Buffer::Stop (on pause/mute transitions) | 55 stops |
| 0x10082dc7 | PlayBuffers | Buffer::Play(0, 0, looping) | 231 plays |
| 0x10082e44 | PlayBuffers | KsPropertySet::Set(EAX20_Buffer, 0x80000003=DEFERRED\|DIRECTHF, ..., &val, 4) | per-frame per-3D-sound |
| 0x10082271 | CSoundLibrary::UpdateSounds (0x81f40) | Listener3D::CommitDeferredSettings | 46,444 commits |
| 0x10081c78 | CSoundLibrary::SetEnvironment (0x81c20) | KsPropertySet::Set(EAX20_Listener, 0x8000000B=DEFERRED\|ENVIRONMENT, &env, 4) | on env change |
| 0x10082780-zone | FUN_10082780 (0x82780) | Buffer::GetStatus / Stop / Release ×3 (channel cleanup) | orphan play-out |
| 0x10082e3e area | CopyMixerBuffer_dsound (0x822e0) → DSLockBuffer | Buffer::Lock/Unlock (mix buffer) + Unlock at 0x100822d0-region | mix loop |

*The beta's `CSoundObject::Update3DEffects` equivalent is a pair:*
**`CSoundObject::Update` (0x875E0)** — per-object parameter computation (calls the spatial
core FUN_10087970, applies master volumes, writes so+0x48..0x68), and
**`CSoundLibrary::PlayBuffers` (0x829F0)** — the per-frame DS3D driver that issues the actual
COM calls. `FUN_10087970` (0x87970, ~3.4 KB) is the spatial math core (≈1.10
Update3DEffects' listener loop, heavily extended).

## 3. Per-frame call order `[VERIFIED]` (matches log exactly)

`CSoundLibrary::UpdateSounds` (exported 0x81F40), called once per game tick:

```
if window changed → SetFormat (full re-init; explains 2nd DirectSoundCreate at log line 1931)
clamp snd_fSoundVolume / snd_fMusicVolume to [0,1]
SetEnvironment(listener env)                       [EAX listener, only if changed]
for each pending CSoundObject:
    if (flags & SOF_PLAY=0x80000000): CSoundObject::Update(obj)   → computes ALL params
    else: RemoveFromPendingList(obj)
Sort object list (by volume — FUN_10081f00)         [voice-steal priority]
clamp snd_iMaxVoices to [4,64]
if DS: DSPlayMainBuffers (start mix buffer if stopped)
install WINMM timer callback once (FUN_1017531e → mix pump)
every mix interval (0.05 s): MixSounds()
if DS:
    PlayBuffers()                                    → drives every DS3D buffer
    Listener3D::CommitDeferredSettings()             → 0x10082271, once per frame
remove all listeners from active list (re-registered next frame by entities)
```

`PlayBuffers` per object (in list order): channel bookkeeping (64-slot array) →
`CommitPlayingBuffer` if needed → `SetCurrentPosition(0)` if fresh → (3D only)
`SetPosition`/`SetVelocity` (deferred) → `GetStatus` → (not muted) `SetVolume`/`SetFrequency`
(immediate) → `Play`/`Stop` management → EAX `Set(DIRECTHF)` (3D, playing) → channel
re-validate (release if the channel's data changed).

## 4. Empirical structure layouts (from decompilation) `[VERIFIED offsets]`

**CSoundLibrary** (channels at +0x74, stride 0x14, 64 slots → list head at +0x574):
```
+0x00  (timer/misc)   +0x14 waveout hdr count   +0x18 waveout hdrs
+0x1c  num devices    +0x24 sl_pDSPrimary       +0x28 sl_pDSPROPERTY(probe KsPropertySet*)
+0x2c  sl_pDS (IDirectSound*)  +0x30 sl_pDSSecondary (mix buffer)
+0x34  sl_pDSListener (IDirectSound3DListener*) +0x38 sl_lhActiveListeners (list head)
+0x44  sl_bUsingDSound (int)   +0x48 sl_bUsingEAX (int)
+0x4c  sl_EsfFormat   +0x50 sl_SwfeFormat (WAVEFORMATEX, 0x10 bytes)
+0x64  mix buffer (AllocMemory) +0x68 decode buffer +0x6c mix buffer size
+0x70  decode size    +0x574 sl_psoObjects (pending object list head)
channel[i] @ +0x74 + i*0x14: { +0x00 CSoundData*; +0x04 owner CSoundObject*; +0x08 IDirectSoundBuffer*; +0x0C IDirectSound3DBuffer*; +0x10 IKsPropertySet* }
```

**CSoundObject** (beta layout — differs from 1.10!):
```
+0x00 next (list node)      +0x08 so_pCsdLink      +0x0C so_penEntity
+0x10 timer0 (double)       +0x18 timer1 (double)  +0x20 timer2 (double)
+0x28 channel index (int, -1 = none)                +0x2C so_slFlags (uint)
+0x30 fade duration (float) +0x34 fade target volume +0x38 current volume (float)
+0x3C pitch (float, 1.0 = normal)
+0x40 sp3_fHotSpot          +0x44 sp3_fFalloff
+0x48..0x50 DS3D position (engine space; z NEGATED at call site)
+0x54..0x5C DS3D velocity (engine space; z NEGATED at call site)
+0x60 distance out          +0x64 DS3D volume factor (0..1)
+0x68 DS3D HF filter factor
+0x6C mixer L volume        +0x70 mixer R volume
+0x74 mixer L bass filter (int)  +0x78 mixer R bass filter (int)
+0x7C mixer distance        +0x80 mixer phase/ITD (float, [-1,1])
+0x84/+0x88 mixer L/R (smoothed)  +0x8C..0x98 last samples/offsets
+0x9C so_psdcDecoder (CSoundDecoder*)
```

**CSoundData**: `+0x0C` name, `+0x14` WAVEFORMATEX (tag/ch/rate/avg/align/bits at
0x14/0x16/0x18/0x1c/0x20/0x22), `+0x28` template IDirectSoundBuffer*, `+0x2C` software
samples (waveOut), `+0x30` seconds (double), `+0x38` sample count, `+0x3C` samples too,
`+0x40` running volume accumulator, `+0x44` flags (bit0 = needs decoder = ogg/mpx).

**CSoundListener** (list node): `+0x00` next, `+0x4C` entity (`[0x13]`), `+0x08..0x10`
position (floats at [2],[3],[4]), `+0x14..0x34` 3×3 rotation matrix (floats at [5..13]),
`+0x38..0x40` velocity ([0xE],[0xF],[0x10]), `+0x44` volume float ([0x11]), `+0x48` filter int ([0x12]).

**Flags seen (beta values, differ from 1.10!)**: 0x1=SOF_LOOP, 0x2=SOF_3D, 0x4=SOF_VOLUMETRIC,
0x8=SOF_LOCAL(listener-entity match), 0x10=SOF_MUSIC(uses snd_fMusicVolume×0.5),
0x20=SOF_NONGAME(not muted on pause), **0x40 = beta flag** (voice: attenuates other
sounds and **excludes this sound from 3D mode**, per CommitPlayingBuffer 0x1008269d),
**0x10000000 = beta flag** (set at commit and at pause-stop, consumed by the finish rule
0x10082d8e), 0x20000000=SOF_PAUSED(manual pause), **0x40000000 = beta flag**
(alpha/smooth-continue path: `Play` 0x872D0 skips the mixer L/R reset when set),
0x80000000=SOF_PLAY `[VERIFIED bits; neutral labels for 0x40/0x10000000/0x40000000]`.
Mask 0x58 = 0x08|0x10|0x40 (LOCAL|MUSIC|voice flag). Steam 1.10 has no voice flag —
nothing to map.

## 5. Residuals / caveats

- FUN_10087970's tail clamp rendering (L/R volume clamp + `32767/x` filter) has Ghidra
  float-compare ambiguities; raw disasm is available in `scratch/beta-engine-disasm.txt`
  (function spans 0x87970-0x886B0). Only affects the software-mixer path (decoder sounds) —
  low priority for the DS3D reimplementation.
- `SetEnvironment`'s env→preset lookup table is 17 dwords at 0x1020f7c8 (not yet dumped).
- FUN_100835b0/FUN_100836a0 (mixer clear + per-object mix) partially read; full software
  mixer resampler (FUN_10083670) not analyzed (not needed for DS3D path).
