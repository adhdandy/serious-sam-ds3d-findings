#!/usr/bin/env python3
"""DSOAL log statistics for the Serious Sam DS3D analysis (Stage 1).

Parses wine-style DSOAL trace logs (as produced by dsoal-aldrv / dsound.dll)
and produces per-call counts, argument histograms, buffer-creation statistics
and vector-length distributions as JSON plus a human-readable summary.

Usage: python logstats.py <logfile> <outjson> <outsummary>
"""
import re
import sys
import json
import math
import collections

LINE_RE = re.compile(
    r'^(?P<tid>[0-9a-fA-F]+):(?P<lvl>\w+):dsound:(?P<method>[\w:]+)(?:\s+(?P<rest>.*))?$'
)
# e.g. "(0x3980e5c)->(1, 0)" or "(0x64e540)" or "({null}, 0x22ff05c, 0x0)"
CALL_RE = re.compile(r'^\((?P<ptr>[^)]*)\)(?:->\((?P<args>.*)\))?$')
KV_RE = re.compile(r'^\s+(?P<key>\w+)\s*=\s*(?P<value>.*?)\s*$')

BUFFERDESC_KEYS = ['Size', 'Flags', 'BufferBytes', '3DAlgorithm']
WAVEFORMAT_KEYS = ['FormatTag', 'Channels', 'SamplesPerSec', 'AvgBytesPerSec',
                   'BlockAlign', 'BitsPerSample', 'Size']

METHODS_OF_INTEREST = [
    'Buffer3D::SetMode', 'Buffer3D::SetPosition', 'Buffer3D::SetVelocity',
    'Buffer3D::SetAllParameters', 'Buffer3D::SetMinDistance', 'Buffer3D::SetMaxDistance',
    'Buffer3D::SetConeAngles', 'Buffer3D::SetConeOrientation', 'Buffer3D::SetConeOutsideVolume',
    'Listener3D::SetAllParameters', 'Listener3D::CommitDeferredSettings',
    'Listener3D::SetDistanceFactor', 'Listener3D::SetDopplerFactor',
    'Listener3D::SetOrientation', 'Listener3D::SetPosition',
    'Listener3D::SetRolloffFactor', 'Listener3D::SetVelocity',
    'Buffer::SetVolume', 'Buffer::SetFrequency', 'Buffer::SetPan',
    'Buffer::Play', 'Buffer::Stop', 'Buffer::Lock', 'Buffer::Unlock',
    'Buffer::SetCurrentPosition', 'Buffer::Restore', 'Buffer::GetStatus',
    'Buffer::GetCurrentPosition', 'Buffer::SetFormat',
    'Primary::SetFormat', 'DSound8OAL::CreateSoundBuffer',
    'DSound8OAL::DuplicateSoundBuffer', 'DirectSoundCreate', 'DirectSoundCreate8',
    'DSound8OAL::SetCooperativeLevel',
]


