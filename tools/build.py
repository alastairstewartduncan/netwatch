"""Builds NetWatch for release.

    python tools/build.py              app + installer + portable zip
    python tools/build.py --no-installer

Steps
  1. Writes version resources from nw/version.py (exe properties, installer defines, licence files)
  2. PyInstaller one-folder build -> dist/NetWatch/NetWatch.exe  (fast start-up, fewer antivirus false alarms)
  3. Optional code signing if NETWATCH_SIGN_CERT (+ NETWATCH_SIGN_PASSWORD) are set
  4. NSIS installer -> dist/NetWatch-Setup-<version>.exe
  5. Portable zip  -> dist/NetWatch-<version>-portable.zip
"""

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from nw.version import VERSION  # noqa: E402

DIST = ROOT / "dist"


def step(msg):
    print(f"\n=== {msg}", flush=True)


def run(cmd, **kw):
    print("  >", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=ROOT, **kw)


def find_makensis():
    for c in (shutil.which("makensis"),
              os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "NSIS", "makensis.exe"),
              os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "NSIS", "makensis.exe")):
        if c and os.path.exists(c):
            return c
    return None


def sign(paths):
    cert = os.environ.get("NETWATCH_SIGN_CERT")
    if not cert:
        return
    signtool = shutil.which("signtool")
    if not signtool:
        print("  ! NETWATCH_SIGN_CERT is set but signtool.exe wasn't found (install the Windows SDK) - skipping signing")
        return
    for p in paths:
        cmd = [signtool, "sign", "/f", cert, "/fd", "SHA256", "/tr", "http://timestamp.digicert.com", "/td", "SHA256",
               "/d", "NetWatch"]
        if os.environ.get("NETWATCH_SIGN_PASSWORD"):
            cmd += ["/p", os.environ["NETWATCH_SIGN_PASSWORD"]]
        run(cmd + [str(p)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-installer", action="store_true")
    args = ap.parse_args()
    if os.name != "nt":
        sys.exit("Build on Windows - PyInstaller can't cross-compile a Windows app.")

    step(f"NetWatch {VERSION}: version resources")
    run([sys.executable, "tools/make_version_info.py"])

    step("Packaging the app (PyInstaller)")
    shutil.rmtree(DIST / "NetWatch", ignore_errors=True)
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--noconsole",
         "--name", "NetWatch", "--icon", "assets/netwatch.ico", "--version-file", "build/version_info.txt",
         "--add-data", f"ui{os.pathsep}ui", "--collect-all", "webview", "--collect-all", "tplinkrouterc6u",
         "--hidden-import", "pystray._win32", "--hidden-import", "clr", "netwatch.py"])
    exe = DIST / "NetWatch" / "NetWatch.exe"
    if not exe.exists():
        sys.exit("PyInstaller didn't produce dist/NetWatch/NetWatch.exe")
    sign([exe])

    if not args.no_installer:
        step("Building the installer (NSIS)")
        makensis = find_makensis()
        if not makensis:
            print("  NSIS isn't installed. Install it with:\n      winget install -e --id NSIS.NSIS\n"
                  "  then run build.bat again. (The app itself is ready in dist\\NetWatch.)")
        else:
            run([makensis, "/V2", "installer/netwatch.nsi"])
            setup = DIST / f"NetWatch-Setup-{VERSION}.exe"
            sign([setup])
            print(f"  Installer: {setup}")

    step("Portable zip")
    z = DIST / f"NetWatch-{VERSION}-portable.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in (DIST / "NetWatch").rglob("*"):
            zf.write(f, Path("NetWatch") / f.relative_to(DIST / "NetWatch"))
        zf.write(ROOT / "LICENSE.txt", "NetWatch/LICENSE.txt")
        zf.write(ROOT / "THIRD-PARTY-NOTICES.txt", "NetWatch/THIRD-PARTY-NOTICES.txt")
    print(f"  Portable: {z}")
    print(f"\nDone - NetWatch {VERSION} is in {DIST}")


if __name__ == "__main__":
    main()
