# 00—Orientation (Stage 1)

Task: inventory of inputs, export diff, DSOAL log re-derivation, DirectSound API version,
vtable verification. All evidence tagged `[VERIFIED]` (seen in log/binary/source and
cross-checked), `[LIKELY]`, or `[HYPOTHESIS]`.

Method: `llvm-objdump -p` header dumps (→ `findings/scratch/*.txt`), Python log analysis
(`findings/scripts/logstats.py`, `condense.py` → `findings/scratch/logstats-{beta,steam}.*`),
export parsing (`findings/scripts/exportdiff.py` → `findings/scratch/exportdiff.md`),
1.10 source cross-reference (`Serious-Engine/Sources/Engine/Sound/*`).

---

## 1. Module inventory and identification

| Module                                     | Size (B)    | SHA-256 (first 16) | PE stamp              | Role                                                                                                                                                                                                                                                                                                  |
| ------------------------------------------ | ----------- | ------------------ | --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SS_TSE_Beta_Bin\Engine.dll`               | 2,334,783   | B6160FE2B896A613   | 3DFEEE6A = 2002-12-17 | **Beta engine. TSE 1.50 generation.** 3532 exports; export list is byte-identical (names+RVAs) to `SE1-StaticLibrariesForGames/SeriousSam/TSE150/Engine.exports.txt` `[VERIFIED]`                                                                                                                     |
| `SS_TSE_Steam_Bin\Engine.dll`              | 2,138,170   | B79BF8BB3927FE4F   | 3CC41450 = 2002-04-22 | **Steam engine. TSE 1.07 generation.** 3189 exports; identical to `.../TSE107/Engine.exports.txt` `[VERIFIED]`                                                                                                                                                                                        |
| `SS_TSE_Beta_Bin\SeriousSamNoCD_b1.50.exe` | 438,343     | 92070BED87CF358C   |—| EXE used for the beta DSOAL capture (user-confirmed). Imports only `Engine.dll` + system DLLs → the logged DS3D behavior comes from stock beta `Engine.dll` `[VERIFIED]`                                                                                                                              |
| `SS_TSE_Beta_Bin\SeriousSam.exe`           | 438,343     | D8BE6E1F74E868E5   |—| Stock beta EXE (same size as NoCD—byte-patched copy)                                                                                                                                                                                                                                                |
| `SS_TSE_Steam_Bin\ClassicsCore.dll`        | 958,563     | 2DCF8E081A999B2C   |—| SuperProject's deployed Core (imports `Engine.dll`)—subject of task S3                                                                                                                                                                                                                              |
| `dsoal_log.txt` (root)                     | 138,908,180 | C854F5E8674682E    |—| **Beta ground truth.** 1,883,674 lines, DSOAL v0.9-990eef8, 1 process session, `DirectSoundCreate` at lines 3 and 1931 (early re-init)                                                                                                                                                                |
| `dsoal_Steam_log.txt` (root)               | 4,305,474   | 9B4BF3A792ED5617   |—| **Steam ground truth.** 68,334 lines, same DSOAL build, 1 session, `DirectSoundCreate` at lines 3 and 125                                                                                                                                                                                             |

- `SE1-StaticLibrariesForGames` `.lib` files are **import libraries** generated from the DLLs
  (repo README documents `lib /def:` generation)—they provide export *names* only, no internal
  symbols. Internal beta functions must come from Ghidra decompilation `[VERIFIED]`.
- Neither engine imports `dsound.dll` statically (both import `WINMM.dll` = waveOut fallback
  path) → DirectSound entry points are loaded dynamically, matching 1.10 source
  (`StartUp_dsound`) `[VERIFIED]`.

## 2. DSOAL log structure

Format: `threadid:level:dsound:Class::Method (thisPtr)->(args)`; multi-line
`Requested buffer:`/`Requested buffer format:` blocks follow `CreateSoundBuffer`/
`ConvertFormat` lines. Levels: `debug` = call entry (counted), `trace` = details
(a method's trace line must NOT be counted—initial run double-counted `CreateSoundBuffer`
838→419 and `GetStatus` 609,418→304,709; fixed in `logstats.py`) `[VERIFIED]`.

## 3. DirectSound API version and vtable verification

- Both builds call **`DirectSoundCreate`** (legacy v1 entry, not `DirectSoundCreate8`)—
  beta log line 3, steam log line 3 `[VERIFIED]`. DSOAL's internal class name
  (`DSound8OAL`) is irrelevant to what the app calls.
- Interfaces used (via QI, from logs): `IDirectSound3DListener` (from primary),
  `IDirectSound3DBuffer` (from secondaries), `IKsPropertySet` (EAX 2.0). No
  IDirectSound8/Buffer8-only methods observed (no `SetFX`, `AcquireResources`) `[VERIFIED]`.
- Vtable slots from `Serious-Engine/Sources/Engine/Sound/DSOUND.H`—**AGENTS.md §6.3 table
  confirmed in full** `[VERIFIED]`:
  - `IDirectSound`: CreateSoundBuffer=3
  - `IDirectSoundBuffer`: Lock=11, Play=12, SetCurrentPosition=13, SetVolume=15, SetFrequency=17, Stop=18, Unlock=19 (DSOUND.H:677-703)
  - `IDirectSound3DBuffer`: SetAllParameters=12, SetConeAngles=13, SetConeOrientation=14, SetConeOutsideVolume=15, SetMaxDistance=16, SetMinDistance=17, **SetMode=18, SetPosition=19 (0x4C), SetVelocity=20 (0x50)** (DSOUND.H:915-941)
  - `IDirectSound3DListener`: SetDopplerFactor=12, SetOrientation=13, SetPosition=14, SetRolloffFactor=15, SetVelocity=16, CommitDeferredSettings=17 (DSOUND.H:842-865)

## 4. Beta log—re-derived facts (corrected counts)

### 4.1 §6.1 claim check

| §6.1 claim | Re-derived | Status |
|---|---|---|
| `SetMode(1,0)`×206, `SetMode(2,0)`×21, no mode 0 | 206 / 21, no 0—exact | `[VERIFIED]` |
| `SetRolloffFactor(0.0, 0)` | `(0.000000, 0)` ×2 (once per device init), apply=IMMEDIATE | `[VERIFIED]` |
| `SetDopplerFactor(1.1, 0)` | `(1.100000, 0)` ×2, IMMEDIATE | `[VERIFIED]` |
| Listener fixed at (0,0,0), orient (0,0,1)/(0,1,0) | ×2 per setter (device inits), never updated after | `[VERIFIED]` |
| SetPosition "mostly length ≈0.9–1.0, one outlier 57.6" | **Deviates**—see 4.2 | `[VERIFIED deviation]` |
| SetVelocity e.g. (-0.000, -0.0655, -1.833) | plausible; magnitudes 0–66.0 | `[VERIFIED]` |
| SetVolume centibels (-538, -1522, -2157, -10000) | 255,926 calls, 5,237 distinct, max **-538** (most common: -538×84,854, -10000×29,109), min -10000 | `[VERIFIED]` |
| SetFrequency always 0 | **Deviates**: 249,903× `0` but 6,023× non-zero (12414×2138, 15659×1915, 29114×885, 18533×446, 22012×296, 21658×291, 21689×52) | `[VERIFIED deviation]` |
| No SetMinDistance/SetMaxDistance/cone setters | none (0 calls) | `[VERIFIED]` |
| SetAllParameters / CommitDeferredSettings unknown | **SetAllParameters: absent. CommitDeferredSettings: 46,444×** (≈1 per frame) | `[VERIFIED, resolved]` |
| ~370 buffers with CTRL3D | **403** CTRL3D creations (399 sound templates + 2 EAX probes (4-byte) + 2 primaries); 419 total CreateSoundBuffer | `[VERIFIED deviation]` |
| dwApply=1 is DS3D_DEFERRED | all 218,313 SetPosition and SetVelocity use apply=1 | `[VERIFIED]` |

### 4.2 Position distribution (new facts)

- `Buffer3D::SetPosition` ×218,313 on ~10 concurrent objects; `SetVelocity` ×218,313—
  strictly paired per update `[VERIFIED]`.
- Length distribution is **trimodal**:
  1. exactly `(0,0,1)` ×101,068 (46%)—a 2D/default placement (unit distance, dead ahead);
  2. spread 0.49–1.0 (≈32,000 calls)—near-field directions, not exactly unit;
  3. continuous tail 1.67→10000 (84,928 calls >1.05 length, 39%), including exactly
     `(0,0,-10000)` ×29,288—the **"parked silent" state** (correlated with
     `SetVolume(-10000)`, e.g. log line 473,724 ff.) and real far positions such as
     `(-1.007717, 9.811462, -107.388222)` (log line 941,859, length ≈107.9).
- §6.1's "57.6 outlier" is not an anomaly; it sits inside the continuous far tail.
  Interpretation (position formula) = task A2 `[HYPOTHESIS: positions are listener-space
  (rotated) coordinates passed to HEADRELATIVE buffers; scaling TBD in A2]`.

### 4.3 Per-frame update pattern (from mid-log frame capture, ~line 941,800)

For each active 3D sound per frame—in this order `[VERIFIED]`:

```
Buffer3D::SetPosition(x, y, z, 1=DEFERRED)
Buffer3D::SetVelocity(x, y, z, 1=DEFERRED)
Buffer::GetStatus           (playing check)
Buffer::SetVolume(centibels)      (IMMEDIATE)
Buffer::SetFrequency(0 or Hz)      (IMMEDIATE)
BufferProp::Set(DSPROPSETID_EAX20_BufferProperties, 0x80000003, 0,0, &val, 4)
  — 0x80000003 = DSPROPERTY_EAXBUFFER_DEFERRED | DSPROPERTY_EAXBUFFER_DIRECTHF
    (eax.h enum: NONE=0, ALLPARAMETERS=1, DIRECT=2, DIRECTHF=3, ...; DEFERRED=0x80000000)
  → the engine's per-sound HF filter is exported as EAX DirectHF (hundredths of dB)
