# 🚀 Employee Activity Monitor - Deployment Guide

This guide ensures you can deploy the complete monitoring system (Tracker + Admin Dashboard) to any new set of machines.

---

## 🏗 Part 1: Setting up the Backend (Admin Control Center)
*The backend should be hosted on a central server or a PC that is always on and accessible by the trackers.*

### Option A (Recommended): Deploy on Render

1. Push this repository to GitHub.
2. In Render, create a new **Web Service** from that GitHub repo.
3. Use these settings:
    - Root Directory: `backend`
    - Build Command: `npm install`
    - Start Command: `npm start`
4. Add environment variables in Render:
    - `MONGO_URI` (required)
    - `ADMIN_USERNAME` (required for admin access lock)
    - `ADMIN_PASSWORD` (required for admin access lock)
    - `GOOGLE_CLIENT_ID` (optional)
    - `NVIDIA_API_KEY` or `LLM_API_KEY` (optional)
5. Deploy and note your public URL, for example:
    - `https://your-app-name.onrender.com`

> This repo now includes `render.yaml` for blueprint-based deployment as well.

1.  **Install Node.js:** Ensure [Node.js](https://nodejs.org/) (v18+) is installed.
2.  **Environment Setup:**
    *   Navigate to the `backend/` folder.
    *   Create a file named `.env`.
    *   Paste your MongoDB Atlas URI and Google OAuth client ID (optional, only required if you want Google login on `setup.html`):
        ```env
        MONGO_URI=mongodb+srv://user:pass@cluster.mongodb.net/activity_monitor
        PORT=3000
        GOOGLE_CLIENT_ID=your_google_oauth_web_client_id.apps.googleusercontent.com
        ```
    *   In Google Cloud Console, add `http://localhost:3000` to **Authorized JavaScript origins** for that OAuth web client.
3.  **Install Dependencies:**
    ```bash
    npm install
    ```
4.  **Start the Server:**
    ```bash
    npm start
    ```
5.  **Access Admin Dashboard:**
    Open your browser to `http://<server-ip>:3000/admin.html`.
    You will be prompted for `ADMIN_USERNAME` and `ADMIN_PASSWORD`.

---

## 🕵️ Part 2: Preparing the Tracker (for Employee PCs)
*Perform these steps on your development PC before sending the files to employees.*

1.  **IMPORTANT: Clear Local Config:**
    *   Delete the folder `activity_data/` or at least the file `activity_data/config.json`.
    *   *If you don't do this, the new PC will "think" it is you and won't show the onboarding popup.*
2.  **Use Employee Distribution Page (NEW):**
    *   Open `/employee-distribution.html` on your hosted backend.
    *   Download either:
       - `employee-monitor-package.zip` (manual), or
       - `employee-bootstrap.ps1` (automated flow).
    *   The generated package now includes a `backend_url.txt` seed so monitors point to your live backend automatically.

---

## 💻 Part 3: Installing on a New PC
*Perform these steps on the target employee/tester's machine.*

1.  **Preferred (Windows): Run Bootstrap Script**
    *   PowerShell command:
      ```powershell
      powershell -ExecutionPolicy Bypass -Command "iwr -UseBasicParsing https://<your-render-url>/api/employee/bootstrap.ps1 -OutFile $env:TEMP\employee-bootstrap.ps1; & $env:TEMP\employee-bootstrap.ps1"
      ```
    *   This will:
      - Download and extract the employee package
      - Run `install.bat` twice
      - Open setup page with auto-close + auto-start hooks

2.  **Preferred (macOS): Direct Installer Download**
    *   Download `https://<your-render-url>/api/employee/macos-install.command`.
    *   Open Terminal and run:
      ```bash
      cd ~/Downloads
      chmod +x employee-monitor-macos-install.command
      ./employee-monitor-macos-install.command
      ```
    *   If Gatekeeper blocks execution, run:
      ```bash
      xattr -dr com.apple.quarantine ~/EmployeeMonitorPackage
      cd ~/EmployeeMonitorPackage
      ./install.sh
      ```

3.  **Preferred (Linux): Direct Installer Download**
    *   Download `https://<your-render-url>/api/employee/linux-install.sh`.
    *   Run:
      ```bash
      cd ~/Downloads
      chmod +x employee-monitor-linux-install.sh
      ./employee-monitor-linux-install.sh
      ```

4.  **Manual ZIP fallback (all platforms):**
    *   Extract the zip in a dedicated folder (e.g., `C:\Users\Public\Monitor`).
    *   Windows: run **`install.bat`**.
    *   macOS: run **`install.command`** (or `./install.sh` from Terminal).
    *   Linux: run **`./install.sh`** from Terminal.

5.  **Run Installer:**
    *   Run the platform installer from inside the extracted package folder.
    *   **What happens automatically:**
        *   Installs Python (if missing).
        *   Installs all Python libraries.
        *   Installs/validates Tesseract OCR.
        *   Triggers the **Onboarding Popup**.
6.  **Onboarding:**
    *   The employee fills in their `Employee ID`, `Company ID`, `Org Name`, and `User ID`.
    *   Once they click "Complete Setup," the monitor starts instantly.
7.  **Stealth Mode:**
    *   The folder will automatically become **Hidden** and marked as a **System File**.
    *   **Deletion Protection** is applied (Windows will block any attempt to delete the folder).
    *   A startup trigger is added to hiddenly launch the monitor every time the PC boots.

---

## 🎮 Part 4: Remote Management
*Manage everything from your Admin Dashboard.*

-   **To Pause/Resume:** Toggle the switch in `admin.html`. The PC will stop/start tracking within 30 seconds.
-   **To Uninstall Remotely:** Click the red **Decommission** button.
    *   The remote PC will remove its startup trigger.
    *   It will unlock the folder and delete itself permanently.
    *   The backend will wipe all reports and history for that user from the cloud database.
    *   If the employee device is offline, uninstall completes on its next check-in.

---

## 🛠 Troubleshooting
-   **No Popup?** Ensure `activity_data/config.json` was deleted before moving files to the new PC.
-   **Data not reaching DB?** Ensure your hosted backend is reachable and `backend_url.txt` in the package points to the live host.
-   **OCR issues?** The script installs Tesseract to `C:\Program Files\Tesseract-OCR`. Ensure this wasn't blocked by antivirus.
 -   **New single-step Windows installer:** A new `bootstrap_all.bat` launcher is included. Double-clicking `bootstrap_all.bat` runs the full install flow (it calls `install.bat` internally) and is the recommended entry point when deploying to many PCs.
 -   **Bundled Tesseract:** If you want the package ZIP to include a Tesseract installer (so target PCs can install offline), place a Windows installer EXE named like `tesseract-ocr-w64-setup-*.exe` in the repository root before building. The package builder will include any matching EXE in the Windows ZIP and the local installer will try it automatically.
-   **Not running after restart (Windows)?** Re-run `install.bat` once as the same user, then reboot. Installer now creates Startup VBS, Scheduled Task, and HKCU Run-key fallback.
-   **Folder not hidden (Windows)?** Installer now applies `attrib +h +s` to the package folder and all child files/folders recursively.
-   **Still not showing in admin?** Check local crash log at `activity_data/monitor_startup_crash.log` and `activity_monitor.log` in the installed package folder.

## 🚀 Deploying the Backend to Render

To make the updated package (including `bootstrap_all.bat` and any bundled Tesseract EXE) available for download, deploy the backend to Render and serve `/api/employee/package.zip` from that host.

Minimum steps:

1. Commit and push your changes to your Git repo (ensure any `tesseract-ocr-w64-setup-*.exe` you want bundled is checked in at the repository root).

2. Create a new Web Service on Render and connect your repository.

3. Configure the service build and start commands (the backend lives in `/backend`):

```bash
# Build (Render build command)
cd backend && npm install

# Start (Render start command)
cd backend && npm start
```

4. (Optional) Set any environment variables in the Render dashboard used by `server.js` (for example `TESSERACT_BUNDLE_WINDOWS` to point to a prebuilt path on the build host, or other deployment secrets required by your backend).

5. Deploy. After the service is live, the package URL will be `https://<your-render-host>/api/employee/package.zip` and the bootstrap scripts (`bootstrap.ps1`, `employee-monitor-linux-install.sh`, etc.) will be generated from the running backend.

Quick local test (before pushing): run the backend locally and verify the package endpoint:

```bash
cd backend
npm install
npm start
# then open: http://localhost:3000/api/employee/package.zip
```

If the ZIP contains `bootstrap_all.bat` and any `tesseract-ocr-w64-setup-*.exe`, the build is correct.
