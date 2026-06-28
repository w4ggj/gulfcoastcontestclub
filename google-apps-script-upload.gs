/**
 * GCCC visitor upload endpoint (Google Apps Script).
 *
 * Receives photo/video uploads from upload.html and saves each file into the
 * club's shared Google Drive folder. Visitors can ADD files but have no way to
 * list, view, or delete anything in the folder — they only ever talk to this
 * endpoint, which only creates files.
 *
 * See UPLOAD-SETUP.md for full step-by-step deployment instructions.
 */

// The shared Drive folder that uploads land in.
// This is the folder ID from the share link you provided.
var FOLDER_ID = '1gQwqY2Dm41JpdAWlGavz_fResDZ_4xmR';

/**
 * Handles file uploads POSTed from the website.
 * The body is a JSON string: { filename, mimeType, uploader, data(base64) }
 */
function doPost(e) {
  try {
    if (!e || !e.postData || !e.postData.contents) {
      return jsonOut({ ok: false, error: 'No data received.' });
    }

    var body = JSON.parse(e.postData.contents);

    if (!body.data) {
      return jsonOut({ ok: false, error: 'No file data.' });
    }

    var bytes = Utilities.base64Decode(body.data);
    var mime  = body.mimeType || 'application/octet-stream';
    var blob  = Utilities.newBlob(bytes, mime, body.filename || 'upload');

    // Build a tidy, collision-resistant filename:
    //   [optional uploader] original-name  (yyyy-MM-dd HHmmss)
    var stamp    = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd HHmmss');
    var original = sanitize(body.filename || 'upload');
    var uploader = body.uploader ? sanitize(body.uploader) + ' - ' : '';

    var dot      = original.lastIndexOf('.');
    var base     = dot > 0 ? original.slice(0, dot) : original;
    var ext      = dot > 0 ? original.slice(dot)    : '';
    var finalName = uploader + base + ' (' + stamp + ')' + ext;

    blob.setName(finalName);

    var folder = DriveApp.getFolderById(FOLDER_ID);
    var file   = folder.createFile(blob);

    return jsonOut({ ok: true, id: file.getId(), name: file.getName() });
  } catch (err) {
    return jsonOut({ ok: false, error: String(err) });
  }
}

/**
 * Lets you confirm the deployment is live by opening the web app URL
 * in a browser — you should see {"ok":true,"status":"GCCC upload endpoint is running"}.
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
