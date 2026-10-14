//@category SeriousSam
// Dumps DirectSound-related analysis for the Serious Sam beta Engine.dll:
//  1) GUID locations (DSound + EAX) and every instruction referencing them
//  2) ASCII string locations ("dsound.dll", "DirectSoundCreate") and refs
//  3) xrefs to the _pSound / _pSoundStock globals
//  4) seed functions = known sound exports + all functions from (1)-(3)
//  5) one-level callee expansion (bounded)
//  6) per-seed: all indirect call sites with operands, direct call graph
//  7) decompiled C for every seed
// Output: <outDir>/sound-analysis.txt

import java.io.BufferedWriter;
import java.io.File;
import java.io.FileWriter;
import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.scalar.Scalar;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.model.symbol.FlowType;

public class DumpSoundAnalysis extends GhidraScript {

    PrintWriter out;
    long base;

    String rva(Function f) {
        if (f == null) return "<null>";
        return "0x" + Long.toHexString(f.getEntryPoint().getOffset() - base);
    }

    static byte[] guidToBytes(String guid) {
        String[] p = guid.split("-");
        long d1 = Long.parseLong(p[0], 16);
        int d2 = Integer.parseInt(p[1], 16);
        int d3 = Integer.parseInt(p[2], 16);
        String tail = p[3] + p[4];
        byte[] b = new byte[16];
        for (int i = 0; i < 4; i++) b[i] = (byte) ((d1 >>> (8 * i)) & 0xFF);
        for (int i = 0; i < 2; i++) b[4 + i] = (byte) ((d2 >>> (8 * i)) & 0xFF);
        for (int i = 0; i < 2; i++) b[6 + i] = (byte) ((d3 >>> (8 * i)) & 0xFF);
        for (int i = 0; i < 8; i++) b[8 + i] = (byte) Integer.parseInt(tail.substring(i * 2, i * 2 + 2), 16);
        return b;
    }

    Address findNext(byte[] pattern, Address after) throws Exception {
        Address start = (after != null) ? after : currentProgram.getMemory().getMinAddress();
        return currentProgram.getMemory().findBytes(start, pattern, null, true, monitor);
    }

    void addCallees(Function f, Set<Function> set) throws Exception {
        if (f == null) return;
        InstructionIterator it = currentProgram.getListing().getInstructions(f.getBody(), true);
        while (it.hasNext()) {
            Instruction ins = it.next();
            FlowType ft = ins.getFlowType();
            if (ft.isCall()) {
                for (Address t : ins.getFlows()) {
                    Function g = currentProgram.getFunctionManager().getFunctionAt(t);
                    if (g != null && set.size() < 600) set.add(g);
                }
            }
        }
    }

