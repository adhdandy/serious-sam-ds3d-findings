#!/usr/bin/env python3
"""Condense logstats JSONs + targeted context extraction from the beta log."""
import json
import re
import sys
import math

# Paths are relative to the analysis project root (set SS_PROJECT_ROOT or pass
# argv: beta_json steam_json beta_log). Defaults assume the original layout.
import os
_ROOT = os.environ.get('SS_PROJECT_ROOT', r'PROJECT_ROOT')
BETA_JSON = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_ROOT, r'findings\scratch\logstats-beta.json')
STEAM_JSON = sys.argv[2] if len(sys.argv) > 2 else os.path.join(_ROOT, r'findings\scratch\logstats-steam.json')
BETA_LOG = sys.argv[3] if len(sys.argv) > 3 else os.path.join(_ROOT, 'dsoal_log.txt')


def facts(jsonfile, label):
    with open(jsonfile) as f:
        d = json.load(f)
    print(f'===== {label} =====')
    sp = d['setposition_length']
    print('SetPosition: n=%s distinct_len10000=%s' % (
        sp['count'],
        sum(1 for l, _, _ in [(x['length'], 0, 0) for x in sp['outliers_gt_1p5']]
            if abs(l - 10000.0) < 0.01)))
    # count of exactly-10000 in histogram
    for k, v in sp['length_histogram'].items():
        if abs(float(k) - 10000.0) < 0.01:
            print('  length==10000.00 count:', v)
    n_sub = sum(v for k, v in sp['length_histogram'].items() if float(k) <= 1.05)
    n_sup = sum(v for k, v in sp['length_histogram'].items() if float(k) > 1.05)
    print(f'  <=1.05: {n_sub}   >1.05: {n_sup}')
    print('  apply modes:', sp['apply_modes'])
    sv = d['setvelocity_length']
    print('SetVelocity: n=%s min=%s max=%s apply=%s' % (
        sv['count'], sv['min'], sv['max'], sv['apply_modes']))
    vols = d['buffer_setvolume_hist']
    if vols:
        iv = {int(k): v for k, v in vols.items()}
        print('SetVolume: distinct=%d min=%d max=%d' % (len(iv), min(iv), max(iv)))
        print('  top20:', sorted(iv.items(), key=lambda kv: -kv[1])[:20])
    freqs = d['buffer_setfrequency_hist']
    if freqs:
        ifreq = {int(k): v for k, v in freqs.items()}
        print('SetFrequency: distinct=%d values=%s' % (
            len(ifreq), sorted(ifreq.items(), key=lambda kv: -kv[1])[:10]))
    print('QueryInterface:', d['queryinterface'])
    print('Buffer::Play %s Stop %s Lock %s' % (
        d['call_counts'].get('Buffer::Play', 0),
        d['call_counts'].get('Buffer::Stop', 0),
        d['call_counts'].get('Buffer::Lock', 0)))
    print('DuplicateSoundBuffer:', d['call_counts'].get('DSound8OAL::DuplicateSoundBuffer', 0))
    print('arg hists for select methods:')
    for m in ['Buffer3D::SetPosition', 'Listener3D::SetDopplerFactor',
              'Listener3D::SetRolloffFactor', 'Buffer::Play', 'Buffer::Stop',
              'Buffer::SetCurrentPosition', 'Listener3D::SetDistanceFactor',
              'Buffer3D::SetMinDistance', 'Buffer3D::SetMaxDistance']:
        h = d['arg_histograms'].get(m, {})
        if h:
            top = sorted(h.items(), key=lambda kv: -kv[1])[:6]
            print(f'  {m}: distinct={len(h)} top={top}')
        else:
            print(f'  {m}: ABSENT')
    print()


def beta_context():
    print('===== beta log context extraction =====')
    dsc_lines = []
    dup_ctx = []
    commit_ctx = []
    setpos10000_ctx = []
    with open(BETA_LOG, encoding='utf-8', errors='replace') as f:
        lines = f.readlines()
    total = len(lines)
    print('total lines:', total)
    for i, ln in enumerate(lines):
        if 'DirectSoundCreate' in ln:
            dsc_lines.append((i + 1, ln.strip()))
        if len(dup_ctx) < 2 and 'DuplicateSoundBuffer' in ln:
            dup_ctx.append(''.join(lines[max(0, i - 8):i + 6]))
        if len(commit_ctx) < 1 and 'CommitDeferredSettings' in ln and i > total // 2:
            commit_ctx.append(''.join(lines[max(0, i - 60):i + 4]))
        if len(setpos10000_ctx) < 1 and 'Buffer3D::SetPosition' in ln:
            parts = re.findall(r'-?\d+\.?\d*', ln)
            if len(parts) >= 3:
                v = [float(p) for p in parts[:3]]
                if math.sqrt(sum(x * x for x in v)) > 9999:
                    setpos10000_ctx.append(''.join(lines[max(0, i - 10):i + 6]))
    print('--- DirectSoundCreate line numbers ---')
    for n, ln in dsc_lines:
        print(f'line {n}: {ln}')
    print('--- first DuplicateSoundBuffer contexts ---')
    for c in dup_ctx:
        print(c)
        print('   ...')
    print('--- mid-log CommitDeferredSettings context (61 lines) ---')
    for c in commit_ctx:
        print(c)
    print('--- first SetPosition with length ~10000 context ---')
    for c in setpos10000_ctx:
        print(c)


if __name__ == '__main__':
    facts(BETA_JSON, 'BETA (dsoal_log.txt)')
    facts(STEAM_JSON, 'STEAM (dsoal_Steam_log.txt)')
    if len(sys.argv) > 1 and sys.argv[1] == 'ctx':
        beta_context()
