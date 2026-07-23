from setuptools import setup

APP = ['main.py']
DATA_FILES = []
OPTIONS = {
    'argv_emulation': False,
    'plist': {
        'CFBundleName': 'HS Arena Plus',
        'CFBundleDisplayName': 'HS Arena Plus',
        'CFBundleIdentifier': 'com.local.hs-arena-plus',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'NSHighResolutionCapable': True,
        'NSScreenCaptureDescription': 'HS Arena Plus needs screen access to read Hearthstone card names during arena draft.',
        'NSAppleEventsUsageDescription': 'HS Arena Plus uses Apple Vision for card name recognition.',
        'LSUIElement': True,  # menu bar app, no dock icon
    },
    'packages': [
        'PyQt6', 'PIL', 'requests', 'difflib',
        'AppKit', 'Quartz', 'Vision', 'Foundation',
    ],
    'includes': [
        'ratings', 'overlay', 'screen_watcher', 'synergy',
        'app', 'settings_window', 'ui_settings', 'calibrate',
    ],
    'excludes': ['pytesseract', 'tkinter'],
}

setup(
    app=APP,
    name='HS Arena Plus',
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
