# Visitor Upload Page — Setup Guide

This repo includes an **unlisted** page at `/upload` (the file `upload/index.html`) that lets visitors upload
photos and videos straight into the club's shared Google Drive folder. Visitors
can **add** files but have **no way to view, list, or delete** anything in the
folder — they only ever talk to a small Google Apps Script endpoint that *only
creates* files.

Because GitHub Pages is static (no server), the saving-to-Drive is brokered by a
free Google Apps Script "web app" that runs as **you** (the folder owner). You
deploy it once, paste its URL into `upload/index.html`, and you're done.

**Large files (1 GB+ videos) are supported.** The script never receives the file
itself — it asks Google Drive to open a *resumable upload session* and hands the
browser a one-time upload URL. The browser then streams the file bytes **directly
to Google's upload servers** in chunks, so there's no practical size limit and a
brief network hiccup won't always restart the upload. That one-time URL can only
add the single new file; it can't read, list, or delete anything.

- **Upload page:** `upload/index.html` → lives at `https://gulfcoastcontestclub.org/upload`
- **Target Drive folder:** `1gQwqY2Dm41JpdAWlGavz_fResDZ_4xmR`
- **The script:** `google-apps-script-upload.gs`

The page is intentionally **not linked** anywhere in the site navigation and is
marked `noindex, nofollow` so search engines won't list it. Share the URL
directly with the people you want to be able to upload.

---

## One-time setup (about 5 minutes)

### 1. Create the Apps Script
1. Sign in to Google with the account that **owns** the Drive folder.
2. Go to **https://script.google.com** and click **New project**.
3. Delete the starter code, then copy in the entire contents of
   `google-apps-script-upload.gs` from this repo.
   - The folder ID is already filled in (`FOLDER_ID`). If you ever change the
     target folder, update that one line.
4. Click the **Save** icon (give the project a name like *GCCC Uploads*).

### 1a. Declare the OAuth scopes (required)
The resumable upload calls the Drive API directly, so the script must be granted
the **Drive** and **external request** scopes explicitly — otherwise Drive
rejects the upload with `403 insufficient authentication scopes`.

1. In the Apps Script editor, click **Project Settings** (⚙ on the left).
2. Tick **“Show ‘appsscript.json’ manifest file in the editor.”**
3. Open the **`appsscript.json`** file that now appears in the editor and make
   sure it contains an `oauthScopes` array with these two entries (copy from
   `appsscript.json` in this repo):
   ```json
   "oauthScopes": [
     "https://www.googleapis.com/auth/drive",
     "https://www.googleapis.com/auth/script.external_request"
   ]
   ```
4. **Save.**
5. Re-authorize: in the editor, choose the **`authorizeOnce`** function in the
   toolbar dropdown and click **Run**. Approve the new permissions when prompted
   (again, click **Advanced ▸ Go to … (unsafe)** if you see the unverified-app
   screen). You should see `Authorized OK` in the execution log.

> If you change scopes later, you must re-run `authorizeOnce` **and** redeploy a
> new version for the change to take effect.

### 2. Deploy it as a web app
1. Click **Deploy ▸ New deployment**.
2. Click the gear ⚙ next to "Select type" and choose **Web app**.
3. Set:
   - **Description:** `GCCC upload endpoint`
   - **Execute as:** **Me** (your email) — *this is what lets visitors upload
     without signing in.*
   - **Who has access:** **Anyone**
4. Click **Deploy**.
5. Click **Authorize access** and approve the permissions. The script asks to
   **see/manage your Drive** and to **connect to an external service** — both are
   needed so it can open the Drive upload session on a visitor's behalf. You may
   see a "Google hasn't verified this app" screen — click
   **Advanced ▸ Go to … (unsafe)**; it's your own script, this is normal.
6. Copy the **Web app URL**. It looks like:
   `https://script.google.com/macros/s/AKfy............/exec`

