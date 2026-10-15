# PyInstaller build: `pyinstaller folio.spec` (run on the target OS).
import sys

from PyInstaller.utils.hooks import collect_data_files

datas = [("folio/assets", "folio/assets")] + collect_data_files("pymupdf_fonts")

# Qt modules the app never uses: keeps the bundle lean.
excludes = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput", "PySide6.Qt3DExtras", "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation", "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQml", "PySide6.QtQuickWidgets",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtGraphs", "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning", "PySide6.QtLocation",
    "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtSpatialAudio", "PySide6.QtTextToSpeech",
    "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtStateMachine", "PySide6.QtHttpServer",
    "PySide6.QtWebSockets", "PySide6.QtNetworkAuth", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "tkinter", "unittest", "pytest", "numpy",
]

a = Analysis(
    ["run_folio.py"],
    pathex=["."],
    datas=datas,
    hiddenimports=["pymupdf_fonts"],
    excludes=excludes,
    noarchive=False,
)
# Pulled in by Qt plugins we do not need (QML, virtual keyboard, PDF image
# plugin, software OpenGL fallback).
DROP = ("opengl32sw", "Qt6Quick", "Qt6Qml", "Qt6Pdf", "Qt6VirtualKeyboard", "qtvirtualkeyboard", "qpdf",
        "libQt6Quick", "libQt6Qml", "libQt6Pdf", "libQt6VirtualKeyboard")
a.binaries = [b for b in a.binaries if not any(d in b[0].replace("\\", "/").split("/")[-1] for d in DROP)]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Folio" if sys.platform == "win32" else "folio",
    console=False,
    icon="folio/assets/folio.ico",
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Folio", upx=False)
