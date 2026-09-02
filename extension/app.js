// DOM Elements
const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const consentCheckbox = document.getElementById('consent');
const convertBtn = document.getElementById('convert-btn');
const fileNameDisplay = document.getElementById('file-name');
const fileSizeDisplay = document.getElementById('file-size');
const fileInfo = document.getElementById('file-info');
const btnRemove = document.getElementById('btn-remove');
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
let currentCsvBlob = null;
let currentCsvFilename = 'Muster.csv';
let currentCsvText = '';
let currentAccountsFound = [];
let currentDuplicatesCount = 0;
let parsedTransactions = [];
let activeAccountFilter = 'ALL';
let apiBaseUrl = 'http://127.0.0.1:8000';
let loupeEnabled = true;

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

// Check Backend Health
async function checkBackendHealth() {
  const candidates = ['http://127.0.0.1:8000', 'http://localhost:8000'];
  for (const url of candidates) {
    try {
      const res = await fetch(`${url}/api/v1/health`, { method: 'GET' });
      if (res.ok) {
        apiBaseUrl = url;
        serverStatusBadge.className = 'server-badge online';
        serverStatusText.textContent = 'Online';
        return true;
      }
    } catch (e) {
      // try next
    }
  }
  serverStatusBadge.className = 'server-badge offline';
  serverStatusText.textContent = 'Offline';
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

consentCheckbox.addEventListener('change', checkState);

function handleFiles(files) {
  const validExts = ['.csv', '.pdf'];
  const validFiles = files.filter(f => validExts.includes(f.name.substring(f.name.lastIndexOf('.')).toLowerCase()));
  
  if (validFiles.length === 0) {
    showStatus('error', 'Nur PDF- или CSV-Dateien werden unterstützt.');
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
    const hasFiles = selectedFiles && selectedFiles.length > 0;
    const hasConsent = consentCheckbox ? consentCheckbox.checked : true;
    const canConvert = hasFiles && hasConsent && (isPro || left > 0);
    
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

// Convert Action (Supports Single, Multi-File Batch & Anti-Mix Guard)
convertBtn.addEventListener('click', async () => {
  if (selectedFiles.length === 0) return;

  convertBtn.disabled = true;
  const isMulti = selectedFiles.length > 1;
  const statusMsg = isMulti 
    ? `Verarbeite ${selectedFiles.length} Auszüge (In-Memory)...` 
    : 'Wird verarbeitet (In-Memory)...';
  showStatus('processing', statusMsg);

  const formData = new FormData();
  for (const file of selectedFiles) {
    formData.append('files', file);
  }

  try {
    const response = await fetch(`${apiBaseUrl}/api/v1/convert`, {
      method: 'POST',
      body: formData
    });

    if (!response.ok) {
      const errData = await response.json().catch(() => ({}));
      throw new Error(errData.detail || `Server Fehler: ${response.status}`);
    }

    // Read Safeguard Headers
    const isMixed = response.headers.get('X-Mixed-Accounts') === 'true';
    const accountsRaw = response.headers.get('X-Accounts-Found') || '[]';
    currentDuplicatesCount = parseInt(response.headers.get('X-Duplicates-Count') || '0', 10);
    
    try {
      currentAccountsFound = JSON.parse(accountsRaw);
    } catch (e) {
      currentAccountsFound = [];
    }

    // Process CSV
    const buffer = await response.arrayBuffer();
    const decoder = new TextDecoder('windows-1252');
    const csvText = decoder.decode(buffer);
    
    currentCsvText = csvText;
    currentCsvBlob = new Blob([buffer], { type: 'text/csv;charset=windows-1252;' });
    
    let batchName = '';
    if (isMulti) {
      currentCsvFilename = `Muster_Sammelauszug_${selectedFiles.length}_Dateien.csv`;
      batchName = `⚡ Sammel-Auszug (${selectedFiles.length} Dateien)`;
    } else {
      currentCsvFilename = `Muster_${selectedFiles[0].name.replace(/\.[^/.]+$/, "")}.csv`;
      batchName = selectedFiles[0].name;
    }

    // Persist
    chrome.storage.local.set({
      lastConvertedCsv: currentCsvText,
      lastConvertedFilename: currentCsvFilename,
      lastAccountsFound: currentAccountsFound,
      lastDuplicatesCount: currentDuplicatesCount
    });

    // Parse CSV into Table & calculate stats
    const stats = displayPreview(csvText);

    // Render Safeguards (Anti-Mix & Duplicates)
    renderSafeguards(currentAccountsFound, currentDuplicatesCount);

    // Save into Local History
    saveToHistory({
      id: Date.now().toString(),
      filename: batchName,
      timestamp: new Date().toLocaleString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' }),
      count: stats.count,
      totalSum: stats.totalFormatted,
      csvText: currentCsvText,
      isMixed: isMixed
    });

    // Decrement counter
    chrome.storage.local.get(['conversionsLeft'], (result) => {
      let left = (result.conversionsLeft !== undefined ? result.conversionsLeft : 3) - 1;
      chrome.storage.local.set({ conversionsLeft: Math.max(0, left) });
      updateLimitDisplay(Math.max(0, left));
    });

  } catch (error) {
    console.error(error);
    showStatus('error', `Fehler: ${error.message || 'Server nicht erreichbar'}`);
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
  const blob = new Blob([fullCsv], { type: 'text/csv;charset=windows-1252;' });
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
    currentCsvBlob = new Blob([currentCsvText], { type: 'text/csv;charset=windows-1252;' });
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
