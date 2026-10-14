# S3 — SuperProject / XGizmo core patch mechanism (how existing engine hooks work)

All paths absolute. Line numbers verified against the working copy on 2026-10-13.
Confidence labels: VERIFIED (read in source on disk), LIKELY, UNVERIFIED.

Workspace caveat (important — updated Phase 2 Task 0, 2026-10-13): at Phase 1 time several git
submodules of `SuperProject` were **empty directories** in this checkout (`Includes` = SE1-ModSDK,
`API`, `Docs`, `Extras/XGizmo`, mod shell), so `SuperProject\API\include\classicspatch_api.h`
(included by `Core/Core.h:24`) could not be quoted. **The API repo is now populated** — as a clone
at the project root `PROJECT_ROOT\API` (`https://github.com/SamClassicPatch/API`,
branch `main` @ 8362c52, 19 files); all API definitions are now quoted and verified in §10 below.
Still empty on disk: `SuperProject\API` (the registered submodule location itself — populate with
`git submodule update --init API` before building, since `Core.h:24` resolves
`<API/include/classicspatch_api.h>` against `$(SolutionDir)` = SuperProject) and `SuperProject\Includes`
(SE1-ModSDK, branch `includes`), which holds the `SE1_VER`/`SE1_GAME` numeric definitions (§10.4;
values pulled from upstream and recorded). XGizmo sources were read from the sibling checkout
`PROJECT_ROOT\XGizmo` (same repo as the `Extras/XGizmo` submodule per `.gitmodules`).

---

## 1. Patch registration

### Sound patches are registered in `ICorePatches::SoundLibrary()`

`PROJECT_ROOT\SuperProject\Core\API\EnginePatches.cpp:391-401`:

```cpp
#include "Patches/SoundLibrary.h"

int ICorePatches::SoundLibrary(void) {
  void (CSoundLibrary::*pListen)(CSoundListener &) = &CSoundLibrary::Listen;
  CreatePatch(pListen, &CSoundLibPatch::P_Listen, "CSoundLibrary::Listen(...)");

  void (CSoundObject::*pUpdate3DEffects)(void) = &CSoundObject::Update3DEffects;
  CreatePatch(pUpdate3DEffects, &CSoundObjPatch::P_Update3DEffects, "CSoundObject::Update3DEffects()");

  return 0;
};
```

