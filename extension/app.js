// DOM Elements
const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const consentCheckbox = document.getElementById('consent');
const convertBtn = document.getElementById('convert-btn');
const convertBtnText = document.getElementById('convert-btn-text');
const valutaAsBookingCheckbox = document.getElementById('valuta-as-booking');
const previewWarningCard = document.getElementById('preview-warning-card');
const previewWarningTitle = document.getElementById('preview-warning-title');
const previewWarningBody = document.getElementById('preview-warning-body');
const fileNameDisplay = document.getElementById('file-name');
const fileSizeDisplay = document.getElementById('file-size');
const fileInfo = document.getElementById('file-info');
const btnRemove = document.getElementById('btn-remove');
const btnLoadDemo = document.getElementById('btn-load-demo');
const limitBar = document.getElementById('limit-bar');

const serverStatusBadge = document.getElementById('server-status');
const serverStatusText = document.getElementById('server-status-text');
const btnOpenTab = document.getElementById('btn-open-tab');

const statusCard = document.getElementById('status-card');
const statusSpinner = document.getElementById('status-spinner');
const statusText = document.getElementById('status-text');

// Conflict, Safeguards & Filter Elements
const conflictCard = document.getElementById('conflict-card');
const conflictList = document.getElementById('conflict-list');
const duplicateCard = document.getElementById('duplicate-card');
const duplicateText = document.getElementById('duplicate-text');
const filterChipsBar = document.getElementById('filter-chips-bar');
const rowPopover = document.getElementById('row-popover');

// Tabs
const tabConvert = document.getElementById('tab-convert');
const tabHistory = document.getElementById('tab-history');

// Views
const uploadView = document.getElementById('upload-view');
const previewView = document.getElementById('preview-view');
const historyView = document.getElementById('history-view');
const historyList = document.getElementById('history-list');
const btnClearHistory = document.getElementById('btn-clear-history');
const btnUpgradePro = document.getElementById('btn-upgrade-pro');

const previewCount = document.getElementById('preview-count');
const previewTotal = document.getElementById('preview-total');
const previewTableBody = document.getElementById('preview-table-body');
const searchInput = document.getElementById('search-input');
const btnDownloadCsv = document.getElementById('btn-download-csv');
const btnDownloadCsvText = document.getElementById('btn-download-csv-text');
const btnExpandPreview = document.getElementById('btn-expand-preview');
const btnNewConvert = document.getElementById('btn-new-convert');

let selectedFiles = [];
let isDemoActive = false;
let backendOnline = false;
let currentCsvBlob = null;
let currentExportBytes = null;
let currentCsvMime = 'text/csv;charset=windows-1252;';
let currentCsvFilename = 'Muster.csv';
let currentCsvText = '';
let currentAccountsFound = [];
let currentDuplicatesCount = 0;
let parsedTransactions = [];
let activeAccountFilter = 'ALL';
let apiBaseUrl = 'http://127.0.0.1:8000';
let loupeEnabled = true;
let currentOperationId = null;
let currentCanonicalResult = null;
let currentExportSource = 'offline'; // 'backend' | 'offline' | 'demo'
let currentSelectedFormat = 'datev';
let exportRequestSeq = 0;
let activeOperationGen = 0;
let activeExportGen = 0;
let activeConvertController = null;
let activeExportController = null;

function invalidatePendingOperations(reason = 'reset') {
  activeOperationGen++;
  activeExportGen++;
  exportRequestSeq++;
  if (activeConvertController) {
    try { activeConvertController.abort(reason); } catch (_) {}
    activeConvertController = null;
  }
  if (activeExportController) {
    try { activeExportController.abort(reason); } catch (_) {}
    activeExportController = null;
  }
  currentOperationId = null;
  currentExportBytes = null;
  currentCsvBlob = null;
  currentCsvText = '';
  currentCsvFilename = '';
  if (btnDownloadCsv) btnDownloadCsv.disabled = true;
}

// Windows-1252 Encoding Mapping for DATEV / BMD NTCS Compatibility
const WIN1252_LOOKUP = {
  0x20ac: 0x80, 0x201a: 0x82, 0x0192: 0x83, 0x201e: 0x84, 0x2026: 0x85, 0x2020: 0x86, 0x2021: 0x87,
  0x02c6: 0x88, 0x2030: 0x89, 0x0160: 0x8a, 0x2039: 0x8b, 0x0152: 0x8c, 0x017d: 0x8e,
  0x2018: 0x91, 0x2019: 0x92, 0x201c: 0x93, 0x201d: 0x94, 0x2022: 0x95, 0x2013: 0x96,
  0x2014: 0x97, 0x02dc: 0x98, 0x2122: 0x99, 0x0161: 0x9a, 0x203a: 0x9b, 0x0153: 0x9c,
  0x017e: 0x9e, 0x0178: 0x9f
};

function encodeWindows1252Strict(str) {
  const bytes = new Uint8Array(str.length);
  let unrepresentableCount = 0;
  for (let i = 0; i < str.length; i++) {
    const code = str.charCodeAt(i);
    if (code <= 0x7f) {
      bytes[i] = code;
    } else if (code >= 0xa0 && code <= 0xff) {
      bytes[i] = code;
    } else if (WIN1252_LOOKUP[code]) {
      bytes[i] = WIN1252_LOOKUP[code];
    } else {
      bytes[i] = 0x3f;
      unrepresentableCount++;
    }
  }
  return { bytes, unrepresentableCount };
}

function encodeWindows1252(str) {
  return encodeWindows1252Strict(str).bytes;
}

function encodeUtf8WithBom(str) {
  const body = new TextEncoder().encode(str);
  const out = new Uint8Array(3 + body.length);
  out[0] = 0xef; out[1] = 0xbb; out[2] = 0xbf;
  out.set(body, 3);
  return out;
}

function buildBlobForFormat(csvText, fmt) {
  if (fmt === 'bmd_bankauszug') {
    const cleanText = csvText.startsWith('\uFEFF') ? csvText.slice(1) : csvText;
    const bytes = encodeUtf8WithBom(cleanText);
    const mime = 'text/csv;charset=utf-8;';
    return { bytes, blob: new Blob([bytes], { type: mime }), mime, unrepresentableCount: 0 };
  }
  const { bytes, unrepresentableCount } = encodeWindows1252Strict(csvText);
  const mime = fmt === 'datev' ? 'text/plain;charset=windows-1252;' : 'text/csv;charset=windows-1252;';
  return { bytes, blob: new Blob([bytes], { type: mime }), mime, unrepresentableCount };
}

function getSelectedFormat() {
  const checkedPreview = document.querySelector('input[name="export-format"]:checked');
  const checkedUpload = document.querySelector('input[name="upload-export-format"]:checked');
  return (checkedPreview && checkedPreview.value) || (checkedUpload && checkedUpload.value) || currentSelectedFormat || 'datev';
}

function syncFormatSelection(fmt) {
  currentSelectedFormat = fmt || 'datev';
  document.querySelectorAll('input[name="export-format"]').forEach(r => { r.checked = (r.value === currentSelectedFormat); });
  document.querySelectorAll('input[name="upload-export-format"]').forEach(r => { r.checked = (r.value === currentSelectedFormat); });
  if (convertBtnText) {
    if (currentSelectedFormat === 'bmd_bankauszug') {
      convertBtnText.textContent = 'In BMD Bankauszug (22 Sp.) konvertieren';
    } else if (currentSelectedFormat === 'bmd') {
      convertBtnText.textContent = 'In BMD NTCS (8 Sp.) konvertieren';
    } else {
      convertBtnText.textContent = 'In DATEV (EXTF) konvertieren';
    }
  }
  updateDownloadButtonText();
}

function showPreviewWarnings(messages, isBlocked = false) {
  if (!previewWarningCard || !previewWarningBody || !previewWarningTitle) return;
  const clean = (messages || []).filter(Boolean);
  if (!clean.length) {
    previewWarningCard.classList.add('hidden');
    previewWarningBody.innerHTML = '';
    return;
  }
  previewWarningTitle.textContent = isBlocked ? 'Export blockiert — Prüfung erforderlich' : 'Hinweis zur Buchungsprüfung';
  previewWarningBody.innerHTML = clean.map(m => `<div style="margin-top:2px;">• ${escapeHtml(m)}</div>`).join('');
  previewWarningCard.classList.remove('hidden');
}

// Realistic Demo Bank Transactions for 1-Click Reviewer Testing
const SAMPLE_TRANSACTIONS = [
  { date: '14.04.2026', text: 'AMZN MKTP DE*NW0077AI4 AMZN.COM/BILL (Referenzwechselkurs 1,085 EUR/USD)', amountStr: '-74,10', numericVal: -74.10, isCredit: false, account: 'American Express (*22001)', card: '22001', file: 'Demo_Amex.pdf' },
  { date: '14.04.2026', text: 'AMZN MKTP DE*NW3K650C4 AMZN.COM/BILL', amountStr: '-26,18', numericVal: -26.18, isCredit: false, account: 'American Express (*22001)', card: '22001', file: 'Demo_Amex.pdf' },
  { date: '15.04.2026', text: 'OPENAI *CHATGPT SUBSCR SAN FRANCISCO (Auslandseinsatz 1,5%)', amountStr: '-17,32', numericVal: -17.32, isCredit: false, account: 'American Express (*22001)', card: '22001', file: 'Demo_Amex.pdf' },
  { date: '16.04.2026', text: 'AMZN MKTP DE*NW9G68QI4 AMZN.COM/BILL', amountStr: '-10,24', numericVal: -10.24, isCredit: false, account: 'American Express (*22001)', card: '22001', file: 'Demo_Amex.pdf' },
  { date: '16.04.2026', text: 'AMZN MKTP DE*NW1M77QR4 AMZN.COM/BILL', amountStr: '-39,66', numericVal: -39.66, isCredit: false, account: 'American Express (*22001)', card: '22001', file: 'Demo_Amex.pdf' },
  { date: '16.04.2026', text: 'AMZN MKTP DE*NW4ZR8Q04 AMZN.COM/BILL', amountStr: '-64,90', numericVal: -64.90, isCredit: false, account: 'American Express (*22001)', card: '22001', file: 'Demo_Amex.pdf' },
  { date: '17.04.2026', text: 'AMAZON.DE*NW0UT97D4 AMAZON.DE', amountStr: '-11,99', numericVal: -11.99, isCredit: false, account: 'American Express (*22001)', card: '22001', file: 'Demo_Amex.pdf' },
  { date: '18.04.2026', text: 'AMZN MKTP DE*NW0XP3I24 AMZN.COM/BILL', amountStr: '-21,99', numericVal: -21.99, isCredit: false, account: 'American Express (*22001)', card: '22001', file: 'Demo_Amex.pdf' },
  { date: '28.04.2026', text: 'PAYPAL *SPORTONAGMB 60434031850', amountStr: '-88,61', numericVal: -88.61, isCredit: false, account: 'Wise Business (EUR)', card: '', file: 'Demo_Wise.csv' },
  { date: '28.04.2026', text: 'AMAZON.DE*NN3GK5G54 AMAZON.DE', amountStr: '-29,27', numericVal: -29.27, isCredit: false, account: 'Wise Business (EUR)', card: '', file: 'Demo_Wise.csv' },
  { date: '28.04.2026', text: 'AMAZON.DE*NN0O75GM4 AMAZON.DE', amountStr: '-125,09', numericVal: -125.09, isCredit: false, account: 'Wise Business (EUR)', card: '', file: 'Demo_Wise.csv' },
  { date: '30.04.2026', text: 'NETFLIX.COM AMSTERDAM', amountStr: '-29,97', numericVal: -29.97, isCredit: false, account: 'Wise Business (EUR)', card: '', file: 'Demo_Wise.csv' },
  { date: '01.05.2026', text: 'AIRBNB * HMSENZMYZC LONDON', amountStr: '-1750,52', numericVal: -1750.52, isCredit: false, account: 'Wise Business (EUR)', card: '', file: 'Demo_Wise.csv' },
  { date: '02.05.2026', text: 'GUTSCHRIFT KUNDENZAHLUNG RE-2026-88', amountStr: '2450,00', numericVal: 2450.00, isCredit: true, account: 'Wise Business (EUR)', card: '', file: 'Demo_Wise.csv' }
];

// Initialize loupe user preference
chrome.storage.local.get(['loupeEnabled'], (res) => {
  loupeEnabled = res.loupeEnabled !== false;
});

function showLoupeToast(msg) {
  let toast = document.getElementById('loupe-toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'loupe-toast';
    toast.className = 'loupe-toast';
    document.body.appendChild(toast);
  }
  toast.innerHTML = msg;
  toast.classList.add('show');
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => {
    toast.classList.remove('show');
  }, 2200);
}

const isFullTab = window.innerWidth > 600 || window.location.search.includes('mode=tab');

// Setup full tab responsive mode
if (isFullTab) {
  document.body.classList.add('full-tab');
  if (btnExpandPreview) btnExpandPreview.style.display = 'none';
}

// Tab Switching
tabConvert.addEventListener('click', () => {
  tabConvert.classList.add('active');
  tabHistory.classList.remove('active');
  historyView.classList.add('hidden');
  
  if (currentCsvText && previewView.classList.contains('hidden') === false) {
    previewView.classList.remove('hidden');
    uploadView.classList.add('hidden');
  } else {
    uploadView.classList.remove('hidden');
    previewView.classList.add('hidden');
  }
});

tabHistory.addEventListener('click', () => {
  tabHistory.classList.add('active');
  tabConvert.classList.remove('active');
  uploadView.classList.add('hidden');
  previewView.classList.add('hidden');
  historyView.classList.remove('hidden');
  renderHistoryView();
});

// Open app in new tab / toggle sidepanel
if (btnOpenTab) {
  if (isFullTab) {
    // In full-screen tab: convert button to "Dock to Sidepanel"
    btnOpenTab.title = 'In Seitenleiste andocken (Sidepanel)';
    btnOpenTab.innerHTML = `
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <rect width="18" height="18" x="3" y="3" rx="2"/>
        <path d="M15 3v18"/>
        <path d="m8 9 3 3-3 3"/>
      </svg>
    `;
    btnOpenTab.addEventListener('click', async () => {
      const stateToSave = {
        lastConvertedCsv: currentCsvText || '',
        lastConvertedFilename: currentCsvFilename || 'Muster.csv',
        lastConvertedFormat: currentSelectedFormat || 'datev',
        lastAccountsFound: currentAccountsFound || [],
        lastDuplicatesCount: currentDuplicatesCount || 0
      };

      // Safely persist state
      if (typeof chrome !== 'undefined' && chrome.storage && chrome.storage.local) {
        try {
          chrome.storage.local.set(stateToSave);
        } catch (storageErr) {
          console.warn('Storage save failed:', storageErr);
        }
      }

      // Check Side Panel API support
      if (typeof chrome === 'undefined' || !chrome.sidePanel || !chrome.sidePanel.open) {
        showToast('Side Panel API wird in diesem Browser-Kontext nicht unterstützt. Der Tab bleibt geöffnet.');
        return;
      }

      // Attempt to open sidepanel under direct user gesture
      try {
        const currentWindow = await chrome.windows.getCurrent();
        await chrome.sidePanel.open({ windowId: currentWindow.id });
        // Only close window if sidePanel.open succeeded!
        window.close();
      } catch (e) {
        console.warn('Could not open sidepanel automatically:', e);
        showToast('Seitenleiste konnte nicht automatisch geöffnet werden. Bitte nutzen Sie das Erweiterungs-Icon in der Leiste.');
      }
    });
  } else {
    // In sidepanel: expand to full tab and close sidepanel to avoid duplicate window!
    btnOpenTab.addEventListener('click', () => {
      const stateToSave = {
        lastConvertedCsv: currentCsvText || '',
        lastConvertedFilename: currentCsvFilename || 'Muster.csv',
        lastConvertedFormat: currentSelectedFormat || 'datev',
        lastAccountsFound: currentAccountsFound || [],
        lastDuplicatesCount: currentDuplicatesCount || 0
      };
      chrome.storage.local.set(stateToSave, () => {
        const targetUrl = currentCsvText 
          ? chrome.runtime.getURL('sidepanel.html?view=preview&mode=tab')
          : chrome.runtime.getURL('sidepanel.html?mode=tab');
        chrome.tabs.create({ url: targetUrl }, () => {
          try {
            window.close();
          } catch (e) {
            console.warn('Could not close sidepanel window:', e);
          }
        });
      });
    });
  }
}

// Expand Preview Table into Full Tab
if (btnExpandPreview) {
  btnExpandPreview.addEventListener('click', () => {
    if (currentCsvText) {
      chrome.storage.local.set({
        lastConvertedCsv: currentCsvText,
        lastConvertedFilename: currentCsvFilename,
        lastConvertedFormat: currentSelectedFormat || 'datev',
        lastAccountsFound: currentAccountsFound,
        lastDuplicatesCount: currentDuplicatesCount
      }, () => {
        chrome.tabs.create({ url: chrome.runtime.getURL('sidepanel.html?view=preview&mode=tab') }, () => {
          try {
            window.close();
          } catch (e) {}
        });
      });
    }
  });
}