def tofloat(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def vec3_length(parts):
    v = [tofloat(p) for p in parts[:3]]
    if any(x is None for x in v):
        return None
    return math.sqrt(sum(x * x for x in v))


class Stats:
    def __init__(self):
        self.call_counts = collections.Counter()
        self.ptrs = collections.defaultdict(set)      # method -> set of object ptrs
        self.arg_hists = collections.defaultdict(collections.Counter)  # method -> Counter(args str)
        self.sessions = 0
        self.directsound_create = 0
        self.bufferdescs = []                          # list of dicts
        self.waveformats = []
        self.qi = collections.Counter()                # IID name -> count
        self.setpos_lengths = []                       # (length, args, ptr)
        self.setvel_lengths = []
        self.setpos_apply = collections.Counter()
        self.setvel_apply = collections.Counter()
        self.vol_hist = collections.Counter()
        self.freq_hist = collections.Counter()
        self.pan_hist = collections.Counter()
        self.lines = 0
        self.unparsed = 0

    def summary(self):
        return {
            'lines': self.lines,
            'unparsed': self.unparsed,
            'sessions_dllmain_init': self.sessions,
            'directsound_create_calls': self.directsound_create,
            'call_counts': dict(self.call_counts),
            'distinct_object_ptrs': {m: len(v) for m, v in self.ptrs.items()},
            'arg_histograms': {m: dict(c) for m, c in self.arg_hists.items()},
            'queryinterface': dict(self.qi),
            'setposition_length': {
                'count': len(self.setpos_lengths),
                'min': min((l for l, _, _ in self.setpos_lengths), default=None),
                'max': max((l for l, _, _ in self.setpos_lengths), default=None),
                'apply_modes': dict(self.setpos_apply),
                'outliers_gt_1p5': [
                    {'length': l, 'args': a, 'ptr': p}
                    for l, a, p in self.setpos_lengths if l is not None and l > 1.5
                ][:40],
                'length_histogram': dict(collections.Counter(
                    round(l, 2) for l, _, _ in self.setpos_lengths if l is not None)),
            },
            'setvelocity_length': {
                'count': len(self.setvel_lengths),
                'min': min((l for l, _, _ in self.setvel_lengths), default=None),
                'max': max((l for l, _, _ in self.setvel_lengths), default=None),
                'apply_modes': dict(self.setvel_apply),
                'length_histogram': dict(collections.Counter(
                    round(l, 4) for l, _, _ in self.setvel_lengths if l is not None)),
            },
            'buffer_setvolume_hist': dict(self.vol_hist),
            'buffer_setfrequency_hist': dict(self.freq_hist),
            'buffer_setpan_hist': dict(self.pan_hist),
            'bufferdescs': self.bufferdescs,
            'waveformats': self.waveformats,
        }


def main(logfile, outjson, outsummary):
    st = Stats()
    cur_multi = None
    cur_multi_type = None

    with open(logfile, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.rstrip('\r\n')
            st.lines += 1

            kv = KV_RE.match(line)
            if kv and cur_multi is not None:
                cur_multi[kv.group('key')] = kv.group('value')
                if cur_multi_type == 'bufferdesc' and kv.group('key') == '3DAlgorithm':
                    st.bufferdescs.append(dict(cur_multi))
                    cur_multi = None
                elif cur_multi_type == 'waveformat' and kv.group('key') == 'Size':
                    st.waveformats.append(dict(cur_multi))
                    cur_multi = None
                continue

            m = LINE_RE.match(line)
            if not m:
                if line.strip():
                    st.unparsed += 1
                continue
            method = m.group('method')
            rest = m.group('rest') or ''

            if method == 'DllMain' and 'Initializing library' in rest:
                st.sessions += 1

            if 'Requested buffer:' in rest:
                cur_multi, cur_multi_type = {}, 'bufferdesc'
            elif 'Requested buffer format:' in rest or 'Requested primary format:' in rest:
                cur_multi, cur_multi_type = {}, 'waveformat'

            cm = CALL_RE.match(rest)
            if cm:
                # Only count actual call-entry lines (debug lines with
                # "(ptr)->(args)" structure); trace continuation lines like
                # "status = 0x..." or "Requested buffer:" must not count.
                if method in METHODS_OF_INTEREST:
                    st.call_counts[method] += 1
                ptr = cm.group('ptr')
                args = cm.group('args')
                if ptr.startswith('0x'):
                    st.ptrs[method].add(ptr)
                if method == 'DirectSoundCreate' or method == 'DirectSoundCreate8':
                    st.directsound_create += 1
                if args is not None and method in METHODS_OF_INTEREST:
                    st.arg_hists[method][args] += 1
                if method == 'Buffer3D::SetPosition' and args is not None:
                    parts = [p.strip() for p in args.split(',')]
                    if len(parts) >= 4:
                        st.setpos_apply[parts[3]] += 1
                        st.setpos_lengths.append((vec3_length(parts), args, ptr))
                elif method == 'Buffer3D::SetVelocity' and args is not None:
                    parts = [p.strip() for p in args.split(',')]
                    if len(parts) >= 4:
                        st.setvel_apply[parts[3]] += 1
                        st.setvel_lengths.append((vec3_length(parts), args, ptr))
                elif method == 'Buffer::SetVolume' and args is not None:
                    st.vol_hist[args.strip()] += 1
                elif method == 'Buffer::SetFrequency' and args is not None:
                    st.freq_hist[args.strip()] += 1
                elif method == 'Buffer::SetPan' and args is not None:
                    st.pan_hist[args.strip()] += 1
                elif method == 'Buffer::QueryInterface' and args is not None:
                    first = args.split(',')[0].strip()
                    if first.startswith('IID_'):
                        st.qi[first] += 1

    data = st.summary()
    with open(outjson, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=1)

    with open(outsummary, 'w', encoding='utf-8') as f:
        w = f.write
        w(f'# logstats: {logfile}\n\n')
        w(f'lines: {data["lines"]} (unparsed non-empty: {data["unparsed"]})\n')
        w(f'DllMain init (sessions): {data["sessions_dllmain_init"]}\n')
        w(f'DirectSoundCreate calls: {data["directsound_create_calls"]}\n\n')
        w('## Call counts (methods of interest)\n')
        for m in METHODS_OF_INTEREST:
            if m in data['call_counts']:
                w(f'  {m}: {data["call_counts"][m]} '
                  f'(distinct objects: {data["distinct_object_ptrs"].get(m, 0)})\n')
        w('\n## QueryInterface by IID\n')
        for k, v in sorted(data['queryinterface'].items()):
            w(f'  {k}: {v}\n')
        w('\n## Buffer3D::SetMode arg histogram\n')
        for a, c in sorted(data['arg_histograms'].get('Buffer3D::SetMode', {}).items()):
            w(f'  ({a}): {c}\n')
        w('\n## Listener3D setters (arg histograms)\n')
        for m in ['Listener3D::SetDopplerFactor', 'Listener3D::SetRolloffFactor',
                  'Listener3D::SetPosition', 'Listener3D::SetOrientation',
                  'Listener3D::SetVelocity', 'Listener3D::SetDistanceFactor']:
            for a, c in sorted(data['arg_histograms'].get(m, {}).items()):
                w(f'  {m} ({a}): {c}\n')
        sp = data['setposition_length']
        w(f'\n## Buffer3D::SetPosition lengths: n={sp["count"]} '
          f'min={sp["min"]} max={sp["max"]} apply={sp["apply_modes"]}\n')
        w('  length histogram (rounded 0.01):\n')
        for l, c in sorted(sp['length_histogram'].items(), key=lambda kv: float(kv[0])):
            w(f'    {l}: {c}\n')
        w('  outliers (>1.5):\n')
        for o in sp['outliers_gt_1p5']:
            w(f'    len={o["length"]:.3f} {o["args"]} ptr={o["ptr"]}\n')
        sv = data['setvelocity_length']
        w(f'\n## Buffer3D::SetVelocity lengths: n={sv["count"]} '
          f'min={sv["min"]} max={sv["max"]} apply={sv["apply_modes"]}\n')
        w('  length histogram (rounded 0.0001):\n')
        for l, c in sorted(sv['length_histogram'].items(), key=lambda kv: float(kv[0])):
            w(f'    {l}: {c}\n')
        w('\n## Buffer::SetVolume value histogram\n')
        for v, c in sorted(data['buffer_setvolume_hist'].items(), key=lambda kv: int(kv[0])):
            w(f'  {v}: {c}\n')
        w('\n## Buffer::SetFrequency value histogram\n')
        for v, c in sorted(data['buffer_setfrequency_hist'].items(), key=lambda kv: int(kv[0])):
            w(f'  {v}: {c}\n')
        if data['buffer_setpan_hist']:
            w('\n## Buffer::SetPan value histogram\n')
            for v, c in sorted(data['buffer_setpan_hist'].items(), key=lambda kv: int(kv[0])):
                w(f'  {v}: {c}\n')
        w('\n## CreateSoundBuffer requested buffer descriptors\n')
        combos = collections.Counter()
        bytes_by_combo = collections.defaultdict(list)
        for bd in data['bufferdescs']:
            key = (bd.get('Flags', '?'), bd.get('3DAlgorithm', '?'))
            combos[key] += 1
            bytes_by_combo[key].append(int(bd.get('BufferBytes', '0')))
        for key, c in combos.items():
            bl = bytes_by_combo[key]
            w(f'  flags=[{key[0]}] alg=[{key[1]}] count={c} '
              f'BufferBytes min={min(bl)} max={max(bl)} distinct={len(set(bl))}\n')
        w('\n## Waveformats requested (ConvertFormat)\n')
        wfmt = collections.Counter()
        for wf in data['waveformats']:
            wfmt[(wf.get('Channels'), wf.get('SamplesPerSec'), wf.get('BitsPerSample'))] += 1
        for key, c in wfmt.items():
            w(f'  channels={key[0]} rate={key[1]} bits={key[2]} count={c}\n')

    print(f'wrote {outjson} and {outsummary}')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], sys.argv[3])
