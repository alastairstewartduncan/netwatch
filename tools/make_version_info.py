"""Writes build/version_info.txt (PyInstaller --version-file) and build/version.nsh (installer defines)
from nw/version.py, so the .exe properties, installer and app always agree on the version."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from nw import version as V  # noqa: E402

BUILD = ROOT / "build"


def main():
    BUILD.mkdir(exist_ok=True)
    vt = V.version_tuple()
    vs = ".".join(map(str, vt))
    (BUILD / "version_info.txt").write_text(f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(filevers={vt}, prodvers={vt}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('080904B0', [
      StringStruct('CompanyName', {V.PUBLISHER!r}),
      StringStruct('FileDescription', {(V.APP_NAME + ' - ' + V.DESCRIPTION)!r}),
      StringStruct('FileVersion', {vs!r}),
      StringStruct('InternalName', {V.APP_NAME!r}),
      StringStruct('LegalCopyright', {V.COPYRIGHT!r}),
      StringStruct('OriginalFilename', 'NetWatch.exe'),
      StringStruct('ProductName', {V.APP_NAME!r}),
      StringStruct('ProductVersion', {V.VERSION!r})])]),
    VarFileInfo([VarStruct('Translation', [2057, 1200])])
  ]
)
""", encoding="utf-8")
    (BUILD / "version.nsh").write_text(
        f'!define APP_NAME "{V.APP_NAME}"\n!define APP_VERSION "{V.VERSION}"\n!define APP_VERSION4 "{vs}"\n'
        f'!define APP_PUBLISHER "{V.PUBLISHER}"\n!define APP_COPYRIGHT "{V.COPYRIGHT}"\n'
        f'!define APP_DESCRIPTION "{V.DESCRIPTION}"\n!define APP_ID "{V.APP_ID}"\n', encoding="utf-8-sig")
    year = V.BUILD_DATE[:4]
    paras = [
        f"NetWatch - {V.DESCRIPTION}",
        f"Copyright (c) {year} {V.PUBLISHER}",
        "MIT License",
        "Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated "
        "documentation files (the \"Software\"), to deal in the Software without restriction, including without limitation "
        "the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to "
        "permit persons to whom the Software is furnished to do so, subject to the following conditions:",
        "The above copyright notice and this permission notice shall be included in all copies or substantial portions of "
        "the Software.",
        "THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO "
        "THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE "
        "AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, "
        "TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE "
        "SOFTWARE.",
        "Only use NetWatch's scanning features on networks you own or are authorised to manage.",
    ]
    # one line per paragraph so the installer's licence box can word-wrap it neatly
    (ROOT / "LICENSE.txt").write_text("\r\n\r\n".join(paras) + "\r\n", encoding="utf-8", newline="")
    notices = ["NetWatch includes the following third-party software, each under its own licence:", ""]
    notices += [f"  {n:<32} {lic:<30} {url}" for n, lic, url in V.CREDITS]
    notices += ["", "NetWatch can use these online services (some only when you turn them on):", ""]
    notices += [f"  {n:<32} {use:<30} {url}" for n, use, url in V.SERVICES]
    (ROOT / "THIRD-PARTY-NOTICES.txt").write_text("\n".join(notices) + "\n", encoding="utf-8")
    print(f"Version files written for {V.APP_NAME} {V.VERSION}")


if __name__ == "__main__":
    main()
