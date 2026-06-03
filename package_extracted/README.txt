Employee Monitor Windows package

This archive is generated live from the Render backend so it always includes the latest app files and backend URL.

Included files:
- monitor.py
- install_and_run.py
- requirements.txt
- backend_url.txt
- backend/public/setup.html
- backend/public/employee-distribution.html

Launcher:
- Windows: bootstrap_all.bat (preferred) or install.bat
- macOS and Linux: install.sh

If a bundled Tesseract directory is present in this ZIP, installer/runtime will use it first.
Expected bundled paths inside ZIP:
- Windows: tesseract/tesseract.exe
- Linux/macOS: tesseract/bin/tesseract

If bundle is missing, installer falls back to system/package-manager install.
You can force bundle source on backend build host with env vars:
- TESSERACT_BUNDLE_WINDOWS
- TESSERACT_BUNDLE_LINUX
- TESSERACT_BUNDLE_MACOS

Launch the installer from this folder, or run it from a terminal with the platform launcher.

Recommended Windows entry point:
- Double-click bootstrap_all.bat for a single-step install.
- It will hand off to install.bat after setting up the package context.

Backend URL:
https://eyeing.onrender.com

macOS Access Notes (Gatekeeper):
1) Open the extracted package folder and double-click install.command.
2) If Gatekeeper blocks it, open Terminal and run these commands inside the extracted folder:
  xattr -dr com.apple.quarantine .
  chmod +x install.sh install.command
  ./install.sh

Tip: Use the direct bootstrap download from employee-distribution.html to avoid manual unzip/chmod steps.
