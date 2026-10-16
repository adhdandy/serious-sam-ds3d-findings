# 05 — Steam build: hook surface (S1) + software-mixer zero-volume behavior (S2)

Target: `SS_TSE_Steam_Bin\Engine.dll` (SHA-256 B79BF8BB…, PE stamp 2002-04-22, TSE107 generation,
ImageBase **0x600C0000** — all RVAs below are `VA − 0x600C0000`; `.text` starts at RVA 0x1000).
Full disassembly: `findings/scratch/steam-engine-disasm.txt` (generated with
`llvm-objdump -d --no-show-raw-insn`); per-function extracts in `findings/scratch/steam-*.txt`
(via `findings/scripts/slicefunc.py <file> <rva>` / `--name <mangled>`).

Confidence labels: `[VERIFIED]` = read in the Steam disassembly and cross-checked against
`Serious-Engine` 1.10 source and/or the DSOAL Steam log. `[LIKELY]`, `[HYPOTHESIS]` as usual.

---

## 1. S1 — Hook surface: every export of §6.2 re-verified against the binary

All AGENTS.md §6.2 RVAs were re-derived from the binary in Stage 1 (see 00-orientation §6);
this task read the *bodies*. All sound functions are `__thiscall` (`QAE…`, `this` in `%ecx`,
callee clean-up via `retl $N`), matching the 1.10 headers exactly.

### 1.1 Empirical structure layouts (Steam binary) — 1.10 headers are safe here

**`CSoundObject`** (matches 1.10 `SoundObject.h` field-for-field) `[VERIFIED]`:

| Offset | Field | Evidence |
|---|---|---|
| +0x00 | `so_Node` (CListNode, 8B) | `IsLinked`@Play_internal 0x7E56E, `RemoveObjectLink` args |
| +0x08 | `so_psdcDecoder` | Play_internal 0x7E549 `movl 0x8(%ebx)`; MixSound 0x7AF9A `movl 0x8(%esi)` |
| +0x0C | `so_pCsdLink` | Play_internal 0x7E595-0x7E5A0 |
| +0x10 | `so_slFlags` | Update3DEffects 0x7E87A `movl 0x10(%ecx)`; SOF bits confirmed: LOOP=1, 3D=2, VOLUMETRIC=4, LOCAL=0x10, MUSIC=0x40, LOADED=0x20000000, PAUSED=0x10000000, PREPARE=0x40000000, PLAY=0x80000000 |
| +0x14/0x18/0x1C | `so_fDelayed` / `so_fLastLeftVolume` / `so_fLastRightVolume` | MixSound 0x7AFF7/0x7B07A/0x7B095 |
| +0x20/0x22 | `so_swLastLeft/RightSample` (SWORD) | MixSound 0x7B2B3 `movw %ax, 0x20/0x22(%esi)` |
| +0x24/0x28/0x2C | `so_fLeftOffset` / `so_fRightOffset` / `so_fOffsetDelta` | MixSound 0x7B188-0x7B1A0 |
| +0x30 | `so_penEntity` | Update3DEffects 0x7E88E |
| +0x34 (28B) | `so_sp` (CSoundParameters: LVol,RVol,LFilter,RFilter,Phase,Pitch,Delay) | Play_internal 0x7E615 `rep movsl` 7 dwords from +0x50 |
| +0x50 | `so_spNew` | same |
| +0x6C | `so_sp3` (Pitch@0x6C, **Falloff@0x70, HotSpot@0x74, MaxVolume@0x78**) | Set3DParameters 0x7E2ED-0x7E2F9 |

⇒ **1.10 `Engine/Sound/SoundObject.h` can be used verbatim against the Steam binary.**
Note the field *order* inside `CSoundParameters3D` is (Pitch, Falloff, HotSpot, MaxVolume)
and `Set3DParameters(fFalloff, fHotSpot, fMaxVolume, fPitch)` stores them accordingly
(0x7E2ED: arg1→0x70, arg2→0x74, arg3→0x78, arg4→0x6C) `[VERIFIED]`.