    @Override
    public void run() throws Exception {
        base = currentProgram.getImageBase().getOffset();
        String outDir = getScriptArgs().length > 0 ? getScriptArgs()[0] : ".";
        new File(outDir).mkdirs();
        out = new PrintWriter(new BufferedWriter(new FileWriter(new File(outDir, "sound-analysis.txt"))));

        out.println("ImageBase = 0x" + Long.toHexString(base));

        // ---------- 1. GUIDs ----------
        String[][] guids = {
            {"IID_IDirectSound",                     "279AFA83-4981-11CE-A521-0020AF0BE560"},
            {"IID_IDirectSound3DListener",           "279AFA84-4981-11CE-A521-0020AF0BE560"},
            {"IID_IDirectSoundBuffer",               "279AFA85-4981-11CE-A521-0020AF0BE560"},
            {"IID_IDirectSound3DBuffer",             "279AFA86-4981-11CE-A521-0020AF0BE560"},
            {"IID_IKsPropertySet",                  "31EFAC30-515C-11D0-A9AA-00AA0061BE93"},
            {"DSPROPSETID_EAX20_ListenerProperties", "0306A6A8-B224-11D2-99E5-0000E8D8C722"},
            {"DSPROPSETID_EAX20_BufferProperties",  "0306A6A7-B224-11D2-99E5-0000E8D8C722"},
        };
        Map<Long, String> targets = new LinkedHashMap<>();
        out.println();
        out.println("=== GUID locations ===");
        for (String[] g : guids) {
            byte[] pat = guidToBytes(g[1]);
            Address a = findNext(pat, null);
            while (a != null && monitor.isCancelled() == false) {
                targets.put(a.getOffset(), g[0]);
                out.println(g[0] + " @ " + a + " (RVA 0x" + Long.toHexString(a.getOffset() - base) + ")");
                a = findNext(pat, a.add(1));
            }
        }

        // ---------- 2. strings ----------
        String[] strings = {"dsound.dll", "DirectSoundCreate", "DirectSoundCreate8", "waveOutOpen"};
        out.println();
        out.println("=== String locations ===");
        for (String s : strings) {
            byte[] pat = (s + "\0").getBytes("US-ASCII");
            Address a = findNext(pat, null);
            while (a != null) {
                targets.put(a.getOffset(), "str:\"" + s + "\"");
                out.println("str \"" + s + "\" @ " + a + " (RVA 0x" + Long.toHexString(a.getOffset() - base) + ")");
                a = findNext(pat, a.add(1));
            }
        }

        // ---------- 3. globals ----------
        long[] globalRvas = {0x0022E9B4L /* _pSound */, 0x00230ED4L /* _pSoundStock */};
        for (long r : globalRvas) {
            Address a = toAddr(base + r);
            Symbol sym = getSymbolAt(a);
            String nm = (sym != null) ? sym.getName() : ("global_RVA_" + Long.toHexString(r));
            targets.put(a.getOffset(), "global:" + nm);
            out.println("global " + nm + " @ " + a + " (RVA 0x" + Long.toHexString(r) + ")");
        }

        // ---------- 4. scan all instructions for refs ----------
        Set<Function> seeds = new LinkedHashSet<>();
        List<String> xrefLines = new ArrayList<>();
        InstructionIterator ii = currentProgram.getListing().getInstructions(true);
        while (ii.hasNext()) {
            Instruction ins = ii.next();
            boolean hit = false;
            StringBuilder which = new StringBuilder();
            for (int i = 0; i < ins.getNumOperands(); i++) {
                for (Object o : ins.getOpObjects(i)) {
                    if (o instanceof Scalar) {
                        String lbl = targets.get(((Scalar) o).getValue());
                        if (lbl != null) { hit = true; which.append(lbl).append(" "); }
                    }
                }
            }
            for (Reference r : ins.getReferencesFrom()) {
                String lbl = targets.get(r.getToAddress().getOffset());
                if (lbl != null) { hit = true; which.append(lbl).append(" "); }
            }
            if (hit) {
                Function f = getFunctionContaining(ins.getAddress());
                if (f != null) seeds.add(f);
                xrefLines.add(String.format("%s  %-46s -> %-40s in %s @%s",
                        ins.getAddress(), ins.toString(), which.toString().trim(),
                        (f == null ? "<no-function>" : f.getName()), rva(f)));
            }
        }
        out.println();
        out.println("=== xrefs to GUIDs/strings/globals (" + xrefLines.size() + ") ===");
        for (String l : xrefLines) out.println(l);

        // ---------- 5. seed exports ----------
        long[] rvas = {
            0x00027270, 0x0007E5F0, 0x000804C0, 0x0001AB80, 0x00086E80, // ctors
            0x0007E630, 0x00080590, 0x00086F20, 0x00027330, 0x0001ACD0, // dtors / op=
            0x0007EA60, 0x00082500, 0x0007EA00, 0x00081BA0, 0x0007E680,
            0x00081BB0, 0x00086F80, 0x000807A0, 0x000807D0, 0x00080860,
            0x00087530, 0x00081D40, 0x000D16D0, 0x00089370, 0x00067550,
            0x00081C80, 0x00080960, 0x00080F10, 0x00080610, 0x000806E0,
            0x000872D0, 0x000829F0, 0x0010E2C0, 0x00082400, 0x00082460,
            0x00088B20, 0x00082740, 0x00082520, 0x000892F0, 0x0001AB40,
            0x00081C20, 0x000870F0, 0x00087190, 0x00087020, 0x00087450,
            0x000874D0, 0x000875E0, 0x00088EE0, 0x000827F0, 0x000822E0,
            0x00082380, 0x00081DD0, 0x00081400, 0x00081630, 0x000824D0,
            0x00088AD0, 0x00088B10, 0x0001AB00, 0x0001AB10, 0x0001AB20,
            0x0001AB30, 0x00081F40, 0x00082560, 0x00088A90
        };
        out.println();
        out.println("=== seed exports ===");
        for (long r : rvas) {
            Address a = toAddr(base + r);
            Function f = getFunctionAt(a);
            if (f == null) {
                out.println("!! no function at RVA 0x" + Long.toHexString(r));
            } else {
                seeds.add(f);
                out.println("seed " + f.getName() + " @ RVA 0x" + Long.toHexString(r));
            }
        }

        // ---------- 6. expand callees (1 level, bounded) ----------
        Set<Function> level1 = new LinkedHashSet<>(seeds);
        for (Function f : seeds) addCallees(f, level1);
        // second level for the most central seeds only (sound library + object core)
        Set<Function> all = new LinkedHashSet<>(level1);

        out.println();
        out.println("=== function set (" + all.size() + " functions) ===");
        for (Function f : all) out.println("  " + f.getName() + " @ RVA " + rva(f));

        // ---------- 7. indirect call table + whole-program 0x4c/0x50 histogram ----------
        Map<String, Integer> histogram = new LinkedHashMap<>();
        out.println();
        out.println("=== per-function indirect/direct calls ===");
        for (Function f : all) {
            out.println("--- " + f.getName() + " @ RVA " + rva(f) + " ---");
            InstructionIterator fi = currentProgram.getListing().getInstructions(f.getBody(), true);
            while (fi.hasNext()) {
                Instruction ins = fi.next();
                FlowType ft = ins.getFlowType();
                if (!ft.isCall()) continue;
                if (ft.isComputed()) {
                    out.println("  INDIRECT " + ins.getAddress() + "  " + ins.toString());
                    String key = f.getName();
                    histogram.merge(key, 1, Integer::sum);
                } else {
                    Address[] flows = ins.getFlows();
                    for (Address t : flows) {
                        Function g = currentProgram.getFunctionManager().getFunctionAt(t);
                        out.println("  direct   " + ins.getAddress() + " -> " +
                                (g == null ? t.toString() : g.getName() + " @" + rva(g)));
                    }
                }
            }
        }

        // whole-program: functions with indirect calls using 0x48/0x4c/0x50 displacements
        out.println();
        out.println("=== whole-program functions w/ indirect [reg+0x48/0x4c/0x50] calls ===");
        InstructionIterator wi = currentProgram.getListing().getInstructions(true);
        Map<String, Integer> wfMap = new LinkedHashMap<>();
        while (wi.hasNext()) {
            Instruction ins = wi.next();
            FlowType ft = ins.getFlowType();
            if (!(ft.isCall() && ft.isComputed())) continue;
            boolean disp = false;
            for (int i = 0; i < ins.getNumOperands(); i++) {
                for (Object o : ins.getOpObjects(i)) {
                    if (o instanceof Scalar) {
                        long v = ((Scalar) o).getValue();
                        if (v == 0x48 || v == 0x4c || v == 0x50) disp = true;
                    }
                }
            }
            if (!disp) continue;
            Function f = getFunctionContaining(ins.getAddress());
            String key = (f == null ? "<none>" : f.getName() + " @" + rva(f));
            wfMap.merge(key, 1, Integer::sum);
        }
        for (Map.Entry<String, Integer> e : wfMap.entrySet()) {
            out.println("  " + e.getKey() + " : " + e.getValue());
        }

        // ---------- 8. decompile ----------
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        int n = 0;
        for (Function f : all) {
            if (n % 25 == 0) println("decompiling " + n + "/" + all.size() + "...");
            n++;
            out.println();
            out.println("=== DECOMP " + f.getName() + " @ RVA " + rva(f) + " ===");
            DecompileResults res = di.decompileFunction(f, 240, monitor);
            if (res != null && res.decompileCompleted()) {
                out.println(res.getDecompiledFunction().getC());
            } else {
                out.println("// decompile failed: " + (res == null ? "null" : res.getErrorMessage()));
            }
        }
        di.dispose();
        out.close();
        println("DumpSoundAnalysis complete: " + all.size() + " functions, output in " + outDir);
    }
}
