/**
 * GCCC Members Area — Document Upload Apps Script
 *
 * SETUP (one-time, ~5 minutes):
 *
 * 1. Go to https://script.google.com and create a new project.
 *    Name it something like "GCCC Docs Upload".
 *
 * 2. Paste this entire file into the editor (replacing the default code).
 *
 * 3. Create two Google Drive folders:
 *    a. A STAGING folder (private) — where uploads first land.
 *    b. A VIEW folder (shared "Anyone with link — Viewer") — where files
 *       appear after the processing trigger moves them.
 *
 *    Paste each folder's ID below (the long string in the Drive URL after
 *    /folders/).
 *
 * 4. Deploy as a Web App:
 *    Deploy → New deployment → Web app
 *      Execute as: Me
 *      Who has access: Anyone (even anonymous)
 *    Copy the /exec URL — that's your DOCS_UPLOAD_ENDPOINT.
 *
 * 5. Set up the processing trigger:
 *    Triggers (clock icon) → Add trigger
 *      Function: processUploads
 *      Event source: Time-driven → Minutes timer → Every 5 minutes
 *
 * 6. Paste the /exec URL into DOCS_UPLOAD_ENDPOINT in members/index.html.
 *    Paste the VIEW folder share link into DOCS_VIEW_URL in members/index.html.
 */

// ── CONFIGURE THESE TWO VALUES ──────────────────────────────────────────────
var STAGING_FOLDER_ID = 'PASTE_YOUR_STAGING_FOLDER_ID_HERE';
var VIEW_FOLDER_ID    = 'PASTE_YOUR_VIEW_FOLDER_ID_HERE';
// ────────────────────────────────────────────────────────────────────────────

/**
 * Handles browser requests via JSONP (called by members/index.html).
 * Opens a Google Drive resumable upload session and returns the upload URL.
 */
function doGet(e) {
  var params   = e.parameter;
  var callback = params.callback || 'callback';
  var filename = params.filename || 'document';
  var mimeType = params.mimeType || 'application/octet-stream';
  var size     = parseInt(params.size, 10) || 0;
  var uploader = params.uploader || 'unknown';
  var notes    = params.notes    || '';

  try {
    // Stamp the filename with uploader tag and timestamp.
    var now = new Date();
    var stamp = Utilities.formatDate(now, Session.getScriptTimeZone(), 'yyyy-MM-dd HHmmss');
    var prefix = uploader ? uploader + ' — ' : '';
    var notesSuffix = notes ? ' (' + notes + ')' : '';
    var ext = filename.match(/(\.[^.]+)$/) ? filename.match(/(\.[^.]+)$/)[1] : '';
    var base = filename.replace(/(\.[^.]+)$/, '');
    var stamped = prefix + base + notesSuffix + ' [' + stamp + ']' + ext;

    var folder = DriveApp.getFolderById(STAGING_FOLDER_ID);
    var token  = ScriptApp.getOAuthToken();

    // Open a resumable upload session with the Drive API.
    var metadata = JSON.stringify({ name: stamped, parents: [STAGING_FOLDER_ID] });
    var response = UrlFetchApp.fetch(
      'https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable',
      {
        method: 'POST',
        headers: {
          'Authorization': 'Bearer ' + token,
          'Content-Type': 'application/json; charset=UTF-8',
          'X-Upload-Content-Type': mimeType,
          'X-Upload-Content-Length': size
        },
        payload: metadata,
        muteHttpExceptions: true
      }
    );

    var uploadUrl = response.getHeaders()['Location'];
    if (!uploadUrl) throw new Error('No upload URL from Drive API');

    var result = JSON.stringify({ ok: true, uploadUrl: uploadUrl });
    return ContentService.createTextOutput(callback + '(' + result + ')')
                         .setMimeType(ContentService.MimeType.JAVASCRIPT);

  } catch (err) {
    var errResult = JSON.stringify({ ok: false, error: String(err.message || err) });
    return ContentService.createTextOutput(callback + '(' + errResult + ')')
                         .setMimeType(ContentService.MimeType.JAVASCRIPT);
  }
}

/**
 * Triggered every 5 minutes. Moves completed uploads from staging → view folder.
 */
function processUploads() {
  if (STAGING_FOLDER_ID === 'PASTE_YOUR_STAGING_FOLDER_ID_HERE') return;
  if (VIEW_FOLDER_ID    === 'PASTE_YOUR_VIEW_FOLDER_ID_HERE')    return;

  var staging = DriveApp.getFolderById(STAGING_FOLDER_ID);
  var view    = DriveApp.getFolderById(VIEW_FOLDER_ID);
  var files   = staging.getFiles();

  while (files.hasNext()) {
    var file = files.next();
    // Only move files that are at least 30 seconds old (allow upload to finish).
    var ageMs = new Date() - file.getDateCreated();
    if (ageMs > 30000) {
      view.addFile(file);
      staging.removeFile(file);
    }
  }
}