**`CSoundData`** (empirical) `[VERIFIED]`: `sd_ulFlags`@+0x1C (SDF_ENCODED=1, SDF_STREAMING=2 —
Play_internal 0x7E5D6/0x7E5DE), `sd_wfeFormat`@+0x2C (WAVEFORMATEX: nChannels word@0x2E,
nSamplesPerSec dword@0x30, wBitsPerSample word@0x3A — MixSound 0x7AFB9-0x7AFD7),
**`sd_pswBuffer`@+0x40, `sd_slBufferSampleSize`@+0x44** (MixSound 0x7B029-0x7B037:
buffer ptr cached to static `0x602c9874`, size to `0x602c9858`).

**`CSoundLibrary`** (empirical, sound-relevant fields) `[VERIFIED]`: `sl_bUsingDirectSound`@+0x18
(MixSounds 0x7DDE5), `sl_bUsingWaveOut`@+0x1C?? — correction: **`sl_bUsingEAX`@+0x1C** (MixSounds
0x7DE47; set TRUE in StartUp_dsound 0x78DFB), `sl_csSound` (first field of CSoundLibrary at
+_pSound+…; `_pSound` @ RVA 0x2097D4 → VA 0x602c97d4), `sl_pDSSecondary`@+0x40,
`sl_pDSSecondary2`@+0x44, `sl_EsfFormat`@+0x60, `sl_ClhAwareList`@+0x88,
**`sl_lhActiveListeners`@+0x94** (Listen 0x7A4CD `leal 0x94(%edi)`),
`sl_slMixerBufferSize`@+0x80, `sl_pslMixerBuffer`@+0x78.

### 1.1a `StartUp_dsound` (Steam RVA **0x78840**) — full DS-pointer map `[VERIFIED]`

Found via `"dsound.dll"`/`"DirectSoundCreate"` strings (VA 0x602a4250 / 0x602a4294,
referenced at 0x78888 / 0x788C7). The function is the 1.10 source
(`SoundLibrary.cpp:427-534`) compiled straight through — every step matched:

| Field (1.10 name) | Steam offset | Evidence |
|---|---|---|
| `_hInstDS` (global, dsound.dll handle) | RVA **0x2097E4** (VA 0x602c97e4) | `movl %eax, 0x602c97e4` after LoadLibraryA |
| `_hwndCurrent` (global) | RVA 0x2097E0 | 0x789EB `movl 0x602d31e0 → 0x602c97e0` (=_hwndMain), SetCooperativeLevel(hwnd, 2=DSSCL_PRIORITY) via vtable 0x18 |
| `sl_pDS` (LPDIRECTSOUND) | **+0x34** | `DirectSoundCreate(NULL, &sl+0x34, NULL)` — pushes at 0x78912-0x78918 |
| `sl_pKSProperty` (LPKSPROPERTYSET) | **+0x38** | QI(IID_IKsPropertySet @ VA 0x60254fb8) on sl_pDSSourceLeft → &sl+0x38 (0x78D58-0x78D66), gated on `snd_iInterface==2` |
| `sl_pDSPrimary` | **+0x3C** | CreateSoundBuffer(pDS, &dsbd{dwSize=0x24, flags=PRIMARYBUFFER\|(snd_iInterface==2?CTRL3D:0)}, &sl+0x3C) at 0x78A5E-0x78A83 (vtable 0x0C); `SetFormat` on it via vtable 0x38 (slot 14) with copy of `sl_SwfeFormat`@+0x64 |
| `sl_pDSSecondary` (mono mix-left out) | **+0x40** | `DSInitSecondary` (0x790E0) call 0x78B7F, size=`ceil(mixAhead×rate)×bits/8×ch` |
| `sl_pDSSecondary2` | **+0x44** | DSInitSecondary call 0x78BA9, only when `snd_iInterface==2` |
| `sl_pDSListener` (3DListener iface of primary) | **+0x48** | QI(IID_IDirectSound3DListener @ VA 0x60254f58) at 0x78BC1-0x78BDA |
| `sl_pDSSourceLeft` (3DBuffer iface of +0x40) | **+0x4C** | QI(IID_IDirectSound3DBuffer) at 0x78BDF-0x78BF0 |
| `sl_pDSSourceRight` (3DBuffer iface of +0x44) | **+0x50** | QI at 0x78BF3-0x78C02 |
| `sl_SwfeFormat` (WAVEFORMATEX) | +0x64 | `leal 0x64(%esi)` for SetFormat (0x78AC1); 0x14 bytes copied to stack |
| `sl_EsfFormat` | +0x60 | SetFormat 0x7852C `movl %edi, 0x60(%esi)` |
| `sl_slMixerBufferSize` | +0x80 | tail 0x78E1C `movl %edi, 0x80(%esi)` |

