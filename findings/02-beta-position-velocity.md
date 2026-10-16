# 02 — Beta position and velocity construction (Task A2)

Function: `FUN_10087970` @ VA 0x10087970 (RVA 0x87970), called from
`CSoundObject::Update` (0x875E0, decomp line 12594). Signature (reconstructed):

```c
void ComputeSpatial(CSoundObject *so,
                   FLOAT3D &vPosition,   // out, engine space
                   FLOAT3D &vSpeed,     // out, engine space
                   FLOAT  &fVolume,     // out (also used as L pan, see tail)
                   FLOAT  &fDistance,  // out
                   FLOAT  &fFilter);   // out
```

All constants below read from the binary (`findings/scripts/readpe.py`) `[VERIFIED]`.

## 1. Defaults (no listener / no entity) `[VERIFIED]`

```c
vSpeed    = (0, 0, 0);
vPosition = (0, 0, 10000.0);   // "parked far in front-behind"
fDistance = 10000.0;
fVolume   = 0.0;               // (param_4, the volume/mix factor)
fFilter   = 0.0;
```
`PlayBuffers` issues `SetPosition(x, y, -z, 1)` → the parked state logs as
`(0.000000, 0.000000, -10000.000000, 1)` — 29,288 occurrences in the log, always paired
with `SetVolume(-10000)` `[VERIFIED; explains §6.1's "outliers"]`.

## 2. Listener loop `[VERIFIED]`

Runs only if `so->so_pCsdLink != NULL && so->so_penEntity != NULL`. Iterates
`_pSound->sl_lhActiveListeners` (list at CSoundLibrary+0x38). For each listener `L`:

```c
bool bVolumetric = (so->flags & SOF_VOLUMETRIC) || (so->decoder != NULL);
if ((so->flags & SOF_LOCAL /*0x8*/) && so->penEntity != L.entity) continue;  // local sounds only for own listener

Δ = entity.pos - L.pos;                    // world-space delta (entity at so+0x3c..0x44 of CEntity)
dist = |Δ|;
if (dist > so->sp3_fFalloff) continue;      // beyond falloff: no contribution at all (→ parked if all skip)

factor     = 1.0;                          // distance factor
volFactor  = 0.0;                          // "inside hotspot" factor = volumetric bias
if (dist > so->sp3_fHotSpot) {
    factor     = (sp3_fFalloff - dist) / (sp3_fFalloff - sp3_fHotSpot);
    volFactor  = ClampUp( (dist - sp3_fHotSpot) / (sp3_fFalloff - sp3_fHotSpot) * 3.0, 1.0 );   // ×3.0 (0x101b9ad4)
}

if (!bVolumetric || volFactor >= 1.0) {
    // plain: rotate delta and entity velocity into listener space (L.matrix, rows at L+0x14..0x34)
    dirR   = Δ × L.matrix;                  // full rotated delta (length = dist)
    velR   = (entityVel - L.vel) × L.matrix;
} else if (volFactor <= 0.0) {
    dirR = (0,0,0); velR = (0,0,-1);        // degenerate
} else {
    // VOLUMETRIC BLEND (inside hotspot): see §3
}
listenerVol = (so->flags & 0x58) ? 0.0 : L.filter_int;    // mask 0x58 = 0x08|0x10|0x40 = SOF_LOCAL|SOF_MUSIC|SOF_VOICE (corrected 2026-10-16, findings 07 §14.3 item 2; NOTE: the beta has no SURROUND bit - that is a 1.10 flag name; Ghidra sound-analysis.txt:7752)
acc.dist    += factor * dist;
acc.dir     += dirR * factor;                // position accumulation
acc.vel     += velR * factor;
acc.volume  += L.vol_float * so->curVolume * factor * factor;   // L+0x44 × so+0x38
acc.filter  += listenerVol * factor;
acc.hotspot += volFactor * factor;
acc.sum     += factor;
```

After the loop (if `acc.sum > 0.001`): divide all accumulators by `acc.sum`
(weighted average over listeners) `[VERIFIED]`.

**=> position = Σ(rotated Δ × factor)/Σfactor** — for a single listener this is the
listener-space relative vector with length = actual distance (NOT normalized).

## 3. Volumetric blend (inside hotspot) `[VERIFIED — LC cross-check 2026-10-16, findings 07 §14.4]`