... once per frame after all sounds:
Listener3D::CommitDeferredSettings()
```

### 4.4 Buffer lifecycle mechanics (log level; disassembly confirmation = A4)

- **399 mono CTRL3D "template" buffers** with flags
  `CTRL3D|CTRLFREQUENCY|CTRLVOLUME|MUTE3DATMAXDISTANCE|LOCDEFER`, 277 distinct sizes
  (2,204 → 1,598,620 B), formats 11/22/44.1 kHz mono 16-bit `[VERIFIED]`.
- **14 stereo non-3D templates** `CTRLFREQUENCY|CTRLPAN|CTRLVOLUME|LOCDEFER` (stereo 44.1/22.05 kHz—
  music/large sounds) `[VERIFIED]`.
- Per play: **`DuplicateSoundBuffer`** ×228 (first at log line 6320) from a template, then
  `QueryInterface(IID_IDirectSound3DBuffer)` (229 total ≈ 228 duplicates + 1 startup probe),
  `SetCurrentPosition(0)` ×228, then `Play` (216× `(0,0,0x0)`, 15× `(0,0,0x1=LOOPING)`),
  `Stop` ×55 `[VERIFIED]`.
- `SetMode` is called once per duplicate: 206× `HEADRELATIVE(1)` for 3D sounds, 21×
  `DISABLE(2)`—presumably stereo/2D sounds (DS3D needs mono) `[VERIFIED counts, LIKELY semantics]`.
- One **stereo software-mix buffer** (35,284 B = 200 ms, `CTRLFREQUENCY|CTRLPAN|CTRLVOLUME|
  GETCURRENTPOSITION2|LOCDEFER`) is also created, played looping, polled
  (`GetCurrentPosition` ×1,391) and re-`Lock`ed—**the 1.10-style software mixer still runs
  in the beta** (what it carries vs. the DS3D path = task A3/A4) `[VERIFIED existence]`.
- EAX probing: startup 4-byte CTRL3D probe buffer + `QuerySupport` for EAX2 Listener/Buffer
  property sets; per-buffer `IKsPropertySet` QI ×208 (= 206 3D commits + 2 startup probes,
  log lines 75 and 2002, one per device generation — see findings/04 §3) `[VERIFIED]`.
- Two device generations (`DirectSoundCreate` line 3 and 1931)—an early re-init, same
  pattern as the Steam log; everything above happens per device generation `[VERIFIED]`.

### 4.5 Beta architecture model (emerging; tasks A1–A4 to confirm)

Software mixer still active (stereo mix buffer) **plus** per-sound hardware DS3D path:
template-per-CSoundData → duplicate-per-play → drive per frame (position/velocity deferred,
volume/frequency immediate, EAX DirectHF deferred) → commit once per frame. Listener frozen
at origin; rolloff 0 (engine computes volume itself); doppler 1.1 (mild DS3D doppler from
real velocities—double-application check = task A3) `[LIKELY]`.

## 5. Steam log—facts

- Primary `CTRL3D` + **two mono 35,284/2 = 17,642 B buffers** `CTRL3D|GETCURRENTPOSITION2`
  = 1.10's `sl_pDSSourceLeft/Right` (`snd_iInterface==2` path, SoundLibrary.cpp:317-343
  `DSInitSecondary` halves size and forces mono) `[VERIFIED]`.
- `SetMinDistance(1.0)` / `SetMaxDistance(9.0)` ×4 = `MINPAN(1.0f)` / `MAXPAN(9.0f)`
  (SoundLibrary.cpp:98-99, 510-513) `[VERIFIED]`.
- Sources positioned once: left `(-1,0,0)`, right `(1,0,0)` (log lines 302-303)—matches
  `sl_pDSSourceLeft->SetPosition(fPanLeft,0,0)` with default pan (SoundLibrary.cpp:1039-1040)
  `[VERIFIED]`.
- Listener: position (0,0,0), orientation (0,0,1)/(0,1,0), rolloff 1.0—all DEFERRED,
  `CommitDeferredSettings` ×3, **no SetDopplerFactor / listener SetVelocity** `[VERIFIED]`.
- **No** per-sound DS activity at all: zero `Buffer3D::SetPosition/Velocity/Volume`,
  zero `Buffer::SetVolume/SetFrequency/SetPan/SetMode`. Only the mix loop:
  `GetStatus` (47,020) / `GetCurrentPosition` (2,420) / `Lock`+`Unlock` (1,122 pairs) on
  the two mix buffers `[VERIFIED]`.
- ⇒ Steam = pure software mixing into two mono DS3D buffers placed at the ears. The §6.3
  `[UNVERIFIED]` lead is now `[VERIFIED]`, with source-level explanation.

## 6. Export diff (sound-related)

Full table: `findings/scratch/exportdiff.md`. Beta 79 / Steam 76 sound symbols; 39 common;
40 beta-only; 37 steam-only.

Key structural differences `[VERIFIED]`:

| Aspect | Beta (TSE150) | Steam (TSE107) / 1.10 |
|---|---|---|
| `Update3DEffects` | **not exported** | `?Update3DEffects@CSoundObject@@QAEXXZ` @ 0007E870 |
| Per-frame update | `?Update@CSoundObject@@QAEXXZ` @ 000875E0 (new) | (inline/mixer-driven) |
| Buffer commit path | `CommitPlayingBuffer(CSoundObject&, int&)` @ 00082560 (private), `ReleasePlayingBuffer(long, int)` @ 00082740, `AddToPendingList` @ 00082500, `RemoveFromPendingList` @ 00082520, `PlayBuffers` @ 000829F0 | none |
| Play/Stop | `Play(CSoundData*, ULONG)` @ 000872D0, `Stop(int)` @ 00087450, `Stop_internal(int)` @ 000874D0, `Play_t(..., ULONG)` | `Play(CSoundData*, LONG)` @ 0007E480, `Stop(void)` @ 0007E750, `Stop_internal(void)` @ 0007E810, `Play_internal(CSoundData*, LONG)` @ 0007E500 |
| Extra int arg | `Set3DParameters(M,M,M,M,H)` @ 0001AB40, `SetVolume(M,H)` @ 00087020, `SetPitch(M,H)` @ 000870F0, `SetRange(M,M,H)` @ 00087190, `Fade(M,M,H)` @ 00087530, `Read/Write_t(...,H)` | `Set3DParameters(M,M,M,M)` @ 0007E2B0, `SetVolume(M,M)` @ 00019E00, `SetPitch(M)` @ 00019E60, no SetRange/Fade |
| Timer/mixing | `MixSounds` private `AAEXXZ` @ 000827F0, `Flush` @ 00081D40, `Mute(M)` @ 00081C80 | `MixSounds` public `QAEXXZ` @ 00079D70, `CSoundTimerHandler` class, `Mute(void)` @ 000782B0 |
| Object linkage | (no per-data object link exports) | `AddObjectLink`/`RemoveObjectLink` @ 000760B0/D0, `Pause/ResumePlayingObjects` @ 00076070/90 |
| Environment | `SetEnvironment(SndEnvFX)` @ 00081C20 | `SetEnvironment(long, long, float)` @ 000781B0 |
| Singleton | `_pSound` @ 0022E9B4, `_pSoundStock` @ 00230ED4 | `_pSound` @ 002097D4, `_pSoundStock` @ 0020C2FC |

Steam RVAs in AGENTS.md §6.2 re-checked against the actual binary export dump: **all match**
(`Listen` 0007A4B0, `MixSounds` 00079D70, `UpdateSounds` 000796F0, `Update3DEffects`
0007E870, `Play` 0007E480, `Play_internal` 0007E500, `Stop` 0007E750, `Stop_internal`
0007E810, `Play_t` 0007F060, `PrepareSound` 0007F010, `Set3DParameters` 0007E2B0,
`SetVolume` 00019E00, `Copy` 0007E1F0, `operator=` 00019F40, `GetPredictionTail` 0007E310,
`ClearBuffer` 00076200, `_pSound` 002097D4, `_pSoundStock` 0020C2FC) `[VERIFIED]`.

`CommitPlayingBuffer` is **beta-only**—confirms §6.2's suspicion `[VERIFIED]`.

## 7. Consequences for the project plan

1. The beta's 3D path is a **different API generation** (channel-index ints, Commit/Release
   PlayingBuffer, no exported Update3DEffects). Reproducing it on the Steam build means
   *reimplementing its behavior* through the Steam/1.10 API surface, not porting code
   1:1—exactly what the SuperProject shadow-buffer plan intends.
2. The beta kept the software mixer running. Whether 3D sounds are simultaneously
   software-mixed (and muted)—the core premise of the shadow-buffer design—is **not yet
   proven by the log**; task A3/A4 must answer it from the beta disassembly (see also S2
   for the Steam mixer's zero-volume behavior).
3. `DuplicateSoundBuffer`-based instantiation + `SetMode(1)` HEADRELATIVE + per-frame
   deferred position/velocity + immediate volume/frequency + EAX DirectHF + per-frame
   commit = the concrete call sequence a reimplementation must reproduce.
4. Steam `Engine.dll` = TSE107 ⇒ the 1.10 open-source code (close to 1.07) is a valid
   structural reference (already confirmed for `DSInitSecondary`/MINPAN/MAXPAN); S1 must
   still verify `Update3DEffects`/`Listen` structure offsets instruction-by-instruction.

## 8. Handoff to next tasks

- **A1**: find beta call sites for the §4.3 pattern; locate the beta's `Update`
  (000875E0) internals; map `CommitPlayingBuffer` (00082560) / `ReleasePlayingBuffer`
  (00082740); identify the position formula (A2: explain the 0.49–1.0 cluster, the (0,0,1)
  default, the far tail, and (0,0,-10000) parking).
- **A3**: explain SetVolume curve (max -538!), the 7 non-zero SetFrequency values, and
  whether doppler is applied once (DS3D) or twice (+software pitch).
- **A4**: template/duplicate lifecycle, stereo handling (SetMode 2), Pause/Resume/SetOffset
  equivalents in the channel API.
- **S1/S2**: verify Steam mixer zero-volume behavior; steam side already anchored by log
  facts in §5.