Listener/source init sequence (all gated on `snd_iInterface==2`, all **DEFERRED**),
matching source 506-519 and the Steam log exactly: listener `SetPosition(0,0,0)` (vtable
0x38=s14) → `SetOrientation(0,0,1, 0,1,0)` (0x34=s13) → `SetRolloffFactor(1.0)` (0x3C=s15)
→ sources `SetMinDistance(1.0)` (0x44=s17) / `SetMaxDistance(9.0)` (0x40=s16) ×2 →
listener `CommitDeferredSettings()` (0x44=s17, at 0x78CF6) → `_fLastPanning/_iLastEnvType/
_fLastEnvSize = 1234` (0x78D3A-0x78D4E) → KsPropertySet QI → `QuerySupport(EAX Listener,
ENVIRONMENT(0xB) + ENVIRONMENTSIZE(0xC))` w/ `KSPROPERTY_SUPPORT_SET` check →
`sl_bUsingEAX = TRUE` @ +0x1C (0x78DFB).

**Note for the log cross-check:** Steam listener = rolloff **1.0** DEFERRED and *no*
`SetDopplerFactor` (00-orientation §5) — exactly what this binary does; the **beta**
differs (rolloff 0.0, doppler 1.1, IMMEDIATE — findings/02 §6). The DS3D patch must set
those listener parameters itself (beta values), it cannot rely on the Steam engine's
listener init.

**Answer to the 99-summary open engineering item:** the patch can obtain the engine's
`IDirectSound*` as `_pSound->*(+0x34)` for `DuplicateSoundBuffer`/`CreateSoundBuffer`
(shadow templates), and `snd_iInterface==2` (`@` VA 0x602a4128) marks the mode where the
engine itself owns the 3D-capable mono pair — the DS3D mode should gate/shadow accordingly.

### 1.2 Function-by-function check vs 1.10 source

