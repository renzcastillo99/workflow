# DocTracker: build and test guide

## Part A: Checks for you (on your Windows laptop, about 20 minutes)

These are the Windows-only parts that could not be tested in the cloud.

### A1. Get the new app.py
Download `doctracker/app.py` from GitHub (branch `claude/admiring-dirac-9jjjih`) and
replace the copy in `C:\Users\rj.castillo\OneDrive - EGIS Group\Desktop\DocTracker\`.

### A2. Run it the normal way first
Open **Command Prompt** in that folder (in File Explorer, click the address bar, type `cmd`, press Enter):

```bat
python -m pip install flask openpyxl
python app.py
```

The browser should open on DocTracker. Click **Load sample data** on the Documents page.

### A3. Open file / Open folder
| Do this | Expected |
|---|---|
| Click **Open file** on any row | The PDF opens in your PDF reader |
| Click **Open folder** on the same row | File Explorer opens with that PDF **highlighted** |
| Open a document, set **Signed/Approved**, choose a signed copy in the box that appears, click **Save**, then **Open signed copy** | The signed file opens. In tracker.xlsx, **Signed Copy Link** is filled in and clickable |
| Click **Open Excel file** | tracker.xlsx opens in Excel (leave it open for A4) |

### A4. Save while Excel has tracker.xlsx open
With tracker.xlsx still open in Excel:
1. Go to **Upload**, choose a PDF, type a subject, From and notes, then click **Save document**.
   * Expected: the red "Close tracker.xlsx and try again..." message. The subject, From and
     notes are still filled in, and it says **File kept**.
2. Close Excel, then click **Save document** again **without choosing the file again**.
   * Expected: "Saved as DOC-...". The document appears in the list.
3. Repeat with Excel open: change a status on a document page, and add a department in Settings.
   Each should show the same friendly message. Close Excel, retry, and it saves.

### A5. Storage folder on a mapped network drive
1. Create a folder on the network drive, for example `Z:\Scans`.
2. In **Settings**, set **Storage folder** to `Z:\Scans` and click **Save settings**.
3. Upload a PDF. Expected: saved, and the file appears in `Z:\Scans` named `DOC-....pdf`.
4. Click **Open file** and **Open folder** for that document. Both should work.
5. Optional: disconnect the drive (or unplug the network) and open the document page.
   Expected: a message saying the file or storage folder is missing, not a crash.
   Reconnect afterwards.
6. Set the storage folder back if Z: was only for testing. Old links will show as
   missing until you do, and that is expected.

Stop the app with **Ctrl+C** in the Command Prompt window.

### A6. Build the double-click version
Build **outside OneDrive**. Otherwise OneDrive tries to sync hundreds of build files.

```bat
mkdir C:\DocTrackerBuild
copy "C:\Users\rj.castillo\OneDrive - EGIS Group\Desktop\DocTracker\app.py" C:\DocTrackerBuild\
cd /d C:\DocTrackerBuild
python -m pip install pyinstaller
python -m PyInstaller --onedir --noconsole --name DocTracker app.py
```

The app is the whole folder `C:\DocTrackerBuild\dist\DocTracker\`. Keep the `_internal`
folder next to `DocTracker.exe`, because the exe does not work without it.

**Where the data lives:** DocTracker keeps `tracker.xlsx`, its backup, the `Files` folder
(the scanned PDFs) and the `Exports` folder **in the same folder as DocTracker.exe**. They are
created the first time it starts.

> ⚠️ **Rebuilding deletes `dist\DocTracker`, including tracker.xlsx and every PDF in it.**
> PyInstaller asks *"...will be REMOVED! Continue? (y/N)"*. Answer **N** if real data is in there.
> For daily use, copy the finished folder somewhere safe, so a rebuild can never touch it:
>
> 1. In File Explorer, copy `C:\DocTrackerBuild\dist\DocTracker` and paste it as `C:\DocTracker`.
> 2. Use `C:\DocTracker\DocTracker.exe` from now on. Right-click it > **Show more options** >
>    **Send to** > **Desktop (create shortcut)**.
> 3. To update the app later: rebuild, then copy **only** `DocTracker.exe` and the `_internal`
>    folder into `C:\DocTracker`, replacing the old ones. Leave tracker.xlsx, Files and Exports alone.
>
> Don't put the folder in `C:\Program Files`; Windows won't let the app save there. If you
> move the whole folder later, it keeps working, and the links inside tracker.xlsx are updated
> automatically the next time DocTracker starts.

### A7. Test the double-click version
| Do this | Expected |
|---|---|
| Double-click the desktop shortcut | No black window. The browser opens DocTracker within a few seconds |
| Close the browser tab, then double-click the shortcut again | The browser reopens on the **same** DocTracker (same address, e.g. `127.0.0.1:5000`) |
| Double-click the shortcut twice quickly | Still only one DocTracker. Task Manager shows one **DocTracker** under background processes. (You may also see a second DocTracker.exe line under it; that is the helper PyInstaller adds and is normal.) |
| Task Manager > DocTracker > **End task**, then double-click again | It starts fresh and your data is still there |

If nothing happens on double-click, open `doctracker_log.txt` in the DocTracker folder.
Any error is written there.

**Company laptop note:** Windows SmartScreen or EGIS antivirus may warn about or block a
new unsigned .exe. If so, click **More info > Run anyway** if allowed, or ask IT to allow
`C:\DocTracker\DocTracker.exe`.

---

## Part B: 10-step checklist to run WITH the end user

Sit next to them and let **them** click. Tick each box. Write down anything that confused them.

| # | Ask them to... | It passes if... | ✓ |
|---|---|---|---|
| 1 | Double-click the **DocTracker** icon on the desktop | The DocTracker page opens in the browser by itself | ☐ |
| 2 | Click **Upload scanned PDF**, choose a real scan, fill in Subject, From and Date received, then click **Save document** | A green "Saved as DOC-2026-...." message appears | ☐ |
| 3 | Click **Back to list** | The new document is at the top with status **Received** | ☐ |
| 4 | Click **Open file**, then **Open folder** on that row | The PDF opens; then the folder opens with the file highlighted | ☐ |
| 5 | Open the document, pick a department under **Route to department**, then click **Save** | Status becomes **Routed**, and a new line appears under **History** | ☐ |
| 6 | Change the status to **Signed/Approved** and click **Save** *without* a file. Then choose the signed scan in the **Signed copy** box that appears, click **Save**, then **Open signed copy** | First Save is refused ("must have its signed copy"). Second Save works, and the signed file opens. In tracker.xlsx the **Signed Copy Link** column is filled in | ☐ |
| 7 | Set the status to **Completed** and click **Save** | The History shows all steps in order; the list shows "-" under Waiting | ☐ |
| 8 | Type part of the subject in the **Search** box and click **Filter**, then try the status filter | Only matching documents show; **Clear** brings all back | ☐ |
| 9 | Click **Open Excel file**, leave Excel open, change any status in the app and click **Save** | A clear "Close tracker.xlsx..." message appears; after closing Excel and clicking **Save** again, it saves | ☐ |
| 10 | Close the browser, then double-click the icon again. Click **Export to Excel** | The same documents are still there; a green "Exported to ..." message shows where the copy was saved | ☐ |

**Before handing over:** if you used **Load sample data** while testing, those six fake
documents (marked "SAMPLE" in Notes) are in tracker.xlsx. To start clean: end DocTracker in
Task Manager, then in the DocTracker folder delete (or move somewhere else) `tracker.xlsx`,
`tracker_backup.xlsx`, `Files` and `Exports`. **Do not delete `DocTracker.exe` or `_internal`.**
A fresh, empty tracker is created on the next start.
