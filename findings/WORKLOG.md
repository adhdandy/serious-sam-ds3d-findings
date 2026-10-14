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

- API repo confirmed populated at project root `PROJECT_ROOT\API`
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
