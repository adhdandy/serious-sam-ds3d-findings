# WORKLOG — Serious Sam DS3D analysis

Running notes: what was tried, what worked, dead ends. Newest entries at the bottom.

## Session 1 — Stage 1 (orientation)

- Confirmed inputs: root `dsoal_log.txt` (beta ground truth, 138.9 MB, 1,883,674 lines,
  captured with `SeriousSamNoCD_b1.50.exe`) and `dsoal_Steam_log.txt` (4.3 MB, 68,334 lines).
  Note: earlier I believed there was also an `SS_TSE_Beta_Bin\dsoallog.txt`; it does not
  exist (glob + Get-Item both negative). There IS an `SS_TSE_Beta_Bin\dsoundlog.txt`
  (name from first directory listing) — not yet examined, low priority.
- llvm-objdump -p dumps of 8 key binaries -> findings/scratch/*.txt.
  Findings: capture EXE imports only Engine.dll (sound code = stock beta Engine.dll).
  Engine2.dll = modern rebuild (internal name Engine.dll, imports steam_api/XINPUT/
  MSVCR71/Core.dll; Core.dll absent from folder) -> NOT part of the 2002 beta sound path.
  Neither Engine.dll imports dsound.dll statically -> dynamic loading.
- DSOUND.H (1.10 source) vtable order verified: matches AGENTS.md 6.3 for
  IDirectSound3DBuffer (SetMode=18, SetPosition=19, SetVelocity=20),
  IDirectSound3DListener (SetDopplerFactor=12, SetOrientation=13, SetPosition=14,
  SetRolloffFactor=15, SetVelocity=16, CommitDeferredSettings=17),
  IDirectSoundBuffer (Lock=11, Play=12, SetCurrentPosition=13, SetVolume=15,
  SetFrequency=17, Stop=18, Unlock=19), IDirectSound (CreateSoundBuffer=3).
- Steam log head: primary CTRL3D + two mono CTRL3D 17642-byte buffers (software mix pair,
  the "couple of buffers" from lead 6.3), THEN listener QI. Beta log head: primary CTRL3D +
  one stereo CTRLPAN/LOCDEFER 35284-byte buffer + 4-byte mono 3D EAX probe (released).
- Next: findings/scripts/logstats.py over both logs.

## Session 1 continued — log analysis + export diff

- logstats.py first run DOUBLE-COUNTED methods that have a debug entry line + trace
  continuation (CreateSoundBuffer 838 -> actual 419; GetStatus 609418 -> 304709).
  Fixed by counting only lines matching the "(ptr)->(args)" call structure. Lesson:
  DSOAL logs method entry (debug) and result details (trace) as separate lines.
- Beta log: CommitDeferredSettings PRESENT (46444x, ~1/frame) - AGENTS.md 6.1 "unknown"
  resolved. SetAllParameters ABSENT.
- Position length distribution is trimodal: exact (0,0,1) x101068; spread 0.49-1.0;
  continuous tail to 10000 incl. parked-silent (0,0,-10000) x29288 + SetVolume(-10000).
  6.1's "one outlier" claim was wrong - there is a whole far-tail.
- SetFrequency not always 0: 6023 nonzero calls, 7 distinct values.
- Per-frame order: SetPosition -> SetVelocity -> GetStatus -> SetVolume -> SetFrequency
  -> EAX BufferProp::Set(EAX20_BufferProperties, 0x80000003 = DEFERRED|DIRECTHF) per sound,
  CommitDeferredSettings once per frame.
- EAX property ID decoded via eax.h enum: 0x80000003 = DSPROPERTY_EAXBUFFER_DEFERRED
  | DSPROPERTY_EAXBUFFER_DIRECTHF.
- Buffer instantiation = DuplicateSoundBuffer (228x) + QI(3DBuffer) + SetCurrentPosition(0)
  + SetMode(1=HEADRELATIVE x206 / 2=DISABLE x21) + Play. Templates: 399 mono CTRL3D
  (MUTE3DATMAXDISTANCE|LOCDEFER etc.), 14 stereo non-3D. Beta ALSO runs the software mixer
  (stereo 35284B mix buffer, looping, polled) - relation between the two paths = A3/A4.
- Steam log decoded completely: 2 mono 17642B CTRL3D mix buffers = 1.10 sl_pDSSourceLeft/
  Right (snd_iInterface==2, DSInitSecondary SoundLibrary.cpp:317-343), MINPAN=1/MAXPAN=9
  (98-99), positioned (-1,0,0)/(1,0,0) once (log 302-303, matches fPanLeft/fPanRight path
  at 1039-1040), rolloff 1 deferred, zero per-sound DS calls. Steam = pure software mix.
- Export diff (scratch/exportdiff.md): beta has NO Update3DEffects export; beta equivalent
  = CSoundObject::Update @ 000875E0 + channel API (CommitPlayingBuffer/ReleasePlayingBuffer/
  AddToPendingList/RemoveFromPendingList) + extra int args on SetVolume/SetPitch/
  Set3DParameters/Stop/Stop_internal/Read_t/Write_t. Stop_internal takes int in beta.
- Engine2.dll classified: PE stamp 2026-03-02, modern third-party rebuild, out of scope.
- Steam RVAs from AGENTS.md 6.2 all re-verified against the binary export dump.
- 00-orientation.md written. Stage 1 complete.

## Session 2 — Stage A (beta reverse engineering)

- Ghidra 12.1.4 headless run on beta Engine.dll (project SamBeta in findings/_ghidra,
  postScript findings/scripts/ghidra/DumpSoundAnalysis.java -> findings/ghidra-out/
  sound-analysis.txt, 401 functions decompiled, ~1 MB).
- S3 explore agent ran in parallel; wrote findings/06-core-patch-mechanism.md (draft;
  citation spot-check still pending). Its "beta may be Classics-patched" worry was wrong:
  DebugFiles/*.map are from modern custom builds, capture EXE imports only Engine.dll.
- Beta's Update3DEffects equivalent = CSoundObject::Update (0x875E0, math via static
  FUN_10087970 @ 0x87970) + CSoundLibrary::PlayBuffers (0x829F0, the DS3D driver).
  UpdateSounds (0x81F40) orders the frame: Update* -> Sort -> DSPlayMainBuffers ->
  MixSounds (timer) -> PlayBuffers -> CommitDeferredSettings (0x82271).
- Full call-site table with log corroboration -> findings/01. All StartUp_dsound,
  LoadWAV_t (templates), CommitPlayingBuffer (Duplicate+QI+SetMode), ReleasePlayingBuffer,
  FUN_10082780 (orphan play-out) decoded.
- Constants extracted via findings/scripts/readpe.py + targeted llvm-objdump:
  volume curve K1=3000.0 (linear default: 3000*(v(v-1)+(1-v)log10 v), threshold 0.005,
  validated against log values -538/-1436/-2157); SetFrequency = rate*pitch or 0;
  doppler c=300 (software path only for waveOut/decoder - no double application);
  EAX DirectHF = round(-100 * hf) clamped; ears +-0.25; pan 0.9; steal threshold 0.333;
  basis (0,0,-1) explains the 101K (0,0,1) positions; parked state (0,0,10000)->z-negated.
- snd_iEmulationType selects DS3DALG GUIDs (0/1/2 = DEFAULT/HRTF_LIGHT/HRTF_FULL).
- Struct layouts (CSoundObject beta layout!, CSoundLibrary channels, CSoundData,
  CSoundListener) documented empirically in findings/01.
- No double audio in beta: MixSounds gates on decoder!=NULL when DS active; zero-L/R
  objects skipped by software mixer entirely.
- Residuals (documented in findings files): volumetric blend angle constant roles
  (0x101b8ca8=0.0 multiply — needs raw disasm if bit-exact copy wanted); L/R tail
  clamps in FUN_10087970 (software-mixer-only path); EAX env preset table at 0x1020f7c8.
- Stage A findings written: 01 (call sites), 02 (position/velocity), 03 (volume/pitch),
  04 (lifecycle). Full beta disasm cached at findings/scratch/beta-engine-disasm.txt.

## Session 3 — Stage B (S1/S2 + S3 citation check)

- Full steam disasm: llvm-objdump -> scratch/steam-engine-disasm.txt (ImageBase 0x600C0000).
  Slicer helper: scripts/slicefunc.py (--name <mangled> | start_rva [end_rva]).
- S1: every §6.2 export body read and matched to 1.10 source instruction-for-instruction -
  NO divergence (findings/05 §1). Empirical layouts: CSoundObject matches 1.10 header
  exactly (flags@0x10, entity@0x30, sp@0x34, spNew@0x50, sp3@0x6C: pitch/falloff/hotspot/maxvol);
  CSoundData: flags@0x1C, wfeFormat@0x2C, pswBuffer@0x40, bufferSampleSize@0x44;
  CSoundLibrary: lhActiveListeners@0x94, pDSSecondary@0x40/2@0x44, ClhAwareList@0x88.
- IMPORTANT hook caveat found: Play_internal (0x7E500) INLINES Stop_internal (no call to
  0x7E810) -> a Stop_internal hook misses re-Play transitions; release shadow buffer in
  the Play_internal wrapper instead.
- S2 ANSWER: MixSound (static @ RVA 0x7AF80, called from MixSounds 0x79D70 per-object gate
  PLAY&PREPARE&!PAUSED&!NONGAME-paused) has the 1.10 zero-volume skip path byte-for-byte:
  all four vols <0.001 -> advance so_fLeft/RightOffset by one mix block, wrap if loop,
  non-looping clears SOF_PLAY ON SCHEDULE (andl 0x7FFFFFFF @ 0x7B29E); lastSamples zeroed;
  EXCEPT SDF_ENCODED sounds: skip path jumps PAST the advance -> muted decoder sound never
  advances/finishes. => shadow-buffer mute-via-SetVolume(0,0) viable for in-memory WAVs;
  decoder sounds must stay in software mix (beta did the same per findings/04).
  Also: delay check precedes volume check; _bMuted/SOF_PAUSED gates are in MixSounds outside
  MixSound -> shadow buffers must honor them separately.
- UpdateSounds (0x796F0) calls Update3DEffects (direct call 0x79BA0) + PrepareSound (0x79BF3)
  per object; Listen (0x7A4B0) = source verbatim; CopyMixerBuffer_dsound static @0x7A180
  confirms vtable Lock=0x2C, 3DBuffer SetPosition=0x4C on sl_pDSSourceLeft/Right.
- S3 citation check (explore agent, 20 claims): 17 exact, 3 corrected in findings/06
  (FileSystem() at SeriousSam.cpp:631; BuildCheck = Core.cpp:99-148; zero-hits caveat re
  Localization\ExtractionTool\Engine.dll export-table strings). CreatePatch/HFuncPatch
  definitions confirmed NOT on disk (empty API submodule) as draft caveats.
- findings/05-steam-hook-surface.md written (S1+S2). Stage B complete.

## Session 3b — Final stage (consolidation)

- findings/99-summary-and-open-questions.md written: 21-entry parameter sheet
  (all beta params VERIFIED except volumetric angle const), beta<->Steam function
  mapping, shadow-buffer verdict = VIABLE with 2 conditions (A: never mute decoder
  sounds - they hang SOF_PLAY; B: shadow buffers must honor _bMuted/SOF_PAUSED/
  game-pause gates that live outside MixSound), 7 ranked unknowns.
- New last open engineering item found while writing: Steam CSoundLibrary DS-pointer
  field offsets (sl_pDS/primary/mix) not yet mapped - must read Steam StartUp_dsound
  before the patch can grab the IDirectSound* for DuplicateSoundBuffer.
- All stages complete: 00 (orientation), 01-04 (beta), 05 (steam S1/S2),
  06 (S3, citation-checked). Analysis phase done per AGENTS.md scope.

## Session 4 — StartUp_dsound (open item from 99 closed)

- Located steam StartUp_dsound: static @ RVA 0x78840, anchored via "dsound.dll"/
  "DirectSoundCreate" strings (VA 0x602a4250/0x602a4294). Raw slice (slicefunc's blank-line
  heuristic cut early -> switched to address-range filter): scratch/steam-startup-region2.txt.
- Full CSoundLibrary DS-pointer map derived (05 §1.1a), matches 1.10 SoundLibrary.h field
  order + SoundLibrary.cpp:427-534 exactly: _hInstDS@RVA 0x2097E4, sl_pDS@+0x34,
  sl_pKSProperty@+0x38, primary@+0x3C, secondary/2@+0x40/+0x44 (EAX mono pair),
  listener@+0x48, sourceLeft/Right 3D ifaces@+0x4C/+0x50, bUsingEAX@+0x1C (set after
  QuerySupport ENVIRONMENT(0xB)+ENVIRONMENTSIZE(0xC) SUPPORT_SET check), EsfFormat@+0x60,
  SwfeFormat@+0x64, mixer buf/size@+0x78/+0x80.
- Also corrected earlier 05 §1.1 note: +0x1C is sl_bUsingEAX (not waveOut).
- Key design consequence recorded: steam listener = rolloff 1.0 DEFERRED, NO doppler
  (log-corroborated) — the DS3D mode must apply the BETA listener params (rolloff 0,
  doppler 1.1) itself; the engine's SetFormat re-init will revert them, so the patch
  must re-apply after every SetFormat (window change/update-sound re-init path).
- 99-summary open engineering item marked RESOLVED.

## Session 5 — correction pass (user-noted)

- 4 user notes verified independently before editing (all confirmed):
  1. 05 §1.1 typo 0x38DFB -> 0x78DFB (StartUp_dsound sets sl_bUsingEAX@+0x1C) - fixed.
  2. 99 §5 stale "not yet mapped" HYPOTHESIS bullet - resolution folded into the bullet
     itself (05 §1.1a reference), duplicate bottom note removed.
  3. 02 §2 accumulator mask 0x58 comment said "SURROUND|LOCAL|MUSIC" - wrong naming:
     Ghidra sound-analysis.txt:7752 confirms flags&0x58 == 0 check; 0x58=0x08|0x10|0x40 =
     SOF_LOCAL|MUSIC|SOF_2D (beta names, 01 §4; no SURROUND bit in beta - 1.10 leftover).
     Same mislabel also found in 03 §5 - both fixed.
  4. KsPropertySet QI accounting (208 vs 206 SetMode(HEADRELATIVE)) resolved from raw
     log: 208 = 206 3D-commit QIs + 2 startup probes (log lines 75 + 2002, one per
     device generation). Residual stated as minor/[LIKELY]: SetMode total 227 vs 228
     duplicates (one unpaired commit); 3DBuffer QI 229 = 228 + 1 probe (second-gen
     probe QI'd KSP only). Notes added to 00 §4.4, 01 §2 table, 04 §3 + §8.
- Files touched: findings 00, 01, 02, 03, 04, 05 (typo only), 99. No analysis conclusions
  changed; all edits are documentation corrections/clarifications.

## Session 6 — Phase 2, Task 0 (API submodule)

- API repo confirmed populated at project root `E:\OpenCode\SeriousSamEngine\API`
  (SamClassicPatch/API, main @ 8362c52). Note: the registered submodule dir
  `SuperProject\API` is still EMPTY — must be populated for building (`Core.h:24`
  resolves `<API/include/classicspatch_api.h>` against SolutionDir).
- Recorded in 06 §10.1: `CreatePatch` is a template taking the function-pointer variable
  by reference (functionpatches.h:70-76) → `CreateOpcodePatch(void*, long, const char*)`
  (L61) → Core side IPatches.cpp:89-123 writes the trampoline back into the caller's
  variable. `HFuncPatch` = `FuncPatch_t*` (L32). `FuncPatch_ForceRewrite(int)` escape
  hatch (L39-50, IPatches.cpp:85-87). All PATCH_API = extern "C" __cdecl.
- Recorded in 06 §10.2: CLASSICSPATCH_* macros — INTERFACE_VERSION 004; Setup/Init/
  Shutdown/Pre-/PostInitPatches (classicspatch_api.h:63-97, once-per-category);
  DEFINE_PLUGIN / PLUGIN_STARTUP(props, events) / PLUGIN_SHUTDOWN (iplugins.h:78-99);
  extension macros (iextensions.h:265-318).
- SE1_VER numeric values: NOT in API repo; they live in Includes (SE1-ModSDK, branch
  `includes`) as MSBuild props — fetched from upstream and recorded in 06 §10.4:
  SE1_105=105, SE1_107=107, SE1_110=110, SE1_150=150; SS_TFE='F', SS_TSE='S', SS_REV='R';
  TSE107 config → SE1_VER=107, SE1_GAME='S'. Feature gating for DS3D = `#if SE1_VER == SE1_107`
  (NOT CHOOSE_FOR_ENGINE, which groups <=107).
- Trampoline pattern (06 §10.3): confirmed for Play_internal/Stop_internal/UpdateSounds/
  SetFormat — all four exported in TSE107 Engine.def (L2167/2817/2951/2646), declared
  non-virtual in 1.10 headers (SoundObject.h:104-105, SoundLibrary.h:130/135), so static
  PMFs hold concrete addresses; recipe = file-static PMF var + CreatePatch + (this->*var)
  per CControlsPatch::P_Load precedent (IGame.cpp:60-75,131-132). Variable must have
  static storage duration for trampoline calls.
- CreatePatch after CorePatches() init (06 §10.5): YES — CreateOpcodePatch has no
  lifecycle gating; plugins already patch engine functions during ClassicsPatch_Init
  (CecilExtensions.cpp:103) which runs BEFORE CorePatches() (line 109). DS3D mode doesn't
  need it (hooks install at CorePatches() time; cvar toggles behavior, not hooks).
- Files touched: findings 06 (caveat update + new §10 + open questions 1-2 resolved),
  99 (§4 #7 resolved + resolved-list entry), WORKLOG. Task 0 complete; Task 2 design
  unblocked. Task 1 (07-implementation-notes.md) not started.

## Session 7 — Phase 2, Tasks 1+2 (G1–G10 + design)

- API submodule verified populated at SuperProject\API (same commit 8362c52).
- **DESIGN-FORCING CORRECTION (G7)**: the Steam zero-volume skip path clears SOF_PLAY
  for non-looping sounds after ONE mix block — instruction-verified (0x6013b1e0 je →
  0x6013b29e, no end-of-buffer check; = SoundMixer.cpp:637-649). Phase-1 verdict
  "finishes on schedule" was wrong for non-looping sounds. 05 §2.2/§2.3 and 99 §3/§5
  corrected with notes. The addendum's zero-volume mute plan would have killed every
  one-shot 3D sound → corrected mechanism: intercept static MixSound (RVA 0x7AF80,
  single call site 0x6013a02c in MixSounds) so shadowed objects are never mixed,
  advanced or finished in software (exact beta model, 04 §6). NO engine-state poisoning
  at all (spNew/sp keep real values). Deviation documented per addendum §1 (07 §7.4).
- G7 write map completed: per-frame spNew→sp copy = UpdateSounds SoundLibrary.cpp:1060
  (unconditional while SOF_PLAY); Update3DEffects writes spNew only; PrepareSound is
  once-per-play (SOF_PREPARE) and master-scales so_fLast*Volume; MixSound applies
  master to so_sp volumes per block (L616-622).
- G1: Read_t downsamples only (min(fileRate, mixerRate)), bits forced 16, +8 pad;
  ClearBuffer (exported) is the single template-cache invalidation point (Reload =
  CSerial::Reload via SetFormat L974).
- G2: SndPostFunc (post: tag, L771-774) → SetFormat on snd_iInterface/format/device/
  mixAhead change → full re-init; gate must test sl_pDSListener != NULL and re-check
  after every SetFormat.
- G3: engine commits = StartUp + rare EAX-panning path only (L1030-1043); wrapper's
  per-frame commit safe.
- G4: SetOffset is a NO-OP (dead code after early return, SoundObject.cpp:329) —
  desync risk void; drift dissolved under corrected mechanism (DS buffer = playback
  authority, GetStatus finish like beta); mid-play cases enumerated (re-play resets
  offsets, Copy/operator= route through public Play, Read_t SOF_LOADED restores,
  Pause/Resume are bare flag flips).
- G5: ear pair at distance == MinDistance 1.0, zero velocity → rolloff/doppler factor
  changes no-ops [LIKELY; log/listening check pending].
- G6: SetFormat fully locked (tm_csHooks + sl_csSound; OPTEX recursive,
  Synchronization.cpp:86-89); watchdog call direct at 0x60139734 (pre-lock).
- G8: UpdateSounds lock verified at 0x60139765 (CTSingleLock ctor call); full lock map
  + shadow-field/thread model recorded.
- G9: failure rules defined (HRESULT → drop; BUFFERLOST → Restore once; not-playing
  anomaly 2 frames; drop procedure writes engine offsets from DS position +
  so_fDelayed sentinel → seamless software resume).
- G10: snd_bLinearVolume ABSENT from Steam binary (byte-grep) → linear curve
  hardcoded; master volume points identified; beta volume formula mapped to Steam
  inputs (sli_fVolume × sp3_fMaxVolume, w², master per frame); snd_iEmulationType /
  snd_iMaxVoices / snd_iMaxSameSounds / snd_bUseEnvironmentFX all absent → patch
  declares them; snd_bDS3DSpatial name free.
- Extra: ~CSoundObject inlines Stop_internal (dtor hook needed, def L384, verified
  0x6013e150); CSoundObject::Read_t/Write_t have no callers in TSE tree (savegame
  leak moot); Mute() live callers in Gfx/Network, body zeroes mix buffers — hook
  added to design (DS keeps playing during muted windows).
- findings/07-implementation-notes.md written (G1–G10 + §12 extra facts + §13
  consequences). findings/08-design.md written (design for approval): 9-hook set
  (Play_internal, Stop_internal, dtor, Update3DEffects, UpdateSounds, SetFormat,
  Mute, ClearBuffer, static MixSound), beta-order per-frame driver, gates/toggle/
  failure policy, threading model, acceptance mapping, Task 3 order adjusted for
  the corrected mechanism (MixSound-skip activated at step 3).
- Stopped per addendum §4: design awaiting user approval before Task 3.

## Session 8 — 2026-10-14 — 08 design review amendments (user-approved)

User reviewed 07/08 and approved the design with changes; all applied to 08/07 this session.

- **Offline prologue check executed** (user change 2, done before Task 3): faithful
  simulation of CPatch::CanRewriteInstructionSet (patcher.cpp:28-224) over the actual
  bytes of all 9 hook targets in SS_TSE_Steam_Bin Engine.dll (read-only; byte dumps via
  python + manual PE parse).
  - 8/9 decode OK (rewriteLens: 5/5/5/9/5/5/6/6).
  - **Stop_internal 0x7E810 FAILS**: prologue 56 8b f1 57 8b 4e 10 — decoder has no
    pattern for 8b 4e (mov ecx,[esi+d8]) at +4. P_Stop_internal must use
    FuncPatch_ForceRewrite(7) (1+2+1+3 = instruction boundary, fits the
    VirtualProtect(...,10) window). Patch-creation failure is fatal at startup
    (IPatches.cpp:102), so this would have crashed release builds on registration.
  - MSVC6 SEH prologue (55 8b ec 6a ff 68 .. .. .. 60 64 a1 ..) decodes FINE (5 bytes,
    instruction-complete) — the predicted dtor problem did not materialize.
  - **Two wrong RVAs found in the 08 draft** (doc-only; hooks resolve by name): dtor
    0x72E50 -> 0x7E150 (07 12.1 VA 0x6013e150 was right); SetFormat 0x78180 -> 0x784A0
    (export dump steam-Engine.txt:2644; 0x78180 lands mid-instruction).
  - MixSound raw-address hook (0x7AF80, prologue 55 8b ec 83 ec 20) decodes OK (6), but
    the patch must byte-compare 55 8b ec 83 ec + verify module identity before patching
    and refuse the mode on mismatch (never patch blind).
- **Finish detection re-specified** (user change 1): cursor-based finish
  (!playing && position-at-end) is unreliable — DS/DSOAL cursor behavior after a
  natural non-looping stop is undocumented; a cursor reset to 0 would replay every
  one-shot in software. Replaced by the pure beta rule: bStarted && not-playing &&
  !SOF_LOOP && no gates -> finished. Failures = HRESULT errors, DSBSTATUS_BUFFERLOST
  (Restore once), DSBSTATUS_TERMINATED. G9 rule 4 (2-frame anomaly) deleted; a sanity
  counter was considered and rejected. 08 4 step 8 + 0 D6, 07 G9 item 4 updated.
- **Driver relocated** (user change 3, adopted): P_Update3DEffects becomes store-only
  (1.10 math + spatial values into DS3DShadow, no COM); the P_UpdateSounds tail sorts
  the shadow table by fLastVolume (beta PlayBuffers per-frame sort, 04 3/4 — required
  for voice stealing) and performs all DS calls in beta order + one commit.
  08 3/4 + 0 D5, 07 13 item 7.
- **Play_internal callers verified** (user change 4): exactly one call site in the
  entire Steam engine disassembly — 0x6013e4d1 inside Play
  (steam-engine-disasm.txt:187561) — first-block registration proof holds (registration
  happens under Play's sl_csSound).
- Tooling note: PowerShell here-strings strip literal backticks and Python backslash-x
  takes exactly 2 hex digits — byte-precise python replacements (x60/u2192/u2014) are
  the reliable way to edit these unicode-dense findings files.

## Session 9 — 2026-10-15 — second user review: offset sync (A) + dangling psdData (B)

Both items verified against source/binary before applying; both were real.

- **A (offset sync, real bug)**: under the MixSound-bypass the engine offsets of a
  shadowed object are frozen at play start, but 07 G4c/G6/G7-companion and 08 still
  recommitted SOF_PAUSED / steal victims / SetFormat survivors at bytes(so_fLeftOffset)
  — i.e. restart from 0. The beta resumes from its elapsed timer (04 5), so the old
  'better than the beta' claim was wrong. Fix: ReleaseKeepingPosition() helper
  (bStarted-guarded GetPosition -> so_fLeft/RightOffset + so_fDelayed sentinel, then
  force-release) applied at: SOF_PAUSED release, voice steal, SetFormat pre-release,
  ClearBuffer forced drop, G9 drop. No sync for buffer-kept parks (game-pause/Mute),
  !bStarted (would cancel delay), or destruction. Rejected: per-frame cursor mirroring
  (breaks acceptance call order); mixer-rate offset conversion across SetFormat
  (stock-parity imprecision kept). Applied: 07 G4(d) new subsection, G4c rows, G6
  wrapper+tail, G7 companion, G9.5, 13 item 11; 08 3 (P_SetFormat/P_ClearBuffer rows),
  4 steps 1/2, 6 (drop bullet + new sync bullet), 8, 11 step 4.
- **B (dangling psdData)**: CSoundData objects are freed at FreeUnusedStock
  (Network.cpp:643, called at level/session transitions 1079/1187/1277/1339/1744/2387);
  ~CSoundData->Clear->ClearBuffer (SoundData.cpp:91-106) goes through our hook, but the
  driver must not rely on it. Changes: shadow caches iRate/iChannels/iBytesPerFrame at
  commit; psdKey is an opaque map key only, never dereferenced after commit (SetFrequency
  and offset conversion use the cached copies); re-play with different data updates
  key+fields; template-cache entries validated on lookup by (sd_pswBuffer ptr, byte size,
  rate, channels) with rebuild on mismatch (address-reuse guard); orphan list documented
  as buffers-only. DSOAL assumption to runtime-test: a duplicate keeps playing after its
  template is Released (shared memory; DS documents it, DSOAL unverified). Applied:
  07 13 items 12-13; 08 4 step 6, 6, 8, 11 step 6.
- Runtime tests added (08 11): pause/resume mid-play of a long one-shot (restart from 0
  would expose a missing sync); orphan playing out while its data's ClearBuffer runs
  under DSOAL.

## Session 10 — 2026-10-15 — third user review: SetFormat recreate, release primitives, delay counter, guards (Task-3 design final)

Five design changes approved and applied; my two proposed fixes for the review's
finish-authority hole were both rejected in favor of a third (bBypass fallback).

- **Recreate after SetFormat** (reverses the 2026-10-15 "not recreated" wording in
  G6): still-playing shadows recommit at synced offsets in the next P_UpdateSounds
  tail; one silent frame per sound accepted (entry bypassed, no buffer). Rationale:
  ambient loops never re-enter Play_internal (and SetFormat also fires from the
  UpdateSounds window watchdog); snd_iEmulationType toggle now observable on running
  sounds (99 #6 mechanism in place). 07 G6 + §13 item 15; 08 §3 P_SetFormat row,
  §11 step 6 (+ new toggle runtime test).
- **Release primitive split**: ReleaseForRecommit (sync via ReleaseKeepingPosition
  body + release + bStarted=false + bSpatialValid=false + keep entry; sites: SOF_PAUSED,
  steal, SetFormat pre-release, ClearBuffer owner-alive) vs DropToSoftware (sync +
  release + remove entry; sites: G9, forced mode disable, listener loss — the ONLY
  mass drop; cvar-off keeps drain semantics). Plain-release sites unchanged
  (stop/orphan, dtor, finish, !SOF_PLAY validation). bStarted=false routes the
  recommit through the bSpatialValid guard. 07 G4c/G4d/G6/G7 companion/G9.5/§13
  item 14 + item 11 rewording; 08 §3 rows, §4 step 1, §6.
- **Delay counter = engine field so_fDelayed**: tail advances it for bDelayPending,
  bBypass=true shadows only (no double-advance with the stock mixer, which consumes
  fallback entries' delay itself); target = so_sp.sp_fDelay (SoundMixer.cpp:595);
  sentinel interplay (started: 9999.9999 survives bStarted=false; pending: partial
  survives re-init); finish path sets so_fDelayed=0 (mixer parity). 07 §13 item 16.
- **bSpatialValid play-latency guard**: initial FALSE, set by the P_Update3DEffects
  store; commit may proceed, Play waits (≤1 frame start latency); stored fields init
  to parked; play-while-parked rejected (clips one-shot attacks). 07 §13 item 18.
- **bBypass software fallback for uncommitted entries** — fixes the finish-authority
  hole (a registered-but-never-committed entry is bypassed by P_MixSound, so nothing
  clears its SOF_PLAY: silent zombie with IsPlaying() true; beta had per-object
  timers instead). My virtual-advancement (reimplements the stock skip path) and
  DropToSoftware-on-overflow (permanently de-spatializes loops that lose a transient
  budget race) both rejected; chosen: bBypass true at registration (first-block
  proof intact) and after ReleaseForRecommit (pause incl.), false only on tail
  commit denial (voice budget, steal victim); stock mixer plays/advances/finishes
  fallback entries; tail retries commits, back at bytes(live so_fLeftOffset).
  DEVIATION from 99 #15 (audible fallback vs beta silence) recorded in 07 §13
  item 19 first, then 08 §0 D7/§4 step 2/§6 + 99 #15 note.
- **bGateStopped**: explicit flag set when the step-6 gate Stops a playing buffer;
  step 7 re-Play condition = buffer && !playing && !gated && !delayPending &&
  bSpatialValid && (!bStarted || bGateStopped); removes the spurious per-finish Play
  and covers non-looping mid-buffer resume. 07 §13 item 20; 08 §4 steps 6-7.
- **Issue B verified from disasm** (Play_internal 0x7E500-0x7E6B0): so_fDelayed IS
  reset by the original on every non-SOF_LOADED play — gate 6013e61e testl
  $0x20000000,%eax (arg2's SOF_LOADED bit) / jne 6013e694; 6013e62b xorl %eax,%eax;
  6013e635/63e/641/644 movl %eax -> 0x24/0x28/0x2c/0x14 (offsets + so_fDelayed);
  last L/R volumes init from so_sp L/R, master-scaled on the smooth-continue path
  (0x6013e665-e691: SOF_MUSIC -> snd_fMusicVolume@602a40fc else
  snd_fSoundVolume@602a40f8). => no P_Play_internal post-original reset (new
  07 §12.7; 08 §3 P_Play_internal row notes it).
- Files touched: findings 07 (G4c rows, G4d, G6, G7 companion, G8 field row, G9.5,
  §12.7, §13 items 11 reword + 14-20), 08 (§0 D7, §3 all rows, §4 preamble + steps
  1/2/3/6/7/8 + fallback note, §6, §7, §8, §11 steps 4/5/6), 99 (#15 deviation note,
  #6 mechanism note), WORKLOG.
- Next: Task 3 step 1 — cvars + empty shadow subsystem + all hooks installed, mode
  off; verify vanilla behavior unchanged (08 §11 step 1, acceptance row "Mode off").

## Session 11 — 2026-10-16 — beta-binary cross-check + design change D8

Documentation/design-amendment session; Task 3 still not started; no hook, RVA, or
threading decision changed.

- **All 6 beta-binary checks PASS** (read-only slices of `scratch/beta-engine-disasm.txt`):
  1. Pause path 0x82CEA-0x82D71: **no SetVolume(−10000)/SetFrequency(0)** — the sets
     are skipped when bShouldPause (`jne 0x10082d5c` at 0x10082c9a); beta flag
     0x10000000 (0x10082d64) + Stop (0x10082d71) only. The old 04 §4 "[mute path]" was
     wrong; the log's −10000 comes from the 0.005 silence gate alone.
  2. Silence gate on so+0x64 (post-budget) at 0x10082ad3 (const 0x101b95cc = 0.005);
     10.0 s release (const 0x101b95c8 = 10.0, non-forced, 0x10082b53-0x10082b6e);
     commit gate 0x10082b99-0x10082bbc; silent uncommitted entries → **no DS calls
     at all** (0x10082bc9 `jl`); finish rule 0x10082d78-0x10082dcf (flag test
     0x10082d8e, `elapsed > sd_tmLength` vs so_pCsdLink+0x30 double, Stop(1) at
     0x10082da7, flag cleared at 0x10082dcf).
  3. `SetCurrentPosition` at 0x10082BFB: **constant 0** argument; the
     GetElapsedTime(0) result is discarded (`fstp %st(0)` at 0x10082bf2) — the beta's
     recommit offset computation is dead.
  4. Update backstop 0x10087693-0x100876eb: `!paused && data && !decoder && !loop &&
     tmPlaying > sd_tmLength + 1.0` (const 0x101b8cd0) → clear SOF_PLAYING.
  5. snd_iMaxVoices default 30 (0x1020f80c); snd_iEmulationType: beta 0/1/2 with
     out-of-range remapped to 1 by a write-back at LoadWAV_t 0x1007f063, `post:`
     SetFormat trigger (Init 0x10081b80).
  6. SetMode/QI block sits inside the bMono branch (0x1008269d `je 0x1008271f`) —
     stereo duplicates never get SetMode.
  En route (PE .data reads via inline Python): 0x101b95bc = 0.333, 0x101b95c4 = 3000.0,
  0x101b95c8 = 10.0, 0x101b95cc = 0.005, 0x101b95c0 = −100.0, 0x101b8c68 = 0.5,
  0x101b8cd0 = 1.0; steal polarity (delta ≥ 0.333 → steal) re-confirmed; master
  factors at the Update head (mute → 0.0, attenuate && !0x40 → 0.5); DirectHF
  `Set` unconditional when the FX cvar is 0 (0x10082def skips only the computation).
  Analysis note: x86 PF is set for EVEN popcount — getting that backwards inverts the
  polarity of every `jp`-based float compare (the 0.333 steal and 0.005 silence gates
  both hinge on it).
- **Design change D8 applied** (user decision 2026-10-16; reason recorded in 07 §14.5
  before the 08 edit per the deviation rule): silent sounds are not committed —
  pre-budget silence test (deliberate deviation from the beta's post-budget test —
  budget-silenced sounds must stay committed or the software fallback defeats
  `snd_iMaxSameSounds`; flagged to the user); not-held+silent → no commit, no voice
  slot, no DS calls, `bBypass=false`; held+silent parked ≤ 10 s then
  `ReleaseForRecommit` + `bBypass=false`; silent→audible → commit at the live offset;
  silent entries never count toward `snd_iMaxVoices`; `DS3DShadow` gains
  `tmSilentSince`. The beta's own finish backstop recorded as the rejected
  alternative (07 §13 item 29).
- **Corrections applied** (07 §14.1): beta recommits always restart at 0 (07 G4c/G4d,
  99 #18, 04 §5 — our synced-offset release is an improvement, not parity); neutral
  labels for beta flag bits 0x40 / 0x10000000 / 0x40000000 (01 §4, 02 §2, 03 §5,
  04 §3); SetMode mono-only (00 §4.4, 04 §2/§3, 99 #7); pause-path correction
  (04 §4, 99 #20, 08 §4 step 6); DirectHF cvar-off note (03 §5, 99 #13); master-factor
  identification DAT_1022e9d8/d4 = menu mute/attenuate (03 §1).
- **99 §4 #1/#2**: volumetric blend formula and Fade() semantics are recorded as
  **HYPOTHESIS — not re-derived from the beta binary** (02 §3, 99 #2); menu-state
  factor values are beta-verified at 0x100875e6-0x1008761a.
- Files touched: 07 (§13 items 21-29, §14, G4c/G4d), 08 (§0 D8 row, §4 steps 2/3/6 +
  closing paragraph, §6 budget bullet, §8 struct, §10 parked row, §11 step 5), 99
  (#5/#7/#13/#15/#17/#18/#20, §4 #1/#2, resolved list), 00 §4.4, 01 §4, 02 §2/§3,
  03 §1/§5, 04 §2/§3/§4/§5/§7, WORKLOG.

## Session 12 — 2026-10-17 — Task 3 step 1: cvars + empty subsystem + all hooks installed (mode off)

- New SuperProject/Core/Patches/SoundDS3D.h/.cpp: 5 cvars (defaults 0/0/30/5/1; names
  absent from 1.10/Steam → no DeclareSymbol collision) + SoundDS3D_Init(); gate
  `_PATCHCONFIG_ENGINEPATCHES && SE1_VER == SE1_107 && defined(NDEBUG)` (invariant 2).
  SoundDS3D_CheckMixSound(): VirtualQuery AllocationBase==HMODULE_ENGINE + memcmp
  `55 8b ec 83 ec` at ADDR_ENGINE+0x7AF80 (invariant 3, 08 §3).
- 8 new hooks installed in ICorePatches::SoundLibrary() (SoundLibrary category now 10:
  Listen + Update3DEffects + 8): Play/Stop_internal, dtor, UpdateSounds, SetFormat,
  Mute, ClearBuffer, MixSound. Bodies pure passthrough → mode off = vanilla. Stop via
  FuncPatch_ForceRewrite(7); dtor via ClassicsCore_GetEngineSymbol("??1CSoundObject@@QAE@XZ");
  MixSound = free-fn raw-address patch (PDS_MixSound, wrapper `void MixSound(CSoundObject*)`,
  SoundLibrary.h:47), byte-compare gated. Trampolines = file-static PMFs in
  SoundLibrary.cpp (invariant 4), extern'd in header. VERIFIED sigs vs 1.10 source.
- Build: SamClassicPatch.sln /p:Configuration=Release_TSE107 /p:Platform=x86
  /p:PlatformToolset=v143 (vcxproj hardcodes stale v60). Only DS3D fixes: SoundDS3D.h/.cpp
  in Core.vcxproj; <Engine/Sound/SoundData.h> include; IChat.cpp <functional>;
  CSoundLibrary::SoundFormat qualification. ClassicsCore.dll clean; other projects'
  failures pre-existing (MFC/afxres, v143 strictness). Committed cf263cc.
- Next: user test run (vanilla unchanged, ListPatches shows the 10 sound patches, cvars
  visible with defaults) → Task 3 step 2.

### Session 12 addendum — user review pass: binary checks + step-1 fixes

- **MixSound calling convention VERIFIED from SS_TSE_Steam_Bin\Engine.dll** (capstone):
  prologue @0x6013af80 = `55 8b ec 83 ec 20` (6 bytes); call site @0x6013a02b =
  `push ecx; call 0x6013af80; add esp,4`; common epilogue @0x6013bbb9 = `mov esp,ebp;
  pop ebp; ret` (plain ret) → __cdecl confirmed, PDS_MixSound passthrough is stack-safe.
  `ADDR_ENGINE` (GameSpecific.h:58,64) = runtime `GetModuleHandleA("Engine.dll")` base,
  not the fixed 0x600C0000 (VirtualQuery check compares against the same HMODULE).
- Review fixes (commit 84f6cd3, pushed): (1) removed all UTF-8 `§` (C2 A7) from the 4
  touched files → ASCII `s` (no more C4819 / CJK newline-swallow risk); (2) added
  `_bDS3DHooksOk` (default TRUE, cleared on dtor-symbol / MixSound-check failure) — step 3
  gates registration on it; (3) widened MixSound byte-compare to the full 6 bytes
  `55 8b ec 83 ec 20`; (4) ForceRewrite(7)/CreatePatch adjacency comment.
- History (final): ds3d-spatial rebuilt linearly on current main (7ddbaf8), dropping the
  earlier GitHub `main` merge (user confirmed it touched nothing DS3D-relevant):
  f0aa0a2 IChat.cpp <functional> (own commit, item 4c) → a97c97c DS3D step 1 (cvars +
  hooks) → 49e2b57 step-1 review fixes. Tree byte-identical to the prior pushed 84f6cd3;
  force-with-lease pushed. Old cf263cc/4134561/1bb3b66/84f6cd3 now only in reflog.
- Core.vcxproj still has the edit-tool BOM-strip churn from the original step-1 commit
  (cosmetic, untouched).
- Rebuilt Core (ClassicsCore.dll) clean on both the merged and main-based trees.
  Next: user vanilla test run.

## Build reproducibility - build.ps1 + BUILD.md

- Added SuperProject/build.ps1 + BUILD.md (commit bdb023e on ds3d-spatial) - Core-only
  reproducible build; command MSBuild SamClassicPatch.sln /t:Core /nologo /m
  /p:Configuration=Release_TSE107 /p:Platform=x86 /p:PlatformToolset=v143.
- Toolchain: vswhere -> VS Community 2022 17.14.37806.7, MSBuild 17.14.60.43110.
  MFC (Microsoft.VisualStudio.Component.VC.ATLMFC) absent; not needed for Core-only
  (full solution still fails on afxres.h). Windows SDK 10.0.19041.0 present.
- API submodule was dirty (detached 8362c52); pinned to bff6141 via
  `git submodule update --init --recursive` (working tree was clean). All submodules populated.
- Baseline (no code changes): 0 warnings / 0 errors in 16.5s. ClassicsCore.dll SHA-256
  14FE6E6B1013FF6E5AA3439EFD572AB4B65E8793F3C957C8532B454BCA6CFC06 deployed to
  ...\testbed\Bin (junction -> D:\Spiele\SteamApps\common\Serious Sam Classic TSE). Game NOT run.
- Next: user runs vanilla test capturing DSOAL log; then Task 3 step 2.

## Core/exe mismatch diagnosis (no deploy)

- testbed set (Core 1F13A561 + exes, 2025-10-15 20:22) = SuperProject release tag 1.9.4
  (b7f2ff4, 2025-10-15 21:40 +0300); built with the legacy VC6 toolchain (imports MSVCP60.dll).
  SS_TSE_Steam_Bin\ClassicsCore.dll (2DCF8E08, 2025-06-22) = 1.9.3.
- Our fork HEAD = 1.9.4-252-gbdb023e (252 commits after the 1.9.4 tag), built v143
  (imports MSVCP140/VCRUNTIME140/UCRT). This is the mismatch.
- SeriousSam_Custom.exe imports 62 symbols from ClassicsCore.dll (15 C-linkage + 47 C++).
  All 15 C symbols present in ours. Only 4 C++ symbols missing in our Core:
  ?CorePatches@ICorePatches@@QAEXXZ (ours QAEHXZ), ?FileSystem@ICorePatches@@QAEXXZ (ours
  QAEHXZ), ?HttpRequest@@YA?AVCTString@@PBG00HP6AXV1@@Z@Z (ours PB_W - wchar_t ABI),
  ?LoadPlugins@CPluginAPI@@QAEXK@Z (ours UAEXK@Z - virtual). 1.9.4 Core satisfies all 62.
- HttpRequest source is present (Core/HttpRequests.cpp:96, LPCWSTR) - not compiled out;
  name differs only because v143 defaults /Zc:wchar_t (native) vs legacy wchar_t=unsigned short.
- Recommendation: (b) build+deploy a matched Core+exe set from the fork (one toolchain); a
  rebase to 1.9.4 alone still mixes a v143 Core with v60-built exes (shared C++ ABI).

## Task 3 prep: native v60 toolchain + build.ps1 (build still blocked)

- Env check per wiki 'Building': MSVC 6.0 SP6, VS2010 and Daffodil R2.6.6 are ALL absent
  (no DevStudio 6.0 reg key, no 'Microsoft Visual Studio 10.0', no v60 props under any
  MSBuild\Microsoft.Cpp). Present: VS2022 Community (v143) + VS2019 BuildTools (MSBuild core
  only). Native command is devenv.com / MSBuild 4.0 with no toolset override, but cannot run.
- Rewrote SuperProject\build.ps1: FULL solution, Release_TSE107|x86, MSBuild 4.0, project v60
  toolset (no override). Verifies VS2010+Daffodil, throws exact prereq list; build.log;
  per-project PASS/FAIL; deploy stages to ..\deploy\Bin and refuses any target resolving into
  steamapps\common (testbed is a junction there). Updated BUILD.md. Parses OK, fails cleanly.
- C++98 static scan: Core + Includes\Engine107 clean for v60 (no C++11 in SoundDS3D.*). C++11
  only as guarded shims: ISteam.h (_MSC_VER<1600), Entity.h `= delete` (_MSC_VER>1600),
  Types.h `long long` (PLATFORM_UNIX). No code changes needed yet.
- Next: install VC6+SP6 / VS2010 / Daffodil -> build.ps1 -> per-project report -> re-verify the
  4 Core imports (CorePatches/FileSystem return type, HttpRequest wchar_t, LoadPlugins virtual).

## First native (v60) full-solution build - PASS

- Toolchain installed: VC6 SP6 E:\...\Visual Studio\VC98 (cl 12.00.8804.0), VS2010
  E:\...\Microsoft Visual Studio 10.0, Daffodil v60 under C:\...\MSBuild\Microsoft.Cpp\v4.0.
  Verified build.ps1 discovery + import chain (VCTargetsPath -> v60 -> DevStudio ProductDir).
- `build.ps1 -Clean` full solution Release_TSE107|x86: PASS, 0 warnings / 0 errors, 74s.
  All expected Bin\Release_TSE107 outputs; ClassicsCore.dll SHA-256 FEFB54F106060DAA...
- ABI: new Core imports MSVCP60/MSVCRT (like shipped 1.9.4/1.9.3 Cores); new
  SeriousSam_Custom.exe imports 66 syms from Core, 0 missing; ?HttpRequest@@...PBG00... now
  matches legacy wchar_t mangling. llvm-readobj delay-import RVA warning also on reference
  Cores -> benign VC6 artifact.
- build.ps1 per-project parser shows only "(solution)": MSBuild 4.0 output is German
  ("Projekt ... auf Knoten"), parser is English-only. Fix pending. Binaries NOT deployed.

## Parser fix + testbed deploy (steam set replaced)

- Parser fixed (commit 7e509dc): locale-neutral summary - project list from .sln, error
  attribution by diagnostic source path, outputs from "X.vcxproj -> out" lines. Re-ran
  build.ps1 -Clean: 21 projects PASS, 1 skip (EntitiesTFE not in TSE107 config), 49s.
- Deployed the full matched set to testbed\Bin (Steam TSE via junction), done directly
  (build.ps1 -Deploy still refuses Steam targets): 18 files CHANGED, 0 added, 0 same,
  18/18 hash-verified after copy. Core 1F13A561... -> 08FEE0D3...; all exes/dlls/plugins
  replaced with v60-built ones from this tree; SDL3.dll updated from Extras\SDL.
- Game not run (user runs it with DSOAL logging next).

## Session 13 - 2026-10-18 - Task 3 step 1: user test run (mode off) PASSED

- Build: full v60 solution (build.ps1), matched Core+exe set deployed to testbed by the user. Custom cvars present in game (user-confirmed). ListPatches() shows 10 sound patches, all [ON]: Listen 79, Update3DEffects 80, Play_internal 81, Stop_internal 82, ~CSoundObject 83, UpdateSounds 84, SetFormat 85, Mute 86, ClearBuffer 87, MixSound 88 (screenshot, user).
- DSOAL log, EAX interface (dsoal_Steam_log_1.txt, 38,227 lines, 2 device generations): structurally identical to the stock Steam baseline (00 s5). Primary CTRL3D + 2 mono CTRL3D ear buffers (min/max 1.0/9.0) at (-1,0,0)/(1,0,0); listener rolloff 1.0 deferred, no doppler/velocity; CommitDeferredSettings x3; Lock/Unlock x930 pairs; BufferProp::Set x6 = EAX listener env/size only.
- Zero DuplicateSoundBuffer / SetMode / SetVelocity / SetVolume / SetFrequency / SetCurrentPosition / SetDopplerFactor. No err lines; only the known GetSpeakerConfig warn per generation. Clean shutdown. => 08 s10 row "Mode off = structurally stock log": PASS.
- Earlier log (dsoal_Steam_log.txt, 37,943 lines) was recorded on plain DirectSound (snd_iInterface != 2): generation 3 has a non-3D primary + a single stereo mix buffer, no listener. Same stock pattern for gens 1-2. Side result: P_SetFormat passthrough survived a re-init to an interface without sl_pDSListener (the G2 situation), no crash.
- Note: the mode needs snd_iInterface == 2 (EAX). Plain DirectSound has no listener, so the gate (08 s6) refuses it. Step 2 tests must run on EAX.
- Not verified from the logs (user-checked or pending): cvar defaults 0/0/30/5/1, normal sound/music behavior, level-change behavior.
- Next: step 2 (listener params, template cache, create/commit/release for one looping ambient, MixSound NOT skipping). Set "Current step: 2" in AGENTS.md.
## Session 14 - 2026-10-18 - Task 3 steps 2+3: shadow buffers + positional mode (built, pending user test)

- Step 2 (commit 1a7bd8e): beta listener params on first registration (99 #1, IMMEDIATE
  notice), per-CSoundData template cache (07 G1: validated/rebuild from live fields),
  lazy commit per shadow (Duplicate + QI 3D + QI Ks non-fatal + SetMode HEADRELATIVE +
  SetCurrentPosition at so_fLeftOffset bytes), Stop/dtor/ClearBuffer/SetFormat releases.
  MixSound passthrough, immediate commit for loops (double audio by design).
- Step 3 (commit 0bc709e): P_MixSound skips membership && bBypass (D1); P_Update3DEffects
  end stores the spatial snapshot (weighted listener walk, volumetric blend, 02 s2/s3,
  no COM); P_UpdateSounds tail: !SOF_PLAY drop, format refresh from so_pCsdLink (item
  17), so_fDelayed advance (item 16 - pulled forward: the skip removes the stock
  advance), lazy commit, driver steps 4-9 (DEFERRED z-negated pos/vel, GetStatus, 99
  #10 volume curve x snd_fSoundVolume, iRate x pitch, Play gated on bSpatialValid,
  finish rule, EAX DirectHF), ONE CommitDeferredSettings on the listener per frame.
- Interim until steps 4-6 (08 s11): no SOF_PAUSED/game-pause/Mute gates, no budget/steal,
  no bBypass software fallback (commit failure drops the entry + one notice), SetFormat
  drops all entries (no synced recommit).
- Build: full v60 solution PASS, 0 errors; ClassicsCore.dll 3F292440C4FC9D34... (12:48).
  Only Core changed since the step-1 deploy, so just ClassicsCore.dll needs replacing.
- Test must run on snd_iInterface == 2 (EAX) - plain DS has no listener (session 13 note).
  Expected DSOAL: DuplicateSoundBuffer + SetMode(1) + SetCurrentPosition per shadow;
  per-frame per-sound pos->vel->GetStatus->vol->freq->EAX, one commit/frame; listener
  0,0,0 (0,0,1)/(0,1,0) rolloff 0.0 doppler 1.1; ear pair unchanged; music/decoder software.

## Session 14b - 2026-10-18 - Steps 2+3 user runtime test: PASSED (headphones, EAX)

- User ran snd_bDS3DSpatial 1 on snd_iInterface 2 with headphones; positional audio as
  expected. Log dsoal_Steam_log.txt (166 MB); grep-only analysis.
- 223 DuplicateSoundBuffer == 223 SetMode(1,0) == 223 SetCurrentPosition; Buffer::Play
  225 / Stop 229 (releases). Listener: ours are the IMMEDIATE(0) calls - pos (0,0,0),
  orient (0,0,1)/(0,1,0), vel 0, rolloff 0.0, doppler 1.1 (doppler/velocity have no
  other caller). Ear pair unchanged ((-1,0,0)/(1,0,0) set once at init); 2 device
  generations, only the 2 known GetSpeakerConfig warns; err: = 0.
- Per-sound order verified in a mid-log window: SetPosition(1) -> SetVelocity(1) ->
  GetStatus -> SetVolume -> SetFrequency -> BufferProp::Set(DIRECTHF, 0x80000003);
  parked sentinel (0,0,-10000); real listener-space positions; volume curve values
  (-2413, -702); frequency 0 when pitch == 1.
- Commit cadence: 9370 = 3 stock at init + ours; gaps between consecutive commits
  cluster at ~233 lines (~32-shadow frame batch), 13-line gaps early (1 shadow/frame)
  => exactly one CommitDeferredSettings per driver frame. EAX20_BufferProperties =
  301259 ~= SetVolume count (playing-gated).
- 08 s10 acceptance rows for steps 2-3: PASS. Next: step 4 (gates, release primitives,
  failure policy; delay-advance + finish reset were pulled into step 3).

## Session 15 - 2026-10-18 - Step 4 implemented (commit e67240a, build PASS, test pending)

- Release primitives (07 s13 item 14): SyncPositionToEngine (bStarted-guarded
  GetCurrentPosition -> so_fLeft/RightOffset as samples + so_fDelayed sentinel),
  ReleaseForRecommit (sync + release, entry kept, bSpatialValid reset), DropToSoftware
  (sync + release + entry removed). Wired: SOF_PAUSED driver step 1 (skips delay
  advance too - stock mixer skips paused), G9 failures, listener-loss SetFormat post,
  ClearBuffer owner-alive.
- Gates: driver step 6 game-pause (stock MixSounds expression, _pNetwork IsPaused ||
  IsServer && GetLocalPause; _pNetwork==NULL -> not paused) -> Stop playing buffer +
  bGateStopped, volume/frequency sets skipped on gated frames (beta order); step 7
  Play gains !gated && (!bStarted || bGateStopped), clears bGateStopped; step 8
  finish adds !gated. P_Mute wrapper: original then DS3D_OnMute (GetStatus-playing
  check only, SetVolume(-10000)+Stop, buffers kept, bGateStopped; window itself is
  unreadable in the tail - original clears _bMuted at L996, 07 G7 companion).
- Failure policy (G9): creation failure -> DropToSoftware; runtime HRESULT on
  pos/vel/GetStatus/vol/freq/Play -> drop; BUFFERLOST -> Restore once (iFailFrames)
  then drop if still lost; TERMINATED -> drop; one console notice per cause/session.
- P_SetFormat: pre = templates freed + ReleaseForRecommit ALL (entries kept); post =
  listener -> re-apply beta params, else DropToSoftware all + disable notice. Guard
  _bDS3DReapplyAfterFormat (armed only if our params were applied) keeps cvar-off
  vanilla (plain DS listener==NULL would otherwise print/charge). P_ClearBuffer now
  walks shadows of the data: SOF_PLAY -> ReleaseForRecommit, else plain remove.
- Build PASS (v60, 0 errors); ClassicsCore.dll 3B31CC0AF1ADB38A... (13:52). Only Core
  changed since the last deploy -> replace ClassicsCore.dll only.
- NEXT: user runtime test (08 s11 step 4, EAX interface): pause/resume mid-play of a
  long one-shot (Esc menu pause + level Pause) - expect Buffer::Stop then Play with a
  nonzero SetCurrentPosition (not 0) after resume; no duplicate audio.

## Session 15b - 2026-10-18 - Step 4 user runtime test: pause/resume PASSED (EAX, headphones)

- Log dsoal_Steam_log.txt (25 MB, 345k lines, 2 device generations at startup = stock).
  0 err:; 93 DuplicateSoundBuffer == 93 SetMode(1) == 93 SetCurrentPosition (ALL value 0
  = initial commits only); 220 Play / 255 Stop; 2825 commits.
- 6 ESC pauses. Each pause: ONE Stop per playing shadow (gate Stop burst, e.g. 24 at
  87650) while parked; paused frames = SetPosition/SetVelocity/GetStatus with NO
  volume/frequency and no Play; resume = Play burst of the same buffers with NO
  SetCurrentPosition (correction to the 15-next guess: DS Stop preserves the cursor,
  so nothing reappears at 0 and no sync offset is needed). Stop/Play counts match per
  pause: 24/24, 24/24, 23+4 new/27, 26/26, 28/28; the 6th pause ended in quit.
- Per-buffer Play/Stop sequences strictly alternate (0 double-plays); the extra final
  Stop = release. Shutdown clean: engine Mute -> OnMute (31 GetStatus, none playing ->
  no-op), then dtor hooks release all 31 shadows, no err.
- Observed deviation: while the ESC menu is up the engine runs UpdateSounds TWICE per
  frame (menu and game chains - our drive-pass GetStatus local 0x19f364 vs 0x19f274
  in-game), so the tail commits twice per paused frame. Gated frames only, benign;
  in-game strictly one pass/commit per frame (session 14b cadence holds).
- NOT exercised: level-transition Mute window, P_SetFormat pre/post recommit (no device
  re-init mid-run - no mass Duplicate burst), listener-loss disable, G9 failures (none
  occurred). Step 4 gates/release primitives: PASS; recommend a level-transition test
  with the step-6 work. Next: step 5 (voice budget/steal, bBypass fallback, D8 silence).

## Session 16 - 2026-10-18 - Step 5 implementation written + loop-orphan decision (build next)

- SoundDS3D.cpp: added _lstOrphans (buffers+3D+KS only) with ReleaseOrphan/DetachToOrphan
  (GetStatus: not playing -> plain release, beta 0x82780) / ScanOrphans; wired into
  OnPlayPost (replay), OnStop, SetFormat-pre (mark generation), OnPlayPre (timer reset);
  tail fast path now also checks orphans.
- Driver tail step 5: D8 gate post-master/pre-budget (silent uncommitted -> bBypass=false,
  no DS calls; held+silent parked + game-tick/real-time silent-since timer, >10 s ->
  ReleaseForRecommit + bBypass=false); voice budget 4..64 + steal (lowest live, 0.333
  margin, commit-then-release, bBypass=true on success); beta sorted pass (vol desc, dist
  asc) via snapshot + qsort + revalidate; same-sounds budget map reset per tail, driven
  entries only (fVol>0.005), over-budget -> volume 0. DriveShadow now takes fVolEff.
- SoundLibrary.cpp: P_Stop_internal = original first, then DS3D_OnStop
  (07 §13 ordering).
- Found spec gap: looping buffer detached to the orphan list loops forever (Clear()/
  explicit Stop of ambients; GetStatus never stops -> no release; replay double-loop).
  User decision (07 §15): looping buffers are FORCE-RELEASED at detach (psh->bLooping
  check in DS3D_DetachToOrphan), non-looping keep non-forced play-out. 07 §13 item 14 /
  §13 item 2 (lifecycle) wording fixed to match; 08 §11 step 5 gained the looping-stop
  runtime test row (Stop+release in log, no continued GetStatus on that buffer).
- BUILD PASS (v60, 0 errors, 44.7 s); ClassicsCore.dll SHA-256
  67025A93B683286CD0571A0E70E8962333B755989A1222F3B55658659F4B2B30 (17:00).
  Next: commit step 5 to ds3d-spatial, then user runtime test (08 §11 step 5 rows:
  D8 out-of-range ambient + looping-stop via level clear), deploy ClassicsCore.dll only.

## Session 17 - 2026-10-18 - Step 5 runtime tests: D8 + looping-stop PASS (log2)

- Test 1 (dsoal_Steam_log.txt, 100119 lines): no D8 release. Water loop parked only ~819
  unpaused frames (~4.8 s at ~170 fps game clock; ESC windows froze the timer) - under the
  10.0 s threshold, expected; the re-test was needed.
- Test 2 (dsoal_Steam_log2.txt, 133493 lines): both 08 s11 step-5 runtime rows PASS.
- D8: water shadow 0x16e9b4d0 gen-2 commit 10339-10689 (synced offset 130828, Play loop);
  out of range from 47195 -> per-frame parked drive (SetPosition (0,0,-10000) sentinel,
  GetStatus 0xd, SetVolume -10000, SetFrequency 0) for 1703 unpaused frames; single
  ReleaseForRecommit at 70926-70931 (GetCurrentPosition sync pos 142526 -> Prop/3D Release
  -> Stop -> Release); ZERO DS calls on that buffer afterwards (later 0x16e9b4d0 mentions
  are the engine template reusing the freed address + app-exit cascade).
- Threshold confirmed at ~10.0 s of game tick (log1 ~4.8 s no release / log2 ~10 s release).
- Level clear/quit clean: ear buffers stopped, templates released at DllMain detach, no
  post-release shadow calls; CommitDeferredSettings only while shadows live (6168/13293).
- Step 5 verified PASS. Next: step 6 (SetFormat re-init robustness, snd_iEmulationType).

## Session 18 - 2026-10-18 - Step 6 code: snd_iEmulationType post: handler

- SoundDS3D.cpp: DS3D_EmulationTypeChanged(INDEX) (shell post: handler; grammar
  type-checks void(INDEX) but passes the variable ADDRESS - stock precedent
  SndPostFunc(void*), patch precedent ResetCameraInternal(INDEX)); declared as a
  function symbol in SoundDS3D_Init, then snd_iEmulationType post: it. Body: free
  templates under own sl_csSound scope, then call SetFormat(sl_EsfFormat) OUTSIDE the
  lock (stock tm_csHooks->sl_csSound order preserved) through the patched entry, so
  P_SetFormat pre frees orphans + ReleaseForRecommit all shadows (entries kept) and
  post re-applies listener params; next tail recommits at synced offsets with the new
  GUID (RECREATE - 08 s2/G6, 07 s12.4, item 15).
- DS3D_FreeTemplates() extracted (shared by P_SetFormat pre and the handler).
- SetFormat pre/post themselves unchanged from step 4 (spec-conform; no gaps found).
- BUILD PASS (v60, 0 errors, 50.9 s); ClassicsCore.dll SHA-256
  4920B2633FF2DA404C0C2A5BC3831935D09BF0A59B79B9D9550542EBF9BC72F7 (17:51).
  Commit 8c571a7 on ds3d-spatial. Next: user runtime test (08 s11 step 6: toggle
  snd_iEmulationType mid-play under DSOAL: device re-init, template rebuild with new
  GUID, re-duplicate + SetMode + SetCurrentPosition(nonzero) + Play, no restart;
  orphan-plays-past-template-release; mute-window + SetFormat recommit re-test).

## Session 19 - 2026-10-18 - Step 6 runtime test analysis: SetFormat/emulation toggle PASS

- User delivered 3 DSOAL logs; analyzed with findings/scripts/logstats.py (sister
  project) + ad hoc parsers in Temp. Mapping (user-confirmed): log1 =
  snd_iEmulationType toggle, log2 = quickload mid voice line, log3 = alt-tab in/out
  + video settings changes.
- log1 toggle 1 (L31202): pre-pass L31175-84 = 4 template Releases ref 0 + live-entry
  sync (GetCurrentPosition 67630) + ReleaseForRecommit; SetCooperativeLevel + old
  device Release ref 0 L31195-96; CreateDeviceShare; new template L31414 HRTF_LIGHT
  GUID; recommit L31426-34: dup -> SetMode(1,0) -> SetCurrentPosition(67630 = same
  cursor); no Play while console-paused (gated), Play @36616 after close. Toggle 2
  L97343-81 same flow, HRTF_FULL, cursor 37874; SetVolume ramp resumes ~L139195.
- log2 quickload mid voice line: the playing voice shadows were gate-stopped by the
  loading Mute first (OnMute L33011/33015 = GS 0xd -> SetVolume(-10000) -> Stop),
  then the engine unloaded them (force release L33021/33027); post-load voice lines
  start fresh (SetPos 0, L33774/34620). No orphan release needed (mute gate wins);
  no UAF. Engine buffers stopped clean at shutdown L41578-80.
- log3 alt-tab + video-settings: focus-loss mutes L22787/L89091 (OnMute -> release
  L22793 -> fresh play L22804 with 118040 preroll); device re-init by alt-tab/video
  change L89134: in-flight sound recommitted at synced offset 63506 (L89344-50)
  after ~12 s backgrounded (gated), Play(loop) L98161 from frozen cursor with
  volume/freq. Hold path L72823 gated Stop -> L73680 SOF_PAUSED synced release
  (GetCurrentPosition 50688, ref 0).
- bGateStopped -> re-Play path was covered by Session 15b (ESC pause/resume: Stop
  per playing shadow, resume Play burst with no SetCurrentPosition); orphan
  play-out now verified in Session 20. No adverse evidence in any capture.
- Step 6 verified PASS structurally (logs), no crash/poison. Steps 1-6 code
  complete; remaining: one positive orphan-play-out capture + user's audible
  confirmation, then final acceptance.

## Session 20 - 2026-10-18 - Orphan play-out runtime capture (weapon spam) PASS

- Run per user: dsoal_Steam_log.txt (20.4 MB, 282839 lines, 2 startup devices =
  stock, 50 DuplicateSoundBuffer), 10-20 s holding fire in a level, quit.
- Orphan play-out captured many times (one-shot re-play/stop mid-buffer, no level
  load / mute). Clean example 0xcdb87a0: driven normally to L35114-35120 (GS 0x9,
  SetVolume -702); detach while playing at ~35120 with NO Stop / no -10000 / no
  Release (re-play detach, forced-stop absent); then 183 sweep-only frames
  (GetStatus 0x19f250 each frame, no SetPosition/SetVolume/SetFrequency - life row
  vol=9 gs=194); natural end GS(0x8) at L46597 -> ReleaseOrphan Ks->3D->Stop->
  Buffer Release L46598-46601. Additional instances: 0xcdb9100 (L96191/123068/
  145603/216317), 0xcdb93d0 (L105024/237047), 0xcdb8f20 (L103196/123208), 0xcdb96a0
  (L138533/244179), 0xcdb8b60 (L82584) - all the same pattern.
- Forced (looping) case never confused with these: every orphan release is
  preceded by a sweep GS(0x8); no Stop+Release at detach time. No calls after any
  ref-0 Release; final quit cascade L276599-279098 + engine shutdown clean.
- Steps 1-6 fully runtime-verified now (6 = Session 19 toggles/alt-tab; 5 = S17
  D8 + this orphan capture; 4 = S15b pause). Remaining: user's audible confirmation,
  then final acceptance/close-out.

## Post-release tweak (2026-10-18) - snd_fDS3DGain post-curve gain offset

- User finding (EAX, verified by user): with snd_bDS3DSpatial=1, shadow-buffer sounds
  (weapons) are louder than software-mixed sounds (voicelines/music/decoder) and drown
  them out; not with cvar=0 or WaveOut; unaffected by snd_iEmulationType 1/2 (HRTF ruled
  out). Cause [HYPOTHESIS]: gain-staging mismatch shadow path vs software ear pair.
- Fix (deliberate beta-parity deviation, 99 #10 curve unchanged, recorded as 07 s16):
  new cvar snd_fDS3DGain (persistent user FLOAT, default -4.0 provisional, clamp -30..0),
  applied at 08 s4 step 6 ungated branch only, immediately after the curve:
  cB = clamp(cB + (LONG)ftol(gain*100), -10000, 0). v<=0.005 still yields exact -10000.
  Pre-curve scale rejected (would shift the D8 0.005 silence threshold and 99 #9 budget).
- Touched only SoundDS3D.h/.cpp (+ Init DeclareSymbol) + docs (08 s2/s4 step 6, 99 #10,
  07 s16). No hooks/gates/budgets/curve changed. Cvar name grep-verified absent from
  Steam Engine.dll and SuperProject.
- Verified: BUILD ONLY (build.ps1 PASS, errors 0). ClassicsCore.dll SHA-256
  F6470C53030CA229392276B8EE2CF8F25BD4900DFD9A6223C0BFB940133B0148.
- Next: user replaces ClassicsCore.dll only, sets snd_fDS3DGain in console (try -3/-6/-9),
  reports the balancing value; then bake that default and re-release. Commit 0a66245.

## Post-release tweak (2026-10-18) - snd_fDS3DGain default finalized to -6.0

- User confirmed the post-curve offset balances the mix at snd_fDS3DGain=-9; baked as the
  default (was -4.0 provisional). Code (SoundDS3D.h/.cpp) + docs (07 s16, 08 s2/s4 step 6)
  updated to -9.0. No other change: curve, gates, budgets untouched.
- Verified: BUILD ONLY (build.ps1 PASS, errors 0). ClassicsCore.dll SHA-256
  E0A0B7C62400F6E8F2AF04CF9BE36D4A516511FF77BAB00FA282218137925331. Commit 546a834.

- Release ds3d-spatial-beta asset replaced (same tag/name): rebuilt zip with the -9.0
  ClassicsCore.dll (and matching .map). Asset now 11067628 B, sha256 3f0cef39a16562ec21a74e182cf16ad5336fa06916abfff8aa259555a844596c; release notes
  updated to document snd_fDS3DGain. Branch pushed (546a834).

- Retune: user found -9 overshot; snd_fDS3DGain default set to -6.0 (code + docs 07 s16/08 s2/
  s4 step 6). Build PASS. ClassicsCore.dll sha256 6DFE0112E5A0F3E49320D447B340D27AD8D6EA270316FB5E1E570C397B3B4B8C. Commit 1b6353e pushed.
- Release ds3d-spatial-beta asset replaced again with the -6.0 build (and .map): 11067629 B,
  sha256 29fb2df96dec1ea6143be515aa7d8144c093fd25d3b7bcd94e7ffc89f0ec5499; notes updated to -6.0.