// Check URL params on initial load
const urlParams = new URLSearchParams(window.location.search);
if (urlParams.get('view') === 'preview') {
  chrome.storage.local.get(['lastConvertedCsv', 'lastConvertedFilename', 'lastConvertedFormat', 'lastAccountsFound', 'lastDuplicatesCount'], (result) => {
    if (result.lastConvertedCsv) {
      const fmt = result.lastConvertedFormat || 'datev';
      syncFormatSelection(fmt);
      currentCsvText = result.lastConvertedCsv;
      currentCsvFilename = result.lastConvertedFilename || 'Muster.csv';
      currentAccountsFound = result.lastAccountsFound || [];
      currentDuplicatesCount = result.lastDuplicatesCount || 0;
      const built = buildBlobForFormat(result.lastConvertedCsv, fmt);
      currentExportBytes = built.bytes;
      currentCsvMime = built.mime;
      currentCsvBlob = built.blob;

      displayPreview(result.lastConvertedCsv);
      renderSafeguards(currentAccountsFound, currentDuplicatesCount);
    }
  });
}

// Format file size
function formatBytes(bytes) {
  if (bytes === 0) return '0 Bytes';
  const k = 1024;
  const sizes = ['Bytes', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

// Check Backend Health (Hybrid mode: in-browser engine is always active; local server is optional)
async function checkBackendHealth() {
  const candidates = ['https://api.statement2muster.com', 'http://127.0.0.1:8000', 'http://localhost:8000'];
  for (const url of candidates) {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 1200);
      const res = await fetch(`${url}/api/v1/health`, { method: 'GET', signal: controller.signal });
      clearTimeout(timeoutId);
      if (res.ok) {
        apiBaseUrl = url;
        backendOnline = true;
        serverStatusBadge.className = 'server-badge online';
        serverStatusText.textContent = 'Server Engine aktiv';
        refreshEntitlementDisplay();
        return true;
      }
    } catch (e) {
      // try next
    }
  }
  backendOnline = false;
  serverStatusBadge.className = 'server-badge online';
  serverStatusText.textContent = 'Lokal aktiv (In-Memory)';
  return false;
}

// Start backend health monitoring
checkBackendHealth();
setInterval(checkBackendHealth, 5000);

// Drag & Drop Listeners
dropZone.addEventListener('click', () => fileInput.click());

['dragenter', 'dragover'].forEach(eventName => {
  dropZone.addEventListener(eventName, (e) => {
    e.preventDefault();
    e.stopPropagation();
    dropZone.classList.add('dragover');
  });
});

['dragleave', 'drop'].forEach(eventName => {
  dropZone.addEventListener(eventName, (e) => {
    e.preventDefault();
    e.stopPropagation();
    dropZone.classList.remove('dragover');
  });
});

dropZone.addEventListener('drop', (e) => {
  const files = Array.from(e.dataTransfer.files);
  if (files && files.length > 0) {
    handleFiles(files);
  }
});

fileInput.addEventListener('change', (e) => {
  const files = Array.from(e.target.files);
  if (files && files.length > 0) {
    handleFiles(files);
  }
});

btnRemove.addEventListener('click', (e) => {
  e.stopPropagation();
  clearFile();
});

// 1-Click Demo Statement Loader for Reviewer and Users
if (btnLoadDemo) {
  btnLoadDemo.addEventListener('click', (e) => {
    e.stopPropagation();
    invalidatePendingOperations('demo_selected');
    isDemoActive = true;
    selectedFiles = [{
      name: 'Demo_Auszug_Musterdaten.csv',
      size: 2450,
      isDemo: true
    }];
    fileNameDisplay.textContent = '✨ Demo-Auszug (14 Musterbuchungen geladen)';
    fileSizeDisplay.textContent = 'Bereit zur Konvertierung';
    fileInfo.classList.remove('hidden');
    dropZone.classList.add('hidden');
    hideStatus();
    checkState();
    showLoupeToast('✨ <strong>Musterdaten geladen!</strong> Wählen Sie Ihr Zielformat und starten Sie die Konvertierung.');
  });
}

consentCheckbox.addEventListener('change', checkState);

function handleFiles(files) {
  invalidatePendingOperations('new_files');
  isDemoActive = false;
  const validExts = ['.csv', '.pdf'];
  const validFiles = files.filter(f => validExts.includes(f.name.substring(f.name.lastIndexOf('.')).toLowerCase()));
  
  if (validFiles.length === 0) {
    showStatus('error', 'Nur PDF- oder CSV-Dateien werden unterstützt.');
    return;
  }

  selectedFiles = validFiles;
  
  if (validFiles.length === 1) {
    fileNameDisplay.textContent = validFiles[0].name;
    fileSizeDisplay.textContent = formatBytes(validFiles[0].size);
  } else {
    fileNameDisplay.textContent = `⚡ ${validFiles.length} Auszüge ausgewählt (Multi-Upload PRO)`;
    const totalSize = validFiles.reduce((acc, f) => acc + f.size, 0);
    fileSizeDisplay.textContent = `Gesamt: ${formatBytes(totalSize)}`;
  }
  
  fileInfo.classList.remove('hidden');
  dropZone.classList.add('hidden');
  hideStatus();
  checkState();
}

function clearFile() {
  invalidatePendingOperations('clear');
  currentCanonicalResult = null;
  selectedFiles = [];
  isDemoActive = false;
  fileInput.value = '';
  fileInfo.classList.add('hidden');
  dropZone.classList.remove('hidden');
  hideStatus();
  checkState();
}

if (valutaAsBookingCheckbox) {
  valutaAsBookingCheckbox.addEventListener('change', () => {
    invalidatePendingOperations('valuta_changed');
  });
}

function checkState() {
  chrome.storage.local.get(['conversionsLeft', 'userSession'], (result) => {
    const isPro = result.userSession && result.userSession.isLoggedIn;
    let left = result.conversionsLeft !== undefined ? result.conversionsLeft : 3;
    const hasFiles = (selectedFiles && selectedFiles.length > 0) || isDemoActive;
    const hasConsent = consentCheckbox ? consentCheckbox.checked : true;
    const canConvert = hasFiles && hasConsent && (isPro || left > 0 || isDemoActive);
    
    if (convertBtn) {
      convertBtn.disabled = !canConvert;
    }
  });
}

function showStatus(type, message) {
  statusCard.className = `status-card ${type}`;
  statusCard.classList.remove('hidden');
  statusText.textContent = message;

  if (type === 'processing') {
    statusSpinner.classList.remove('hidden');
  } else {
    statusSpinner.classList.add('hidden');
  }
}

function hideStatus() {
  statusCard.classList.add('hidden');
}

// Client-Side Normalization Helpers
function normalizeDate(d) {
  if (!d) return '';
  d = d.trim().split(' ')[0];
  let day = 0, month = 0, year = 0;
  let m = d.match(/^(\d{4})[-\/\.](\d{1,2})[-\/\.](\d{1,2})/);
  if (m) {
    year = parseInt(m[1], 10);
    month = parseInt(m[2], 10);
    day = parseInt(m[3], 10);
  } else {
    m = d.match(/^(\d{1,2})[\/\.](\d{1,2})[\/\.](\d{2,4})/);
    if (m) {
      day = parseInt(m[1], 10);
      month = parseInt(m[2], 10);
      let y = m[3];
      if (y.length === 2) y = '20' + y;
      year = parseInt(y, 10);
    }
  }
  if (!m || month < 1 || month > 12 || day < 1 || day > 31) return '';
  const testDate = new Date(year, month - 1, day);
  if (testDate.getFullYear() !== year || testDate.getMonth() !== month - 1 || testDate.getDate() !== day) {
    return ''; // Invalid calendar date (e.g. 31.02)
  }
  return `${String(day).padStart(2, '0')}.${String(month).padStart(2, '0')}.${year}`;
}

function normalizeAmount(val) {
  if (!val) return '0,00';
  let str = String(val).trim().replace(/[€$£\s]/g, '');
  let isNegative = false;
  if (str.endsWith('-') || str.startsWith('-') || str.endsWith('S') || str.endsWith('s')) {
    isNegative = true;
  }
  if (str.endsWith('CR') || str.endsWith('cr') || str.endsWith('H') || str.endsWith('h') || str.startsWith('+')) {
    isNegative = false;
  }
  str = str.replace(/[+\-SsHhCRcr]/g, '').trim();

  if (str.includes(',') && str.includes('.')) {
    if (str.lastIndexOf(',') > str.lastIndexOf('.')) {
      str = str.replace(/\./g, '').replace(',', '.');
    } else {
      str = str.replace(/,/g, '');
    }
  } else if (str.includes(',')) {
    str = str.replace(',', '.');
  }

  let num = parseFloat(str);
  if (isNaN(num)) num = 0;
  if (isNegative && num > 0) num = -num;

  const fixed = Math.abs(num).toFixed(2).replace('.', ',');
  return (num < 0 ? '-' : '') + fixed;
}