When the sound is volumetric and inside the hotspot (`volFactor < 1`):
```c
if (volFactor <= 0) {
    dirR = (0,0,-1);  velR = (0,0,0);      // "in front", static — the log's 101K (0,0,1) after z-negation
} else {
    n = normalize(dirR);                   // rotated delta normalized
    t = clamp(n.z, 0.0, 1.0)               // dot with the (0,0,-1) basis
    plane = normalize(n × (0,0,-1));       // axis in the horizontal plane
    ort2  = (0,0,-1) × plane
    ort1  = lerp(ort2, (0,1,0), max(-n.z, 0.0))    // downward directions lerp toward +Y
    angle = ACos(n.z) * volFactor          // bias = volFactor (the ×3 ramp of §2, clamped to 1)
    dirFinal = (0,0,-1)*cos(angle) + ort1*sin(angle)
    velR = velR * volFactor                // attenuated speed
}
```
**Resolved (2026-10-16)**: the earlier ambiguity about `_DAT_101b8ca8 = 0.0` ("angle scale
constant, multiply in the acos path") was a **Ghidra misread** — that constant is the
volumetric-bias *default* 0.0, not part of the angle computation; there is no extra angle
scale (07 §14.4). bias = 0 (inside hotspot) → `(0,0,−1)` and zero speed; 0 < bias < 1 →
the axis-lerp construction above; bias ≥ 1 → the plain rotated delta of §2 (no blend).

## 4. How this explains the log distribution `[VERIFIED mapping]`

| Log population | Count | Origin |
|---|---|---|
| exactly `(0,0,1)` | 101,068 | volumetric sounds at/near listener → default basis (0,0,-1) → z-negated → +1 |
| lengths 0.49–1.0 | ~32,000 | volumetric blend outputs (rotated, ≤1) |
| lengths 1.67–~100+ (continuous) | ~55,000 | non-volumetric 3D sounds: rotated deltas, length = true distance (e.g. log line 941859: `(-1.007717, 9.811462, -107.388222)` = a sound 107.9 m away, inside its falloff) |
| exactly `(0,0,-10000)` | 29,288 | parked: no entity / no listener in range / beyond falloff |

The §6.1 claim "one outlier (length 57.6)" was a misreading — there is a whole
population of true-distance positions. **Positions are listener-relative world units
(meters), NOT normalized** (except the volumetric near-field case) `[VERIFIED]`.

## 5. Velocity `[VERIFIED]`

`vSpeed = Σ((entityVel − L.vel) × L.matrix × factor)/Σfactor` — relative velocity rotated
into listener space. Max magnitude seen in log: 66.0 (= 66 m/s, fast projectiles/player).
**`PlayBuffers` negates z for both SetPosition and SetVelocity** (0x10082c34/0x10082c4f):
`SetPosition(so.x, so.y, -so.z, 1)` — the engine's z axis is flipped w.r.t. DS3D's.

## 6. Apply mode and commit `[VERIFIED]`

- `SetPosition`/`SetVelocity`: always `dwApply = 1` (DS3D_DEFERRED) — all 218,313 calls.
- `SetMode`: `dwApply = 0` (IMMEDIATE) at commit time.
- `Listener3D::CommitDeferredSettings` is called **once per frame** from `UpdateSounds`
  (0x10082271) after `PlayBuffers` — 46,444 times in the log ≈ one per frame for a
  ~13 min session. No per-buffer commit is ever issued (none exists in DS3D).
- The listener itself is initialized once in `StartUp_dsound` and **never moved** —
  position (0,0,0), orientation (0,0,1)/(0,1,0), rolloff 0 (engine does its own
  attenuation), doppler factor 1.1. All spatialization is precomputed by the engine in
  listener space; buffers run HEADRELATIVE `[VERIFIED]`.

## 7. Pseudocode summary for the implementation

```
per 3D sound object per frame:
    if (!entity || !anyListenerInRange(falloff)):
        pos = (0,0,10000); vol = 0            # parked
    else:
        wsum = Σ listeners: w = clamp01((falloff - d)/(falloff - hotspot))
        pos  = Σ(rotate(entity.pos - L.pos) * w) / wsum        # z stays engine-space
        vel  = Σ(rotate(entity.vel - L.vel) * w) / wsum
        vol  = clamp01(Σ(L.vol * so.curVolume * w²) / wsum)     # ≤ 1.0
        (volumetric inside hotspot: replace pos by the blend of §3)
    DS3D: SetPosition(pos.x, pos.y, -pos.z, DEFERRED)
          SetVelocity(vel.x, vel.y, -vel.z, DEFERRED)
after all sounds: Listener::CommitDeferredSettings()
```
