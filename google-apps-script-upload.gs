/**
 * GCCC visitor upload endpoint (Google Apps Script).
 *
 * Lets visitors upload photos and LARGE videos (multi-GB) into the club's
 * shared Google Drive folder WITHOUT signing in — and with no way to list,
 * view, or delete anything.
 *
 * How large files are handled:
 *   The browser cannot send a 1 GB file through Apps Script (Apps Script caps
 *   a POST at ~50 MB). Instead, this script starts a Google Drive *resumable
 *   upload session* on the visitor's behalf and returns a one-time session URL.
 *   The browser then streams the file bytes DIRECTLY to Google's upload
 *   servers using that URL — bypassing Apps Script entirely, so there is no
 *   size limit. The session URL is scoped to that single new file: it cannot
 *   be used to read, list, or delete any other file in the folder.
 *
 * See UPLOAD-SETUP.md for full deployment instructions.
 */

// The shared Drive folder that uploads land in (the folder ID from your link).
var FOLDER_ID = '1gQwqY2Dm41JpdAWlGavz_fResDZ_4xmR';

/**
 * Starts a resumable upload session and returns its one-time URL to the browser.
 * Request body is a JSON string: { filename, mimeType, size, uploader }
 */
function doPost(e) {
  try {
    if (!e || !e.postData || !e.postData.contents) {
      return jsonOut({ ok: false, error: 'No data received.' });
    }

    var body = JSON.parse(e.postData.contents);

    // Touching DriveApp here validates the folder AND ensures this script is
    // authorized with the Drive scope, so the OAuth token below works.
    var folder = DriveApp.getFolderById(FOLDER_ID);

    // Build a tidy, collision-resistant filename:
    //   [optional uploader] original-name (yyyy-MM-dd HHmmss).ext
    var stamp    = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd HHmmss');
    var original = sanitize(body.filename || 'upload');
    var uploader = body.uploader ? sanitize(body.uploader) + ' - ' : '';
    var dot      = original.lastIndexOf('.');
    var base     = dot > 0 ? original.slice(0, dot) : original;
    var ext      = dot > 0 ? original.slice(dot)    : '';
    var finalName = uploader + base + ' (' + stamp + ')' + ext;

    var mimeType = body.mimeType || 'application/octet-stream';

    var metadata = { name: finalName, parents: [folder.getId()] };

    var initUrl = 'https://www.googleapis.com/upload/drive/v3/files'
                + '?uploadType=resumable&supportsAllDrives=true';

    var res = UrlFetchApp.fetch(initUrl, {
      method: 'post',
      contentType: 'application/json; charset=UTF-8',
      headers: {
        'Authorization': 'Bearer ' + ScriptApp.getOAuthToken(),
        'X-Upload-Content-Type': mimeType,
        'X-Upload-Content-Length': String(body.size || '')
      },
      payload: JSON.stringify(metadata),
      muteHttpExceptions: true
    });

    var code = res.getResponseCode();
    if (code < 200 || code >= 300) {
      return jsonOut({ ok: false, error: 'Could not start upload (HTTP ' + code + '): ' + res.getContentText().slice(0, 300) });
    }

    var headers = res.getAllHeaders();
    var uploadUrl = headers['Location'] || headers['location'];
    if (!uploadUrl) {
      return jsonOut({ ok: false, error: 'No upload session URL returned by Drive.' });
    }

    return jsonOut({ ok: true, uploadUrl: uploadUrl, name: finalName });
  } catch (err) {
    return jsonOut({ ok: false, error: String(err) });
  }
}

/**
 * Open the web app URL in a browser to confirm the deployment is live —
 * you should see {"ok":true,"status":"GCCC upload endpoint is running"}.
 */
function doGet() {
  return jsonOut({ ok: true, status: 'GCCC upload endpoint is running' });
}

// Strip characters that don't belong in a Drive filename.
function sanitize(name) {
  return String(name).replace(/[\\\/:*?"<>|]+/g, '_').slice(0, 120).trim();
}

function jsonOut(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