// Client-Side CSV Parser for Wise, PayPal, Bank CSVs
function parseCsvClientSide(csvText, filename = 'statement.csv') {
  const lines = csvText.split(/\r?\n/).map(l => l.trim()).filter(l => l.length > 0);
  if (lines.length < 2) return { transactions: [], accounts: [] };

  const sample = lines[0];
  let delimiter = ';';
  const semiCount = (sample.match(/;/g) || []).length;
  const commaCount = (sample.match(/,/g) || []).length;
  const tabCount = (sample.match(/\t/g) || []).length;
  if (tabCount > semiCount && tabCount > commaCount) delimiter = '\t';
  else if (commaCount > semiCount) delimiter = ',';

  function parseCsvLine(line, delim) {
    const result = [];
    let cur = '';
    let inQuotes = false;
    for (let i = 0; i < line.length; i++) {
      const c = line[i];
      if (c === '"') {
        if (inQuotes && line[i + 1] === '"') {
          cur += '"';
          i++;
        } else {
          inQuotes = !inQuotes;
        }
      } else if (c === delim && !inQuotes) {
        result.push(cur.trim());
        cur = '';
      } else {
        cur += c;
      }
    }
    result.push(cur.trim());
    return result;
  }

  const headerRow = parseCsvLine(lines[0], delimiter).map(h => h.toLowerCase().replace(/['"]/g, ''));
  
  let dateIdx = headerRow.findIndex(h => h.includes('datum') || h.includes('date') || h.includes('valuta') || h.includes('tag') || h.includes('zeit'));
  let textIdx = headerRow.findIndex(h => h.includes('text') || h.includes('beschreibung') || h.includes('description') || h.includes('verwendungszweck') || h.includes('name') || h.includes('empfänger') || h.includes('begünstigter') || h.includes('partner'));
  let amountIdx = headerRow.findIndex(h => h.includes('betrag') || h.includes('amount') || h.includes('umsatz') || h.includes('wert') || h.includes('summe') || h.includes('saldo'));
  let currIdx = headerRow.findIndex(h => h.includes('währung') || h.includes('currency') || h.includes('curr'));

  if (dateIdx === -1) dateIdx = 0;
  if (textIdx === -1) textIdx = 1 < headerRow.length ? 1 : 0;
  if (amountIdx === -1) amountIdx = 2 < headerRow.length ? 2 : 1;

  const isWise = filename.toLowerCase().includes('wise') || csvText.includes('TransferWise') || csvText.includes('Wise');
  const accountHolder = isWise ? 'Wise Business' : (filename.replace(/\.[^/.]+$/, "") || 'Bank CSV');

  const transactions = [];
  for (let i = 1; i < lines.length; i++) {
    const cols = parseCsvLine(lines[i], delimiter);
    if (!cols || cols.length <= Math.max(dateIdx, amountIdx)) continue;

    let dateVal = cols[dateIdx] || '';
    let textVal = cols[textIdx] || '';
    let amountVal = cols[amountIdx] || '';
    let currVal = currIdx !== -1 && cols[currIdx] ? cols[currIdx] : 'EUR';

    if (!dateVal || !amountVal) continue;

    dateVal = normalizeDate(dateVal);
    amountVal = normalizeAmount(amountVal);

    transactions.push({
      date: dateVal,
      text: textVal,
      amountStr: amountVal,
      currency: currVal || 'EUR',
      belegNr: `CSV-${transactions.length + 1}`,
      konto: '',
      account: accountHolder,
      sourceFile: filename
    });
  }

  return {
    transactions,
    accounts: [{ name: accountHolder, card: '', count: transactions.length, files: [filename] }]
  };
}

// Client-side strict validation & parity helpers (Erste Bank / Visa / BMD 22-col / DATEV EXTF)
function parseStrictDmyClient(raw) {
  if (!raw) return null;
  const s = String(raw).trim();
  const m = s.match(/^(\d{2})\.(\d{2})\.(\d{4})$/);
  if (!m) return null;
  const d = parseInt(m[1], 10), mo = parseInt(m[2], 10), y = parseInt(m[3], 10);
  const dt = new Date(Date.UTC(y, mo - 1, d));
  if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== mo - 1 || dt.getUTCDate() !== d) return null;
  return `${m[1]}.${m[2]}.${m[3]}`;
}

function isValidIbanClient(iban) {
  const cleaned = String(iban || '').replace(/\s+/g, '').toUpperCase();
  if (!/^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$/.test(cleaned)) return false;
  if (cleaned.startsWith('AT') && cleaned.length !== 20) return false;
  if (cleaned.startsWith('DE') && cleaned.length !== 22) return false;
  const rearranged = cleaned.slice(4) + cleaned.slice(0, 4);
  let mod = 0;
  for (let i = 0; i < rearranged.length; i++) {
    const ch = rearranged.charCodeAt(i);
    const digits = (ch >= 65 && ch <= 90) ? String(ch - 55) : rearranged[i];
    for (let j = 0; j < digits.length; j++) {
      mod = (mod * 10 + Number(digits[j])) % 97;
    }
  }
  return mod === 1;
}

function parseStrictEurCentsClient(raw) {
  if (!raw) return null;
  const cleaned = String(raw)
    .replace(/\u00a0/g, ' ')
    .replace(/\u202f/g, ' ')
    .replace(/\u2212/g, '-')
    .replace(/EUR|€/gi, '')
    .trim();
  const m = cleaned.match(/^([+-]?)\s*(\d{1,3}(?:\.\d{3})*|\d+),(\d{2})\s*([+-]?)$/);
  if (!m) return null;
  const lead = m[1], intPart = m[2], decPart = m[3], trail = m[4];
  if (lead && trail) return null;
  if (intPart.includes('.')) {
    const grp = intPart.split('.');
    if (grp[0].length < 1 || grp[0].length > 3 || grp.slice(1).some(g => g.length !== 3)) return null;
  }
  const cents = parseInt(intPart.replace(/\./g, ''), 10) * 100 + parseInt(decPart, 10);
  if (lead === '-' || trail === '-') return cents === 0 ? 0 : -cents;
  return cents;
}

function formatCentsCommaClient(cents) {
  const n = Number(cents) || 0;
  if (n === 0) return '0,00';
  const sign = n < 0 ? '-' : '';
  const absC = Math.abs(Math.round(n));
  return `${sign}${Math.floor(absC / 100)},${String(absC % 100).padStart(2, '0')}`;
}

function formatIsoOrDmyToDmy(val) {
  if (!val) return '';
  if (/^\d{2}\.\d{2}\.\d{4}$/.test(val)) return val;
  const m = String(val).match(/^(\d{4})-(\d{2})-(\d{2})/);
  return m ? `${m[3]}.${m[2]}.${m[1]}` : String(val);
}

function formatDmyToIso(val) {
  if (!val) return null;
  if (/^\d{4}-\d{2}-\d{2}$/.test(val)) return val;
  const m = String(val).match(/^(\d{2})\.(\d{2})\.(\d{4})$/);
  return m ? `${m[3]}-${m[2]}-${m[1]}` : null;
}

function sanitizeCsvTextClient(val) {
  let s = String(val || '').replace(/[\r\n\t]+/g, ' ').trim();
  if (s && ['=', '+', '-', '@'].includes(s[0])) s = "'" + s;
  return s;
}

function sanitizeCsvFieldClient(val) {
  const s = sanitizeCsvTextClient(val);
  if (/[;"\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

function csvQuoteAllCell(val) {
  const cleaned = String(val ?? '').replace(/\r/g, '').replace(/\n/g, ' ');
  return `"${cleaned.replace(/"/g, '""')}"`;
}

function parseDmyOrAmtToCents(amountStr) {
  const c = parseStrictEurCentsClient(amountStr);
  if (c !== null) return c;
  const n = parseFloat(String(amountStr || '0').replace(/\./g, '').replace(',', '.'));
  return isNaN(n) ? 0 : Math.round(n * 100);
}

// In-Browser PDF Text Extraction using Mozilla PDF.js (visual Y-line / X-coord ordered)
async function extractTextFromPdf(arrayBuffer) {
  if (typeof pdfjsLib === 'undefined') {
    throw new Error('PDF-Engine wird geladen. Bitte kurz warten oder Demo-Auszug testen.');
  }
  pdfjsLib.GlobalWorkerOptions.workerSrc = chrome.runtime.getURL('lib/pdf.worker.min.js');
  const loadingTask = pdfjsLib.getDocument({ data: arrayBuffer });
  const pdfDoc = await loadingTask.promise;
  const pageTexts = [];
  const lowTextPages = [];
  for (let p = 1; p <= pdfDoc.numPages; p++) {
    const page = await pdfDoc.getPage(p);
    const content = await page.getTextContent();
    const lines = [];
    for (const item of content.items) {
      const str = (item.str || '').trim();
      if (!str) continue;
      const x = item.transform && typeof item.transform[4] === 'number' ? item.transform[4] : 0;
      const y = item.transform && typeof item.transform[5] === 'number' ? item.transform[5] : 0;
      let line = lines.find(l => Math.abs(l.y - y) <= 3.0);
      if (!line) {
        line = { y, items: [] };
        lines.push(line);
      }
      line.items.push({ x, str });
    }
    lines.sort((a, b) => b.y - a.y);
    const pageStr = lines.map(l => {
      l.items.sort((a, b) => a.x - b.x);
      return l.items.map(it => it.str).join(' ');
    }).join('\n');
    pageTexts.push(pageStr);
    if (pageStr.trim().length < 20) lowTextPages.push(p);
  }
  return { text: pageTexts.join('\n'), pageTexts, lowTextPages };
}

function classifyErstePartnerClient(extraLines, line1Text) {
  if (!extraLines || !extraLines.length) return { partner: null, rest: [] };
  const cand = extraLines[0].trim();
  const low = cand.toLowerCase();
  const skipPrefixes = ['kartenendnummer', 's visa card', 's mastercard', 'iban', 'bic', 'mandatsreferenz', 'gläubiger-id', 'referenz', 'reklamationen', 'verwendungszweck', 'kurs', 'entgelt'];
  if (!cand || skipPrefixes.some(p => low.startsWith(p)) || low.includes('iban') || /\b(?:AT|DE)\d{2}\s?\d{4}/.test(cand)) {
    return { partner: null, rest: extraLines };
  }
  if ((line1Text || '').toLowerCase().includes('kreditkartenrechnung') && low.includes('visa card')) {
    return { partner: null, rest: extraLines };
  }
  const hasCompanyMarker = /\b(gmbh|ag|kg|og|ug|e\.u\.|ltd|limited|inc\.?|mbh|bank|wien|österreich|austria|finanzamt|gericht)\b/i.test(cand) || /^(HG|BG|LG)\s/.test(cand);
  const isCleanName = /^[A-ZÄÖÜ][A-Za-zÄÖÜäöüß&\.\-]+(?:\s+[A-ZÄÖÜa-zäöüß&\.\-]+){1,4}$/.test(cand) && !/\d/.test(cand);
  if (hasCompanyMarker || isCleanName) {
    return { partner: cand, rest: extraLines.slice(1) };
  }
  return { partner: null, rest: extraLines };
}

function parseErsteBankTextClientSide(extracted, filename, useValuta) {
  const pageTexts = typeof extracted === 'string' ? [extracted] : (extracted.pageTexts || [extracted.text || '']);
  const warnings = [];
  const errors = [];
  if (extracted.lowTextPages && extracted.lowTextPages.length > 0 && pageTexts.some(t => t.trim().length >= 50)) {
    errors.push(`Seite(n) ${extracted.lowTextPages.join(', ')} enthalten keine lesbare Textebene (Misch-PDF).`);
  }

  let accountIban = '';
  let currency = 'EUR';
  const currMatch = (pageTexts[0] || '').match(/Betr[äa]ge\/Amounts\s+in\s+([A-Z]{3})/i);
  if (currMatch) currency = currMatch[1].toUpperCase();

  let holder = 'Erste Bank Austria';
  const p1Lines = (pageTexts[0] || '').split('\n').map(l => l.trim()).filter(Boolean);
  for (let i = 1; i < p1Lines.length; i++) {
    if (p1Lines[i].toLowerCase().includes('zuletzt gültiger kontowortlaut')) {
      if (!/erste bank|sparkasse|am belvedere/i.test(p1Lines[i - 1])) {
        holder = p1Lines[i - 1];
      }
      break;
    }
  }

  const segments = [];
  const transactions = [];
  let activeSeg = null;
  const rowRe = /^(.+?)\s+(\d{2}\.\d{2}\.\d{4})(?:\s*\*)?\s+([+-]?\s*(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2}\s*[+-]?)$/;

  for (let idx = 0; idx < pageTexts.length; idx++) {
    const pText = pageTexts[idx];
    const pageNum = idx + 1;
    if (pText.trim().length < 20) continue;

    let candIbanRaw = '';
    const mIbanLine = pText.match(/IBAN\s*:\s*([^\r\n]+)/i);
    if (mIbanLine) {
      const tail = mIbanLine[1].split(/(?:^|\s)\b(?:BIC|SWIFT)\b\s*:?/i)[0].trim();
      const tok = tail.match(/^([A-Z]{2}\d{2}(?:[ \t]*[A-Z0-9]{1,4}){2,8})/i);
      candIbanRaw = tok ? tok[1] : (tail.split(/\s+/)[0] || '');
    } else {
      const mStand = pText.match(/\b(AT\d{2}(?:\s?\d{4}){4})\b/);
      if (mStand) candIbanRaw = mStand[1];
    }
    if (candIbanRaw) {
      const candIban = candIbanRaw.replace(/\s+/g, '').toUpperCase();
      if (!isValidIbanClient(candIban)) {
        errors.push(`Seite ${pageNum}: Ungültige IBAN-Prüfsumme ('${candIban}').`);
      } else if (!accountIban) {
        accountIban = candIban;
      } else if (candIban !== accountIban) {
        errors.push(`Seite ${pageNum}: Abweichende IBAN '${candIban}' im PDF.`);
      }
    }

    const mSeg = pText.match(/\bNr\.\s*(\d{1,4})\/(\d{4})\b/i);
    const segNum = mSeg ? parseInt(mSeg[1], 10) : null;
    const segYear = mSeg ? mSeg[2] : null;
    const mOpen = pText.match(/Alter\s+Kontostand(?:\s+Old\s+Balance)?\s+([+-]?\s*(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2}\s*[+-]?)/i);
    const closeMatches = [...pText.matchAll(/Neuer\s+Kontostand(?:\/New\s+Balance)?\s+([+-]?\s*(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2}\s*[+-]?)/gi)];
    const openCents = mOpen ? parseStrictEurCentsClient(mOpen[1]) : null;
    const closeCents = closeMatches.length ? parseStrictEurCentsClient(closeMatches[closeMatches.length - 1][1]) : null;

    if (!activeSeg || (segNum !== null && (activeSeg.stmtNum !== segNum || activeSeg.stmtYear !== segYear))) {
      activeSeg = { stmtNum: segNum, stmtYear: segYear, openingCents: openCents, closingCents: closeCents, txs: [] };
      segments.push(activeSeg);
    } else if (closeCents !== null) {
      activeSeg.closingCents = closeCents;
    }

    const lines = pText.split('\n').map(l => l.trim()).filter(Boolean);
    let inTable = false;
    let current = null;
    let afterAbschluss = false;

    const flush = () => {
      if (!current) return;
      const { partner, rest } = classifyErstePartnerClient(current.extra, current.line1);
      const desc = [current.line1, ...rest].join(' ').replace(/\s+/g, ' ').trim();
      const segTag = segNum !== null ? `ERS-${String(segNum).padStart(3, '0')}` : `ERS-P${pageNum}`;
      const txObj = {
        booking_date: useValuta ? formatDmyToIso(current.valutaStr) : null,
        value_date: formatDmyToIso(current.valutaStr),
        date: useValuta ? current.valutaStr : '',
        valutaDate: current.valutaStr,
        partner,
        partner_iban: null,
        description: desc.slice(0, 250),
        text: desc.slice(0, 250),
        amount_cents: current.cents,
        amountStr: formatCentsCommaClient(current.cents),
        currency,
        reference: `${segTag}-${transactions.length + 1}`,
        belegNr: `${segTag}-${transactions.length + 1}`,
        account_id: accountIban,
        bank_name: 'Erste Bank Austria',
        source_file_id: filename,
        validation_status: 'VALID',
      };
      activeSeg.txs.push(txObj);
      transactions.push(txObj);
      current = null;
    };

    for (const line of lines) {
      const low = line.toLowerCase();
      if (low.includes('buchungstext') && low.includes('valuta')) {
        inTable = true;
        continue;
      }
      if (!inTable) continue;
      if (low.startsWith('neuer kontostand') || /^AT\d{2}[\d\s]{14,}\s+\d{2}\.\d{2}\.\d{4}/.test(line) || low.startsWith('iban datum/date')) {
        flush();
        break;
      }
      if (/^\*{3}\s*Abschlussbuchung/i.test(line)) {
        flush();
        afterAbschluss = true;
        continue;
      }
      const m = line.match(rowRe);
      if (m) {
        flush();
        afterAbschluss = false;
        const valOk = parseStrictDmyClient(m[2]);
        const cents = parseStrictEurCentsClient(m[3]);
        if (!valOk || cents === null) {
          errors.push(`Seite ${pageNum}: Ungültige Zeile '${line}'.`);
          continue;
        }
        current = { line1: m[1].trim(), extra: [], valutaStr: valOk, cents };
      } else if (afterAbschluss && low.startsWith('reklamationen')) {
        continue;
      } else {
        // Guard R62-4: Reject damaged amounts following a DD.MM.YYYY date instead of absorbing into description
        const mBroken = line.match(/^(.+?)\s+(\d{2}\.\d{2}\.\d{4})(?:\s*\*)?\s+(\S+(?:\s+[+-])?)$/);
        if (mBroken && !/^\*{3}/.test(line)) {
          const brokenAmt = mBroken[3].trim();
          const looksDamagedAmt = (/\d/.test(brokenAmt) || /[A-Za-z*?]{1,4}[,.][A-Za-z0-9*?]{1,3}[+-]?/.test(brokenAmt))
            && (brokenAmt.includes(',') || brokenAmt.includes('.') || /[+-]$/.test(brokenAmt) || /^[+-]/.test(brokenAmt));
          if (looksDamagedAmt) {
            flush();
            errors.push(`Seite ${pageNum}: Nicht eindeutiger Betrag '${brokenAmt}' bei '${mBroken[1].trim()}'.`);
            continue;
          }
        }
        if (current) {
          current.extra.push(line);
        } else {
          errors.push(`Seite ${pageNum}: Nicht zugeordnete Zeile im Umsatzbereich: '${line}'.`);
        }
      }
    }
    flush();
  }

  let overallRecon = 'UNVERIFIED';
  const seenSeg = new Set();
  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i];
    if (seg.stmtNum !== null && seg.stmtYear) {
      const k = `${seg.stmtYear}-${seg.stmtNum}`;
      if (seenSeg.has(k)) errors.push(`Doppelter Auszug Nr. ${seg.stmtNum}/${seg.stmtYear}.`);
      seenSeg.add(k);
      if (i > 0 && segments[i - 1].stmtNum !== null && segments[i - 1].stmtYear === seg.stmtYear && seg.stmtNum !== segments[i - 1].stmtNum + 1) {
        errors.push(`Fehlender Auszug zwischen Nr. ${segments[i - 1].stmtNum} und ${seg.stmtNum}.`);
      }
    }
    if (seg.openingCents !== null && seg.closingCents !== null) {
      const sum = seg.txs.reduce((a, t) => a + t.amount_cents, 0);
      if (seg.openingCents + sum !== seg.closingCents) {
        errors.push(`Saldendifferenz in Auszug Nr. ${seg.stmtNum || '?'}/${seg.stmtYear || '?'}.`);
      }
    }
    if (i > 0 && segments[i - 1].closingCents !== null && seg.openingCents !== null && segments[i - 1].closingCents !== seg.openingCents) {
      errors.push(`Saldensprung zwischen Auszügen.`);
    }
  }

  const allBalanced = segments.length > 0 && segments.every(s => s.openingCents !== null && s.closingCents !== null) && errors.length === 0;
  if (errors.length > 0) overallRecon = 'DISCREPANCY';
  else if (allBalanced) overallRecon = 'BALANCED';

  if (transactions.length > 0) {
    if (useValuta) {
      warnings.push("Valutadatum als Buchungsdatum verwendet (Quellspalte 'Valuta/Value' des Erste Bank PDFs).");
    } else {
      warnings.push("Auszug enthält nur Valutadaten ('Valuta/Value'), kein separates Buchungsdatum. Aktivieren Sie 'Valutadatum als Buchungsdatum', falls zulässig.");
    }
  }
  warnings.push(...errors);
  if (errors.length && transactions.length) transactions[0].validation_status = 'ERROR';

  return {
    transactions,
    account: holder,
    card: accountIban,
    bankName: 'Erste Bank Austria',
    openingCents: segments.length ? segments[0].openingCents : null,
    closingCents: segments.length ? segments[segments.length - 1].closingCents : null,
    reconciliation: overallRecon,
    warnings,
    segments: segments.map(s => ({
      file: filename,
      stmtNum: s.stmtNum,
      stmtYear: s.stmtYear,
      openingCents: s.openingCents,
      closingCents: s.closingCents,
      txs: s.txs,
    })),
  };
}

function parseErsteVisaTextClientSide(extracted, filename) {
  const pageTexts = typeof extracted === 'string' ? [extracted] : (extracted.pageTexts || [extracted.text || '']);
  const warnings = [];
  const errors = [];
  if (extracted.lowTextPages && extracted.lowTextPages.length > 0 && pageTexts.some(t => t.trim().length >= 50)) {
    errors.push(`Seite(n) ${extracted.lowTextPages.join(', ')} enthalten keine lesbare Textebene.`);
  }

  let card = '';
  const mCard = (pageTexts[0] || '').match(/Kartennummer\s*\/\s*Card\s*Number\s*[\r\n\s]*([0-9Xx\*]{8,20})/i)
    || (pageTexts[0] || '').match(/Umsatz\s+der\s+Karte\s+([0-9Xx\*]{4,20})/i);
  if (mCard) card = mCard[1].trim();

  let openingCents = null;
  let closingCents = null;
  const transactions = [];
  const rowRe = /^(\d{2}\.\d{2}\.\d{4})\s+(\d{2}\.\d{2}\.\d{4})\s+(.+?)\s+([+-]?\s*(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2}\s*[+-]?)$/;
  let inTable = false;

  for (let p = 0; p < pageTexts.length; p++) {
    const pText = pageTexts[p];
    const mPrev = pText.match(/Offener\s+Betrag\s+Vormonat\s+([+-]?\s*(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2}\s*[+-]?)/i);
    if (mPrev && openingCents === null) openingCents = parseStrictEurCentsClient(mPrev[1]);
    const mOut = pText.match(/Offener\s+Betrag\s*\/\s*Outstanding\s+balance\s+([+-]?\s*(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2}\s*[+-]?)/i);
    if (mOut) closingCents = parseStrictEurCentsClient(mOut[1]);

    for (const rawLine of pText.split('\n')) {
      const line = rawLine.trim();
      const low = line.toLowerCase();
      if (!line) continue;
      if (low.includes('betrag eur') || low.startsWith('offener betrag vormonat') || low.startsWith('umsatz der karte')) {
        inTable = true;
        continue;
      }
      if (low.startsWith('offener betrag / outstanding') || low.startsWith('einzugsbetrag') || low.startsWith('der einzugsbetrag wird')) {
        inTable = false;
        continue;
      }
      if (!inTable || /kauf\s+buchung|contracting company|amount foreign currency/i.test(line)) continue;
      const m = line.match(rowRe);
      if (!m) {
        errors.push(`Seite ${p + 1}: Unvollständige Kreditkarten-Zeile: '${line}'.`);
        continue;
      }
      const kaufOk = parseStrictDmyClient(m[1]);
      const buchOk = parseStrictDmyClient(m[2]);
      const cents = parseStrictEurCentsClient(m[4]);
      if (!kaufOk || !buchOk || cents === null) {
        errors.push(`Seite ${p + 1}: Ungültige Daten in '${line}'.`);
        continue;
      }
      let core = m[3].trim();
      let foreignCurrency = null, foreignAmountCents = null, fxNote = '';
      const fxTail = core.match(/\s+(\d[\d\.,]*\s+[A-Z]{3})\s+(\d+[\.,]\d+)(?:\s+(\d+[\.,]\d+))?$/);
      if (fxTail) {
        const fxParts = fxTail[1].match(/^(\d[\d\.,]*)\s+([A-Z]{3})$/);
        if (fxParts) {
          const normFx = (!fxParts[1].includes(',') && fxParts[1].includes('.')) ? fxParts[1].replace('.', ',') : fxParts[1];
          const fCents = parseStrictEurCentsClient(normFx);
          if (fCents !== null) {
            foreignCurrency = fxParts[2];
            foreignAmountCents = cents < 0 ? -Math.abs(fCents) : Math.abs(fCents);
          }
        }
        const feePart = fxTail[3] ? `, Entgelt ${fxTail[3]} EUR` : '';
        fxNote = ` (${fxTail[1]}, Kurs ${fxTail[2]}${feePart})`;
        core = core.slice(0, fxTail.index).trim();
      }
      const isNotice = core.toLowerCase().includes('ihre zahlung');
      let partner = null, ort = '';
      if (!isNotice) {
        const idxSp = core.lastIndexOf(' ');
        if (idxSp > 0) {
          partner = core.slice(0, idxSp).trim();
          ort = core.slice(idxSp + 1).trim();
        } else {
          partner = core;
        }
      }
      const desc = isNotice
        ? `${core}${fxNote}`
        : [ort || `Kartenumsatz (Kauf ${kaufOk})`, fxNote.trim(), ort ? `Kauf ${kaufOk}` : ''].filter(Boolean).join(' ').trim();
      const ref = `VISA-${buchOk.slice(0, 2)}${buchOk.slice(3, 5)}-${transactions.length + 1}`;
      transactions.push({
        booking_date: formatDmyToIso(buchOk),
        value_date: null,
        date: buchOk,
        partner,
        partner_iban: null,
        foreign_currency: foreignCurrency,
        foreign_amount_cents: foreignAmountCents,
        description: desc.slice(0, 250),
        text: desc.slice(0, 250),
        amount_cents: cents,
        amountStr: formatCentsCommaClient(cents),
        currency: 'EUR',
        reference: ref,
        belegNr: ref,
        account_id: card || 's Visa Card Business',
        bank_name: 'Erste Bank s Visa Card',
        source_file_id: filename,
        validation_status: 'VALID',
      });
    }
  }

  let recon = 'UNVERIFIED';
  if (openingCents !== null && closingCents !== null && transactions.length) {
    const sum = transactions.reduce((a, t) => a + t.amount_cents, 0);
    recon = (openingCents + sum === closingCents && errors.length === 0) ? 'BALANCED' : 'DISCREPANCY';
  } else if (errors.length > 0) {
    recon = 'DISCREPANCY';
  }
  warnings.push(...errors);
  if (errors.length && transactions.length) transactions[0].validation_status = 'ERROR';

  return {
    transactions,
    account: 's Visa Card Business',
    card: card || 's Visa Card Business',
    bankName: 'Erste Bank s Visa Card',
    openingCents,
    closingCents,
    reconciliation: recon,
    warnings,
    segments: [{
      file: filename,
      stmtNum: null,
      stmtYear: null,
      openingCents,
      closingCents,
      txs: transactions,
    }],
  };
}

// Parse Amex, Erste Bank, Visa Gold, or Universal Bank Statement Text Client-Side
function parsePdfTextClientSide(extracted, filename = '', useValuta = false) {
  const text = typeof extracted === 'string' ? extracted : (extracted?.text || '');
  const upper = text.toUpperCase();

  if ((upper.includes('MONATSRECHNUNG') || upper.includes('MONTHLY STATEMENT'))
      && upper.includes('KAUF') && upper.includes('BUCHUNG')
      && (upper.includes('VERTRAGSUNTERNEHMEN') || upper.includes('CONTRACTING COMPANY'))) {
    return parseErsteVisaTextClientSide(extracted, filename);
  }
  if ((upper.includes('ERSTE BANK') || upper.includes('OESTERREICHISCHEN SPARKASSEN') || upper.includes('GIBAATWW'))
      && (upper.includes('KONTOAUSZUG') || upper.includes('ACCOUNT STATEMENT'))
      && upper.includes('BUCHUNGSTEXT') && upper.includes('VALUTA')) {
    return parseErsteBankTextClientSide(extracted, filename, useValuta);
  }

  // Amex Format Check
  if (/american express|amex/i.test(text) || /american express|amex/i.test(filename)) {
    let year = '2026';
    let stmtMonth = '';
    const dateMatch = text.match(/Datum\s+(\d{2})\.(\d{2})\.(\d{2,4})/i);
    if (dateMatch) {
      stmtMonth = dateMatch[2];
      const matched = dateMatch[3];
      year = matched.length === 2 ? '20' + matched : matched;
    } else {
      const yearMatch = text.match(/\b(202[0-9])\b/);
      if (yearMatch) year = yearMatch[1];
    }

    let card = '';
    const cardMatch = text.match(/(?:[xX0-9]{4}-[xX0-9]{6}-(\d{5})|Kartennummer\s+([xX0-9\-]+))/i);
    if (cardMatch) {
      card = (cardMatch[1] || cardMatch[2] || '').trim();
    }

    let holder = 'American Express';
    const holderMatch = text.match(/^([A-Za-zÄÖÜäöüß0-9\.\,\-\s\&]{3,50})\s+[xX0-9]{4}-[xX0-9]{6}/m)
      || text.match(/(?:Neue\s+)?Belastungen\s+für\s+([A-Za-zÄÖÜäöüß0-9\.\,\-\s\&]{3,50})/i);
    if (holderMatch) {
      holder = holderMatch[1].trim();
    }

    const txs = [];
    const linePattern = /^(\d{2}\.\d{2})\s+(\d{2}\.\d{2})\s+(.+?)\s+([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})(?:\s+(CR))?$/;
    const lines = text.split('\n');

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].trim();
      const match = line.match(linePattern);
      if (match) {
        const [_, transDate, bookDate, details, amountRaw, isCredit] = match;
        const [day, mo] = transDate.split('.');
        let txYear = year;
        if ((stmtMonth === '01' || stmtMonth === '02') && (mo === '11' || mo === '12')) {
          txYear = (parseInt(year, 10) - 1).toString();
        }
        const fullDate = `${day}.${mo}.${txYear}`;
        const finalAmount = isCredit ? amountRaw : '-' + amountRaw;
        const cents = parseDmyOrAmtToCents(finalAmount);
        txs.push({
          booking_date: formatDmyToIso(fullDate),
          date: fullDate,
          text: details.trim(),
          description: details.trim(),
          amountStr: formatCentsCommaClient(cents),
          amount_cents: cents,
          currency: 'EUR',
          belegNr: `AMEX-${txs.length + 1}`,
          reference: `AMEX-${txs.length + 1}`,
          konto: '',
          account: holder,
          card: card,
          account_id: card || holder,
          bank_name: holder,
          sourceFile: filename,
          source_file_id: filename,
          validation_status: 'VALID',
        });
      }
    }

    if (txs.length > 0) {
      return { transactions: txs, account: holder, card: card, warnings: [], reconciliation: 'UNVERIFIED' };
    }
  }

  return parseUniversalBankText(text, filename);
}

function parseUniversalBankText(text, filename = '') {
  const ibanMatch = text.match(/\b((?:DE|AT)\d{2}\s?(?:\d{4}\s?){3,5}\d{1,4})\b/);
  const iban = ibanMatch ? ibanMatch[1].replace(/\s+/g, '') : '';

  let holder = 'Bank Konto';
  const holderMatch = text.match(/(?:Kontoinhaber(?:in)?|Konto\s+lautend\s+auf|Name\s*:\s*|Empfänger\s*:\s*)\s*:?\s*([A-Za-zÄÖÜäöüß0-9\.\,\-\s\&]{3,60})/i);
  if (holderMatch) {
    holder = holderMatch[1].trim().split('\n')[0];
  } else if (/vr[\s\-]bank|volksbank/i.test(text)) {
    holder = 'VR Bank Konto';
  } else if (/sparkasse/i.test(text)) {
    holder = 'Sparkasse Konto';
  } else if (filename) {
    holder = filename.replace(/\.[^/.]+$/, "");
  }

  const lines = text.split('\n').map(l => l.trim()).filter(l => l.length > 0);
  const txs = [];
  const datePattern = /^(\d{2}\.\d{2}(?:\.\d{2,4})?)/;
  const amountPattern = /([+\-]?[0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}(?:\s*[SH\-])?|[0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}\s*CR)$/i;

  let currentTx = null;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const dMatch = line.match(datePattern);
    if (dMatch) {
      if (currentTx && currentTx.amountStr) {
        txs.push(currentTx);
        currentTx = null;
      }

      const rawDate = dMatch[1];
      const rest = line.substring(rawDate.length).trim();
      const aMatch = rest.match(amountPattern);
      const normD = normalizeDate(rawDate);

      if (aMatch) {
        const rawAmount = aMatch[1];
        const desc = rest.substring(0, rest.lastIndexOf(rawAmount)).trim();
        const amtNorm = normalizeAmount(rawAmount);
        currentTx = {
          booking_date: formatDmyToIso(normD),
          date: normD,
          text: desc || 'Bank Buchung',
          description: desc || 'Bank Buchung',
          amountStr: amtNorm,
          amount_cents: parseDmyOrAmtToCents(amtNorm),
          currency: 'EUR',
          belegNr: `BELEG-${txs.length + 1}`,
          reference: `BELEG-${txs.length + 1}`,
          konto: '',
          account: holder,
          card: iban,
          account_id: iban || holder,
          bank_name: holder,
          sourceFile: filename,
          source_file_id: filename,
          validation_status: 'VALID',
        };
      } else {
        currentTx = {
          booking_date: formatDmyToIso(normD),
          date: normD,
          text: rest,
          description: rest,
          amountStr: '',
          amount_cents: 0,
          currency: 'EUR',
          belegNr: `BELEG-${txs.length + 1}`,
          reference: `BELEG-${txs.length + 1}`,
          konto: '',
          account: holder,
          card: iban,
          account_id: iban || holder,
          bank_name: holder,
          sourceFile: filename,
          source_file_id: filename,
          validation_status: 'VALID',
        };
      }
    } else if (currentTx) {
      const aMatch = line.match(amountPattern);
      if (aMatch && !currentTx.amountStr) {
        const rawAmount = aMatch[1];
        const extraText = line.substring(0, line.lastIndexOf(rawAmount)).trim();
        if (extraText) {
          currentTx.text += ' ' + extraText;
          currentTx.description = currentTx.text;
        }
        currentTx.amountStr = normalizeAmount(rawAmount);
        currentTx.amount_cents = parseDmyOrAmtToCents(currentTx.amountStr);
      } else if (!currentTx.amountStr) {
        currentTx.text += ' ' + line;
        currentTx.description = currentTx.text;
      }
    }
  }

  if (currentTx && currentTx.amountStr) {
    txs.push(currentTx);
  }

  return { transactions: txs, account: holder, card: iban, warnings: [], reconciliation: 'UNVERIFIED' };
}