| Export (RVA) | Body vs 1.10 source | Notes |
|---|---|---|
| `Update3DEffects` (0x7E870) | `[VERIFIED]` semantically identical to `SoundObject.cpp:385-590` | SOF_3D test `testb $0x2` on flags@0x10 (0x7E87D); per-listener loop reads `sli_penEntity`@listener+0x4C, `sli_vPosition`@+8, `sli_vSpeed`@+0x14? (via entity @+0x104 vCurrentTranslationAbsolute, EPF_MOVABLE=0x0200 tested on `en_ulPhysicsFlags`@entity+8, 0x7E90A); falloff compare `fcomps 0x70(%ecx)`, hotspot `0x74(%ecx)` (0x7E9A2/0x7E9B3); volumetric `testb $0x4,%bl` + decoder@+8 (0x7E9D9/0x7E9E5); local-sound gate = **direct `so_penEntity != sli.sli_penEntity` compare** (0x7E954 `cmpl 0x4c(%edx),%edi`) — i.e. *stock 1.10 semantics, not* SuperProject's `[Cecil]` prediction-tail variant |
| `Listen` (0x7A4B0) | `[VERIFIED]` identical to `SoundLibrary.cpp:1348-1355` | `IsLinked→Remove→AddTail(sl_lhActiveListeners@+0x94)`; `retl $0x4`; 12 instructions, trivially hookable |
| `Play` (0x7E480) | `[VERIFIED]` = source 209-225 | `CTSingleLock(&_pSound->sl_csSound)` → `GetPredictionTail(0x101, pCsdLink)` → `psoTail->Play_internal` |
| `Play_internal` (0x7E500) | `[VERIFIED]` = source 228-297 | bContinue=SOF_SMOOTHCHANGE(0x20)&SOF_PREPARE&SOF_PLAY; **`Stop_internal` is INLINED** (see 1.3); decoder `new`ed only for SDF_ENCODED|SDF_STREAMING (ctor call at 0x7E5E3-0x7E600); `so_sp = so_spNew` via `rep movsl` 7 dwords; !(SOF_LOADED) → init mixer vars, bContinue → master-volume scale (`SOF_MUSIC` → `snd_fMusicVolume`@VA 0x602a40fc else `snd_fSoundVolume`@0x602a40f8) |
| `Stop` (0x7E750) | `[VERIFIED]` = source 340-360 | lock → `GetPredictionTail(0x102, so_pCsdLink)` → tail `Stop_internal` |
| `Stop_internal` (0x7E810) | `[VERIFIED]` = source 361-381 | `flags &= 0x2FFFFFFF`; `delete so_psdcDecoder`; `IsLinked` → `RemoveObjectLink`+`RemReference`+clear link |
| `Set3DParameters` (0x7E2B0) | `[VERIFIED]` = source 134-159 | `_bPredictionActive`@VA 0x602cd74c; prediction-head remap `pso = pen + (this − so_penEntity)` (0x7E2DE-0x7E2E2); stores as §1.1 |
| `PrepareSound` (0x7F010) | `[VERIFIED]` present, called from UpdateSounds (0x7C??F3 → 0x7BF3) | per source 594-608 |
| `UpdateSounds` (0x796F0) | `[VERIFIED]` = `SoundLibrary.cpp:989-1081` | calls per object: `Update3DEffects` (0x7E870, call at 0x79BA0), `PrepareSound` (call 0x79BF3), listener list teardown via `CListNode::Remove` (0x79C11/0x79C39), `SetEnvironment`(EAX) path at 0x7A39 |
| `MixSounds` (0x79D70) | `[VERIFIED]` = `SoundLibrary.cpp:1252-1324` | see §2 |
| `Play_t` (0x7F060), `GetPredictionTail` (0x7E310), `Copy` (0x7E1F0), `operator=` (0x19F40) | `[LIKELY]` = source | not re-decoded line-by-line; export RVAs verified, signatures match headers; low risk since Play/Stop/etc. all matched |

