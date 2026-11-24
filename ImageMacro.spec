# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

source = Path(SPECPATH) / 'src'
icon = str(source / 'image-macro.ico')
datas = [(icon, '.')] + collect_data_files('tkinterdnd2')
analysis = Analysis(
    [str(source / 'app.py')],
    datas=datas,
    excludes=['matplotlib', 'scipy', 'pandas', 'torch'],
)
pyz = PYZ(analysis.pure)
exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name='Image Macro',
          console=False, upx=False, icon=icon)
collection = COLLECT(exe, analysis.binaries, analysis.datas, upx=False, name='Image Macro')