function computeClientExportBlocks(result, fmt, defaultBankAccount = null) {
  const blocks = [];
  const txs = result?.transactions || [];
  if (!txs.length) {
    blocks.push('Keine Buchungssätze vorhanden.');
    return blocks;
  }
  if (result.overall_reconciliation === 'DISCREPANCY') {
    blocks.push('Saldenabweichung (DISCREPANCY) festgestellt: Anfangssaldo + Umsätze stimmt nicht mit Endsaldo überein.');
  }
  if (txs.some(t => t.validation_status === 'ERROR')) {
    blocks.push('Mindestens eine Buchung enthält einen Validierungsfehler.');
  }
  if (txs.some(t => !t.booking_date)) {
    blocks.push("Fehlendes Buchungsdatum (nur Valutadatum vorhanden). Bitte 'Valutadatum als Buchungsdatum verwenden' aktivieren.");
  }
  const accts = new Set(txs.map(t => t.account_id).filter(Boolean));
  if (accts.size > 1) {
    blocks.push(`Gemischte Bankkonten erkannt (${Array.from(accts).join(', ')}). Buchhaltungsexport erfordert genau ein Konto.`);
  }
  const currs = new Set(txs.map(t => t.currency).filter(Boolean));
  if (currs.size > 1) {
    blocks.push(`Gemischte Währungen erkannt (${Array.from(currs).join(', ')}).`);
  }
  if (defaultBankAccount !== null && defaultBankAccount !== undefined && String(defaultBankAccount).trim() !== '' && !/^[0-9]{3,9}$/.test(String(defaultBankAccount).trim())) {
    blocks.push("Ungültiges Bankkonto (Erwartet: 3- bis 9-stellige Ziffernfolge).");
  }
  if (txs.some(t => t.contra_account && !/^[0-9]{3,9}$/.test(String(t.contra_account).trim()))) {
    blocks.push("Ungültiges Gegenkonto (contra_account): Erwartet wird eine 3- bis 9-stellige Ziffernfolge.");
  }
  if (fmt === 'bmd_bankauszug' && txs.some(t => (t.currency || 'EUR').toUpperCase() !== 'EUR')) {
    blocks.push("Format 'BMD Bankauszug (22 Spalten)' unterstützt aktuell nur EUR.");
  }
  if (fmt === 'datev') {
    const years = new Set(txs.filter(t => t.booking_date).map(t => String(t.booking_date).slice(0, 4)));
    if (years.size > 1) {
      blocks.push(`Mehrere Geschäftsjahre erkannt (${Array.from(years).join(', ')}). DATEV EXTF erfordert genau ein Jahr.`);
    }
  }
  return blocks;
}

function buildCanonicalResultExport(result, fmt, defaultBankAccount = null) {
  const txs = result.transactions || [];
  if (fmt === 'bmd_bankauszug') {
    const hdr = [
      'Transaction Booking Date','Transaction Purpose','Transaction Partner','Transaction Partner IBAN',
      'Transaction Foreign Currency','Transaction Foreign Amount','Transaction Currency','Transaction Amount',
      'Booking Amount','Invoice Type','Invoice Currency','Invoice Total','Invoice Number','Invoice Internal No',
      'Invoice Date','Invoice Partner Company','Invoice Partner Number','Invoice Document ID','Invoice File',
      'Invoice Tags','Transaction ID','Payment Category'
    ];
    const rows = txs.map(tx => {
      const bDate = formatIsoOrDmyToDmy(tx.booking_date);
      const partner = (tx.partner || '').trim();
      let purpose = (tx.description || '').trim();
      if (partner && purpose.toLowerCase().startsWith(partner.toLowerCase() + ' - ')) {
        purpose = purpose.slice(partner.length + 3).trim();
      } else if (partner && purpose === partner) {
        purpose = '';
      }
      let pIban = (tx.partner_iban || '').replace(/\s+/g, '');
      if (pIban && tx.account_id && pIban.toUpperCase() === String(tx.account_id).replace(/\s+/g, '').toUpperCase()) {
        pIban = '';
      }
      const fCurr = tx.foreign_currency ? String(tx.foreign_currency).toUpperCase() : '';
      const fAmt = (fCurr && tx.foreign_amount_cents != null) ? formatCentsCommaClient(tx.foreign_amount_cents) : '';
      const curr = (tx.currency || 'EUR').toUpperCase();
      const amtStr = formatCentsCommaClient(tx.amount_cents);
      return [
        bDate, sanitizeCsvFieldClient(purpose), sanitizeCsvFieldClient(partner), sanitizeCsvFieldClient(pIban),
        sanitizeCsvFieldClient(fCurr), fAmt, sanitizeCsvFieldClient(curr),
        amtStr, amtStr,
        ...new Array(13).fill('')
      ].join(';');
    });
    const csvText = hdr.join(';') + '\r\n' + rows.join('\r\n') + '\r\n';
    const built = buildBlobForFormat(csvText, 'bmd_bankauszug');
    return { csvText, filename: 'BMD_Bankauszug_22.csv', ...built };
  }

  if (fmt === 'bmd' || fmt === 'bmd_ntcs') {
    const bmdKonto = (defaultBankAccount && String(defaultBankAccount).trim() !== '1200')
      ? String(defaultBankAccount).trim()
      : '2800';
    const hdr = ['Satzart', 'Belegdatum', 'Konto', 'Gegenkonto', 'Betrag', 'Währung', 'Text', 'Belegnummer']
      .map(csvQuoteAllCell).join(';');
    const rows = txs.map(tx => {
      const bDate = formatIsoOrDmyToDmy(tx.booking_date);
      const p = (tx.partner || '').trim();
      const d = (tx.description || '').trim();
      const fullTxt = (p && d && !d.includes(p)) ? `${p} - ${d}` : (d || p);
      const cleanTxt = sanitizeCsvTextClient(fullTxt).slice(0, 120);
      const cleanRef = sanitizeCsvTextClient(tx.reference || '').slice(0, 30);
      const contra = (tx.contra_account || '').trim();
      const curr = (tx.currency || 'EUR').trim();
      return [
        '0',
        bDate,
        bmdKonto,
        contra,
        formatCentsCommaClient(tx.amount_cents),
        curr,
        cleanTxt,
        cleanRef,
      ].map(csvQuoteAllCell).join(';');
    });
    const csvText = hdr + '\r\n' + rows.join('\r\n') + '\r\n';
    const built = buildBlobForFormat(csvText, 'bmd');
    return { csvText, filename: 'BMD_Bankauszug.csv', ...built };
  }

  // DATEV EXTF (Exact backend parity: 22-field Row 1 with WKZ in col 22, QUOTE_ALL Row 2 & data rows)
  const datevKonto = (defaultBankAccount && String(defaultBankAccount).trim()) ? String(defaultBankAccount).trim() : '1200';
  const years = txs.filter(t => t.booking_date).map(t => String(t.booking_date).slice(0, 4)).sort();
  const yr = years[0] || String(new Date().getFullYear());
  const nowStr = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14) + '000';
  const extfLine1 = `"EXTF";700;21;"Buchungsstapel";12;${nowStr};;"";"";"";1001;10001;${yr}0101;4;${yr}0101;${yr}1231;"Statement2Muster";"";1;;0;"EUR"`;
  const extfLine2 = [
    'Umsatz (ohne Soll/Haben-Kz)', 'Soll/Haben-Kennzeichen', 'WKZ Umsatz', 'Kurs',
    'Basis-Umsatz', 'WKZ Basis-Umsatz', 'Konto', 'Gegenkonto (ohne BU-Schlüssel)',
    'BU-Schlüssel', 'Belegdatum', 'Belegfeld 1', 'Belegfeld 2', 'Skonto', 'Buchungstext'
  ].map(csvQuoteAllCell).join(';');
  const rows = txs.map(tx => {
    const cents = Number(tx.amount_cents) || 0;
    const sh = cents >= 0 ? 'S' : 'H';
    const absAmt = formatCentsCommaClient(Math.abs(cents));
    const curr = (tx.currency || 'EUR').trim();
    const contra = (tx.contra_account || '').trim();
    const dmy = formatIsoOrDmyToDmy(tx.booking_date);
    const ttmm = dmy.length >= 5 ? dmy.slice(0, 2) + dmy.slice(3, 5) : '0000';
    const p = (tx.partner || '').trim();
    const d = (tx.description || '').trim();
    const fullTxt = (p && d && !d.includes(p)) ? `${p} - ${d}` : (d || p);
    const cleanRef = sanitizeCsvTextClient(tx.reference || '').slice(0, 36);
    const cleanTxt = sanitizeCsvTextClient(fullTxt).slice(0, 60);
    return [
      absAmt, sh, curr, '', '', '',
      datevKonto, contra, '', ttmm, cleanRef, '', '', cleanTxt,
    ].map(csvQuoteAllCell).join(';');
  });
  const csvText = extfLine1 + '\r\n' + extfLine2 + '\r\n' + rows.join('\r\n') + '\r\n';
  const built = buildBlobForFormat(csvText, 'datev');
  return { csvText, filename: 'EXTF_Buchungsstapel.csv', ...built };
}

