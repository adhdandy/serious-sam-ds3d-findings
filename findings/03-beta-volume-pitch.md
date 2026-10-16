# 03 — Beta volume and pitch (Task A3)

## 1. Volume chain (float 0..1) `[VERIFIED]`

Per 3D sound, computed in `Update` (0x875E0) + `FUN_10087970` (0x87970):

```
vol_spatial = clamp01( Σ_listeners( L.vol_float × so.curVolume(+0x38) × w² ) / Σ w )
              (w = distance factor; for 2D sounds: vol_spatial = so.curVolume directly)
vol_fade    = crossfade(vol_spatial → so.fadeTarget(+0x34)) over so.fadeTime(+0x30)   [Fade()]
master      = snd_fSoundVolume            (normal sounds)
            | snd_fMusicVolume × 0.5      (SOF_MUSIC 0x10; the 0.5 is const 0x101b8c68)
            × menu-state factors: _bMuteVolume (DAT_1022e9d8) → 0; _bAttenuateVolume
              (DAT_1022e9d4) → 0.5 except SOF_VOICE sounds (set by UpdateSounds when a
              SOF_VOICE sound with current volume > 0.2 is pending; beta 0x100875e6-0x1008761a)
              [identified via LC cross-check 2026-10-16 — findings 07 §14.3 item 6;
              Steam has neither → N/A for the mode]
volume      = vol_fade × master           # stored at so+0x64
```

**Per-CSoundData throttle** (`snd_iMaxSameSounds`, default 5, clamped 1..99): each frame
`data+0x40` (running sum) is reset; an object only keeps its volume if
`volume + data.running ≤ snd_iMaxSameSounds`, else `so+0x64 = 0.0` (silent but still
playing — a per-sound-type loudness budget) `[VERIFIED; UpdateSounds 0x81F40 + Update tail]`.

## 2. The centibel curve (PlayBuffers 0x82CEA-0x82D11, raw disasm) `[VERIFIED]`

```
if (volume ≤ 0.005)  SetVolume(-10000);                     # silent  (const 0x101b95cc = 0.005)
else if (snd_bLinearVolume == 0):                           # logarithmic mode
    SetVolume( ftol( 3000.0 × log10(volume) ) );            # K1 = 3000.0 (0x101b95c4)
else:                                                       # linear mode (DEFAULT = 1)
    SetVolume( ftol( 3000.0 × ( v(v-1) + (1-v)·log10(v) ) ) );
```

Derivation from disassembly (x87): `fldlg2; flds v; fyl2x` → log10(v); the linear branch
computes `v·(v−1)`, `(1−v)·log10(v)`, adds, multiplies by 3000.0, `ftol`.

**Log validation** `[VERIFIED]`: with snd_fSoundVolume = 0.8 (default):
- v = 0.8: 0.8·(−0.2) + 0.2·log10(0.8) = −0.16 − 0.01939 = −0.17939 × 3000 = **−538** ✓
  (the most common log value, 84,854 calls)
- v = 0.4 → −1436 ✓ (2nd most common cluster); v = 0.2 → −2157 ✓; v = 0.005 → −10000 ✓.
Top log values −538/−10000/−2157/−1436 correspond exactly to v = 0.8·1.0 / 0 / 0.25 / 0.5
typical per-sound max volumes.

## 3. SetFrequency `[VERIFIED]` (0x82D14-0x82D3F)

```
if (so.pitch(+0x3C) == 1.0f) SetFrequency(0);               # DSBFREQUENCY_ORIGINAL
else                         SetFrequency( ftol( data.nSamplesPerSec(+0x18) × so.pitch ) );
```
The 7 non-zero log values decode as template rates × pitch:
12414 = 11025×1.126, 15659 = 22050×0.710, 18533 = 22050×0.840, 21658/21689 = 22050×0.982/0.984,
22012 = 22050×0.998, 29114 = 22050×1.321 — i.e. entity pitch variation on 11/22 kHz sounds.
`SetFrequency` is NOT used for doppler (see §4).