> Quick test: paste that URL into a browser. You should see
> `{"ok":true,"status":"GCCC upload endpoint is running"}`.

### 3. Connect the page to your script
1. Open `upload/index.html` in this repo.
2. Near the bottom, find this line:
   ```js
   var UPLOAD_ENDPOINT = "PASTE_YOUR_APPS_SCRIPT_WEB_APP_URL_HERE";
   ```
3. Replace the placeholder with the Web app URL you copied, e.g.:
   ```js
   var UPLOAD_ENDPOINT = "https://script.google.com/macros/s/AKfy............/exec";
   ```
4. Commit and push. Within a minute or two the live page will accept uploads.

---

## 4. Auto-publish uploads to a view-only gallery (optional)

Uploads first land in your **private staging folder** (`FOLDER_ID`). A background
job then moves them into a **public, view-only folder** so members can browse the
media — without being able to delete anything. After a successful upload the page
tells the visitor their files "will be viewable in a few minutes at" that folder.

**a. Create & share the view folder**
1. In Google Drive, create a folder (e.g. *GCCC Event Media*).
2. **Share** → General access → **Anyone with the link** → role **Viewer**. *(Viewer,
   not Editor — this is what makes it view-only: people can see and download, but
   not delete or change anything.)*
3. Copy its **folder ID** (the part of the URL after `/folders/`) and its **share link**.

**b. Point the script and page at it**
- In `google-apps-script-upload.gs`, set `VIEW_FOLDER_ID` to the view folder's ID.
- In `upload/index.html`, set `VIEW_FOLDER_URL` to the view folder's share link.
  *(Both are already filled in for the current folder — only change them if you
  use a different folder.)*

**c. Run the mover on a schedule**
1. In the Apps Script editor, click the **clock icon (Triggers)** on the left.
2. **+ Add Trigger** → Function: **`processUploads`** · Event source: **Time-driven**
   · Type: **Minutes timer** · **Every 5 minutes** → **Save**.
3. Approve permissions if prompted. From now on, anything uploaded is moved to the
   public view folder within ~5 minutes.

> Want to review media before it goes public? Just **don't** add the trigger —
> instead run `processUploads` yourself (or move files in Drive by hand) whenever
> you're ready to publish a batch.

> Keep the **staging** folder (`FOLDER_ID`) private. Only the **view** folder is
> shared publicly — and only as **Viewer**, so the public can't delete anything.

---

## How it works (and why visitors can't delete anything)

- When a visitor picks a file, the page POSTs only its **name, type, and size**
  to your Apps Script URL — never the file itself.
- The script asks Google Drive to open a **resumable upload session** targeting
  your folder and returns the session's one-time upload URL. Starting a session
  is the **only** Drive operation it performs — there is no code path that lists,
  reads, or deletes files, so a visitor literally cannot remove anything.
- The browser streams the file bytes **directly to Google's upload servers**
  using that URL. The session URL is bound to that single new file; it grants no
  other access to the folder.
- The script runs **as you**, so visitors never sign in and never get any access
  to the folder itself.
- The folder's own sharing settings are unchanged. Keep the folder private (or
  view-only) so the public share link can't be used to delete files either.

## Notes & limits

- **File size:** effectively unlimited for this use — multi-GB videos upload fine
  because the bytes go straight to Google, not through Apps Script. The page sets
  a 6 GB sanity ceiling and uploads in 16 MB chunks.
- **Keep the tab open:** for very large files, ask uploaders to keep the page
  open and their device awake until each file shows **Done ✓**.
- **Filenames:** uploads are saved as
  `[name/callsign] - original-name (date time).ext` so nothing overwrites
  anything and you can see who sent what.
- **Updating the script later:** after editing the `.gs` code, do
  **Deploy ▸ Manage deployments ▸ (edit) ▸ Version: New version ▸ Deploy**. The
  URL stays the same, so you don't need to touch `upload/index.html` again.
- **Cost:** free, within normal Google quotas.
