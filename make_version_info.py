"""Generate _version.py and version_info.txt (PyInstaller VERSIONINFO) from pyproject.toml.

Run before PyInstaller (hustle-on.spec also calls it, so any build is covered)."""
import os
import re

ROOT = os.path.dirname(os.path.abspath(__file__))
OWNER = "Sheriff Abdullah"


def read_version():
    with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as f:
        return re.search(r'(?m)^version\s*=\s*"([^"]+)"', f.read()).group(1)


def version_info_text(version):
    nums = [int(x) for x in re.findall(r"\d+", version)[:4]]
    nums += [0] * (4 - len(nums))
    t = tuple(nums)
    return f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(filevers={t}, prodvers={t}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', '{OWNER}'),
      StringStruct('FileDescription', 'HustleOn - keep Windows awake with the lid closed'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'hustle-on'),
      StringStruct('LegalCopyright', 'Copyright (c) 2026 {OWNER}. MIT License.'),
      StringStruct('OriginalFilename', 'hustle-on.exe'),
      StringStruct('ProductName', 'HustleOn'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def generate(root=ROOT):
    v = read_version()
    with open(os.path.join(root, "_version.py"), "w", encoding="utf-8") as f:
        f.write("__version__ = %r\n" % v)
    with open(os.path.join(root, "version_info.txt"), "w", encoding="utf-8") as f:
        f.write(version_info_text(v))
    return v


if __name__ == "__main__":
    print(generate())