function displayCanonicalPreview(result) {
  const txs = result?.transactions || [];
  parsedTransactions = [];
  let sumCents = 0;

  txs.forEach(tx => {
    const cents = Number(tx.amount_cents) || 0;
    sumCents += cents;
    const dateDisp = tx.booking_date
      ? formatIsoOrDmyToDmy(tx.booking_date)
      : (tx.value_date ? `${formatIsoOrDmyToDmy(tx.value_date)} (Valuta)` : '—');
    const p = (tx.partner || '').trim();
    const d = (tx.description || '').trim();
    const textDisp = (p && !d.toLowerCase().startsWith(p.toLowerCase())) ? (d ? `${p} — ${d}` : p) : (d || p || 'Buchung');
    parsedTransactions.push({
      date: dateDisp,
      text: textDisp,
      amountStr: formatCentsCommaClient(cents),
      numericVal: cents / 100,
      currency: tx.currency || 'EUR',
      belegNr: tx.reference || '',
      konto: tx.contra_account || '',
    });
  });

  renderTableRows(parsedTransactions);
  if (previewCount) previewCount.textContent = parsedTransactions.length;
  const totalFormatted = (sumCents / 100).toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' €';
  if (previewTotal) previewTotal.textContent = totalFormatted;
  if (searchInput) searchInput.value = '';
  if (uploadView) uploadView.classList.add('hidden');
  if (previewView) previewView.classList.remove('hidden');
  if (historyView) historyView.classList.add('hidden');
  return { count: parsedTransactions.length, totalFormatted };
}

function chainClientFileSegments(segments) {
  if (!segments || segments.length <= 1) {
    if (segments && segments.length === 1) {
      const seg = segments[0];
      const o = seg.openingCents;
      const c = seg.closingCents;
      if (o !== null && o !== undefined && c !== null && c !== undefined && seg.txs && seg.txs.length) {
        const sum = seg.txs.reduce((acc, t) => acc + (Number(t.amount_cents) || 0), 0);
        if (o + sum !== c) {
          return {
            hasDiscrepancy: true,
            warnings: [`Saldendifferenz in Datei '${seg.file || 'unbekannt'}': Anfangssaldo + Umsätze stimmt nicht mit Endsaldo überein.`],
          };
        }
      }
    }
    return { hasDiscrepancy: false, warnings: [] };
  }

  let hasDiscrepancy = false;
  const warnings = [];

  // 1. Validate internal Solldoppik balance for every segment
  for (const seg of segments) {
    if (seg.openingCents !== null && seg.openingCents !== undefined && seg.closingCents !== null && seg.closingCents !== undefined && seg.txs && seg.txs.length) {
      const sum = seg.txs.reduce((acc, t) => acc + (Number(t.amount_cents) || 0), 0);
      if (seg.openingCents + sum !== seg.closingCents) {
        hasDiscrepancy = true;
        warnings.push(`Saldendifferenz in Datei '${seg.file || 'unbekannt'}': Anfangssaldo + Umsätze stimmt nicht mit Endsaldo überein.`);
      }
    }
  }

  // 2. Duplicate statement number or identical duplicate statement payload detection
  const segSignature = (seg) => {
    const txSigs = (seg.txs || []).map(t =>
      `${t.booking_date || ''}|${t.value_date || ''}|${Number(t.amount_cents) || 0}|${(t.currency || 'EUR').toUpperCase()}|${(t.description || '').trim()}|${(t.partner || '').trim()}`
    ).sort();
    return JSON.stringify([seg.openingCents ?? null, seg.closingCents ?? null, seg.stmtYear ?? null, seg.stmtNum ?? null, txSigs]);
  };
  const segDateBounds = (seg) => {
    const ds = (seg.txs || []).map(t => t.booking_date || t.value_date).filter(Boolean).sort();
    return ds.length ? [ds[0], ds[ds.length - 1]] : [null, null];
  };

  const seenStmtNums = new Set();
  const seenSigs = new Set();
  for (const seg of segments) {
    if (seg.stmtNum !== null && seg.stmtNum !== undefined && seg.stmtYear) {
      const k = `${seg.stmtYear}-${seg.stmtNum}`;
      if (seenStmtNums.has(k)) {
        hasDiscrepancy = true;
        warnings.push(`Doppelter Auszug Nr. ${String(seg.stmtNum).padStart(3, '0')}/${seg.stmtYear} im Multi-Datei-Batch ('${seg.file || 'unbekannt'}').`);
      }
      seenStmtNums.add(k);
    }
    const sig = segSignature(seg);
    if (seenSigs.has(sig)) {
      hasDiscrepancy = true;
      warnings.push(`Doppelte oder überlappende Auszugsdatei im Batch erkannt ('${seg.file || 'unbekannt'}').`);
    }
    seenSigs.add(sig);
  }

  // 3. Require balances on either all segments or none
  const anyMissingBal = segments.some(s => s.openingCents === null || s.openingCents === undefined || s.closingCents === null || s.closingCents === undefined);
  const anyPresentBal = segments.some(s => (s.openingCents !== null && s.openingCents !== undefined) || (s.closingCents !== null && s.closingCents !== undefined));
  if (anyMissingBal) {
    if (anyPresentBal) {
      hasDiscrepancy = true;
      warnings.push('Unvollständige Saldenkette im Multi-Datei-Batch: Mindestens eine Datei enthält keine Kontostände.');
    }
    return { hasDiscrepancy, warnings };
  }

  // 4. Order-independent chaining by statement numbers or unique closing->opening permutation
  const allHaveStmtNums = segments.every(s => s.stmtNum !== null && s.stmtNum !== undefined && s.stmtYear);
  if (allHaveStmtNums) {
    const ordered = [...segments].sort((a, b) => (Number(a.stmtYear) - Number(b.stmtYear)) || (Number(a.stmtNum) - Number(b.stmtNum)));
    for (let i = 1; i < ordered.length; i++) {
      const prev = ordered[i - 1];
      const curr = ordered[i];
      if (String(prev.stmtYear) === String(curr.stmtYear) && Number(prev.stmtNum) + 1 !== Number(curr.stmtNum)) {
        hasDiscrepancy = true;
        warnings.push(`Fehlende Auszugsnummer zwischen Nr. ${String(prev.stmtNum).padStart(3, '0')}/${prev.stmtYear} und Nr. ${String(curr.stmtNum).padStart(3, '0')}/${curr.stmtYear}.`);
      }
      if (prev.closingCents !== curr.openingCents) {
        hasDiscrepancy = true;
        warnings.push(`Saldensprung im Multi-Datei-Batch zwischen '${prev.file}' und '${curr.file}' (fehlender oder überlappender Auszug).`);
      }
      const [, prevMaxD] = segDateBounds(prev);
      const [currMinD] = segDateBounds(curr);
      if (prevMaxD && currMinD && prevMaxD > currMinD) {
        hasDiscrepancy = true;
        warnings.push(`Zeitliche Überlappung im Multi-Datei-Batch zwischen '${prev.file}' und '${curr.file}'.`);
      }
    }
    return { hasDiscrepancy, warnings };
  }

  const n = segments.length;
  const adjUndirected = new Map();
  const inDeg = new Map();
  const outDeg = new Map();
  const edgesFrom = new Map();
  const nodes = new Set();

  for (let i = 0; i < n; i++) {
    const u = Number(segments[i].openingCents);
    const v = Number(segments[i].closingCents);
    nodes.add(u);
    nodes.add(v);
    if (!adjUndirected.has(u)) adjUndirected.set(u, new Set());
    if (!adjUndirected.has(v)) adjUndirected.set(v, new Set());
    adjUndirected.get(u).add(v);
    adjUndirected.get(v).add(u);
    outDeg.set(u, (outDeg.get(u) || 0) + 1);
    inDeg.set(v, (inDeg.get(v) || 0) + 1);
    if (!edgesFrom.has(u)) edgesFrom.set(u, []);
    edgesFrom.get(u).push(i);
  }

  // O(N) Connectivity & Eulerian degree check (R63-2)
  let eulerPossible = nodes.size > 0;
  const startNodes = [];
  const endNodes = [];
  if (eulerPossible) {
    const firstNode = nodes.values().next().value;
    const visitedNodes = new Set([firstNode]);
    const queue = [firstNode];
    for (let qi = 0; qi < queue.length; qi++) {
      for (const nxt of (adjUndirected.get(queue[qi]) || [])) {
        if (!visitedNodes.has(nxt)) {
          visitedNodes.add(nxt);
          queue.push(nxt);
        }
      }
    }
    if (visitedNodes.size < nodes.size) {
      eulerPossible = false;
    } else {
      for (const node of nodes) {
        const diff = (outDeg.get(node) || 0) - (inDeg.get(node) || 0);
        if (diff === 1) startNodes.push(node);
        else if (diff === -1) endNodes.push(node);
        else if (diff !== 0) {
          eulerPossible = false;
          break;
        }
      }
      if (eulerPossible && !((startNodes.length === 1 && endNodes.length === 1) || (startNodes.length === 0 && endNodes.length === 0))) {
        eulerPossible = false;
      }
    }
  }

  const solutions = [];
  let budgetExhausted = false;
  if (eulerPossible) {
    const bounds = segments.map(segDateBounds);
    const candidateStarts = startNodes.length === 1
      ? (edgesFrom.get(startNodes[0]) || [])
      : Array.from({ length: n }, (_, idx) => idx);
    const MAX_STEPS = 25000;
    const useBitMemo = n <= 26;
    const fullMask = useBitMemo ? ((1 << n) - 1) : 0;
    const deadStates = new Set();
    const usedArr = new Array(n).fill(false);
    const path = [];
    let steps = 0;

    const dfs = (usedMask, lastIdx) => {
      if (solutions.length >= 2 || budgetExhausted) return false;
      if (path.length === n) {
        solutions.push([...path]);
        return true;
      }
      if (steps >= MAX_STEPS) {
        budgetExhausted = true;
        return false;
      }
      steps++;
      const stateKey = useBitMemo ? `${usedMask}:${lastIdx}` : null;
      if (stateKey && deadStates.has(stateKey)) return false;

      const prevClose = Number(segments[lastIdx].closingCents);
      const prevMaxD = bounds[lastIdx][1];
      let anyFound = false;
      for (const nxt of (edgesFrom.get(prevClose) || [])) {
        if (usedArr[nxt]) continue;
        const currMinD = bounds[nxt][0];
        if (prevMaxD && currMinD && prevMaxD > currMinD) continue;
        usedArr[nxt] = true;
        path.push(nxt);
        const nxtMask = useBitMemo ? (usedMask | (1 << nxt)) : 0;
        if (dfs(nxtMask, nxt)) anyFound = true;
        path.pop();
        usedArr[nxt] = false;
        if (solutions.length >= 2 || budgetExhausted) break;
      }
      if (!anyFound && !budgetExhausted && solutions.length < 2 && stateKey) {
        deadStates.add(stateKey);
      }
      return anyFound;
    };

    for (const sIdx of candidateStarts) {
      if (solutions.length >= 2 || budgetExhausted) break;
      usedArr[sIdx] = true;
      path.push(sIdx);
      dfs(useBitMemo ? (1 << sIdx) : 0, sIdx);
      path.pop();
      usedArr[sIdx] = false;
    }
  }

  if (budgetExhausted || solutions.length !== 1) {
    hasDiscrepancy = true;
    if (budgetExhausted) {
      warnings.push('Saldenkette zu komplex oder mehrdeutig für automatische Rekonstruktion (Bitte Auszüge mit Auszugsnummern hochladen).');
    } else {
      warnings.push(
        solutions.length > 1
          ? 'Mehrdeutige Auszugsreihenfolge im Multi-Datei-Batch: mehrere Saldenketten möglich.'
          : 'Saldensprung oder zeitliche Lücke im Multi-Datei-Batch (fehlender, vertauschter oder überlappender Auszug).'
      );
    }
  }
  return { hasDiscrepancy, warnings };
}

function applyClientSideExportToPreview(result, fmt, batchName) {
  syncFormatSelection(fmt);
  const blocks = computeClientExportBlocks(result, fmt);
  const allWarnings = [...(result.warnings || [])];
  if (blocks.length > 0) {
    currentExportBytes = null;
    currentCsvBlob = null;
    if (btnDownloadCsv) btnDownloadCsv.disabled = true;
    showPreviewWarnings([...allWarnings, ...blocks], true);
    return { blocked: true };
  }

  const out = buildCanonicalResultExport(result, fmt);
  if (out.unrepresentableCount > 0) {
    allWarnings.push(`${out.unrepresentableCount} Sonderzeichen außerhalb Windows-1252 wurden durch '?' ersetzt.`);
  }
  currentCsvText = out.csvText;
  currentExportBytes = out.bytes;
  currentCsvBlob = out.blob;
  currentCsvMime = out.mime;
  currentCsvFilename = out.filename;
  if (btnDownloadCsv) btnDownloadCsv.disabled = false;
  showPreviewWarnings(allWarnings, false);

  chrome.storage.local.set({
    lastConvertedCsv: currentCsvText,
    lastConvertedFilename: currentCsvFilename,
    lastConvertedFormat: fmt,
    lastAccountsFound: currentAccountsFound,
    lastDuplicatesCount: currentDuplicatesCount,
    lastReconciliationStatus: result.overall_reconciliation || 'UNVERIFIED'
  });

  if (batchName) {
    const totalFormatted = ((result.transactions || []).reduce((a, t) => a + (Number(t.amount_cents) || 0), 0) / 100)
      .toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' €';
    saveToHistory({
      id: Date.now().toString(),
      filename: batchName,
      timestamp: new Date().toLocaleString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' }),
      count: (result.transactions || []).length,
      totalSum: totalFormatted,
      csvText: currentCsvText,
      format: fmt,
      isMixed: Object.keys(result.accounts || {}).length > 1 || (currentAccountsFound || []).length > 1
    });
  }
  return { blocked: false };
}

