#!/usr/bin/env python3
"""Slice function disassembly from llvm-objdump output by RVA (steam Engine.dll)."""
import sys, re

IMAGE_BASE = 0x600C0000

def load(path):
    lines = []
    label_re = re.compile(r"^([0-9a-f]+) <([^>]+)>:$")
    labels = {}  # name -> index
    cur = None
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f):
            line = line.rstrip("\n")
            m = label_re.match(line)
            if m:
                addr = int(m.group(1), 16)
                name = m.group(2).split("+")[0]
                if name not in labels:
                    labels[name] = (i, addr)
                cur = (name, addr)
            lines.append((line, cur))
    return lines, labels

def slice_rva(lines, start_rva, end_rva=None):
    start = IMAGE_BASE + start_rva
    out = []
    started = False
    addr_re = re.compile(r"^([0-9a-f]+):\s")
    for line, _ in lines:
        m = addr_re.match(line)
        if m:
            a = int(m.group(1), 16)
            if a >= start:
                started = True
            if started:
                if end_rva is not None and a >= IMAGE_BASE + end_rva:
                    break
                out.append(line)
        elif started and line.strip() == "" and out and out[-1].strip() == "":
            break
        elif started and "<" in line and ":$" not in line and line.endswith(":") and not addr_re.match(line):
            break
    return out

def slice_name(lines, labels, name):
    if name not in labels:
        return None
    idx, addr = labels[name]
    out = [lines[j][0] for j in range(idx, len(lines))]
    # cut at next top-level label
    res = []
    label_re = re.compile(r"^([0-9a-f]+) <[^>]+>:$")
    addr_re = re.compile(r"^([0-9a-f]+):\s")
    cur_func = None
    for j in range(idx, len(lines)):
        line = lines[j][0]
        if label_re.match(line):
            m = label_re.match(line)
            if int(m.group(1), 16) != addr:
                break
        res.append(line)
        if not addr_re.match(line) and line.strip() == "" and len(res) > 1:
            break
    return res

if __name__ == "__main__":
    path = sys.argv[1]
    lines, labels = load(path)
    if sys.argv[2] == "--name":
        name = sys.argv[3]
        print("\n".join(slice_name(lines, labels, name)))
    else:
        start = int(sys.argv[2], 16)
        end = int(sys.argv[3], 16) if len(sys.argv) > 3 else None
        print("\n".join(slice_rva(lines, start, end)))