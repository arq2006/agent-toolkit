"""Auxiliares de teste: srt FALSO (sem sandbox algum). Serve só para exercitar a lógica do launcher e
do doctor (parsing, timeout, fail-closed); NUNCA é evidência de isolamento."""
import os
import stat

import srt_launcher as L

FAKE_SRT = '''#!/usr/bin/env python3
import json, os, sys, time
a = sys.argv[1:]
mode = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "mode")).read().strip()
if len(a) < 4 or a[0] != "--settings" or a[2] != "--":
    sys.exit(9)
if mode in ("validate", "validate_noop") :
    try:
        json.load(open(a[1]))
    except Exception:
        sys.stderr.write("settings invalid or missing\\n")
        sys.exit(1)
if mode == "crash":
    sys.exit(7)
if mode == "hang":
    time.sleep(60)
if mode == "ignore_settings_ok":
    pass
os.execv(a[3], a[3:])
'''


def make_fake_deps(tmpdir, mode):
    d = os.path.join(tmpdir, "fakebin")
    os.makedirs(d, exist_ok=True)
    srt = os.path.join(d, "srt")
    with open(srt, "w") as f:
        f.write(FAKE_SRT)
    os.chmod(srt, os.stat(srt).st_mode | stat.S_IXUSR)
    with open(os.path.join(d, "mode"), "w") as f:
        f.write(mode)
    ok = lambda n, p: L.DepInfo(n, p, "x", True)
    return L.Dependencies({"srt": ok("srt", srt), "node": ok("node", "/usr/bin/env"),
                           "bwrap": ok("bwrap", "/usr/bin/env"), "socat": ok("socat", "/usr/bin/env"),
                           "rg": ok("rg", "/usr/bin/env")})