async function switchPreviewFormat(fmt, expectedConvGen = null) {
  syncFormatSelection(fmt);
  if (currentExportSource === 'backend') {
    if (!currentOperationId) {
      if (btnDownloadCsv) btnDownloadCsv.disabled = true;
      showPreviewWarnings(['Operation nicht mehr im Cache. Bitte Datei erneut konvertieren.'], true);
      return false;
    }
    const convGen = expectedConvGen !== null ? expectedConvGen : activeOperationGen;
    const expGen = ++activeExportGen;
    exportRequestSeq++;
    if (activeExportController) {
      try { activeExportController.abort('superseded'); } catch (_) {}
      activeExportController = null;
    }
    currentExportBytes = null;
    currentCsvBlob = null;
    if (btnDownloadCsv) btnDownloadCsv.disabled = true;

    let token = '';
    try {
      if (typeof chrome !== 'undefined' && chrome.storage) {
        if (chrome.storage.local) {
          const l = await chrome.storage.local.get('authToken');
          token = (l && l.authToken) ? l.authToken : '';
        }
        if (!token && chrome.storage.session) {
          const s = await chrome.storage.session.get('authToken');
          token = (s && s.authToken) ? s.authToken : '';
        }
      }
    } catch (e) {}
    if (convGen !== activeOperationGen || expGen !== activeExportGen) return false;

    const reqHeaders = {};
    if (token) reqHeaders['Authorization'] = `Bearer ${token}`;

    const timeoutMs = window.__EXPORT_TIMEOUT_MS || window.__CONVERT_TIMEOUT_MS || 30000;
    const controller = new AbortController();
    activeExportController = controller;
    const timeoutId = setTimeout(() => {
      try { controller.abort('timeout'); } catch (_) {}
    }, timeoutMs);

    try {
      const resp = await fetch(`${apiBaseUrl}/api/v1/operations/${encodeURIComponent(currentOperationId)}/export?format=${encodeURIComponent(fmt)}`, {
        method: 'GET',
        headers: reqHeaders,
        signal: controller.signal
      });
      if (convGen !== activeOperationGen || expGen !== activeExportGen) return false;

      if (!resp.ok) {
        const errData = await resp.json().catch(() => ({}));
        if (convGen !== activeOperationGen || expGen !== activeExportGen) return false;
        if (resp.status === 410) {
          currentOperationId = null;
        }
        showPreviewWarnings([errData.detail || `Export blockiert (${resp.status})`], true);
        if (btnDownloadCsv) btnDownloadCsv.disabled = true;
        return false;
      }

      const buffer = await resp.arrayBuffer();
      if (convGen !== activeOperationGen || expGen !== activeExportGen) return false;

      const bytes = new Uint8Array(buffer);
      const disp = resp.headers.get('Content-Disposition') || '';
      const fnMatch = disp.match(/filename="?([^";]+)"?/);
      const mime = resp.headers.get('Content-Type') || (fmt === 'bmd_bankauszug' ? 'text/csv;charset=utf-8;' : 'text/csv;charset=windows-1252;');
      currentExportBytes = bytes;
      currentCsvMime = mime;
      currentCsvBlob = new Blob([bytes], { type: mime });
      currentCsvFilename = (fnMatch && fnMatch[1]) || (fmt === 'bmd_bankauszug' ? 'BMD_Bankauszug_22.csv' : fmt === 'bmd' ? 'BMD_Bankauszug.csv' : 'EXTF_Buchungsstapel.csv');
      const decoder = new TextDecoder(fmt === 'bmd_bankauszug' ? 'utf-8' : 'windows-1252');
      currentCsvText = decoder.decode(bytes);
      if (btnDownloadCsv) btnDownloadCsv.disabled = false;
      showPreviewWarnings(currentCanonicalResult?.warnings || [], false);

      chrome.storage.local.set({
        lastConvertedCsv: currentCsvText,
        lastConvertedFilename: currentCsvFilename,
        lastConvertedFormat: fmt,
        lastAccountsFound: currentAccountsFound,
        lastDuplicatesCount: currentDuplicatesCount,
        lastReconciliationStatus: currentCanonicalResult?.overall_reconciliation || 'UNVERIFIED'
      });
      return true;
    } catch (err) {
      if (convGen !== activeOperationGen || expGen !== activeExportGen) return false;
      if (controller.signal.aborted && controller.signal.reason === 'timeout') {
        showPreviewWarnings([`Zeitüberschreitung beim Export (${timeoutMs / 1000}s).`], true);
      } else {
        showPreviewWarnings([err.message || 'Export konnte nicht geladen werden.'], true);
      }
      if (btnDownloadCsv) btnDownloadCsv.disabled = true;
      return false;
    } finally {
      clearTimeout(timeoutId);
      if (activeExportController === controller) activeExportController = null;
    }
  }

  if (currentCanonicalResult) {
    const res = applyClientSideExportToPreview(currentCanonicalResult, fmt, null);
    return !res.blocked;
  }
  return false;
}

async function readFileAsText(file) {
  const buffer = await file.arrayBuffer();
  try {
    const utf8Decoder = new TextDecoder('utf-8', { fatal: true });
    return utf8Decoder.decode(buffer);
  } catch (e) {
    const winDecoder = new TextDecoder('windows-1252');
    return winDecoder.decode(buffer);
  }
}

// 1-Click Instant Demo Conversion
async function processDemoConversion(convGen = activeOperationGen) {
  await new Promise(r => setTimeout(r, 150));
  if (convGen !== activeOperationGen) return;
  const selectedFormat = getSelectedFormat();
  currentExportSource = 'demo';
  currentOperationId = null;

  currentAccountsFound = [
    { name: 'American Express (*22001)', card: '22001', count: 8, files: ['Demo_Amex.pdf'] },
    { name: 'Wise Business (EUR)', card: '', count: 6, files: ['Demo_Wise.csv'] }
  ];
  currentDuplicatesCount = 0;

  const txs = SAMPLE_TRANSACTIONS.map((tx, idx) => ({
    booking_date: formatDmyToIso(tx.date),
    value_date: null,
    partner: null,
    partner_iban: null,
    description: tx.text,
    amount_cents: Math.round(tx.numericVal * 100),
    currency: 'EUR',
    reference: `DEMO-${idx + 1}`,
    account_id: tx.account,
    bank_name: tx.account,
    validation_status: 'VALID',
  }));

  currentCanonicalResult = {
    transactions: txs,
    accounts: { amex: { account_id: '22001' }, wise: { account_id: 'Wise' } },
    overall_reconciliation: 'UNVERIFIED',
    warnings: [],
  };

  displayCanonicalPreview(currentCanonicalResult);
  updateReconciliationBadge('UNVERIFIED');
  renderSafeguards(currentAccountsFound, currentDuplicatesCount);

  // Demo intentionally shows mixed-accounts showcase; keep demo download enabled cleanly via single-demo override if blocked
  const out = buildCanonicalResultExport(currentCanonicalResult, selectedFormat);
  currentCsvText = out.csvText;
  currentExportBytes = out.bytes;
  currentCsvBlob = out.blob;
  currentCsvMime = out.mime;
  currentCsvFilename = out.filename;
  if (btnDownloadCsv) btnDownloadCsv.disabled = false;
  showPreviewWarnings(['Hinweis: Demo-Datensatz kombiniert Amex + Wise zur Darstellung des Anti-Mix-Guards.'], false);

  saveToHistory({
    id: Date.now().toString(),
    filename: '✨ Demo-Auszug (14 Buchungen)',
    timestamp: new Date().toLocaleString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' }),
    count: txs.length,
    totalSum: (txs.reduce((a, t) => a + t.amount_cents, 0) / 100).toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' €',
    csvText: currentCsvText,
    format: selectedFormat,
    isMixed: true
  });

  chrome.storage.local.get(['conversionsLeft'], (result) => {
    let left = (result.conversionsLeft !== undefined ? result.conversionsLeft : 3) - 1;
    chrome.storage.local.set({ conversionsLeft: Math.max(0, left) });
    updateLimitDisplay(Math.max(0, left));
  });

  hideStatus();
  showLoupeToast('✅ <strong>Musterdaten erfolgreich konvertiert!</strong>');
}

// Visual Reconciliation Badge (Solldoppik status)
function updateReconciliationBadge(status) {
  const badge = document.getElementById('reconciliation-badge');
  const icon = document.getElementById('reconciliation-badge-icon');
  const text = document.getElementById('reconciliation-badge-text');
  if (!badge) return;

  badge.classList.remove('hidden');
  if (status === 'BALANCED') {
    badge.style.background = '#ecfdf5';
    badge.style.color = '#046a4e';
    badge.style.borderColor = '#059669';
    if (icon) icon.textContent = '✓';
    if (text) text.textContent = 'Salden ausgeglichen (Solldoppik)';
  } else if (status === 'DISCREPANCY') {
    badge.style.background = '#fef2f2';
    badge.style.color = '#991b1b';
    badge.style.borderColor = '#dc2626';
    if (icon) icon.textContent = '⚠';
    if (text) text.textContent = 'Saldenabweichung (Prüfung nötig)';
  } else {
    badge.style.background = '#f5f5f4';
    badge.style.color = '#382823';
    badge.style.borderColor = '#d5c3ba';
    if (icon) icon.textContent = 'ℹ';
    if (text) text.textContent = 'Einzelbeleg (kein Saldo)';
  }
}

// Backend Conversion Handler (Strict Managed Policy: NEVER silently falls back to offline client-side on API error)
async function processBackendConversion(files, convGen = activeOperationGen) {
  const isMulti = files.length > 1;
  const formData = new FormData();
  for (const file of files) {
    formData.append('files', file);
  }

  const selectedFormat = getSelectedFormat();
  const useValuta = Boolean(valutaAsBookingCheckbox && valutaAsBookingCheckbox.checked);

  let token = '';
  try {
    if (typeof chrome !== 'undefined' && chrome.storage) {
      if (chrome.storage.local) {
        const l = await chrome.storage.local.get('authToken');
        token = (l && l.authToken) ? l.authToken : '';
      }
      if (!token && chrome.storage.session) {
        const s = await chrome.storage.session.get('authToken');
        token = (s && s.authToken) ? s.authToken : '';
      }
    }
  } catch (e) {}
  if (convGen !== activeOperationGen) return;

  const reqHeaders = {};
  if (token) {
    reqHeaders['Authorization'] = `Bearer ${token}`;
  }

  const timeoutMs = window.__CONVERT_TIMEOUT_MS || 30000;
  const controller = new AbortController();
  activeConvertController = controller;
  const timeoutId = setTimeout(() => {
    try { controller.abort('timeout'); } catch (_) {}
  }, timeoutMs);

  let data = null;
  let reconStatus = 'UNVERIFIED';
  let isMixed = false;
  let blockedPayload = null;
  try {
    const response = await fetch(
      `${apiBaseUrl}/api/v1/convert?format=json&target_format=${encodeURIComponent(selectedFormat)}&use_valuta_as_booking_date=${useValuta ? 'true' : 'false'}`,
      {
        method: 'POST',
        headers: reqHeaders,
        body: formData,
        signal: controller.signal
      }
    );
    if (convGen !== activeOperationGen) return;

    reconStatus = response.headers.get('X-Reconciliation-Status') || 'UNVERIFIED';
    isMixed = response.headers.get('X-Mixed-Accounts') === 'true';
    const accountsRaw = response.headers.get('X-Accounts-Found') || '[]';
    currentDuplicatesCount = parseInt(response.headers.get('X-Duplicates-Count') || '0', 10);
    try {
      currentAccountsFound = JSON.parse(accountsRaw);
    } catch (e) {
      currentAccountsFound = [];
    }

    if (response.status === 422) {
      const errData = await response.json().catch(() => ({}));
      if (convGen !== activeOperationGen) return;
      if (errData && errData.result) {
        blockedPayload = {
          result: errData.result,
          blocks: errData.export_blocks && errData.export_blocks.length ? errData.export_blocks : [errData.detail || 'Export blockiert'],
        };
      } else {
        throw new Error(errData.detail || 'Validierungsfehler (422)');
      }
    } else if (!response.ok) {
      const errData = await response.json().catch(() => ({}));
      throw new Error(errData.detail || `Server Fehler: ${response.status}`);
    } else {
      data = await response.json();
      if (convGen !== activeOperationGen) return;
    }
  } catch (fetchErr) {
    if (convGen !== activeOperationGen) return;
    if (controller.signal.aborted && controller.signal.reason === 'timeout') {
      throw new Error(`Zeitüberschreitung: Der Server hat nicht innerhalb von ${timeoutMs / 1000}s geantwortet.`);
    }
    throw fetchErr;
  } finally {
    clearTimeout(timeoutId);
    if (activeConvertController === controller) activeConvertController = null;
  }

  if (convGen !== activeOperationGen) return;

  if (blockedPayload) {
    currentExportSource = 'backend';
    currentCanonicalResult = blockedPayload.result;
    currentOperationId = null;
    currentExportBytes = null;
    currentCsvBlob = null;
    currentCsvText = '';
    displayCanonicalPreview(blockedPayload.result);
    updateReconciliationBadge(blockedPayload.result.overall_reconciliation || reconStatus);
    renderSafeguards(currentAccountsFound, currentDuplicatesCount);
    if (btnDownloadCsv) btnDownloadCsv.disabled = true;
    showPreviewWarnings([...(blockedPayload.result.warnings || []), ...blockedPayload.blocks], true);
    hideStatus();
    return;
  }

  currentExportSource = 'backend';
  currentCanonicalResult = data;
  currentOperationId = data.operation_id || null;

  const stats = displayCanonicalPreview(data);
  updateReconciliationBadge(data.overall_reconciliation || reconStatus);
  renderSafeguards(currentAccountsFound, currentDuplicatesCount);

  if (!currentOperationId || (data.export_blocks && data.export_blocks.length > 0)) {
    if (btnDownloadCsv) btnDownloadCsv.disabled = true;
    showPreviewWarnings([...(data.warnings || []), ...(data.export_blocks || ['Export blockiert — bitte prüfen.'])], true);
    hideStatus();
    return;
  }

  const exportedOk = await switchPreviewFormat(selectedFormat, convGen);
  if (convGen !== activeOperationGen || !exportedOk) {
    hideStatus();
    return;
  }

  const batchName = isMulti ? `⚡ Sammel-Auszug (${files.length} Dateien)` : files[0].name;
  if (currentCsvText) {
    saveToHistory({
      id: Date.now().toString(),
      filename: batchName,
      timestamp: new Date().toLocaleString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' }),
      count: stats.count,
      totalSum: stats.totalFormatted,
      csvText: currentCsvText,
      format: selectedFormat,
      isMixed: isMixed
    });
  }

  chrome.storage.local.get(['conversionsLeft'], (result) => {
    let left = (result.conversionsLeft !== undefined ? result.conversionsLeft : 3) - 1;
    chrome.storage.local.set({ conversionsLeft: Math.max(0, left) });
    updateLimitDisplay(Math.max(0, left));
  });

  hideStatus();
}

// In-Browser Client-Side Conversion Handler (Only used in standalone offline mode)
async function processClientSideFiles(files, convGen = activeOperationGen) {
  const selectedFormat = getSelectedFormat();
  const useValuta = Boolean(valutaAsBookingCheckbox && valutaAsBookingCheckbox.checked);

  let allTransactions = [];
  const processedAccounts = {};
  const accountSegments = {};
  const allWarnings = [];
  const reconStatuses = [];
  let totalDuplicates = 0;

  for (const file of files) {
    const isCsv = file.name.toLowerCase().endsWith('.csv');
    const isPdf = file.name.toLowerCase().endsWith('.pdf');

    if (isCsv) {
      const text = await readFileAsText(file);
      if (convGen !== activeOperationGen) return;
      const res = parseCsvClientSide(text, file.name);
      if (res.transactions.length > 0) {
        res.transactions.forEach(t => {
          const cents = parseDmyOrAmtToCents(t.amountStr);
          allTransactions.push({
            ...t,
            booking_date: formatDmyToIso(t.date),
            value_date: null,
            description: t.text,
            amount_cents: cents,
            reference: t.belegNr || '',
            account_id: t.account || 'Bank CSV',
            validation_status: 'VALID',
          });
        });
        res.accounts.forEach(acc => {
          if (!processedAccounts[acc.name]) {
            processedAccounts[acc.name] = { name: acc.name, card: acc.card, count: 0, files: [] };
          }
          processedAccounts[acc.name].count += acc.count;
          if (!processedAccounts[acc.name].files.includes(file.name)) {
            processedAccounts[acc.name].files.push(file.name);
          }
        });
      }
    } else if (isPdf) {
      const buffer = await file.arrayBuffer();
      if (convGen !== activeOperationGen) return;
      const extracted = await extractTextFromPdf(buffer);
      if (convGen !== activeOperationGen) return;
      const res = parsePdfTextClientSide(extracted, file.name, useValuta);
      if (res.warnings && res.warnings.length) {
        allWarnings.push(...res.warnings);
      }
      if (res.reconciliation) reconStatuses.push(res.reconciliation);
      const accName = res.account || file.name.replace(/\.[^/.]+$/, "");
      const accSegKey = res.card || accName;
      if (res.segments && res.segments.length) {
        if (!accountSegments[accSegKey]) accountSegments[accSegKey] = [];
        accountSegments[accSegKey].push(...res.segments);
      } else if (res.openingCents !== undefined || res.closingCents !== undefined) {
        if (!accountSegments[accSegKey]) accountSegments[accSegKey] = [];
        accountSegments[accSegKey].push({
          file: file.name,
          stmtNum: null,
          stmtYear: null,
          openingCents: res.openingCents ?? null,
          closingCents: res.closingCents ?? null,
          txs: res.transactions || [],
        });
      }
      if (res.transactions.length > 0) {
        res.transactions.forEach(t => allTransactions.push(t));
        if (!processedAccounts[accName]) {
          processedAccounts[accName] = { name: accName, card: res.card || '', count: 0, files: [] };
        }
        processedAccounts[accName].count += res.transactions.length;
        if (!processedAccounts[accName].files.includes(file.name)) {
          processedAccounts[accName].files.push(file.name);
        }
      }
    }
  }

  let chainDiscrepancy = false;
  for (const segs of Object.values(accountSegments)) {
    const chainRes = chainClientFileSegments(segs);
    if (chainRes.hasDiscrepancy) chainDiscrepancy = true;
    if (chainRes.warnings && chainRes.warnings.length) {
      allWarnings.push(...chainRes.warnings);
    }
  }

  const seen = new Set();
  for (const tx of allTransactions) {
    const key = `${tx.booking_date || tx.valutaDate || ''}_${tx.description}_${tx.amount_cents}`;
    if (seen.has(key)) totalDuplicates++;
    else seen.add(key);
  }

  if (allTransactions.length === 0) {
    throw new Error(allWarnings[0] || 'Keine Buchungssätze in der Datei erkannt. Bitte prüfen Sie das Dateiformat.');
  }

  if (convGen !== activeOperationGen) return;

  const isMulti = files.length > 1;
  const accountsFound = Object.values(processedAccounts);
  const overallRecon = (chainDiscrepancy || reconStatuses.includes('DISCREPANCY'))
    ? 'DISCREPANCY'
    : (reconStatuses.length > 0 && reconStatuses.every(s => s === 'BALANCED'))
      ? 'BALANCED'
      : 'UNVERIFIED';

  currentExportSource = 'offline';
  currentOperationId = null;
  currentAccountsFound = accountsFound;
  currentDuplicatesCount = totalDuplicates;
  currentCanonicalResult = {
    transactions: allTransactions,
    accounts: processedAccounts,
    overall_reconciliation: overallRecon,
    warnings: Array.from(new Set(allWarnings)),
  };

  displayCanonicalPreview(currentCanonicalResult);
  updateReconciliationBadge(overallRecon);
  renderSafeguards(currentAccountsFound, currentDuplicatesCount);

  const batchName = isMulti ? `⚡ Sammel-Auszug (${files.length} Dateien)` : files[0].name;
  const exportRes = applyClientSideExportToPreview(currentCanonicalResult, selectedFormat, batchName);

  if (!exportRes || !exportRes.blocked) {
    chrome.storage.local.get(['conversionsLeft'], (result) => {
      let left = (result.conversionsLeft !== undefined ? result.conversionsLeft : 3) - 1;
      chrome.storage.local.set({ conversionsLeft: Math.max(0, left) });
      updateLimitDisplay(Math.max(0, left));
    });
  }

  hideStatus();
}

