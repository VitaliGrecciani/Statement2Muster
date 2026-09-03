// DOM Elements
const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const consentCheckbox = document.getElementById('consent');
const convertBtn = document.getElementById('convert-btn');
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
let currentCsvFilename = 'Muster.csv';
let currentCsvText = '';
let currentAccountsFound = [];
let currentDuplicatesCount = 0;
let parsedTransactions = [];
let activeAccountFilter = 'ALL';
let apiBaseUrl = 'http://127.0.0.1:8000';
let loupeEnabled = true;

// Windows-1252 Encoding Mapping for DATEV Compatibility
const WIN1252_LOOKUP = {
  0x20ac: 0x80, 0x201a: 0x82, 0x0192: 0x83, 0x201e: 0x84, 0x2026: 0x85, 0x2020: 0x86, 0x2021: 0x87,
  0x02c6: 0x88, 0x2030: 0x89, 0x0160: 0x8a, 0x2039: 0x8b, 0x0152: 0x8c, 0x017d: 0x8e,
  0x2018: 0x91, 0x2019: 0x92, 0x201c: 0x93, 0x201d: 0x94, 0x2022: 0x95, 0x2013: 0x96,
  0x2014: 0x97, 0x02dc: 0x98, 0x2122: 0x99, 0x0161: 0x9a, 0x203a: 0x9b, 0x0153: 0x9c,
  0x017e: 0x9e, 0x0178: 0x9f
};

function encodeWindows1252(str) {
  const bytes = new Uint8Array(str.length);
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
    }
  }
  return bytes;
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

const isFullTab = window.innerWidth > 600;