## 4. Doppler — single application `[VERIFIED]`

Two implementations exist, **mutually exclusive**:

1. **Software doppler** (FUN_10087970 tail): active only
   `if (sl_bUsingDSound(+0x44) == 0 || so->decoder != 0)` — i.e. waveOut mode or
   streaming sounds:
   ```
   vr = dot(normalize(pos), vel);               # radial relative speed
   if (|vr| > 1e-3?)
       so.pitch(+0x3C) *= 300.0 / (vr + 300.0); # c = 300 m/s (const 0x101b9ad0, NOT a cvar in beta)
   ```
2. **DS3D hardware doppler** (the normal DS3D path): real velocities are passed via
   `SetVelocity` (deferred) and `Listener3D::SetDopplerFactor(1.1, 0)` at startup.

For the DS3D path (sl_bUsingDSound=1, no decoder) the software branch is skipped —
**no double application**. The observed `SetFrequency` values are pitch variation only.

## 5. EAX DirectHF per frame `[VERIFIED]` (PlayBuffers 0x82E3E-0x82E44)

```
if (is3D && playing && channel.KsPropertySet && snd_bUseEnvironmentFX /*DAT_1020f82c*/):
    val = ROUND( so.hfFilter(+0x68) × (−100.0) );           # 0x101b95c0 = -100.0
    clamp val to [−10000, 0];
    KsPropertySet::Set(DSPROPSETID_EAX20_BufferProperties,
                       0x80000003 = DEFERRED | DSPROPERTY_EAXBUFFER_DIRECTHF,
                       NULL, 0, &val, 4);
```
`so.hfFilter` = weighted average of listener filter ints (CSoundListener+0x48,
`[0x12]`), skipped for sounds with flags & 0x58 = **SOF_VOICE|SOF_LOCAL|SOF_MUSIC**
(corrected 2026-10-16 — 0x40 is `SOF_VOICE`, not "SOF_2D"; findings 07 §14.3 item 2;
no SURROUND bit in the beta - 1.10 name leftover).
This exports the engine's per-ear HF filter to EAX on the DS3D path
(the software mixer instead applies it in the resampler via so+0x74/+0x78 = `ROUND(32767/vol)`).
**LC/beta nuance (2026-10-16)**: the `Set` is issued **also when `snd_bUseEnvironmentFX == 0`**
(with value 0 — the beta skips only the computation, not the call, 0x10082def/0x10082e44;
findings 07 §14.2). Our design gates the call on the cvar (cvar-off only, low priority).

## 6. Listener-side parameters `[VERIFIED]`

- `SetRolloffFactor(0.0, 0)` — DS3D distance attenuation OFF; the engine's own
  falloff/hotspot factor is folded into the volume (and volume goes through the
  centibel curve above).
- `SetDopplerFactor(1.1, 0)` — mild DS3D doppler (1.1×) on real velocities.
- No `SetDistanceFactor`, `SetMinDistance`/`SetMaxDistance` on 3D sound buffers, no cone
  setters, no `SetAllParameters` — all confirmed absent in the binary and log.

## 7. What a reimplementation must reproduce (parameter sheet extract)

| Parameter | Value |
|---|---|
| Volume curve | `cB = 3000 × (v(v−1)+(1−v)log10 v)` (linear mode, default) or `3000×log10 v`; `v ≤ 0.005 → −10000` |
| Frequency | `pitch==1 → 0` else `rate × pitch` |
| Doppler | DS3D via `SetVelocity` + `DopplerFactor 1.1` (software formula only for waveOut/decoder: `c=300`) |
| HF filter | EAX DirectHF = `round(−100 × hfFactor)` clamped `[−10000, 0]`, deferred |
| Rolloff | 0 (engine-computed attenuation) |