// Convert Action (Supports Single, Multi-File Batch & Strict Managed Policy)
convertBtn.addEventListener('click', async () => {
  if (selectedFiles.length === 0 && !isDemoActive) return;

  invalidatePendingOperations('new_convert');
  const convGen = activeOperationGen;

  convertBtn.disabled = true;
  const isMulti = selectedFiles.length > 1;
  const statusMsg = isMulti
    ? `Verarbeite ${selectedFiles.length} Auszüge (In-Memory)...`
    : 'Wird verarbeitet (In-Memory)...';
  showStatus('processing', statusMsg);

  // 1. Demo mode
  if (isDemoActive) {
    try {
      await processDemoConversion(convGen);
    } catch (e) {
      if (convGen !== activeOperationGen) return;
      console.error(e);
      showStatus('error', `Fehler: ${e.message}`);
      checkState();
    }
    return;
  }

  // 2. Managed API / Authenticated session check: NEVER silently fall back to offline JS on error
  let hasManagedToken = false;
  try {
    const stor = await chrome.storage.local.get(['authToken']);
    hasManagedToken = Boolean(stor && stor.authToken);
  } catch (e) {}
  if (convGen !== activeOperationGen) return;

  if (backendOnline || hasManagedToken) {
    try {
      await processBackendConversion(selectedFiles, convGen);
      return;
    } catch (backendError) {
      if (convGen !== activeOperationGen) return;
      console.error('Backend conversion failed:', backendError);
      showStatus('error', `Server-Fehler: ${backendError.message || 'Verarbeitung fehlgeschlagen'}`);
      checkState();
      return;
    }
  }

  // 3. Standalone Client-Side In-Memory Engine (only when strictly offline / unauthenticated local mode)
  try {
    await processClientSideFiles(selectedFiles, convGen);
  } catch (error) {
    if (convGen !== activeOperationGen) return;
    console.error(error);
    showStatus('error', `Fehler: ${error.message || 'Verarbeitung fehlgeschlagen'}`);
    checkState();
  }
});

// Render Safeguards Alerts (Anti-Mix Guard & Duplicates)
function renderSafeguards(accounts, dupes) {
  // 1. Anti-Mix Guard Breakdown
  if (accounts && accounts.length > 1) {
    conflictCard.classList.remove('hidden');
    filterChipsBar.classList.remove('hidden');
    conflictList.innerHTML = '';
    filterChipsBar.innerHTML = '';

    // "Alle" filter chip
    const allChip = document.createElement('button');
    allChip.className = 'filter-chip active';
    allChip.textContent = `Alle (${parsedTransactions.length})`;
    allChip.addEventListener('click', () => {
      document.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
      allChip.classList.add('active');
      activeAccountFilter = 'ALL';
      applyFilters();
    });
    filterChipsBar.appendChild(allChip);

    // Update main download button text
    if (btnDownloadCsvText) {
      btnDownloadCsvText.textContent = `📦 ${accounts.length} getrennte CSVs laden`;
    }

    accounts.forEach(acc => {
      const accKey = acc.card ? `${acc.name} (${acc.card})` : acc.name;
      
      // Filter chip for this account
      const chip = document.createElement('button');
      chip.className = 'filter-chip';
      chip.textContent = `${acc.name} (${acc.count})`;
      chip.title = `Nur Buchungen für ${accKey} anzeigen`;
      chip.addEventListener('click', () => {
        document.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
        chip.classList.add('active');
        activeAccountFilter = accKey;
        applyFilters();
      });
      filterChipsBar.appendChild(chip);

      // Detailed Account Box in Conflict Card
      const box = document.createElement('div');
      box.className = 'conflict-group-box';

      const fileChipsHtml = (acc.files || []).map(f => `
        <span class="file-chip">
          <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
          </svg>
          ${escapeHtml(f)}
        </span>
      `).join('');

      box.innerHTML = `
        <div class="group-title-row">
          <div class="group-title-left">
            <span>🏢 <strong>${escapeHtml(acc.name)}</strong></span>
            ${acc.card ? `<span class="group-badge">Karte ${escapeHtml(acc.card)}</span>` : ''}
            <span class="group-badge">${acc.count} Buchungen</span>
          </div>
          <button class="btn-download-single-acc" style="opacity: 0.5; cursor: not-allowed;" title="Mandanten-Einzelexport ist zum Schutz vor Datenmischung vorübergehend deaktiviert (Sicherheits-Audit R0)">
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="7 10 12 15 17 10"></polyline>
              <line x1="12" y1="15" x2="12" y2="3"></line>
            </svg>
            <span>CSV (Gesperrt)</span>
          </button>
        </div>
        <div class="group-files-list">
          ${fileChipsHtml}
        </div>
      `;

      // Single Account Download Trigger
      box.querySelector('.btn-download-single-acc').addEventListener('click', (e) => {
        e.stopPropagation();
        downloadAccountSpecificCsv(acc);
      });

      conflictList.appendChild(box);
    });

  } else {
    conflictCard.classList.add('hidden');
    filterChipsBar.classList.add('hidden');
    updateDownloadButtonText();
  }

  // 2. Duplicate Detection
  if (dupes > 0) {
    duplicateCard.classList.remove('hidden');
    duplicateText.textContent = `✓ ${dupes} identische Buchung(en) wurden automatisch dedupliziert.`;
  } else {
    duplicateCard.classList.add('hidden');
  }
}

// Download only transactions of a specific company (R0 fix: disabled to prevent cross-account contamination)
function downloadAccountSpecificCsv(acc) {
  showStatus('error', 'Mandanten-Einzelexport ist zum Schutz vor Datenmischung vorübergehend deaktiviert (Sicherheits-Audit R0). Bitte nutzen Sie den Gesamtexport.');
  return;
}

// Render Preview Table with Floating Loupe Popover
function displayPreview(csvText) {
  const lines = csvText.trim().split(/\r?\n/);
  if (lines.length <= 1) {
    showStatus('error', 'Keine Zeilen im Auszug gefunden.');
    return { count: 0, totalFormatted: '0,00 €' };
  }

  function parseRow(row) {
    const res = [];
    let cur = '';
    let inQ = false;
    for (let i = 0; i < row.length; i++) {
      const c = row[i];
      if (c === '"') {
        if (inQ && row[i + 1] === '"') {
          cur += '"';
          i++;
        } else {
          inQ = !inQ;
        }
      } else if (c === ';' && !inQ) {
        res.push(cur.trim());
        cur = '';
      } else {
        cur += c;
      }
    }
    res.push(cur.trim());
    return res;
  }

  parsedTransactions = [];
  let totalSum = 0;
  const firstHeaderLine = (lines[0] || '').replace(/^\uFEFF/, '');

  // 1. DATEV EXTF Format
  if (firstHeaderLine.startsWith('"EXTF"') || firstHeaderLine.startsWith('EXTF')) {
    let year = '2026';
    const yrMatch = firstHeaderLine.match(/;\b(202[0-9])0101;/);
    if (yrMatch) year = yrMatch[1];
    const dataRows = lines.slice(2);
    dataRows.forEach(row => {
      if (!row.trim()) return;
      const cols = parseRow(row).map(c => c.replace(/^"|"$/g, '').trim());
      const amountRaw = cols[0] || '0,00';
      const sh = (cols[1] || 'S').toUpperCase();
      const currency = cols[2] || 'EUR';
      const konto = cols[6] || '';
      const ttmm = cols[9] || '0101';
      const date = ttmm.length === 4 ? `${ttmm.substring(0, 2)}.${ttmm.substring(2, 4)}.${year}` : ttmm;
      const belegNr = cols[10] || '';
      const text = cols[13] || '';

      const numericBase = parseFloat(amountRaw.replace(/\./g, '').replace(',', '.'));
      let numericVal = isNaN(numericBase) ? 0 : numericBase;
      let amountStr = amountRaw;
      if (sh === 'H') {
        numericVal = -Math.abs(numericVal);
        amountStr = '-' + amountRaw;
      } else {
        numericVal = Math.abs(numericVal);
      }
      totalSum += numericVal;

      parsedTransactions.push({
        date,
        text,
        amountStr,
        numericVal,
        currency,
        belegNr,
        konto
      });
    });
  } else if (firstHeaderLine.startsWith('Transaction Booking Date')) {
    // 2. BMD Bankauszug (22 columns)
    const dataRows = lines.slice(1);
    dataRows.forEach(row => {
      if (!row.trim()) return;
      const cols = parseRow(row).map(c => c.replace(/^"|"$/g, '').trim());
      const date = cols[0] || '';
      const purpose = cols[1] || '';
      const partner = cols[2] || '';
      const text = (partner && purpose && !purpose.toLowerCase().startsWith(partner.toLowerCase()))
        ? `${partner} — ${purpose}`
        : (purpose || partner || '');
      const currency = cols[6] || 'EUR';
      const amountStr = cols[7] || '0,00';
      const belegNr = cols[20] || '';
      const konto = '';

      const numericVal = parseFloat(amountStr.replace(/\./g, '').replace(',', '.'));
      if (!isNaN(numericVal)) totalSum += numericVal;

      parsedTransactions.push({
        date,
        text,
        amountStr,
        numericVal: isNaN(numericVal) ? 0 : numericVal,
        currency,
        belegNr,
        konto
      });
    });
  } else if (firstHeaderLine.includes('Satzart')) {
    // 3. BMD NTCS Format (8 columns)
    const dataRows = lines.slice(1);
    dataRows.forEach(row => {
      if (!row.trim()) return;
      const cols = parseRow(row).map(c => c.replace(/^"|"$/g, '').trim());
      const date = cols[1] || '';
      const konto = cols[2] || '';
      const amountStr = cols[4] || '0,00';
      const currency = cols[5] || 'EUR';
      const text = cols[6] || '';
      const belegNr = cols[7] || '';

      const numericVal = parseFloat(amountStr.replace(/\./g, '').replace(',', '.'));
      if (!isNaN(numericVal)) totalSum += numericVal;

      parsedTransactions.push({
        date,
        text,
        amountStr,
        numericVal,
        currency,
        belegNr,
        konto
      });
    });
  } else {
    // 3. Standard Muster CSV
    const dataRows = lines.slice(1);
    dataRows.forEach(row => {
      if (!row.trim()) return;
      const cols = parseRow(row).map(c => c.replace(/^"|"$/g, '').trim());
      const date = cols[0] || '';
      const text = cols[1] || '';
      const amountStr = cols[2] || '0,00';
      const currency = cols[3] || 'EUR';
      const belegNr = cols[4] || '';
      const konto = cols[5] || '';

      const numericVal = parseFloat(amountStr.replace(/\./g, '').replace(',', '.'));
      if (!isNaN(numericVal)) {
        totalSum += numericVal;
      }

      parsedTransactions.push({
        date,
        text,
        amountStr,
        numericVal,
        currency,
        belegNr,
        konto
      });
    });
  }

  renderTableRows(parsedTransactions);

  if (previewCount) previewCount.textContent = parsedTransactions.length;
  const totalFormatted = totalSum.toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' €';
  if (previewTotal) previewTotal.textContent = totalFormatted;

  if (searchInput) searchInput.value = '';

  // Switch to Preview View
  if (uploadView) uploadView.classList.add('hidden');
  if (previewView) previewView.classList.remove('hidden');
  if (historyView) historyView.classList.add('hidden');

  return { count: parsedTransactions.length, totalFormatted };
}

function applyFilters() {
  const query = searchInput ? searchInput.value.toLowerCase().trim() : '';
  let filtered = parsedTransactions;

  // Search Text Query
  if (query) {
    filtered = filtered.filter(item => 
      item.text.toLowerCase().includes(query) || 
      item.date.toLowerCase().includes(query) ||
      item.amountStr.includes(query)
    );
  }

  renderTableRows(filtered);

  // Update filtered summary
  previewCount.textContent = filtered.length;
  const sum = filtered.reduce((acc, it) => acc + (it.numericVal || 0), 0);
  previewTotal.textContent = sum.toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' €';
}

function renderTableRows(items) {
  previewTableBody.innerHTML = '';
  
  if (items.length === 0) {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td colspan="3" style="text-align: center; color: #94a3b8; padding: 20px;">Keine Einträge gefunden</td>`;
    previewTableBody.appendChild(tr);
    return;
  }

  items.forEach(item => {
    const isCredit = !item.amountStr.startsWith('-');
    const amountClass = isCredit ? 'amount-credit' : 'amount-debit';
    const displayAmount = isCredit ? `+${item.amountStr} €` : `${item.amountStr} €`;

    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td class="td-date">${item.date}</td>
      <td class="td-text">${escapeHtml(item.text)}</td>
      <td class="td-amount ${amountClass}">${displayAmount}</td>
    `;

    // Double Click to Toggle Loupe Popover Off / On
    tr.addEventListener('dblclick', () => {
      loupeEnabled = !loupeEnabled;
      chrome.storage.local.set({ loupeEnabled: loupeEnabled });
      
      if (rowPopover) {
        rowPopover.classList.remove('visible');
        rowPopover.classList.add('hidden');
      }
      
      const toastMsg = loupeEnabled
        ? `🔍 <strong>Lupe aktiviert</strong>`
        : `👁️ <strong>Lupe deaktiviert</strong> (Doppelklick zum Reaktivieren)`;
      showLoupeToast(toastMsg);
    });

    // Floating Loupe Popover on Hover (Variant 1)
    tr.addEventListener('mouseenter', (e) => {
      if (!rowPopover || !loupeEnabled) return;
      
      rowPopover.innerHTML = `
        <div class="popover-header">
          <span class="popover-date-badge">📅 ${item.date}</span>
          <span class="popover-amount ${amountClass}">${displayAmount}</span>
        </div>
        <div class="popover-body">
          ${escapeHtml(item.text)}
        </div>
        <div class="popover-footer">
          <span>Beleg: ${escapeHtml(item.belegNr || 'DATEV')}</span>
          <span>Währung: ${escapeHtml(item.currency || 'EUR')}</span>
        </div>
        <div class="popover-hint">
          <span>💡 Tipp: Doppelklick zum Aus-/Einschalten</span>
        </div>
      `;

      rowPopover.classList.remove('hidden');
      void rowPopover.offsetWidth;
      rowPopover.classList.add('visible');
      positionPopover(e);
    });

    tr.addEventListener('mousemove', (e) => {
      if (!loupeEnabled) return;
      positionPopover(e);
    });

    tr.addEventListener('mouseleave', () => {
      if (!rowPopover) return;
      rowPopover.classList.remove('visible');
      setTimeout(() => {
        if (!rowPopover.classList.contains('visible')) {
          rowPopover.classList.add('hidden');
        }
      }, 150);
    });

    previewTableBody.appendChild(tr);
  });
}

function positionPopover(e) {
  if (!rowPopover) return;
  const popoverWidth = 320;
  const popoverHeight = rowPopover.offsetHeight || 120;
  const margin = 16;

  let x = e.clientX + margin;
  let y = e.clientY - (popoverHeight / 2);

  // Clamp horizontal
  if (x + popoverWidth > window.innerWidth - 10) {
    x = e.clientX - popoverWidth - margin;
  }
  if (x < 10) x = 10;

  // Clamp vertical
  if (y + popoverHeight > window.innerHeight - 10) {
    y = window.innerHeight - popoverHeight - 10;
  }
  if (y < 10) y = 10;

  rowPopover.style.left = `${x}px`;
  rowPopover.style.top = `${y}px`;
}

// Search / Filter
if (searchInput) {
  searchInput.addEventListener('input', applyFilters);
}

// Main Download Button
btnDownloadCsv.addEventListener('click', () => {
  // R0 fix (A08): Auto-split into multiple pseudo-separated files is disabled
  // to prevent cross-client data leaks until canonical tenant model is implemented in R4.
  // Single unified account download
  if (!currentCsvBlob && currentExportBytes) {
    currentCsvBlob = new Blob([currentExportBytes], { type: currentCsvMime });
  }
  if (!currentCsvBlob) return;

  downloadCsvBlob(currentCsvBlob, currentCsvFilename);
});

function downloadCsvBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const saveAs = window.__SAVE_AS_OVERRIDE !== undefined ? window.__SAVE_AS_OVERRIDE : false;
  chrome.downloads.download({
    url: url,
    filename: filename,
    saveAs: saveAs
  }, (downloadId) => {
    window.__lastDownloadId = downloadId;
    if (chrome.runtime.lastError) {
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      a.click();
    }
  });
}

