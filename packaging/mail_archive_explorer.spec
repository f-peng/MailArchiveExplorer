# -*- mode: python -*-
# Build : pyinstaller packaging/mail_archive_explorer.spec  (depuis la racine du dépôt)
import sys
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None
EXCLUDES = [  # modules Qt jamais utilisés : réduisent la taille
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput", "PySide6.Qt3DLogic", "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras", "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtBluetooth",
    "PySide6.QtNfc", "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtSerialBus", "PySide6.QtTest",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtSql", "PySide6.QtQuick3D", "PySide6.QtRemoteObjects",
    "PySide6.QtScxml", "PySide6.QtStateMachine", "PySide6.QtTextToSpeech", "PySide6.QtSpatialAudio",
    "PySide6.QtLocation", "PySide6.QtGraphs", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "tkinter", "unittest", "pydoc",
]

a = Analysis(
    ["launcher.py"],
    pathex=["../src"],
    binaries=[],
    datas=[("../LICENSE", "."), ("../THIRD_PARTY_NOTICES.md", ".")],
    hiddenimports=["pypff"] + collect_submodules("mail_archive_explorer"),
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="MailArchiveExplorer",
          console=False, disable_windowed_traceback=False, argv_emulation=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="MailArchiveExplorer")
if sys.platform == "darwin":
    app = BUNDLE(coll, name="MailArchiveExplorer.app", bundle_identifier="org.mailarchiveexplorer.app",
                 info_plist={"CFBundleShortVersionString": "0.1.0", "NSHighResolutionCapable": True})