[VERIFIED] The pattern is always:
1. a local member-function-pointer variable is initialized with `&Class::Method`
   (the engine function's address, resolved through the linked import stub — see §4),
2. `CreatePatch(<that variable>, &PatchClass::P_Method, "<printable name>")` is called.

`CreatePatch` returns an `HFuncPatch` (assigned in e.g. `Core\API\IGame.cpp:132`). Its definition
lives in the missing API submodule header and could not be quoted — but see `CreateOpcodePatch`
in §3, which is the underlying registry entry point and shows the semantics: the **storage holding
the engine function address is overwritten with the trampoline address**, so the caller variable
becomes an "original function" pointer.

### Full list of engine functions currently patched (names, as passed to CreatePatch)

All in `EnginePatches.cpp` unless noted. [VERIFIED]

- **Entities** (90-184): `CEntity::ReadProperties_t`, `CEntity::SendEvent`, `CRationalEntity::Call`,
  `CPlayer::ReceiveItem` (via GetEntitiesSymbol), `CPlayer::RenderGameView` (via GetEntitiesSymbol),
  `CPlayer::GetModelForRendering` (via GetEntitiesSymbol), `CWorldBase::GetForce`,
  `CMovingBrush::GetForce` (vtable slots of temp entities, guarded by `_PATCHCONFIG_ENTITY_FORCE`).
- **LogicTimers** (188-198): `CRationalEntity::SetTimerAfter`.
- **Network** (202-309): `CCommunicationInterface::EndWinsock` (only `#if _PATCHCONFIG_NEW_QUERY`),
  `Server_Init_t`, `Server_Close`; `CMessageDispatcher::SendToServerReliable`, `ReceiveFromClient`,
  `ReceiveFromClientReliable`; `CNetworkLibrary::ChangeLevel_internal`, `Save_t`, `Load_t`,
  `StopGame`, `StartPeerToPeer_t`, `StartDemoPlay_t`, `StartDemoRec_t`, `StopDemoRec`;
  `CSessionState::FlushProcessedPredictions`, `Start_AtClient_t`, `WaitStream_t`,
  `ProcessGameStreamBlock`, `Stop`, `Read_t`, `Write_t`, `MakeSynchronisationCheck`;
  `CPlayerEntity::Write_t`, `CPlayerEntity::ChecksumForSync` (both via GetEngineSymbol).
- **Rendering** (313-343): `::RenderView`, `::Particle_GetViewer`, `CPerspectiveProjection3D::Prepare`
  (via GetEngineSymbol), `CRenderer::RenderLensFlares` (via `StructPtr(ADDR_RENDERLENSFLARES)`).
- **Ska** (345-389): `RM_DoFogAndHaze`, `shaDoFogPass`, `shaEnd`, `shaSetLightColor`,
  `CModelInstance::Copy` — only `#if SE1_VER >= SE1_107 && defined(NDEBUG)`.
- **SoundLibrary** (391-401): `CSoundLibrary::Listen`, `CSoundObject::Update3DEffects` (see above).
- **Strings** (403-429): `::CPrintF`, `::CPutString`, `CTString::VPrintF`, `CTString::Undecorated`.
- **Textures** (431-456): `CTextureData::Create_t`, `CTextureData::Write_t` (via GetEngineSymbol),
  `ProcessScript_t`, `CreateTexture_t` (out and in variants).
- **Worlds** (458-478): `CWorld::Load_t`, `CWorld::LoadBrushes_t`, `CWorld::ReadInfo_t`,
  `CWorld::CreateEntity_t`.
- **UnpageStreams** (480-562): `CTStream::AllocateVirtualMemory`, `CTStream::FreeBuffer`,
  `CTFileStream::Create_t`, `Open_t`, `Close`; plus dummies replacing `CTStream::CommitPage`,
  `DecommitPage`, `ProtectPageFromWritting`, `CTFileStream::WritePageToFile`, `FileCommitPage`,
  `FileDecommitPage`, `CNetworkLibrary::FinishCRCGather`, `CSessionState::RememberCurrentLevel`,
  `FindRememberedLevel`, `RestoreOldLevel`, `ForgetOldLevels`.
- **FileSystem** (564-621): `CEntityClass::ObtainComponents_t`, `CEntityClass::Read_t` (via
  GetEngineSymbol), `CShader::Read_t` (SE1_VER >= 107, via GetEngineSymbol), `CTStream::GetLine_t`
  (via GetEngineSymbol, name differs per version), `CTStream::ReadDictionary_intenal_t`,
  `::InitStreams` (via `StructPtr(ADDR_INITSTREAMS)`), `::MakeDirList`, `::ExpandFilePath`.

### Initialization order

[VERIFIED]

- `ICorePatches::CorePatches()` (`EnginePatches.cpp:52-86`) calls, in order: `Strings()`,
  `Textures()`; then (game/server/editor) `Entities()`, `LogicTimers()`, `Network()`, `Worlds()`;
  then (game/editor) `Rendering()`, `Ska()`; then (game only) **`SoundLibrary()`**.
- Callers of `_EnginePatches.CorePatches()`:
  - `CustomGameClient\Cecil\CecilExtensions.cpp:101-109` — `ClassicsPatch_InitExt()`, called from
    `CustomGameClient\SeriousSam.cpp:665` **after** `SE_InitEngine(...)` (line 662).
  - `CustomDedicatedServer\DedicatedServer.cpp:129`.
  - `CustomMod\Game\Game.cpp:75`.
  - `CustomEngineGUI\Cecil\CecilExtensions.cpp:62`.
- Pre-engine patches: `CustomGameClient\SeriousSam.cpp:631` (inside `#if _PATCHCONFIG_ENGINEPATCHES`
  at 629-632) calls `_EnginePatches.FileSystem()` *before* window creation, i.e. before the
  engine is up. [Line number corrected in citation check, session 3.]
- Generic dispatch: `ClassicsPatch_PreInitPatches` / `ClassicsPatch_PostInitPatches`
  (`Core\Core.cpp:301-315`) → `ICorePatches::ApplyPreInit` / `ApplyPostInit`
  (`EnginePatches.cpp:628-664`) which string-dispatch on a category name via the
  `APPLY_PATCH(_FunctionName)` macro. Sound patches are post-init only.
- Cleanup: `ICorePatches::Cleanup()` is **empty** (`EnginePatches.cpp:623-626`); Core engine
  patches are never un-hooked at shutdown (they die with the process / `CoreFunctionPatch_t`
  destructors).

## 2. Replacement bodies

`Core\Patches\SoundLibrary.cpp` (whole file, 246 lines) — both bodies are inside
`#if _PATCHCONFIG_ENGINEPATCHES` (line 20); header `Core\Patches\SoundLibrary.h:23-35` declares
`class CSoundLibPatch : public CSoundLibrary` and `class CSoundObjPatch : public CSoundObject`
so the replacements get the engine classes' layout.

### P_Listen (SoundLibrary.cpp:22-33)

```cpp
void CSoundLibPatch::P_Listen(CSoundListener &sl)
{
  // Ignore sound listener
  if (_EnginePatches.GetNoListening()) return;

  // Original function code
  if (sl.sli_lnInActiveListeners.IsLinked()) {
    sl.sli_lnInActiveListeners.Remove();
  }

  sl_lhActiveListeners.AddTail(sl.sli_lnInActiveListeners);
};
```

[VERIFIED] `[Cecil]` addition: early-out when `_EnginePatches.GetNoListening()` (member set via
`ICorePatches::SetNoListening`, `Core\API\IPatches.h:82-83`). The rest is a verbatim copy of 1.10
`CSoundLibrary::Listen` (compare `Serious-Engine\Sources\Engine\Sound\SoundLibrary.cpp`). **It does
not call the original via trampoline** — full replacement.

### P_Update3DEffects (SoundLibrary.cpp:35-244)

[VERIFIED] A faithful line-by-line port of 1.10 `CSoundObject::Update3DEffects`
(`Serious-Engine\Sources\Engine\Sound\SoundObject.cpp:385` onward): same SOF_3D early-out, same
per-listener accumulation (`fTLVolume/fTRVolume/fTLFilter/fTRFilter/fTLDelay/fTRDelay/fTPitchShift`),
same falloff/hotspot distance factor, volumetric handling, Doppler pitch shift, ear distances,
LR/FB/UD filter factors, panning, final 2D parameter clamping and `SetVolume/SetFilter/SetDelay/
SetPitch/SetPhase` calls.

Differences vs 1.10 source (both `[Cecil]`, marked in comments):

1. **Cvar reads via `CSymbolPtr`** instead of engine externs (lines 40-47):
```cpp
static CSymbolPtr pfDopplerSoundSpeed("snd_fDopplerSoundSpeed");
static CSymbolPtr pfEarsDistance("snd_fEarsDistance");
static CSymbolPtr pfDelaySoundSpeed("snd_fDelaySoundSpeed");
static CSymbolPtr pfPanStrength("snd_fPanStrength");
static CSymbolPtr pfLRFilter("snd_fLRFilter");
...
```
`static` + constructor does `_pShell->GetSymbol(name, TRUE)` (`XGizmo\Objects\SymbolPtr.h:37-44`),
so values are looked up lazily once and read via `GetFloat()` at use sites (e.g. lines 126-127,
134-135, 158).

2. **Local-sound listener fix** (lines 77-84, comment `[Cecil] Fixed local sounds not being played
for predicted listeners`):
```cpp
if (so_slFlags & SOF_LOCAL) {
  if (sli.sli_penEntity == NULL) continue;
  if (so_penEntity != sli.sli_penEntity->GetPredictionTail()) continue;
}
```
1.10 (`SoundObject.cpp:430`) instead compares `so_penEntity != sli.sli_penEntity` directly.

3. Minor: volumetric branch also tests `so_psdcDecoder != NULL` (line 111) — 1.10's has the same
decoder check in its volumetric condition (`SoundObject.cpp`, `so_psdcDecoder != NULL`).

No trampoline call — `Update3DEffects` is also a **full replacement**. Trampoline-style "call the
original first" exists elsewhere, e.g. `CControlsPatch::P_Load` (`Core\API\IGame.cpp:63-75`):
```cpp
void CControlsPatch::P_Load(CTFileName fnFile) {
  // Proceed to the original function
  (this->*pLoadControls)(fnFile);
  ...
```
where `pLoadControls` is the variable CreatePatch overwrote with the trampoline address.

## 3. Trampoline mechanics — `XGizmo\Patcher\patcher.cpp` / `patcher.h` (`class CPatch`)

[VERIFIED — read from `PROJECT_ROOT\XGizmo\Patcher\patcher.cpp` (same repo as the
`SuperProject\Extras\XGizmo` submodule per `SuperProject\.gitmodules`)]

### HookFunction (patcher.cpp:226-314)

- Creates a private executable heap once (lines 228-233): `HeapCreate(0x00040000|HEAP_NO_SERIALIZE, 1MB, 0)`.
- `VirtualProtect(iFuncToHook, 10, PAGE_READWRITE)` on the target function bytes (line 248).
- `CanRewriteInstructionSet(iFuncToHook, iRewriteLen)` (lines 28-224) walks x86 instructions from
  the function start until **>= 5 bytes** have been consumed, using a hand-rolled opcode table
  (`0xE9 jmp DWORD` = 5; `push/mov r,/mov XX,[ebp+a]/lea/mov eax,DWORD/...` = 2-6 bytes each,
  lines 59-190). Special case: if the first byte is `0xE9` (an existing jmp DWORD), it records
  `m_iOldJump = 5 + iAddress + *(long*)(iAddress+1)` (line 63) — the real continuation target —
  and the trampoline then starts *at the jmp target* instead of copying the jmp.
- Builds the **trampoline** in the heap (lines 264-285):
  - copies the first `iRewriteLen` original bytes into `m_pPatchInstructionSet`,
  - appends `E9 <rel32>` jumping to `iFuncToHook + iRewriteLen` (or to `m_iOldJump` if the first
    instruction was a jmp — line 281: `long iJumpNew = m_iOldJump ? m_iOldJump : iFuncToHook + iRewriteLen;`),
  - makes it `PAGE_EXECUTE_READWRITE` (line 299),
  - **`*piNewCallAddress = (long)m_pPatchInstructionSet`** (line 267) — the caller's function
    pointer variable is rewritten to point at the trampoline; that's the "original function".
- Builds the **hook patch**: 5 bytes `{0xE9, rel32}` jumping to the hook function (lines 271,
  289), saved in `m_pRestorePatchSet`, and `SetPatch()` (lines 363-379) `memcpy`s those 5 bytes
  over the function start (after `VirtualProtect` RW).
  → **The hook is a `jmp rel32` written over the first >=5 bytes of the engine function.**

### HookClassFunctions (patcher.h:44-55)

```cpp
template<class FuncType1, class FuncType2> inline
void HookClassFunctions(FuncType1 &funcToHook, FuncType2 funcToCall, bool bPatchNow)
{
  // Get address of where to put the new call
  FuncType1 *pFuncOld = &funcToHook;
  long &iNewCallAddress = *reinterpret_cast<long *>(pFuncOld);
  // Get target address for the jump
  long iJumpAddress = *reinterpret_cast<long *>(&funcToCall);
  HookFunction(iNewCallAddress, iJumpAddress, &iNewCallAddress, bPatchNow);
};
```

I.e. it dereferences the *variable holding the engine function address* as both "function to hook"
and "place to store the trampoline address". The `CPatch` constructors (patcher.h:62-99,
`patcher_defines.h:114-153` for the 0..7-arg const/non-const member variants) do the same.

### RemovePatch (patcher.cpp:317-360)

- Restores the original bytes (`memcpy(iFuncToHook, m_pPatchInstructionSet, m_iRestoreSize)` —
  note it copies from the trampoline buffer, which holds the pristine original prologue), and if
  `m_iOldJump` was set, rewrites the `E9` at `iFuncToHook + m_iRestoreSize - 5` to jump to the old
  target (lines 336-339).
- `bForever` frees the heap block and backup (lines 350-359). `~CPatch()` calls
  `RemovePatch(true)` unless `m_bSetForever` (patcher.h:105-109).

### Registry wrapper (`Core\API\IPatches.cpp`)

`CoreFunctionPatch_t : FuncPatch_t` (lines 23-75) owns a `CPatch*`; `CreateOpcodePatch`
(lines 89-123) allocates `new CPatch(FALSE)` and calls `HookFunction` manually, registers the
patch in `static se1::map<ULONG, HFuncPatch> _mapFuncPatches` keyed by name hash (line 113), and
AddPatch'es it into `_pInitializingPlugin` if one is loading (lines 116-120). Failure is fatal in
release (`FatalError`, line 102). `DestroyPatch` (126-138) erases and deletes.

## 4. How engine function addresses are resolved

Two mechanisms, both [VERIFIED]:

### a) Linked import stubs (primary, used by Listen / Update3DEffects)

- Core includes engine headers (`#include <Engine/Engine.h>`, `Core\Core.h:20`) and links against
  the per-version **import library** `Engine.lib` produced from `Engine.def` — the libraries live in
  `PROJECT_ROOT\SE1-StaticLibrariesForGames\SeriousSam\<TFE105|TSE105|TSE107|...>`
  (each folder has `Engine.def`, `Engine.exports.txt`, `Engine.lib`; `TSE150` also exists).
  `Core\Core.h:80` has `#pragma comment(lib, "ClassicsCore.lib")` style linking; engine libs come
  via the `$(SamEngineLibraries)` / `$(SamEngineIncludes)` / `$(SamEnginePreproc)` macros defined in
  `..\Includes\Properties\TSE107.props` etc. (imported per configuration in
  `Core\Core.vcxproj:235-250`; include/lib paths at lines 274-335, `Properties\Common.props:7-13`).
  The `Includes` submodule (SE1-ModSDK) that contains those .props **is empty in this checkout** —
  exact macro values UNVERIFIED here.
- Taking `&CSoundLibrary::Listen` therefore yields the runtime-resolved address of the exported
  `?Listen@CSoundLibrary@@QAEXAAVCSoundListener@@@Z` in `Engine.dll` (through the import thunk).
  `HookClassFunctions` then rewrites the local pointer variable to the trampoline. Note the rewrite
  target is the *local variable*, so the local is only useful inside the registering function —
  Core sound patches discard it (no original call), while `IGame.cpp:131` keeps it in a static
  (`pLoadControls`) for trampoline calls.

### b) GetProcAddress fallback (for functions Core does NOT link)

`Core\API\ICore.cpp:250-266`:

```cpp
HMODULE ClassicsCore_GetEngineHandle(void) {
  static HMODULE _hEngine = HMODULE_ENGINE;
  return _hEngine;
};
void *ClassicsCore_GetEngineSymbol(const char *strSymbol) {
  return GetProcAddress(ClassicsCore_GetEngineHandle(), strSymbol);
};
void *ClassicsCore_GetEntitiesSymbol(const char *strSymbol) {
  return GetProcAddress(ClassicsCore_GetEntitiesHandle(), strSymbol);
};
```

with `HMODULE_ENGINE` = `GetModuleHandleA("Engine.dll")` (Debug: `"EngineD.dll"`) defined in
`Core\GameSpecific.h:57-61`, and `ClassicsCore_GetEntitiesHandle` = `LoadLibraryA` of the Entities
DLL (`ICore.cpp:255-258`). Used e.g. for `CPlayerEntity::Write_t`
(`EnginePatches.cpp:293-294`, raw mangled name string) and `CShader::Read_t` (589-590).
Raw-address fallbacks also exist: `ADDR_ENGINE + 0x...` constants in `GameSpecific.h:64-183` with
per-version offsets chosen by `CHOOSE_FOR_GAME`, e.g. `ADDR_RENDERLENSFLARES` (line 119) used via
`StructPtr` at `EnginePatches.cpp:329`.

**Implication for new hooks:** any function listed in `Engine.def` of the matching version can be
hooked exactly like `Listen`; anything not linked can be hooked by mangled-name `GetProcAddress`
or hardcoded RVA, exactly as `CPlayerEntity::Write_t` does.

## 5. Cvar / shell symbol declaration

[VERIFIED]

- Engine-side cvars are declared by the patch with `_pShell->DeclareSymbol`; full example
  `Core\API\EnginePatches.cpp:333-337` (inside `Rendering()`):
```cpp
_pShell->DeclareSymbol("persistent user INDEX sam_bAdjustForAspectRatio;", &_EnginePatches._bAdjustForAspectRatio);
_pShell->DeclareSymbol("persistent user INDEX sam_bUseVerticalFOV;",          &_EnginePatches._bUseVerticalFOV);
_pShell->DeclareSymbol("persistent user FLOAT sam_fCustomFOV;",              &_EnginePatches._fCustomFOV);
```
  Other instances: `EnginePatches.cpp:82, 301, 422-423, 474-475`; `ICore.cpp:325-340`.
- Existing (engine-declared) cvars are *read* through `CSymbolPtr`
  (`XGizmo\Objects\SymbolPtr.h:26-98`; usage `Patches\SoundLibrary.cpp:40-47`, values via
  `.GetFloat()` at 126-127 etc.).
- Plugin modules declare their own symbols via `CPluginSymbol`
  (`Extensions\ExtendedInput\Main.cpp:32,41`): `_psAxisPressThreshold.Register("inp_fAxisPressThreshold");`.
- All patches are exposed as console commands: `ListPatches()`, `EnablePatch(INDEX)`,
  `DisablePatch(INDEX)`, `GetFuncPatch(CTString)` — `Core\API\IPatches.cpp:244-250`
  (`IInitAPI::Patches()`, called from `ClassicsPatch_Init`, `Core\Core.cpp:243`).

## 6. Version gating

[VERIFIED as far as on-disk files go]

- `CHOOSE_FOR_ENGINE(_107, _150, _110)` and `CHOOSE_FOR_GAME(_TFE105, _TSE105, _TSE107)` are
  defined in `Core\GameSpecific.h:23-54`:
```cpp
#if SE1_VER <= SE1_107
  #define CHOOSE_FOR_ENGINE(_107, _150, _110) _107
#elif SE1_VER == SE1_150
  #define CHOOSE_FOR_ENGINE(_107, _150, _110) _150
#elif SE1_VER == SE1_110
  #define CHOOSE_FOR_ENGINE(_107, _150, _110) _110
#else
  #error Unsupported engine version!
#endif
```
  Games: `SE1_GAME` ∈ `SS_TFE`, `SS_TSE`, `SS_REV` (usages all over; e.g. `Core.h:27,33,55`;
  `ICore.cpp:282` prints `CHOOSE_FOR_GAME("TFE", "TSE", "TSE")`). Engine versions referenced:
  `SE1_105`, `SE1_107`, `SE1_110`, `SE1_150`. **The numeric definitions of SE1_VER/SE1_GAME live in
  the empty Includes/API submodules — values UNVERIFIED on disk.**
- Solution configurations: `Release_TFE105`, `Release_TSE105`, `Release_TSE107` (+`Release_SSR110`,
  `Release_TSE110` per the vcxproj PropertySheet imports `Core\Core.vcxproj:235-250`).
- Feature toggles: `Core\Config.h:70-106` (`_PATCHCONFIG_*`, with `_APCT_NREV`/`_APCT_N110`
  automatic-disable macros). Sound patches are gated only by `_PATCHCONFIG_ENGINEPATCHES`
  (`Config.h:94`) plus app-type checks in `CorePatches()` (game client only, `EnginePatches.cpp:76-78`).
- Divergence handling: `#error` in the CHOOSE macros (above); `BuildCheck()`
  (`Core\Core.cpp:~120-148`) fatal-errors on wrong patch build for game; unsupported-version paths
  in `GameSpecific.h` produce compile errors rather than silent fallbacks. Version-sensitive symbol
  names are chosen at runtime, e.g. `CTStream::GetLine_t` UAEX vs QAEX
  (`EnginePatches.cpp:594-598`).

## 7. Hookability of `Play_internal` / `Stop_internal`

- [VERIFIED] **No source reference** to `Play_internal` or `Stop_internal` exists anywhere in
  `SuperProject` today (grep over the tree: zero hits in code; the only match anywhere is the
  bundled binary `SuperProject\Localization\ExtractionTool\Engine.dll`, where the names appear
  in the PE export table — not a code reference). [Clarified in citation check, session 3.]
- [VERIFIED] Both are **exported by the engine import libraries**: `SE1-StaticLibrariesForGames\
SeriousSam\TSE107\Engine.def` contains `?Play_internal@CSoundObject@@QAEXPAVCSoundData@@J@Z` and
`?Stop_internal@CSoundObject@@QAEXXZ` (also `Play_t`, `Play`, `Stop`, `PrepareSound`,
`Set3DParameters`, `SetOffset`, `GetPredictionTail`, `_pSound`, etc.). The TSE105/TFE105 defs were
not diffed here (LIKELY same).
- Conclusion (LIKELY): hooking works **exactly like `Listen`** — declare
`void (CSoundObject::*pPlay)(CSoundData *, SLONG) = &CSoundObject::Play_internal;` and
`CreatePatch(...)` — *provided* the SE1-ModSDK `Engine/Sound/SoundObject.h` used by Core declares
them (the 1.10 header does, and Core compiles the class already, so LIKELY no header work needed).
No import-list maintenance is required beyond linking `Engine.lib`, which is already linked; if a
symbol were ever missing from the .def/import lib, the `ClassicsCore_GetEngineSymbol(mangled)`
route (§4b) works with zero build-system changes.

## 8. Plugin / API surface

[VERIFIED]

- Core engine patches are **hardcoded** in one place: `ICorePatches::ApplyPostInit`
  (`EnginePatches.cpp:642-664`) string-dispatches category names (`CorePatches`, `Entities`,
  ... `SoundLibrary`, ...) to private methods of the `_EnginePatches` singleton. Adding a new Core
  patch category means: new `Patches\Xxx.cpp/.h`, new method in `IPatches.h`, an `APPLY_PATCH` line
  in `ApplyPostInit`, and a call in `CorePatches()`.
- Loadable extension modules (DLLs in `Bin\Plugins\`, see `Builds\TSE107\Bin\Plugins`) use the
  plugin API: `CLASSICSPATCH_DEFINE_EXTENSION("PATCH_EXT_input", k_EPluginFlagEngine, ...)`,
  `CLASSICSPATCH_EXTENSION_SIGNALS_BEGIN`, and a module entry point
  `CLASSICSPATCH_PLUGIN_STARTUP(HIniConfig props, PluginEvents_t &events)` in which they may call
  the **same** `CreatePatch` (e.g. `Extensions\ExtendedInput\Main.cpp:21-46`). Definitions of these
  macros are in the missing API submodule (UNVERIFIED exact text).
- Plugins are loaded by Core at init: `GetPluginAPI()->LoadPlugins(k_EPluginFlagEngine)`
  (`Core\Core.cpp:255`) inside `ClassicsPatch_Init` (called from the exes after `SE_InitEngine`).
  Plugin classes: `Core\Modules\PluginModule.h/.cpp`, `PluginStock.h/.cpp`, API `Core\API\IPlugins.h`
  (`LoadPlugin_t`, `ObtainPlugin_t`, `AddPatch` — `IPlugins.cpp:258-397`).
- Because plugins run inside the ClassicsCore process with the same patcher, **a plugin can patch
  engine functions too** (ExtendedInput patches `CInput::*` which lives in Engine.dll). A later
  3D-audio mode could therefore ship as a plugin without touching Core — but it would still use the
  same registration helpers; there is no per-function dynamic registration API beyond
  `CreatePatch`/`CreateOpcodePatch` themselves.

## 9. Build / deploy / load

[VERIFIED]

- Core project: `SuperProject\Core\Core.vcxproj`, `<TargetName>ClassicsCore</TargetName>`
  (lines 280-335, per-config) → `ClassicsCore.dll`.
- Deployment: `SuperProject\DeployToBin - Release.bat` copies
  `Bin\Release_TSE107\ClassicsCore.dll`, `ClassicsExtras_Custom.dll`,
  `DedicatedServer_Custom.exe`, `SeriousSam_Custom.exe`, `SeriousEditor_Custom.exe`,
  `Shaders.dll`, `EngineGUI.dll`, `Entities_Custom.dll`, `Game_Custom.dll`, `GameGUI_Custom.dll`
  into the game's `Bin\` (per `Builds\README.txt`, original vanilla DLLs are replaced/packed).
- Loading: **SuperProject ships its own exes** — e.g. `SeriousSam_Custom.exe` built from
  `CustomGameClient\SeriousSam.cpp`, which orchestrates the patch manually:
  line 622 `ClassicsPatch_Setup(k_EClassicsPatchAppType_Game);`
  line 629 `_EnginePatches.FileSystem();`
  line 662 `SE_InitEngine(sam_strGameName);`
  line 665 `ClassicsPatch_InitExt();` → `_EnginePatches.CorePatches()` (incl. sound patches)
  line 844 `ClassicsPatch_Shutdown();`
  There is no runtime injection into the stock exes. `ClassicsPatch_Setup` (`Core\Core.cpp:150-160`)
  also runs `BuildCheck()` which compares `_SE_BUILD_MAJOR/_SE_BUILD_MINOR` against the loaded
  engine build (`Core\Core.cpp:99-148`, `FatalError` at 141-147) and `FatalError`s on mismatch.
  [Range corrected in citation check, session 3.]

---

## 10. API submodule verified (Phase 2, Task 0 — 2026-10-13)

Source: `PROJECT_ROOT\API` (clone of `https://github.com/SamClassicPatch/API`,
branch `main` @ 8362c52). `[VERIFIED]` = read on disk in that clone. Line numbers refer to files
under `API\include\`.

### 10.1 Function-patch API (`functionpatches.h`)

- `HFuncPatch` = `typedef FuncPatch_t *HFuncPatch;` (L32). `FuncPatch_t` interface (L12-29):
  `GetName()`, `GetHash()`, `IsPatched()`, `Enable()`, `Disable()`.
- Linkage: `PATCH_API` = `extern "C" __declspec(dllexport)` when `CORELIB_EXPORTS` is defined,
  else `__declspec(dllimport)` (`classicspatch_common.h:13-17`); `PATCH_CALLTYPE` = `__cdecl`
  (L19). So `CreateOpcodePatch` etc. are `extern "C" __cdecl` exports of `ClassicsCore.dll`.
- `PATCH_API void FuncPatch_SetDebug(bool)` (L37). `PATCH_API void FuncPatch_ForceRewrite(int nBytes)`
  (L39-50): documented escape hatch for when `CanRewriteInstructionSet` cannot decode a prologue —
  lets the patcher blindly replace `nBytes` bytes (the `E9 jmp rel32` is 5 bytes); resets after
  the next `CreateOpcodePatch`. Core side: `IPatches.cpp:85-87` (`CPatch::_iForceRewriteLen`).
- `PATCH_API HFuncPatch CreateOpcodePatch(void *pOpcodeToReplace, long iJumpDestinationAddress, const char *strIdentifier)` (L61).
- **`CreatePatch` — exact signature** (L70-76, template, not a macro):

```cpp
template<class FuncType1, class FuncType2> inline
HFuncPatch CreatePatch(FuncType1 &funcOld, FuncType2 funcNew, const char *strName) {
  void *pOpcodeAddress = reinterpret_cast<void *>(&funcOld);
  long iJumpAddress = *reinterpret_cast<long *>(&funcNew);

  return CreateOpcodePatch(pOpcodeAddress, iJumpAddress, strName);
};
```

  `funcOld` is taken **by reference**: the *variable* holding the engine function address is
  what gets passed. The Core-side `CreateOpcodePatch` (`IPatches.cpp:89-123`) casts it to
  `long*`, hooks the function at `*piNewCallAddress`, and writes the **trampoline address back
  into that same variable** (`IPatches.cpp:95-96` → XGizmo `HookFunction`, patcher.cpp:226-314,
  store at :267). Consequence: a caller that wants to invoke the original must keep the variable
  alive with **static storage duration** and call through it — exactly the `CControlsPatch::P_Load`
  precedent (`Core\API\IGame.cpp:60-75`, hook creation :131-132, trampoline call :65). The
  local-variable style used by the current `SoundLibrary()` registration
  (`EnginePatches.cpp:394-398`) is only usable for full replacements.
  Header comment L57-60: patches created inside a plugin's `CLASSICSPATCH_PLUGIN_STARTUP` are
  auto-added to that plugin's patch registry (Core side `IPatches.cpp:115-120`) — no manual
  `DestroyPatch` needed at plugin shutdown.
- `PATCH_API void DestroyPatch(HFuncPatch)` (L79) — erases from the registry and permanently
  restores bytes (`IPatches.cpp:126-138`); used by `P_Load` to un-hook after one shot
  (`IGame.cpp:72`).
- `PATCH_API HFuncPatch FuncPatch_FindByName(const char *)` (L82).
- Virtual wrapper `IClassicsFuncPatches` (L88-96) exposes the same operations for the
  `ClassicsPatchAPI()` interface.

### 10.2 API-level macros and lifecycle

- `classicspatch_api.h:32`: `#define CLASSICSPATCH_INTERFACE_VERSION 004`.
- Lifecycle exports (classicspatch_api.h:63-97): `ClassicsPatch_Setup(EClassicsPatchAppType)`
  (before `SE_InitEngine`), `ClassicsPatch_Init(void)` (after), `ClassicsPatch_Shutdown(void)`,
  `ClassicsPatch_PreInitPatches(const char *category)` (before engine init, after Setup),
  `ClassicsPatch_PostInitPatches(const char *category)` (after engine init AND after Init);
  each category may be applied **once**, undone only by full shutdown. `IClassicsPatchAPI`
  (L118-132) is the virtual interface aggregating `Chat/Config/GameplayExt/Core/Game/ModData/
  Plugins/FuncPatches/Packets/Extensions/INI`; also `ClassicsPatchAPI()`, `ClassicsPatchAPI_IsRunning()`,
  `ClassicsPatchAPI_Verify()` and the `ClassicsPatchGlobalFunctions` GetProcAddress helper
  (L138-185).
- Plugin module macros (`iplugins.h`): `MODULE_API` = `extern "C" __declspec(dllexport)` (L51);
  prototype/method/pointer macros (L54-66); `CLASSICSPATCH_DEFINE_PLUGIN(utility, version,
  author, name, description)` (L78-83); `CLASSICSPATCH_PLUGIN_STARTUP` (L90-91, expands to a
  method with signature `(HIniConfig props, PluginEvents_t &events)`); `CLASSICSPATCH_PLUGIN_SHUTDOWN`
  (L98-99, `(HIniConfig props)`).
- Extension macros (`iextensions.h:261-318`): `CLASSICSPATCH_DEFINE_EXTENSION(extension,
  utility, version, author, name, description)` (L265-271), `CLASSICSPATCH_DEFINE_EXTENSION_HANDLE`
  (L285-286), `EXTENSIONMODULE_LOCALHANDLE` (L277), `CLASSICSPATCH_EXTENSION_PROPS_BEGIN/END`
  (L304-305), `CLASSICSPATCH_EXTENSION_SIGNALS_BEGIN/END` (L317-318).

### 10.3 Trampoline pattern confirmed for `Play_internal` / `Stop_internal` / `UpdateSounds` / `SetFormat`

`[VERIFIED]` All prerequisites for hooking these four exactly like `Listen` hold:

| Function (1.10 decl, all non-virtual) | Header | TSE107 `Engine.def` |
|---|---|---|
| `void CSoundObject::Play_internal(CSoundData *, SLONG)` | `Serious-Engine\Sources\Engine\Sound\SoundObject.h:104` | L2167 `?Play_internal@CSoundObject@@QAEXPAVCSoundData@@J@Z` |
| `void CSoundObject::Stop_internal(void)` | `SoundObject.h:105` | L2817 `?Stop_internal@CSoundObject@@QAEXXZ` |
| `void CSoundLibrary::UpdateSounds(void)` | `Serious-Engine\Sources\Engine\Sound\SoundLibrary.h:135` | L2951 `?UpdateSounds@CSoundLibrary@@QAEXXZ` |
| `CSoundLibrary::SoundFormat CSoundLibrary::SetFormat(SoundFormat, BOOL=FALSE)` | `SoundLibrary.h:130` | L2646 `?SetFormat@CSoundLibrary@@QAE?AW4SoundFormat@1@W421@H@Z` |

- Non-virtual ⇒ statically-typed `&Class::Method` PMFs hold the concrete function address on
  MSVC x86 (4-byte PMF), so the `long*` reinterpret in `CreateOpcodePatch` is valid — proven in
  shipped code by every existing PMF patch (`EnginePatches.cpp:394-398` `pListen`,
  `pUpdate3DEffects`) and end-to-end by `P_Load`'s trampoline call `(this->*pLoadControls)(fnFile)`
  (`IGame.cpp:65`).
- **Wrapper (call-the-original) recipe**, per the `P_Load` precedent:
  1. a **file-static** PMF variable, e.g.
     `static void (CSoundObject::*pPlayInternal)(CSoundData *, SLONG) = &CSoundObject::Play_internal;`
  2. `CreatePatch(pPlayInternal, &CSoundObjPatch::P_Play_internal, "...")` at registration time
     (e.g. inside `ICorePatches::SoundLibrary()`, `EnginePatches.cpp:393-401`);
  3. inside the replacement: `(this->*pPlayInternal)(...)` invokes the original through the
     trampoline; return values (e.g. `SetFormat`'s `SoundFormat`) pass through unchanged.
- Contingency: `FuncPatch_ForceRewrite(nBytes)` (§10.1) if `CanRewriteInstructionSet` fails on
  any of the four prologues; relevant only at build/test time.
- Caveat (unchanged, 05 §1.3): Steam `Play_internal` inlines `Stop_internal` on re-Play, so the
  `Stop_internal` hook only sees calls entering via the exported entry (explicit `Stop()` →
  `Stop_internal`); the re-Play case is covered by the `Play_internal` wrapper (99 §2 mapping
  note).

### 10.4 `SE1_VER` / `SE1_105/107/110/150` numeric values — live in `Includes` (SE1-ModSDK), not in the API submodule

`[VERIFIED]` They are **not defined anywhere in the API repo**. They are MSBuild macros in
`Includes\Properties\*.props` of the SE1-ModSDK (branch `includes`; registered as
`SuperProject\Includes`, still empty on disk), imported per configuration by
`Core\Core.vcxproj:235-270` (`..\Includes\Properties\TSE107.props` etc.) and injected as
preprocessor definitions via `$(SamEnginePreproc)` (`Core.vcxproj:345,383,...`). Fetched from
upstream (`https://raw.githubusercontent.com/DreamyCecil/SE1-ModSDK/includes/Properties/...`)
and recorded:

- `SeriousEngine.props`:
  `SE1Versions = SE1_EVA=1;SE1_PB1=10;SE1_PB2=20;SE1_PB21=21;SE1_100=100;SE1_102=102;SE1_104=104;SE1_105=105;SE1_107=107;SE1_110=110;SE1_150=150`
  `SE1SamGames = SS_TFE='F';SS_TSE='S';SS_XBX='X';SS_150='B';SS_REV='R';SS_EVA='A';` (plus non-Sam `SE_ABZ`… IDs).
- `SE1SDK.props` (imports `SeriousEngine.props`) adds
  `SamSdkPreproc = SE1_D3D;DIRECT3D_VERSION=0x0800;WIN32;_WINDOWS;_WINDLL;_USRDLL;_USE_32BIT_TIME_T;`
  and `SE1SdkPreproc = $(SE1AllGames);$(SE1Versions);$(SamSdkPreproc);`.
- `TSE107.props` sets `SamEnginePreproc = $(SE1SdkPreproc);SE1_VER=SE1_107;SE1_GAME=SS_TSE;`
  plus `SamEngineIncludes/Libraries` = `Includes\Engine107\` + `Includes\Common\`.

So in the TSE107 configuration the compiler sees **`SE1_VER = 107`**, **`SE1_GAME = 'S'`**.
**Feature-gating condition for the DS3D mode (Task 2):** `#if SE1_VER == SE1_107` — uniquely
true for `Release_TSE107` and `Debug_TSE107` (105/110/150 configs set SE1_VER to 105/110/150).
Do not reuse `CHOOSE_FOR_ENGINE` for feature gating: it groups `SE1_VER <= SE1_107`
(`GameSpecific.h:24-32`), i.e. it also selects 1.05.

### 10.5 `CreatePatch` callable after `CorePatches()` init — yes

`[VERIFIED]` `CreateOpcodePatch` (`IPatches.cpp:89-123`) has no lifecycle gating: it only
requires the target module to be loaded (engine function address resolvable through the import
stub) and registers into the static `_mapFuncPatches`. Plugins create engine-function patches
during `ClassicsPatch_Init()` → `LoadPlugins(k_EPluginFlagEngine)` (`Core\Core.cpp:255`), which
runs **before** `CorePatches()` (`CustomGameClient\Cecil\CecilExtensions.cpp:101-112`:
`ClassicsPatch_Init()` at :103, `_EnginePatches.CorePatches()` at :109); ExtendedInput patches
engine `CInput::*` functions that way. Any code running while `Engine.dll` is loaded may call
`CreatePatch`; there is no init window. The DS3D mode needs none of this — its hooks install at
`CorePatches()` time in a Core patch category and the mode toggles inside the replacement
bodies via the cvar (per open question 5: no runtime hook/unhook).

## Open questions / anomalies

1. **`CreatePatch` definition — RESOLVED (Phase 2 Task 0, 2026-10-13).** Now on disk and quoted:
   `API\include\functionpatches.h:70-76` — a template taking the function-pointer *variable*
   by reference, forwarding to `CreateOpcodePatch` (L61). Semantics match the Phase 1 inference
   exactly (variable overwritten with trampoline, returns `HFuncPatch`). Full record in §10.1.
2. **`SE1_VER` numeric values — RESOLVED (Phase 2 Task 0, 2026-10-13).** They live in the
   **Includes (SE1-ModSDK)** submodule, not in the API repo: MSBuild macros in
   `Includes\Properties\*.props` (see §10.4 with the values from upstream:
   `SE1_105=105, SE1_107=107, SE1_110=110, SE1_150=150`; `SS_TFE='F', SS_TSE='S', SS_REV='R'`;
   TSE107 config compiles with `SE1_VER=107`, `SE1_GAME='S'`).
3. **Beta build includes a ClassicsCore patch already:** `SS_TSE_Beta_Bin\DebugFiles\ClassicsCore.map`
   exists (found during this task). This is a potential *bonus* source of beta-era symbol/layout
   info for task group A — worth checking whether the user's "1.50 beta" is itself a patched build.
4. **Sound patches are a full replacement, not a wrapper.** `P_Listen`/`P_Update3DEffects` never
   call the original; any new behavior (e.g. DS3D shadow buffers) must be added *inside* these
   bodies (or by converting them to call-the-original wrappers using the trampoline variable,
   which CreatePatch provides).
5. **Removal is untested for Core patches**: `ICorePatches::Cleanup()` is empty; only plugin-level
   patches are destroyed (`DestroyPatch`), and `CPatch::~CPatch` restores bytes. A mode toggled at
   runtime (cvar on/off) should toggle *behavior inside the replacement*, not hook/unhook, unless
   Enable/DisablePatch (`IPatches.cpp:186-224`) semantics are proven safe mid-game.
6. `P_Listen`'s `GetNoListening()` early-out happens *before* the listener is (re)linked, so it
   also skips re-linking — consistent with its purpose, but a wrapper version must preserve
   ordering if it chains.