// Format Selection Change Listener
function updateDownloadButtonText() {
  const selectedFormat = getSelectedFormat();
  if (!btnDownloadCsvText) return;
  if (selectedFormat === 'bmd_bankauszug') {
    btnDownloadCsvText.textContent = 'BMD Bankauszug (22 Sp.) laden';
  } else if (selectedFormat === 'bmd') {
    btnDownloadCsvText.textContent = 'BMD NTCS (8 Sp.) laden';
  } else if (selectedFormat === 'muster_csv') {
    btnDownloadCsvText.textContent = 'Muster CSV laden';
  } else {
    btnDownloadCsvText.textContent = 'DATEV EXTF CSV laden';
  }
}

document.querySelectorAll('input[name="upload-export-format"]').forEach(radio => {
  radio.addEventListener('change', (e) => {
    syncFormatSelection(e.target.value);
  });
});

document.querySelectorAll('input[name="export-format"]').forEach(radio => {
  radio.addEventListener('change', (e) => {
    switchPreviewFormat(e.target.value);
  });
});

// Convert Another File
btnNewConvert.addEventListener('click', () => {
  clearFile();
  if (rowPopover) {
    rowPopover.classList.remove('visible');
    rowPopover.classList.add('hidden');
  }
  showPreviewWarnings([], false);
  conflictCard.classList.add('hidden');
  duplicateCard.classList.add('hidden');
  filterChipsBar.classList.add('hidden');
  activeAccountFilter = 'ALL';
  previewView.classList.add('hidden');
  uploadView.classList.remove('hidden');
  historyView.classList.add('hidden');
});

// ==========================================================================
// History Management (Lokal im Browser)
// ==========================================================================

function saveToHistory(entry) {
  chrome.storage.local.get(['statementHistory'], (res) => {
    let list = res.statementHistory || [];
    list.unshift(entry);
    list = list.slice(0, 15);
    chrome.storage.local.set({ statementHistory: list });
  });
}

function renderHistoryView() {
  chrome.storage.local.get(['statementHistory'], (res) => {
    const list = res.statementHistory || [];
    historyList.innerHTML = '';

    if (list.length === 0) {
      historyList.innerHTML = `
        <div class="empty-history">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="1.8" style="margin-bottom: 6px;">
            <circle cx="12" cy="12" r="10"></circle>
            <polyline points="12 6 12 12 16 14"></polyline>
          </svg>
          <p>Noch keine Auszüge im Verlauf.</p>
        </div>
      `;
      return;
    }

    list.forEach(item => {
      const el = document.createElement('div');
      el.className = 'history-item';
      const isMixedBadge = item.isMixed ? `<span style="font-size:9px; background:#fef3c7; color:#92400e; padding:1px 4px; border-radius:3px; font-weight:700; margin-left:4px;">⚠️ Multi-Firma</span>` : '';
      el.innerHTML = `
        <div class="history-item-left">
          <div class="history-icon">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
            </svg>
          </div>
          <div class="history-info">
            <div class="history-name" title="${escapeHtml(item.filename)}">${escapeHtml(item.filename)} ${isMixedBadge}</div>
            <div class="history-meta">${item.timestamp} • <strong>${item.count} Pos.</strong> (${item.totalSum})</div>
          </div>
        </div>
        <div class="history-actions">
          <button class="btn-history-action btn-view-hist" title="Tabelle anzeigen">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
              <circle cx="12" cy="12" r="3"></circle>
            </svg>
            <span>Vorschau</span>
          </button>
          <button class="btn-history-action btn-down-hist" title="CSV herunterladen">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="7 10 12 15 17 10"></polyline>
              <line x1="12" y1="15" x2="12" y2="3"></line>
            </svg>
            <span>CSV</span>
          </button>
          <button class="btn-history-delete" title="Löschen">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>
      `;

function detectCsvFormatFromText(csvText, fallbackFormat = 'datev') {
  const firstLine = ((csvText || '').split(/\r?\n/)[0] || '').replace(/^\uFEFF/, '');
  if (firstLine.startsWith('Transaction Booking Date')) return 'bmd_bankauszug';
  if (firstLine.startsWith('"EXTF"') || firstLine.startsWith('EXTF')) return 'datev';
  if (firstLine.includes('Satzart')) return 'bmd';
  return fallbackFormat;
}

      // View Button
      el.querySelector('.btn-view-hist').addEventListener('click', () => {
        const fmt = item.format || detectCsvFormatFromText(item.csvText);
        syncFormatSelection(fmt);
        currentExportSource = 'history';
        currentOperationId = null;
        currentCanonicalResult = null;
        currentCsvText = item.csvText;
        const extPrefix = fmt === 'bmd_bankauszug' ? 'BMD_Bankauszug_22' : fmt === 'bmd' ? 'BMD' : fmt === 'datev' ? 'EXTF' : 'Muster';
        currentCsvFilename = item.filename.startsWith('⚡')
          ? `${extPrefix}_Sammelauszug.csv`
          : `${extPrefix}_${item.filename.replace(/\.[^/.]+$/, "")}.csv`;
        const built = buildBlobForFormat(item.csvText, fmt);
        currentExportBytes = built.bytes;
        currentCsvMime = built.mime;
        currentCsvBlob = built.blob;
        if (btnDownloadCsv) btnDownloadCsv.disabled = false;
        showPreviewWarnings([], false);

        tabConvert.classList.add('active');
        tabHistory.classList.remove('active');
        displayPreview(item.csvText);
      });

      // Download Button
      el.querySelector('.btn-down-hist').addEventListener('click', () => {
        const fmt = item.format || detectCsvFormatFromText(item.csvText);
        const built = buildBlobForFormat(item.csvText, fmt);
        const extPrefix = fmt === 'bmd_bankauszug' ? 'BMD_Bankauszug_22' : fmt === 'bmd' ? 'BMD' : fmt === 'datev' ? 'EXTF' : 'Muster';
        const name = item.filename.startsWith('⚡')
          ? `${extPrefix}_Sammelauszug.csv`
          : `${extPrefix}_${item.filename.replace(/\.[^/.]+$/, "")}.csv`;
        downloadCsvBlob(built.blob, name);
      });

      // Delete Button
      el.querySelector('.btn-history-delete').addEventListener('click', () => {
        deleteHistoryItem(item.id);
      });

      historyList.appendChild(el);
    });
  });
}

function deleteHistoryItem(id) {
  chrome.storage.local.get(['statementHistory'], (res) => {
    let list = res.statementHistory || [];
    list = list.filter(item => item.id !== id);
    chrome.storage.local.set({ statementHistory: list }, () => {
      renderHistoryView();
    });
  });
}

btnClearHistory.addEventListener('click', () => {
  chrome.storage.local.set({ statementHistory: [] }, () => {
    chrome.storage.local.remove(['lastConvertedCsv', 'lastConvertedFilename', 'lastConvertedFormat', 'lastAccountsFound', 'lastDuplicatesCount', 'lastReconciliationStatus'], () => {
      currentCsvText = null;
      currentExportBytes = null;
      currentCsvBlob = null;
      currentCsvFilename = null;
      currentOperationId = null;
      currentCanonicalResult = null;
      parsedTransactions = [];
      if (typeof previewTableBody !== 'undefined' && previewTableBody) previewTableBody.innerHTML = '';
      if (typeof previewView !== 'undefined' && previewView) previewView.classList.add('hidden');
      renderHistoryView();
      showStatus('info', 'Historie und temporärer Zwischenspeicher vollständig gelöscht.');
      setTimeout(hideStatus, 2000);
    });
  });
});

// Pro Upgrade Promo action
btnUpgradePro.addEventListener('click', () => {
  window.open('https://buy.stripe.com/14AfZh6jr2NbedI6urebu04', '_blank');
});

// ==========================================================================
// Extension Authentication Manager
// ==========================================================================

const btnOpenAuth = document.getElementById('btn-open-auth');
const authBtnLabel = document.getElementById('auth-btn-label');
const limitMainLabel = document.getElementById('limit-main-label');
const limitPulseDot = document.getElementById('limit-pulse-dot');
const extAuthModal = document.getElementById('ext-auth-modal');
const btnCloseExtModal = document.getElementById('btn-close-ext-modal');

function initAuthState() {
  chrome.storage.local.get(['userSession'], (res) => {
    const user = res.userSession;
    if (user && user.isLoggedIn) {
      applyLoggedInState(user);
    } else {
      applyLoggedOutState();
    }
  });
}

function applyLoggedInState(user) {
  const plan = (user.plan || 'trial').toLowerCase();
  const proFeatures = ['pro', 'lifetime', 'kanzlei_trial'].includes(plan);
  const planLabel = plan === 'kanzlei_trial' ? 'Kanzleitest aktiv' : plan === 'trial' ? 'Kostenloser Zugang' : plan === 'pro' ? 'Business PRO' : plan === 'lifetime' ? 'Lifetime' : plan === 'starter' ? 'Starter' : 'Account';
  if (authBtnLabel) authBtnLabel.textContent = user.name || 'Account';
  if (btnOpenAuth) btnOpenAuth.classList.add('logged-in');
  if (limitPulseDot) limitPulseDot.classList.toggle('pro', proFeatures);
  if (limitMainLabel) {
    limitMainLabel.innerHTML = `Status: <strong style="color:#046a4e;">${escapeHtml(planLabel)}</strong>`;
  }
}

function applyLoggedOutState() {
  if (authBtnLabel) authBtnLabel.textContent = 'Anmelden';
  if (btnOpenAuth) btnOpenAuth.classList.remove('logged-in');
  if (limitPulseDot) limitPulseDot.classList.remove('pro');
  chrome.storage.local.get(['conversionsLeft', 'convertLimit'], (res) => {
    const count = typeof res.conversionsLeft === 'number' ? res.conversionsLeft : (typeof res.convertLimit === 'number' ? res.convertLimit : 3);
    if (limitMainLabel) {
      limitMainLabel.innerHTML = `Testphase: <strong>${count} Auszüge frei</strong>`;
    }
  });
}

let lastEntitlementCheck = 0;
function refreshEntitlementDisplay() {
  if (Date.now() - lastEntitlementCheck < 60000) return;
  lastEntitlementCheck = Date.now();
  chrome.storage.local.get(['authToken', 'userSession'], async result => {
    if (!result.authToken || !result.userSession?.isLoggedIn) return;
    try {
      const response = await fetch(`${apiBaseUrl}/api/v1/me/entitlements`, {
        headers: { Authorization: `Bearer ${result.authToken}` }
      });
      if (response.status === 401) {
        if (limitMainLabel) limitMainLabel.textContent = 'Sitzung abgelaufen. Bitte erneut anmelden.';
        return;
      }
      if (!response.ok) return;
      const entitlement = await response.json();
      if (entitlement.plan === 'kanzlei_trial' && limitMainLabel) {
        const remaining = Number(entitlement.remaining_units) || 0;
        const end = entitlement.valid_until ? new Date(entitlement.valid_until).toLocaleDateString('de-DE') : null;
        limitMainLabel.textContent = end
          ? `Kanzleitest: ${remaining} Auszüge frei · bis ${end}`
          : `Kanzleitest: ${remaining} Auszüge frei · 30 Tage ab dem ersten Erfolg`;
      }
    } catch (_) { /* Keep the previous status while offline. */ }
  });
}

function updateLimitDisplay(count) {
  chrome.storage.local.get(['userSession'], (res) => {
    const user = res.userSession;
    if (user && user.isLoggedIn) {
      applyLoggedInState(user);
    } else {
      if (limitMainLabel) {
        limitMainLabel.innerHTML = `Testphase: <strong>${count} Auszüge frei</strong>`;
      }
    }
  });
}

if (btnOpenAuth) {
  btnOpenAuth.addEventListener('click', () => {
    chrome.storage.local.get(['userSession'], (res) => {
      const user = res.userSession;
      if (user && user.isLoggedIn) {
        if (confirm(`👤 Angemeldet als: ${user.name || user.email}\nTarif: ${user.plan || 'Standard'}\n\nMöchten Sie sich abmelden?`)) {
          invalidatePendingOperations('logout');
          currentCanonicalResult = null;
          chrome.storage.local.get(['authToken'], (tokenRes) => {
            const tok = tokenRes ? tokenRes.authToken : null;
            const logoutHeaders = {};
            if (tok) logoutHeaders['Authorization'] = `Bearer ${tok}`;
            fetch(`${apiBaseUrl}/api/v1/auth/logout`, { method: 'POST', headers: logoutHeaders }).catch(() => {});
            chrome.storage.local.remove(['userSession', 'authToken'], () => {
              if (chrome.storage && chrome.storage.session) {
                chrome.storage.session.remove(['userSession', 'authToken']).catch(() => {});
              }
              initAuthState();
            });
          });
        }
      } else {
        if (extAuthModal) {
          extAuthModal.classList.remove('hidden');
          const stepEmail = document.getElementById('auth-step-email');
          const stepCode = document.getElementById('auth-step-code');
          const statusMsg = document.getElementById('auth-status-msg');
          if (stepEmail) stepEmail.style.display = 'block';
          if (stepCode) stepCode.style.display = 'none';
          if (statusMsg) statusMsg.style.display = 'none';
        }
      }
    });
  });
}

if (btnCloseExtModal) {
  btnCloseExtModal.addEventListener('click', () => {
    if (extAuthModal) extAuthModal.classList.add('hidden');
  });
}

// 2-Step OTP Authentication Event Handlers (B01)
const btnRequestOtp = document.getElementById('btn-request-otp');
const btnVerifyOtp = document.getElementById('btn-verify-otp');
const btnBackEmail = document.getElementById('btn-back-email');
const inputAuthEmail = document.getElementById('ext-auth-email');
const inputAuthCode = document.getElementById('ext-auth-code');
const authStatusMsg = document.getElementById('auth-status-msg');
const stepEmailEl = document.getElementById('auth-step-email');
const stepCodeEl = document.getElementById('auth-step-code');

if (btnRequestOtp) {
  btnRequestOtp.addEventListener('click', async () => {
    const email = (inputAuthEmail ? inputAuthEmail.value : '').trim();
    if (!email || !email.includes('@')) {
      showAuthStatus('Bitte geben Sie eine gültige E-Mail-Adresse ein.', true);
      return;
    }
    btnRequestOtp.disabled = true;
    btnRequestOtp.textContent = 'Code wird gesendet...';
    try {
      const resp = await fetch(`${apiBaseUrl}/api/v1/auth/request-code`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email })
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        throw new Error(data.detail || `Fehler: ${resp.status}`);
      }
      showAuthStatus('Code wurde per E-Mail gesendet.', false);
      if (stepEmailEl) stepEmailEl.style.display = 'none';
      if (stepCodeEl) stepCodeEl.style.display = 'block';
      if (inputAuthCode) inputAuthCode.focus();
    } catch (err) {
      showAuthStatus(err.message || 'Verbindungsfehler beim Anfordern des Codes.', true);
    } finally {
      btnRequestOtp.disabled = false;
      btnRequestOtp.textContent = 'Code per E-Mail anfordern';
    }
  });
}

if (btnVerifyOtp) {
  btnVerifyOtp.addEventListener('click', async () => {
    const email = (inputAuthEmail ? inputAuthEmail.value : '').trim();
    const code = (inputAuthCode ? inputAuthCode.value : '').trim();
    if (!code || code.length !== 6) {
      showAuthStatus('Bitte geben Sie den 6-stelligen Code ein.', true);
      return;
    }
    btnVerifyOtp.disabled = true;
    btnVerifyOtp.textContent = 'Wird verifiziert...';
    try {
      const resp = await fetch(`${apiBaseUrl}/api/v1/auth/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, code })
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        throw new Error(data.detail || `Ungültiger Code: ${resp.status}`);
      }
      const user = {
        isLoggedIn: true,
        email: email,
        name: email.split('@')[0],
        plan: data.plan || 'Standard'
      };
      chrome.storage.local.set({
        authToken: data.access_token,
        userSession: user
      }, () => {
        invalidatePendingOperations('login');
        currentCanonicalResult = null;
        applyLoggedInState(user);
        lastEntitlementCheck = 0;
        refreshEntitlementDisplay();
        if (extAuthModal) extAuthModal.classList.add('hidden');
      });
    } catch (err) {
      showAuthStatus(err.message || 'Verifizierung fehlgeschlagen.', true);
    } finally {
      btnVerifyOtp.disabled = false;
      btnVerifyOtp.textContent = 'Anmelden & Verifizieren';
    }
  });
}

if (btnBackEmail) {
  btnBackEmail.addEventListener('click', () => {
    if (stepEmailEl) stepEmailEl.style.display = 'block';
    if (stepCodeEl) stepCodeEl.style.display = 'none';
    if (authStatusMsg) authStatusMsg.style.display = 'none';
  });
}

function showAuthStatus(msg, isError) {
  if (!authStatusMsg) return;
  authStatusMsg.style.display = 'block';
  authStatusMsg.style.color = isError ? '#feb2b2' : '#9ae6b4';
  authStatusMsg.textContent = msg;
}

// Initialize on extension startup
initAuthState();
syncFormatSelection(getSelectedFormat());

function escapeHtml(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
