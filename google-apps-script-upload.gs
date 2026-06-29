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
 * Why the request comes in as a GET with a "callback":
 *   An Apps Script web app cannot send the CORS header a browser needs to read
 *   a normal cross-origin fetch() response. So the page calls this script via
 *   JSONP instead — a GET request whose result is wrapped in a callback. JSONP
 *   isn't subject to CORS, so it works reliably from the website.
 *
 * See UPLOAD-SETUP.md for full deployment instructions.
 */

// The shared Drive folder that uploads land in (the folder ID from your link).
var FOLDER_ID = '1gQwqY2Dm41JpdAWlGavz_fResDZ_4xmR';

/**
 * The website calls this via JSONP:
 *   ...exec?callback=FN&filename=...&mimeType=...&size=...&uploader=...
 * With no "filename", it's just a health check.
 */
function doGet(e) {
  var cb = (e && e.parameter && e.parameter.callback) || '';
  if (!e || !e.parameter || !e.parameter.filename) {
    return out({ ok: true, status: 'GCCC upload endpoint is running' }, cb);
  }
  return out(startSession(e.parameter), cb);
}

/** Kept so server-side/manual POSTs still work (not used by the browser). */
function doPost(e) {
  try {
    var body = (e && e.postData && e.postData.contents) ? JSON.parse(e.postData.contents) : {};
    return out(startSession(body), '');
  } catch (err) {
    return out({ ok: false, error: String(err) }, '');
  }
}

/**
 * Starts a Drive resumable upload session and returns its one-time URL.
 * Input: { filename, mimeType, size, uploader }
 */
function startSession(p) {
  try {
    if (!p || !p.filename) return { ok: false, error: 'Missing filename.' };

    // Touching DriveApp validates the folder AND ensures this script is
    // authorized with the Drive scope, so the OAuth token below works.
    var folder = DriveApp.getFolderById(FOLDER_ID);

    // Build a tidy, collision-resistant filename:
    //   [optional uploader] original-name (yyyy-MM-dd HHmmss).ext
    var stamp    = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd HHmmss');
    var original = sanitize(p.filename);
    var uploader = p.uploader ? sanitize(p.uploader) + ' - ' : '';
    var dot      = original.lastIndexOf('.');
    var base     = dot > 0 ? original.slice(0, dot) : original;
    var ext      = dot > 0 ? original.slice(dot)    : '';
    var finalName = uploader + base + ' (' + stamp + ')' + ext;

    var mimeType = p.mimeType || 'application/octet-stream';
    var metadata = { name: finalName, parents: [folder.getId()] };

    var initUrl = 'https://www.googleapis.com/upload/drive/v3/files'
                + '?uploadType=resumable&supportsAllDrives=true';

    var res = UrlFetchApp.fetch(initUrl, {
      method: 'post',
      contentType: 'application/json; charset=UTF-8',
      headers: {
        'Authorization': 'Bearer ' + ScriptApp.getOAuthToken(),
        'X-Upload-Content-Type': mimeType,
        'X-Upload-Content-Length': String(p.size || '')
      },
      payload: JSON.stringify(metadata),
      muteHttpExceptions: true
    });

    var code = res.getResponseCode();
    if (code < 200 || code >= 300) {
      return { ok: false, error: 'Could not start upload (HTTP ' + code + '): ' + res.getContentText().slice(0, 200) };
    }

    var headers = res.getAllHeaders();
    var uploadUrl = headers['Location'] || headers['location'];
    if (!uploadUrl) return { ok: false, error: 'No upload session URL returned by Drive.' };

    return { ok: true, uploadUrl: uploadUrl, name: finalName };
  } catch (err) {
    return { ok: false, error: String(err) };
  }
}

/**
 * Run this ONCE from the Apps Script editor (select authorizeOnce, click Run)
 * after adding the OAuth scopes to the manifest. It forces Google to show the
 * re-authorization prompt for the Drive + external-request scopes the resumable
 * upload needs. You should see "Authorized OK" in the execution log.
 */
function authorizeOnce() {
  DriveApp.getFolderById(FOLDER_ID).getName();
  UrlFetchApp.fetch('https://www.googleapis.com/drive/v3/about?fields=user', {
    headers: { 'Authorization': 'Bearer ' + ScriptApp.getOAuthToken() },
    muteHttpExceptions: true
  });
  Logger.log('Authorized OK');
}

// Strip characters that don't belong in a Drive filename.
function sanitize(name) {
  return String(name).replace(/[\\\/:*?"<>|]+/g, '_').slice(0, 120).trim();
}

// Return JSONP (callback-wrapped) when a callback is given, else plain JSON.
function out(obj, cb) {
  var json = JSON.stringify(obj);
  if (cb) {
    return ContentService
      .createTextOutput(cb + '(' + json + ');')
      .setMimeType(ContentService.MimeType.JAVASCRIPT);
  }
  return ContentService
    .createTextOutput(json)
    .setMimeType(ContentService.MimeType.JSON);
}
