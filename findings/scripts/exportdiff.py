#!/usr/bin/env python3
"""Export diff: beta vs Steam Engine.dll, sound-related symbols.

Reads the dumpbin-style export dumps and produces a markdown table
of sound-related symbols present in each build, with RVAs.
"""
import re
import sys

LINE_RE = re.compile(r'^\s*\d+\s+[0-9A-F]+\s+([0-9A-F]{8})\s+(\S+)\s*$')
SOUND_RE = re.compile(r'(CSound|_pSound|SoundListener|SoundFormat|SndEnv)', re.I)


def load(path):
    out = {}
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            m = LINE_RE.match(line)
            if m:
                name = m.group(2)
                if SOUND_RE.search(name):
                    out[name] = int(m.group(1), 16)
    return out


def main(beta_path, steam_path, out_path):
    beta = load(beta_path)
    steam = load(steam_path)
    lines = []
    w = lines.append
    w('# Sound-related export diff: beta (TSE150) vs Steam (TSE107)')
    w('')
    w(f'Beta sound symbols: {len(beta)}; Steam sound symbols: {len(steam)}')
    w('')
    both = sorted(set(beta) & set(steam))
    beta_only = sorted(set(beta) - set(steam))
    steam_only = sorted(set(steam) - set(beta))
    w(f'## In both ({len(both)})')
    w('')
    w('| symbol | beta RVA | steam RVA |')
    w('|---|---|---|')
    for n in both:
        w(f'| `{n}` | {beta[n]:08X} | {steam[n]:08X} |')
    w('')
    w(f'## Beta-only ({len(beta_only)})')
    w('')
    for n in beta_only:
        w(f'- `{n}` @ {beta[n]:08X}')
    w('')
    w(f'## Steam-only ({len(steam_only)})')
    w('')
    for n in steam_only:
        w(f'- `{n}` @ {steam[n]:08X}')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print(f'beta={len(beta)} steam={len(steam)} both={len(both)} '
          f'beta_only={len(beta_only)} steam_only={len(steam_only)}')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], sys.argv[3])