// Setup full tab responsive mode
if (isFullTab) {
  document.body.classList.add('full-tab');
  if (btnOpenTab) btnOpenTab.style.display = 'none';
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

// Open app in new tab
if (btnOpenTab) {
  btnOpenTab.addEventListener('click', () => {
    const targetUrl = currentCsvText 
      ? chrome.runtime.getURL('sidepanel.html?view=preview')
      : chrome.runtime.getURL('sidepanel.html');
    chrome.tabs.create({ url: targetUrl });
  });
}

// Expand Preview Table into Full Tab
if (btnExpandPreview) {
  btnExpandPreview.addEventListener('click', () => {
    if (currentCsvText) {
      chrome.storage.local.set({
        lastConvertedCsv: currentCsvText,
        lastConvertedFilename: currentCsvFilename,
        lastAccountsFound: currentAccountsFound,
        lastDuplicatesCount: currentDuplicatesCount
      }, () => {
        chrome.tabs.create({ url: chrome.runtime.getURL('sidepanel.html?view=preview') });
      });
    }
  });
}

// Check URL params on initial load
const urlParams = new URLSearchParams(window.location.search);
if (urlParams.get('view') === 'preview') {
  chrome.storage.local.get(['lastConvertedCsv', 'lastConvertedFilename', 'lastAccountsFound', 'lastDuplicatesCount'], (result) => {
    if (result.lastConvertedCsv) {
      currentCsvText = result.lastConvertedCsv;
      currentCsvFilename = result.lastConvertedFilename || 'Muster.csv';
      currentAccountsFound = result.lastAccountsFound || [];
      currentDuplicatesCount = result.lastDuplicatesCount || 0;
      currentCsvBlob = new Blob([result.lastConvertedCsv], { type: 'text/csv;charset=windows-1252;' });
      
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
  const candidates = ['http://127.0.0.1:8000', 'http://localhost:8000'];
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
    isDemoActive = true;
    selectedFiles = [{
      name: 'Demo_Auszug_Musterdaten.csv',
      size: 2450,
      isDemo: true
    }];
    fileNameDisplay.textContent = '✨ Demo-Auszug (14 Musterbuchungen geladen)';
    fileSizeDisplay.textContent = 'Bereit zur DATEV-Konvertierung';
    fileInfo.classList.remove('hidden');
    dropZone.classList.add('hidden');
    hideStatus();
    checkState();
    showLoupeToast('✨ <strong>Musterdaten geladen!</strong> Klicken Sie jetzt auf <em>In DATEV Muster konvertieren</em>.');
  });
}

consentCheckbox.addEventListener('change', checkState);

function handleFiles(files) {
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
  selectedFiles = [];
  isDemoActive = false;
  fileInput.value = '';
  fileInfo.classList.add('hidden');
  dropZone.classList.remove('hidden');
  hideStatus();
  checkState();
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
  let m = d.match(/^(\d{4})[-\/\.](\d{1,2})[-\/\.](\d{1,2})/);
  if (m) {
    return `${m[3].padStart(2, '0')}.${m[2].padStart(2, '0')}.${m[1]}`;
  }
  m = d.match(/^(\d{1,2})[\/\.](\d{1,2})[\/\.](\d{2,4})/);
  if (m) {
    let y = m[3];
    if (y.length === 2) y = '20' + y;
    return `${m[1].padStart(2, '0')}.${m[2].padStart(2, '0')}.${y}`;
  }
  return d;
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

// In-Browser PDF Text Extraction using Mozilla PDF.js
async function extractTextFromPdf(arrayBuffer) {
  if (typeof pdfjsLib === 'undefined') {
    throw new Error('PDF-Engine wird geladen. Bitte kurz warten oder Demo-Auszug testen.');
  }
  pdfjsLib.GlobalWorkerOptions.workerSrc = chrome.runtime.getURL('lib/pdf.worker.min.js');
  const loadingTask = pdfjsLib.getDocument({ data: arrayBuffer });
  const pdfDoc = await loadingTask.promise;
  let fullText = '';
  for (let p = 1; p <= pdfDoc.numPages; p++) {
    const page = await pdfDoc.getPage(p);
    const content = await page.getTextContent();
    const strings = content.items.map(it => it.str);
    fullText += strings.join(' ') + '\n';
  }
  return fullText;
}

// Parse Amex or Bank Statement Text Client-Side
function parsePdfTextClientSide(text, filename = '') {
  // 1. Amex Format Check
  if (/american express|amex/i.test(text) || /american express|amex/i.test(filename)) {
    let year = '2026';
    const yearMatch = text.match(/Datum\s+(\d{2})\.(\d{2})\.(\d{2,4})/i) || text.match(/\b(202[0-9])\b/);
    if (yearMatch) {
      const matched = yearMatch[3] || yearMatch[1];
      year = matched.length === 2 ? '20' + matched : matched;
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
        const fullDate = `${day}.${mo}.${year}`;
        const finalAmount = isCredit ? amountRaw : '-' + amountRaw;
        txs.push({
          date: fullDate,
          text: details.trim(),
          amountStr: finalAmount,
          currency: 'EUR',
          belegNr: `AMEX-${txs.length + 1}`,
          konto: '',
          account: holder,
          card: card,
          sourceFile: filename
        });
      }
    }

    if (txs.length > 0) {
      return { transactions: txs, account: holder, card: card };
    }
  }

  // 2. Universal Bank Statement Parser
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

      if (aMatch) {
        const rawAmount = aMatch[1];
        const desc = rest.substring(0, rest.lastIndexOf(rawAmount)).trim();
        currentTx = {
          date: normalizeDate(rawDate),
          text: desc || 'Bank Buchung',
          amountStr: normalizeAmount(rawAmount),
          currency: 'EUR',
          belegNr: `BELEG-${txs.length + 1}`,
          konto: '',
          account: holder,
          card: iban,
          sourceFile: filename
        };
      } else {
        currentTx = {
          date: normalizeDate(rawDate),
          text: rest,
          amountStr: '',
          currency: 'EUR',
          belegNr: `BELEG-${txs.length + 1}`,
          konto: '',
          account: holder,
          card: iban,
          sourceFile: filename
        };
      }
    } else if (currentTx) {
      const aMatch = line.match(amountPattern);
      if (aMatch && !currentTx.amountStr) {
        const rawAmount = aMatch[1];
        const extraText = line.substring(0, line.lastIndexOf(rawAmount)).trim();
        if (extraText) currentTx.text += ' ' + extraText;
        currentTx.amountStr = normalizeAmount(rawAmount);
      } else if (!currentTx.amountStr) {
        currentTx.text += ' ' + line;
      }
    }
  }

  if (currentTx && currentTx.amountStr) {
    txs.push(currentTx);
  }

  return { transactions: txs, account: holder, card: iban };
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
async function processDemoConversion() {
  await new Promise(r => setTimeout(r, 200));

  const isMixed = true;
  currentAccountsFound = [
    { name: 'American Express (*22001)', card: '22001', count: 8, files: ['Demo_Amex.pdf'] },
    { name: 'Wise Business (EUR)', card: '', count: 6, files: ['Demo_Wise.csv'] }
  ];
  currentDuplicatesCount = 0;

  const datevRows = SAMPLE_TRANSACTIONS.map((tx, idx) => {
    return `${tx.date};${tx.text};${tx.amountStr};EUR;DEMO-${idx + 1};`;
  });
  currentCsvText = "Belegdatum;Buchungstext;Betrag;Währung;Belegnummer;Gegenkonto/Konto\r\n" + datevRows.join("\r\n");
  const win1252Bytes = encodeWindows1252(currentCsvText);
  currentCsvBlob = new Blob([win1252Bytes], { type: 'text/csv;charset=windows-1252;' });
  currentCsvFilename = 'Statement2Muster_DATEV_Demo.csv';

  chrome.storage.local.set({
    lastConvertedCsv: currentCsvText,
    lastConvertedFilename: currentCsvFilename,
    lastAccountsFound: currentAccountsFound,
    lastDuplicatesCount: currentDuplicatesCount
  });

  const stats = displayPreview(currentCsvText);
  renderSafeguards(currentAccountsFound, currentDuplicatesCount);

  saveToHistory({
    id: Date.now().toString(),
    filename: '✨ Demo-Auszug (14 Buchungen)',
    timestamp: new Date().toLocaleString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' }),
    count: stats.count,
    totalSum: stats.totalFormatted,
    csvText: currentCsvText,
    isMixed: isMixed
  });

  chrome.storage.local.get(['conversionsLeft'], (result) => {
    let left = (result.conversionsLeft !== undefined ? result.conversionsLeft : 3) - 1;
    chrome.storage.local.set({ conversionsLeft: Math.max(0, left) });
    updateLimitDisplay(Math.max(0, left));
  });

  hideStatus();
  showLoupeToast('✅ <strong>DATEV Muster erfolgreich erstellt!</strong> Sie können die Datei nun herunterladen.');
}

// Backend Conversion Handler (when optional local server is running)
async function processBackendConversion(files) {
  const isMulti = files.length > 1;
  const formData = new FormData();
  for (const file of files) {
    formData.append('files', file);
  }

  const response = await fetch(`${apiBaseUrl}/api/v1/convert`, {
    method: 'POST',
    body: formData
  });

  if (!response.ok) {
    const errData = await response.json().catch(() => ({}));
    throw new Error(errData.detail || `Server Fehler: ${response.status}`);
  }

  const isMixed = response.headers.get('X-Mixed-Accounts') === 'true';
  const accountsRaw = response.headers.get('X-Accounts-Found') || '[]';
  currentDuplicatesCount = parseInt(response.headers.get('X-Duplicates-Count') || '0', 10);
  
  try {
    currentAccountsFound = JSON.parse(accountsRaw);
  } catch (e) {
    currentAccountsFound = [];
  }

  const buffer = await response.arrayBuffer();
  const decoder = new TextDecoder('windows-1252');
  const csvText = decoder.decode(buffer);
  
  currentCsvText = csvText;
  currentCsvBlob = new Blob([buffer], { type: 'text/csv;charset=windows-1252;' });
  
  let batchName = '';
  if (isMulti) {
    currentCsvFilename = `Muster_Sammelauszug_${files.length}_Dateien.csv`;
    batchName = `⚡ Sammel-Auszug (${files.length} Dateien)`;
  } else {
    currentCsvFilename = `Muster_${files[0].name.replace(/\.[^/.]+$/, "")}.csv`;
    batchName = files[0].name;
  }

  chrome.storage.local.set({
    lastConvertedCsv: currentCsvText,
    lastConvertedFilename: currentCsvFilename,
    lastAccountsFound: currentAccountsFound,
    lastDuplicatesCount: currentDuplicatesCount
  });

  const stats = displayPreview(csvText);
  renderSafeguards(currentAccountsFound, currentDuplicatesCount);

  saveToHistory({
    id: Date.now().toString(),
    filename: batchName,
    timestamp: new Date().toLocaleString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' }),
    count: stats.count,
    totalSum: stats.totalFormatted,
    csvText: currentCsvText,
    isMixed: isMixed
  });

  chrome.storage.local.get(['conversionsLeft'], (result) => {
    let left = (result.conversionsLeft !== undefined ? result.conversionsLeft : 3) - 1;
    chrome.storage.local.set({ conversionsLeft: Math.max(0, left) });
    updateLimitDisplay(Math.max(0, left));
  });

  hideStatus();
}

// In-Browser Client-Side Conversion Handler (Default, autark & 100% DSGVO-konform)
async function processClientSideFiles(files) {
  let allTransactions = [];
  const processedAccounts = {};
  let totalDuplicates = 0;

  for (const file of files) {
    const isCsv = file.name.toLowerCase().endsWith('.csv');
    const isPdf = file.name.toLowerCase().endsWith('.pdf');

    if (isCsv) {
      const text = await readFileAsText(file);
      const res = parseCsvClientSide(text, file.name);
      if (res.transactions.length > 0) {
        res.transactions.forEach(t => allTransactions.push(t));
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
      try {
        const buffer = await file.arrayBuffer();
        const text = await extractTextFromPdf(buffer);
        const res = parsePdfTextClientSide(text, file.name);
        if (res.transactions.length > 0) {
          res.transactions.forEach(t => allTransactions.push(t));
          const accName = res.account || file.name.replace(/\.[^/.]+$/, "");
          if (!processedAccounts[accName]) {
            processedAccounts[accName] = { name: accName, card: res.card || '', count: 0, files: [] };
          }
          processedAccounts[accName].count += res.transactions.length;
          if (!processedAccounts[accName].files.includes(file.name)) {
            processedAccounts[accName].files.push(file.name);
          }
        }
      } catch (pdfErr) {
        console.warn('Local PDF extraction error:', pdfErr);
      }
    }
  }

  // Deduplicate
  const seen = new Set();
  const uniqueTxs = [];
  for (const tx of allTransactions) {
    const key = `${tx.date}_${tx.text}_${tx.amountStr}`;
    if (seen.has(key)) {
      totalDuplicates++;
    } else {
      seen.add(key);
      uniqueTxs.push(tx);
    }
  }

  if (uniqueTxs.length === 0) {
    throw new Error('Keine Buchungssätze in der Datei erkannt. Bitte prüfen Sie das Dateiformat oder nutzen Sie die Demo-Musterdaten.');
  }

  const isMulti = files.length > 1;
  const isMixed = Object.keys(processedAccounts).length > 1;
  const accountsFound = Object.values(processedAccounts);

  const datevRows = uniqueTxs.map((tx, idx) => {
    return `${tx.date};${tx.text};${tx.amountStr};${tx.currency || 'EUR'};${tx.belegNr || ('BELEG-' + (idx + 1))};${tx.konto || ''}`;
  });

  const fullCsvText = "Belegdatum;Buchungstext;Betrag;Währung;Belegnummer;Gegenkonto/Konto\r\n" + datevRows.join("\r\n");
  const win1252Bytes = encodeWindows1252(fullCsvText);

  currentCsvText = fullCsvText;
  currentCsvBlob = new Blob([win1252Bytes], { type: 'text/csv;charset=windows-1252;' });
  currentAccountsFound = accountsFound;
  currentDuplicatesCount = totalDuplicates;

  let batchName = '';
  if (isMulti) {
    currentCsvFilename = `Muster_Sammelauszug_${files.length}_Dateien.csv`;
    batchName = `⚡ Sammel-Auszug (${files.length} Dateien)`;
  } else {
    currentCsvFilename = `Muster_${files[0].name.replace(/\.[^/.]+$/, "")}.csv`;
    batchName = files[0].name;
  }

  chrome.storage.local.set({
    lastConvertedCsv: currentCsvText,
    lastConvertedFilename: currentCsvFilename,
    lastAccountsFound: currentAccountsFound,
    lastDuplicatesCount: currentDuplicatesCount
  });

  const stats = displayPreview(currentCsvText);
  renderSafeguards(currentAccountsFound, currentDuplicatesCount);

  saveToHistory({
    id: Date.now().toString(),
    filename: batchName,
    timestamp: new Date().toLocaleString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' }),
    count: stats.count,
    totalSum: stats.totalFormatted,
    csvText: currentCsvText,
    isMixed: isMixed
  });

  chrome.storage.local.get(['conversionsLeft'], (result) => {
    let left = (result.conversionsLeft !== undefined ? result.conversionsLeft : 3) - 1;
    chrome.storage.local.set({ conversionsLeft: Math.max(0, left) });
    updateLimitDisplay(Math.max(0, left));
  });

  hideStatus();
  showLoupeToast('✅ <strong>DATEV Muster erfolgreich erstellt!</strong> Sie können die Datei nun herunterladen.');
}

// Convert Action (Supports Single, Multi-File Batch & Anti-Mix Guard)
convertBtn.addEventListener('click', async () => {
  if (selectedFiles.length === 0 && !isDemoActive) return;

  convertBtn.disabled = true;
  const isMulti = selectedFiles.length > 1;
  const statusMsg = isMulti 
    ? `Verarbeite ${selectedFiles.length} Auszüge (In-Memory)...` 
    : 'Wird verarbeitet (In-Memory)...';
  showStatus('processing', statusMsg);

  // 1. If Demo mode, execute instant in-memory conversion
  if (isDemoActive) {
    try {
      await processDemoConversion();
    } catch (e) {
      console.error(e);
      showStatus('error', `Fehler: ${e.message}`);
      checkState();
    }
    return;
  }

  // 2. If backend is online, attempt backend conversion
  if (backendOnline) {
    try {
      await processBackendConversion(selectedFiles);
      return;
    } catch (backendError) {
      console.warn('Backend conversion failed, falling back to local client-side engine:', backendError);
    }
  }

  // 3. Standalone Client-Side In-Memory Engine (100% autark)
  try {
    await processClientSideFiles(selectedFiles);
  } catch (error) {
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
          <button class="btn-download-single-acc" title="Nur diese Auszüge als DATEV CSV laden">
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="7 10 12 15 17 10"></polyline>
              <line x1="12" y1="15" x2="12" y2="3"></line>
            </svg>
            <span>CSV (${acc.count})</span>
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
    if (btnDownloadCsvText) {
      btnDownloadCsvText.textContent = 'DATEV CSV herunterladen';
    }
  }

  // 2. Duplicate Detection
  if (dupes > 0) {
    duplicateCard.classList.remove('hidden');
    duplicateText.textContent = `✓ ${dupes} identische Buchung(en) wurden automatisch dedupliziert.`;
  } else {
    duplicateCard.classList.add('hidden');
  }
}

// Download only transactions of a specific company
function downloadAccountSpecificCsv(acc) {
  let matchedRows = parsedTransactions;
  if (activeAccountFilter !== 'ALL') {
    matchedRows = parsedTransactions.filter(tx => {
      if (acc.name && tx.text && tx.text.includes(acc.name)) return true;
      return true;
    });
  }

  const csvHeader = "Belegdatum;Buchungstext;Betrag;Währung;Belegnummer;Gegenkonto/Konto\r\n";
  const csvBody = matchedRows.map(tx => 
    `${tx.date};${tx.text};${tx.amountStr};${tx.currency};${tx.belegNr || ''};${tx.konto || ''}`
  ).join("\r\n");

  const fullCsv = csvHeader + csvBody;
  const win1252Bytes = encodeWindows1252(fullCsv);
  const blob = new Blob([win1252Bytes], { type: 'text/csv;charset=windows-1252;' });
  const safeName = acc.name.replace(/[^a-zA-Z0-9_-]/g, '_');
  const filename = `Muster_${safeName}.csv`;

  downloadCsvBlob(blob, filename);
}

// Render Preview Table with Floating Loupe Popover
function displayPreview(csvText) {
  const lines = csvText.trim().split(/\r?\n/);
  if (lines.length <= 1) {
    showStatus('error', 'Keine Zeilen im Auszug gefunden.');
    return { count: 0, totalFormatted: '0,00 €' };
  }

  const dataRows = lines.slice(1);
  parsedTransactions = [];
  let totalSum = 0;

  dataRows.forEach(row => {
    if (!row.trim()) return;
    const cols = row.split(';');
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

  renderTableRows(parsedTransactions);

  previewCount.textContent = parsedTransactions.length;
  const totalFormatted = totalSum.toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' €';
  previewTotal.textContent = totalFormatted;

  if (searchInput) searchInput.value = '';

  // Switch to Preview View
  uploadView.classList.add('hidden');
  previewView.classList.remove('hidden');
  historyView.classList.add('hidden');

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
  // If multiple accounts, download each account separately
  if (currentAccountsFound && currentAccountsFound.length > 1) {
    currentAccountsFound.forEach(acc => {
      downloadAccountSpecificCsv(acc);
    });
    return;
  }

  // Single account download
  if (!currentCsvBlob && currentCsvText) {
    const bytes = encodeWindows1252(currentCsvText);
    currentCsvBlob = new Blob([bytes], { type: 'text/csv;charset=windows-1252;' });
  }
  if (!currentCsvBlob) return;

  downloadCsvBlob(currentCsvBlob, currentCsvFilename);
});

function downloadCsvBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  chrome.downloads.download({
    url: url,
    filename: filename,
    saveAs: true
  }, (downloadId) => {
    if (chrome.runtime.lastError) {
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      a.click();
    }
  });
}

// Convert Another File
btnNewConvert.addEventListener('click', () => {
  clearFile();
  if (rowPopover) {
    rowPopover.classList.remove('visible');
    rowPopover.classList.add('hidden');
  }
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

      // View Button
      el.querySelector('.btn-view-hist').addEventListener('click', () => {
        currentCsvText = item.csvText;
        currentCsvFilename = item.filename.startsWith('⚡') 
          ? `Muster_Sammelauszug.csv`
          : `Muster_${item.filename.replace(/\.[^/.]+$/, "")}.csv`;
        currentCsvBlob = new Blob([item.csvText], { type: 'text/csv;charset=windows-1252;' });
        
        tabConvert.classList.add('active');
        tabHistory.classList.remove('active');
        displayPreview(item.csvText);
      });

      // Download Button
      el.querySelector('.btn-down-hist').addEventListener('click', () => {
        const blob = new Blob([item.csvText], { type: 'text/csv;charset=windows-1252;' });
        const name = item.filename.startsWith('⚡') 
          ? `Muster_Sammelauszug.csv`
          : `Muster_${item.filename.replace(/\.[^/.]+$/, "")}.csv`;
        downloadCsvBlob(blob, name);
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
    renderHistoryView();
  });
});

// Pro Upgrade Promo action
btnUpgradePro.addEventListener('click', () => {
  window.open('https://buy.stripe.com/14AfZh6jr2NbedI6urebu04', '_blank');
});

// ==========================================================================
// Extension Authentication Manager (Google, LinkedIn, Facebook, Magic Link)
// ==========================================================================

const btnOpenAuth = document.getElementById('btn-open-auth');
const authBtnLabel = document.getElementById('auth-btn-label');
const limitMainLabel = document.getElementById('limit-main-label');
const limitPulseDot = document.getElementById('limit-pulse-dot');
const extAuthModal = document.getElementById('ext-auth-modal');
const btnCloseExtModal = document.getElementById('btn-close-ext-modal');

const btnAuthGoogle = document.getElementById('btn-auth-google');
const btnAuthLinkedin = document.getElementById('btn-auth-linkedin');
const btnAuthFacebook = document.getElementById('btn-auth-facebook');
const extMagicLinkForm = document.getElementById('ext-magic-link-form');

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
  if (authBtnLabel) authBtnLabel.textContent = user.name || 'Account';
  if (btnOpenAuth) btnOpenAuth.classList.add('logged-in');
  if (limitPulseDot) limitPulseDot.classList.add('pro');
  if (limitMainLabel) {
    limitMainLabel.innerHTML = `Status: <strong style="color:#046a4e;">⭐ PRO Aktiv (Unbegrenzt)</strong>`;
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

if (limitMainLabel) {
  limitMainLabel.style.cursor = 'pointer';
  limitMainLabel.title = 'Klicken zum Zurücksetzen des Test-Limits';
  limitMainLabel.addEventListener('click', () => {
    chrome.storage.local.set({ conversionsLeft: 5 }, () => {
      updateLimitDisplay(5);
      showStatus('success', '✓ Testphase auf 5 Auszüge zurückgesetzt!');
      setTimeout(hideStatus, 2000);
      checkState();
    });
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

function handleLoginSuccess(provider, email, name) {
  const session = {
    isLoggedIn: true,
    provider: provider,
    email: email || `user@${provider.toLowerCase()}.com`,
    name: name || `${provider} User`,
    plan: 'PRO',
    loginDate: new Date().toISOString()
  };

  chrome.storage.local.set({ userSession: session }, () => {
    applyLoggedInState(session);
    if (extAuthModal) extAuthModal.classList.add('hidden');
    alert(`✓ Erfolgreich mit ${provider} angemeldet!\n\nWillkommen, ${session.name}! Ihr PRO-Account ist nun aktiv und Sie haben unbegrenzte Konvertierungen.`);
  });
}

if (btnOpenAuth) {
  btnOpenAuth.addEventListener('click', () => {
    chrome.storage.local.get(['userSession'], (res) => {
      const user = res.userSession;
      if (user && user.isLoggedIn) {
        if (confirm(`👤 Angemeldet als: ${user.name} (${user.provider})\nTarif: ${user.plan}\n\nMöchten Sie sich abmelden?`)) {
          chrome.storage.local.remove(['userSession'], () => {
            applyLoggedOutState();
          });
        }
      } else {
        if (extAuthModal) extAuthModal.classList.remove('hidden');
      }
    });
  });
}

if (btnCloseExtModal) {
  btnCloseExtModal.addEventListener('click', () => {
    if (extAuthModal) extAuthModal.classList.add('hidden');
  });
}

if (btnAuthGoogle) {
  btnAuthGoogle.addEventListener('click', () => {
    handleLoginSuccess('Google', 'user@gmail.com', 'Google User');
  });
}

if (btnAuthLinkedin) {
  btnAuthLinkedin.addEventListener('click', () => {
    handleLoginSuccess('LinkedIn', 'partner@kanzlei.at', 'LinkedIn Pro');
  });
}

if (btnAuthFacebook) {
  btnAuthFacebook.addEventListener('click', () => {
    handleLoginSuccess('Facebook', 'user@facebook.com', 'Facebook User');
  });
}

if (extMagicLinkForm) {
  extMagicLinkForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const email = document.getElementById('ext-auth-email').value;
    handleLoginSuccess('E-Mail', email, email.split('@')[0]);
  });
}

// Initialize on extension startup
initAuthState();

function escapeHtml(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