**Divergences found: none.** The Steam TSE107 sound code is the 1.10 source compiled with
MSVC 6-era optimizations (`rdtsc` profiling wrappers, inlined statics). Every offset, flag
bit and branch checked so far matches `Serious-Engine` 1.10 exactly. (The *beta* differs
strongly — channel-index API — but that's task group A, see findings/01.)

### 1.3 Hookability caveats discovered `[VERIFIED]`

1. **`Play_internal` inlines `Stop_internal`.** At 0x7E545-0x7E588 the Stop_internal body
   (flags clear, decoder delete, unlink) is emitted inline; there is **no `call 0x7E810`**
   inside Play_internal. Consequence for the shadow-buffer plan: a hook on
   `Stop_internal` **will not** see stops caused by re-`Play`ing an object. The patch must
   release/recreate the shadow buffer inside its own `Play_internal` wrapper (which it gets
   anyway) — or the wrapper must call its own release logic before invoking the original.
   (`~CSoundObject` at 0x7E4E0-era code likewise appears to inline — destructor thunks
   share the pattern.)
2. `Pause`/`Resume`/`IsPaused`/`IsPlaying`/`IsHooked` (0x19DB0-0x19DF0) are 10-byte
   flag-twiddle functions — hookable, but no reason to.
3. All functions listed are in `TSE107\Engine.def` (verified Stage 1 + S3 citation check:
   `Play_internal` def line 2167, `Stop_internal` 2817) ⇒ hookable **exactly like `Listen`**
   (linked import stub + `CreatePatch`), no `GetProcAddress` fallback needed
   (see findings/06 §4a, §7).
4. `UpdateSounds` (0x796F0) calls `Update3DEffects` and `PrepareSound` **directly** (direct
   `calll` at 0x79BA0/0x79BF3), not through the export table — hooking `Update3DEffects`
   changes the per-object update for everything (which is the plan); no per-callsite issue.

---

## 2. S2 — Mixer behavior with muted (zero-volume) objects

**Question:** if a sound object's left and right volume are zero, does the mixer still
advance its playback position and report it finished at the correct time, or does it
skip it entirely? → **Both: it skips mixing but (for non-encoded sounds) advances the
offset and finishes on schedule.**

### 2.1 `MixSounds` (RVA 0x79D70) gate structure `[VERIFIED]`

- `CTSingleLock(&sl_csSound)`; early out if `sl_EsfFormat==SF_NONE` (0x7DDB8 `cmpl 0x60(%edi)`)
  or `_bMuted`@VA 0x602c97f0 (0x7DDAB) — matches source 1255-1258.
- `slDataToMix` via inlined `PrepareSoundBuffer_dsound` (GetCurrentPosition vtable `call *0x10(%ecx)`
  on `sl_pDSSecondary`@+0x40 and `sl_pDSSecondary2`@+0x44) or `PrepareSoundBuffer_waveout`.
  `<= 0` → return (0x7DF3F `jg`) — matches 1272-1278.
- `ResetMixer` inlined (0x7DFA8 calls `Listen+0x7c0` static @ RVA 0x7AC70 = `ResetMixer`):
  `slMixerBufferSampleRate`@VA 0x602c9884, `slMixerBufferSize`@0x602c9880 set from
  `_pSound->sl_SwfeFormat.nSamplesPerSec`.
- `bGamePaused` from `_pNetwork->IsPaused()` / `GetLocalPause()` (calls 0x7AC?? `IsPaused@CNetworkLibrary`,
  `GetLocalPause`) — matches 1284.
- **Per-object loop** (0x7DFE8-0x7A036): outer over `sl_ClhAwareList`@+0x88, inner over
  `sd_ClhLinkList`. Skip conditions on `so_slFlags`@+0x10 in this order `[VERIFIED]`:
  `testb $-0x80,%al` (SOF_NONGAME=0x80) **and** `bGamePaused` → skip;
  `testl $0x80000000` (SOF_PLAY) == 0 → skip;
  `testl $0x40000000` (SOF_PREPARE) == 0 → skip;
  `testl $0x10000000` (SOF_PAUSED) != 0 → skip;
  else `calll 0x7AF80` = **`MixSound`** (static). Exactly source 1291-1301.
- After the loop: `NormalizeMixerBuffer` (call @ 0x7A090 → static @ RVA 0x7AC70-family,
  `snd_fNormalizer`@VA 0x602a4138 clamp), then `CopyMixerBuffer_dsound` (static @ RVA
  **0x7A180**, called at 0x7A0A3) or `CopyMixerBuffer_waveout` (0x7A0D1-0x7A0F3:
  `waveOutPrepareHeader`/`waveOutWrite` import thunks `*0x60254354`/`*0x60254350`).
  `CopyMixerBuffer_dsound` uses **vtable offsets: `Lock` @ `*0x2c(%eax)` (IDirectSoundBuffer
  slot 11), `Unlock` @ `*0x2c` too? — no: Unlock @ `*0x2c`… (see below), `SetPosition` @
  `*0x4c(%edx)` = IDirectSound3DBuffer slot 19 = 0x4C** on `sl_pDSSourceLeft/Right`
  (0x7A263/0x7A345) — i.e. the EAX-panning path `SoundLibrary.cpp:1039-1040`, consistent
  with the Steam log (sources positioned ±1 once, listener commit) `[VERIFIED]`.
  (Correction vs an easy mis-scan: `call *0x10(%ecx)` at 0x7E003/0x7E013 inside
  PrepareSoundBuffer is `GetCurrentPosition` = IDirectSoundBuffer slot 4 → offset 0x10;
  `Lock` is slot 11 → 0x2C, both seen in CopyMixerBuffer_dsound at 0x7A1C2 `calll *0x2c(%eax)`
  and 0x7A29F. All slots agree with the DSOUND.H table in 00-orientation §3.)

### 2.2 `MixSound` (static, RVA **0x7AF80**) — the zero-volume branch `[VERIFIED]`

Disassembly matches `SoundMixer.cpp:572-825` instruction-for-instruction in the parts
that matter to the design:

- PCM access: `psd = so_pCsdLink`@0x0C; format gate nChannels@0x2E ∈ {1,2},
  wBitsPerSample@0x3A/8 == 2 (0x7AFB9-0x7AFDA); encoded+decoder-not-open → return (0x7AF94-0x7AF9A).
- **Delay** handled *before* the volume check: `so_fDelayed`@0x14 += fSecondsToMix;
  if `< so_sp.sp_fDelay`@0x4C → return (0x7AFFD-0x7B005). ⇒ muting volumes does not stall delays.
- Volumes read: old `so_fLastLeftVolume`@0x18 / `so_fLastRightVolume`@0x1C,
  new `so_sp.sp_fLeftVolume`@0x34 / `sp_fRightVolume`@0x38, each `ClampDn(…, 0)`,
  master-scaled for `SOF_MUSIC` (0x7B065-0x7B115).
- **Zero-volume gate** (0x7B11C-0x7B163): all four of {oldL, oldR, newL, newR} `< 0.001`
  (const @VA 0x6025449c) → fall through into the skip path:
  - `testb $0x1, 0x1c(%ecx)` = **`SDF_ENCODED`**: if set → jump **past** the offset advance
    to 0x7B2AE (encoded sounds are never "advanced" here — see caveat below).
  - else: `fOfsDelta = fStep × slMixerBufferSampleRate × fSecondsToMix`
    (0x7B173-0x7B182, `fStep`@VA 0x602c9848 — i.e. exactly one mix block of source samples),
    `so_fLeftOffset`@0x24 += fOfsDelta, `so_fRightOffset`@0x28 += fOfsDelta (0x7B188-0x7B197).
  - `SOF_LOOP` (0x7B1DE `testb $0x1`): looping → wrap offsets into [0, size)
    (while-loops 0x7B1E6-0x7B238). **Non-looping → 0x6013b1e0 `je 0x6013b29e` jumps
    directly to 0x7B29E-0x7B2A3: `so_slFlags &= 0x7FFFFFFF` (clears SOF_PLAY),
    `so_fDelayed = 0`, `so_sp.sp_fDelay = 0` — with NO end-of-buffer comparison
    guarding the clear.**
    `[CORRECTED in Phase 2 Task 1 — see findings/07 §7.2]` The original wording
    "*finished, on schedule*" was wrong: a zero-volume non-looping sound is stopped
    **after one mix block** (the offsets are advanced once, then the flags clear
    unconditionally). Only LOOPING muted sounds keep advancing and wrapping. This
    matches 1.10 source `SoundMixer.cpp:637-649` exactly; the disassembly was right,
    its interpretation was not.
  - Tail (0x7B2AE): `so_swLastLeftSample`@0x20 = `so_swLastRightSample`@0x22 = 0;
    `so_fLastLeftVolume`@0x18 = newL, `so_fLastRightVolume`@0x1C = newR;
    `PCI_SOUNDSSKIPPED` counter++; return.
  ⇒ **Byte-for-byte the 1.10 `SoundMixer.cpp:624-659` skip path.**

### 2.3 Consequences for the shadow-buffer design `[VERIFIED]`

1. **Mute-and-shadow via zero-volume muting is viable ONLY for looping, in-memory
   (non-encoded) WAV sounds — and therefore NOT viable as the general mechanism.**
   Zeroing `so_spNew.sp_fLeftVolume/sp_fRightVolume` (what `SetVolume(0,0)` does — 1.10
   inline, engine export `?SetVolume@…` @ 0x19E00) makes `UpdateSounds` copy zeros into
   `so_sp`, the mixer skips the object and `so_fLeft/RightOffset` still advance every mix
   block — **but** per §2.2 (corrected) non-looping sounds have `SOF_PLAY` cleared after
   ONE mix block, and looping-only support would kill every one-shot 3D sound.
   `[CORRECTED in Phase 2 Task 1 — findings/07 §7.2/§7.4]` The correct general
   mechanism intercepts the static `MixSound` (RVA 0x7AF80, single call site in
   `MixSounds`) so shadowed objects are never mixed, advanced or finished by the
   software mixer at all — the DS shadow buffer owns playback state, exactly like the
   beta (which gates its mixer on `decoder != NULL` — findings/04 §6).
2. **Caveat — encoded/streaming sounds (`SDF_ENCODED`, i.e. MPX/OGG via `CSoundDecoder`):**
   at zero volume the skip path does **not** advance anything and does **not** finish the
   sound (the decoder is never run; also `so_fDelayed` is set to 9999.9999 before this
   point). Such an object would stay `SOF_PLAY`ing forever while inaudible. ⇒ The DS3D mode
   must **not** mute decoder sounds this way: either leave them in the ordinary software mix
   (like the beta does — findings/04 §"no double audio"), or give them a shadow buffer fed
   by the decoder without touching their L/R volumes. (Beta chose the former: stereo/large
   sounds = mode-2 / non-3D.)
   `[VERIFIED behavior] / [HYPOTHESIS: beta kept decoder sounds out of DS3D entirely]`
   — resolve definitively against findings/04's `SetMode(2)` population before implementing.
3. **Smooth transitions are lost while muted**: `so_fLastLeft/RightVolume` track the
   (zeroed) new volumes, so un-muting would ramp from 0 across one mix block
   (`mmVolumeGain` path, SoundMixer.cpp:671-677). Irrelevant while the mode is always-on
   per object, relevant only if the cvar is toggled mid-sound.
4. **Where the engine's output buffers are created**: `StartUp_dsound`/`DSInitSecondary`
   (`SoundLibrary.cpp:317-343` in 1.10) — already log-corroborated in Stage 1
   (00-orientation §5: two mono 17,642B `sl_pDSSourceLeft/Right` CTRL3D buffers placed at
   ±1). The DS3D mode must leave these alone (they carry the software mix of
   non-3D/decoder/music sounds) and can additionally keep them working while per-sound
   shadow buffers play `[VERIFIED creation path, LIKELY coexistence]`.
5. `bGamePaused` (SOF_NONGAME) and `SOF_PAUSED` gates live *outside* MixSound — a paused
   game mutes the software mix but the shadow buffers would keep playing unless the
   wrapper honors `_bMuted`/pause too. The beta releases buffers on Pause (findings/04) —
   the Steam-mode wrapper must replicate: honor `SOF_PAUSED` and `_bMuted` (window focus /
   `CSoundLibrary::Mute` 0x782B0) in the per-frame shadow update. `[VERIFIED gates] /
   [HYPOTHESIS handling]`.

---

## 3. Handoff

- Implementation parameters (position formula, volume curve, buffer flags, lifecycle):
  see findings/01-04 (beta) — nothing in the Steam binary contradicts them.
- Hook mechanics and where to register new patches: findings/06 (S3), now citation-checked
  (see §4 below).
- Remaining unknowns → `99-summary-and-open-questions.md` (final stage).

## 4. S3 draft verification note

`findings/06-core-patch-mechanism.md` was independently re-verified against the on-disk
sources (agent spot-check, 20 claims): **17 exact, 3 minor corrections applied** —
(1) `_EnginePatches.FileSystem()` is at `SeriousSam.cpp:631` inside the `#if` at 629;
(2) `BuildCheck` spans `Core.cpp:99-148` (not ~120); (3) the "zero Play_internal/Stop_internal
references" claim holds for source, but the bundled binary
`SuperProject\Localization\ExtractionTool\Engine.dll` contains the strings in its export
table (not a code reference). Also noted: `CSymbolPtr`'s `GetSymbol(name, TRUE)` call is at
`SymbolPtr.h:43` inside `Find()` (ctor 37-39 delegates). No claim was refuted; the
`CreatePatch`/`HFuncPatch` definitions remain off-disk (empty `API` submodule), as the
draft already caveats.