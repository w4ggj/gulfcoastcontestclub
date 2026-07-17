/**
 * GCCC Members Area — Wishlist Request Apps Script
 *
 * SETUP (one-time, ~3 minutes):
 *
 * 1. Go to https://script.google.com and create a new project.
 *    Name it something like "GCCC Wishlist".
 *
 * 2. Paste this entire file into the editor (replacing the default code).
 *
 * 3. Deploy as a Web App:
 *    Deploy → New deployment → Web app
 *      Execute as: Me
 *      Who has access: Anyone (even anonymous)
 *    Copy the /exec URL.
 *
 * 4. Paste the /exec URL into WISHLIST_ENDPOINT in members/index.html.
 *
 * That's it. On the very first wishlist submission, this script
 * automatically creates a "GCCC Wishlist Requests" Google Sheet in your
 * Drive and adds a header row. All future submissions append to it.
 * Find the sheet at drive.google.com.
 */

var SHEET_NAME = 'Requests';

/**
 * Returns (or creates on first call) the spreadsheet and target sheet.
 */
function getSheet() {
  var props = PropertiesService.getScriptProperties();
  var ssId  = props.getProperty('WISHLIST_SS_ID');

  var ss;
  if (ssId) {
    try { ss = SpreadsheetApp.openById(ssId); } catch (e) { ssId = null; }
  }

  if (!ssId) {
    ss   = SpreadsheetApp.create('GCCC Wishlist Requests');
    ssId = ss.getId();
    props.setProperty('WISHLIST_SS_ID', ssId);

    var sheet = ss.getActiveSheet();
    sheet.setName(SHEET_NAME);
    sheet.appendRow(['Timestamp', 'Callsign', 'Category', 'Description', 'Status']);
    sheet.setFrozenRows(1);

    // Make the header row bold and resize columns for readability.
    sheet.getRange(1, 1, 1, 5).setFontWeight('bold');
    sheet.setColumnWidth(1, 160);
    sheet.setColumnWidth(2, 90);
    sheet.setColumnWidth(3, 140);
    sheet.setColumnWidth(4, 420);
    sheet.setColumnWidth(5, 100);
  }

  var sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) {
    sheet = ss.insertSheet(SHEET_NAME);
    sheet.appendRow(['Timestamp', 'Callsign', 'Category', 'Description', 'Status']);
    sheet.setFrozenRows(1);
    sheet.getRange(1, 1, 1, 5).setFontWeight('bold');
  }

  return sheet;
}

/**
 * Handles wishlist form submissions from members/index.html via JSONP.
 */
function doGet(e) {
  var params      = e.parameter;
  var callback    = params.callback    || 'callback';
  var callsign    = (params.callsign    || '').trim().toUpperCase();
  var category    = (params.category    || 'Other').trim();
  var description = (params.description || '').trim();

  try {
    if (!callsign)    throw new Error('Callsign is required.');
    if (!description) throw new Error('Description is required.');

    var sheet = getSheet();
    var timestamp = Utilities.formatDate(
      new Date(),
      Session.getScriptTimeZone(),
      'yyyy-MM-dd HH:mm:ss'
    );

    sheet.appendRow([timestamp, callsign, category, description, 'Open']);

    var result = JSON.stringify({ ok: true });
    return ContentService.createTextOutput(callback + '(' + result + ')')
                         .setMimeType(ContentService.MimeType.JAVASCRIPT);

  } catch (err) {
    var errResult = JSON.stringify({ ok: false, error: String(err.message || err) });
    return ContentService.createTextOutput(callback + '(' + errResult + ')')
                         .setMimeType(ContentService.MimeType.JAVASCRIPT);
  }
}
