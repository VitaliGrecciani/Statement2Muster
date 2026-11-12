// ==========================================================================
// Statement2Muster Landing Page Interactive Logic
// ==========================================================================

const apiBaseUrl = ['localhost', '127.0.0.1'].includes(location.hostname) ? 'http://127.0.0.1:8000' : 'https://api.statement2muster.com';

// Sample demo data for instant 1-click preview
const SAMPLE_TRANSACTIONS = [
  { date: '14.04.2026', text: 'AMZN MKTP DE*NW0077AI4 AMZN.COM/BILL (Referenzwechselkurs 1,085 EUR/USD)', amountStr: '-74,10', numericVal: -74.10, isCredit: false },
  { date: '14.04.2026', text: 'AMZN MKTP DE*NW3K650C4 AMZN.COM/BILL', amountStr: '-26,18', numericVal: -26.18, isCredit: false },
  { date: '15.04.2026', text: 'OPENAI *CHATGPT SUBSCR SAN FRANCISCO (Auslandseinsatz 1,5%)', amountStr: '-17,32', numericVal: -17.32, isCredit: false },
  { date: '16.04.2026', text: 'AMZN MKTP DE*NW9G68QI4 AMZN.COM/BILL', amountStr: '-10,24', numericVal: -10.24, isCredit: false },
  { date: '16.04.2026', text: 'AMZN MKTP DE*NW1M77QR4 AMZN.COM/BILL', amountStr: '-39,66', numericVal: -39.66, isCredit: false },
  { date: '16.04.2026', text: 'AMZN MKTP DE*NW4ZR8Q04 AMZN.COM/BILL', amountStr: '-64,90', numericVal: -64.90, isCredit: false },
  { date: '17.04.2026', text: 'AMAZON.DE*NW0UT97D4 AMAZON.DE', amountStr: '-11,99', numericVal: -11.99, isCredit: false },
  { date: '18.04.2026', text: 'AMZN MKTP DE*NW0XP3I24 AMZN.COM/BILL', amountStr: '-21,99', numericVal: -21.99, isCredit: false },
  { date: '28.04.2026', text: 'PAYPAL *SPORTONAGMB 60434031850', amountStr: '-88,61', numericVal: -88.61, isCredit: false },
  { date: '28.04.2026', text: 'AMAZON.DE*NN3GK5G54 AMAZON.DE', amountStr: '-29,27', numericVal: -29.27, isCredit: false },
  { date: '28.04.2026', text: 'AMAZON.DE*NN0O75GM4 AMAZON.DE', amountStr: '-125,09', numericVal: -125.09, isCredit: false },
  { date: '30.04.2026', text: 'NETFLIX.COM AMSTERDAM', amountStr: '-29,97', numericVal: -29.97, isCredit: false },
  { date: '01.05.2026', text: 'AIRBNB * HMSENZMYZC LONDON', amountStr: '-1750,52', numericVal: -1750.52, isCredit: false },
  { date: '02.05.2026', text: 'GUTSCHRIFT KUNDENZAHLUNG RE-2026-88', amountStr: '+2450,00', numericVal: 2450.00, isCredit: true }
];

// DOM Elements
const landingDropzone = document.getElementById('landing-dropzone');
const landingFileInput = document.getElementById('landing-file-input');
const btnLoadSample = document.getElementById('btn-load-sample');
const demoStatus = document.getElementById('demo-status');
const demoStatusText = document.getElementById('demo-status-text');
const demoResult = document.getElementById('demo-result');
const demoTableBody = document.getElementById('demo-table-body');
const demoCount = document.getElementById('demo-count');
const demoSum = document.getElementById('demo-sum');
const btnDownloadDemoCsv = document.getElementById('btn-download-demo-csv');
const btnDownloadDemoText = document.getElementById('btn-download-demo-text');
const demoWarnings = document.getElementById('demo-warnings');
const demoReconBadge = document.getElementById('demo-recon-badge');
const demoReconText = document.getElementById('demo-recon-text');
const demoResultFormatSelect = document.getElementById('demo-result-format-select');
const landingValutaCheckbox = document.getElementById('landing-valuta-as-booking');
const landingPopover = document.getElementById('landing-popover');

let currentDemoBytes = null;
let currentDemoFilename = 'EXTF_Buchungsstapel.csv';
let currentDemoMime = 'text/csv;charset=windows-1252;';
let currentOperationId = null;
let currentCanonicalData = null;
let isSampleMode = false;
let landingExportSeq = 0;
let activeLandingOpGen = 0;
let activeLandingExportGen = 0;
let activeLandingConvertCtrl = null;
let activeLandingExportCtrl = null;

function invalidateLandingOperations(reason = 'reset') {
  activeLandingOpGen++;
  activeLandingExportGen++;
  landingExportSeq++;
  if (activeLandingConvertCtrl) {
    try { activeLandingConvertCtrl.abort(reason); } catch (_) {}
    activeLandingConvertCtrl = null;
  }
  if (activeLandingExportCtrl) {
    try { activeLandingExportCtrl.abort(reason); } catch (_) {}
    activeLandingExportCtrl = null;
  }
  currentOperationId = null;
  currentDemoBytes = null;
  if (btnDownloadDemoCsv) btnDownloadDemoCsv.disabled = true;
}

const LANDING_WIN1252 = {
  0x20ac: 0x80, 0x201a: 0x82, 0x0192: 0x83, 0x201e: 0x84, 0x2026: 0x85, 0x2020: 0x86, 0x2021: 0x87,
  0x02c6: 0x88, 0x2030: 0x89, 0x0160: 0x8a, 0x2039: 0x8b, 0x0152: 0x8c, 0x017d: 0x8e,
  0x2018: 0x91, 0x2019: 0x92, 0x201c: 0x93, 0x201d: 0x94, 0x2022: 0x95, 0x2013: 0x96,
  0x2014: 0x97, 0x02dc: 0x98, 0x2122: 0x99, 0x0161: 0x9a, 0x203a: 0x9b, 0x0153: 0x9c,
  0x017e: 0x9e, 0x0178: 0x9f
};

function encodeWindows1252(str) {
  const bytes = new Uint8Array(str.length);
  let replacedCount = 0;
  for (let i = 0; i < str.length; i++) {
    const code = str.charCodeAt(i);
    if (code <= 0x7f) {
      bytes[i] = code;
    } else if (code >= 0xa0 && code <= 0xff) {
      bytes[i] = code;
    } else if (LANDING_WIN1252[code]) {
      bytes[i] = LANDING_WIN1252[code];
    } else {
      bytes[i] = 0x3f;
      replacedCount++;
    }
  }
  return { bytes, replacedCount };
}

function encodeUtf8WithBom(str) {
  const body = new TextEncoder().encode(str);
  const out = new Uint8Array(3 + body.length);
  out[0] = 0xef; out[1] = 0xbb; out[2] = 0xbf;
  out.set(body, 3);
  return out;
}

function sanitizeCsvTextLanding(val) {
  let s = String(val || '').replace(/[\r\n\t]+/g, ' ').trim();
  if (s && ['=', '+', '-', '@'].includes(s[0])) s = "'" + s;
  return s;
}

function sanitizeCsvField(val) {
  const s = sanitizeCsvTextLanding(val);
  if (/[;"\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

function csvQuoteAllLanding(val) {
  const s = String(val ?? '');
  return `"${s.replace(/"/g, '""')}"`;
}

function formatDmyToIsoLanding(dmy) {
  if (!dmy) return '';
  if (/^\d{4}-\d{2}-\d{2}$/.test(dmy)) return dmy;
  const m = String(dmy).match(/^(\d{2})\.(\d{2})\.(\d{4})/);
  return m ? `${m[3]}-${m[2]}-${m[1]}` : String(dmy);
}

function formatIsoToDmy(iso) {
  if (!iso) return '';
  if (/^\d{2}\.\d{2}\.\d{4}$/.test(iso)) return iso;
  const m = String(iso).match(/^(\d{4})-(\d{2})-(\d{2})/);
  return m ? `${m[3]}.${m[2]}.${m[1]}` : String(iso);
}

function formatCentsComma(cents) {
  const n = Number(cents) || 0;
  if (n === 0) return '0,00';
  const sign = n < 0 ? '-' : '';
  const absC = Math.abs(Math.round(n));
  return `${sign}${Math.floor(absC / 100)},${String(absC % 100).padStart(2, '0')}`;
}

function getSelectedLandingFormat() {
  const r = document.querySelector('input[name="landing-export-format"]:checked');
  return r ? r.value : 'datev';
}

function syncLandingFormatUI(fmt) {
  document.querySelectorAll('input[name="landing-export-format"]').forEach(el => {
    el.checked = (el.value === fmt);
  });
  if (demoResultFormatSelect && demoResultFormatSelect.value !== fmt) {
    demoResultFormatSelect.value = fmt;
  }
  if (btnDownloadDemoText) {
    if (fmt === 'bmd_bankauszug') {
      btnDownloadDemoText.textContent = 'BMD Bankauszug (22 Sp.) laden';
    } else if (fmt === 'bmd_ntcs') {
      btnDownloadDemoText.textContent = 'BMD NTCS (8 Sp.) laden';
    } else {
      btnDownloadDemoText.textContent = 'DATEV CSV herunterladen';
    }
  }
}

function showDemoWarnings(messages, isError = false) {
  if (!demoWarnings) return;
  const clean = (messages || []).filter(Boolean);
  if (!clean.length) {
    demoWarnings.classList.add('hidden');
    demoWarnings.textContent = '';
    return;
  }
  demoWarnings.className = isError ? 's2m-alert s2m-alert--danger' : 's2m-alert s2m-alert--warning';
  demoWarnings.innerHTML = clean.map(m => `<div>${escapeHtml(m)}</div>`).join('');
  demoWarnings.classList.remove('hidden');
}

function updateLandingReconBadge(status) {
  if (!demoReconBadge || !demoReconText) return;
  if (status === 'BALANCED') {
    demoReconBadge.className = 's2m-badge s2m-badge--success';
    demoReconText.textContent = 'Salden ausgeglichen';
  } else if (status === 'DISCREPANCY') {
    demoReconBadge.className = 's2m-badge s2m-badge--danger';
    demoReconText.textContent = 'Saldenabweichung erkannt';
  } else {
    demoReconBadge.className = 's2m-badge s2m-badge--info';
    demoReconText.textContent = 'Exportvorschau bereit';
  }
}

function buildLandingCanonicalExport(txList, fmt, defaultBankAccount = null) {
  const txs = txList || [];
  if (fmt === 'bmd_bankauszug') {
    const headers22 = [
      'Transaction Booking Date','Transaction Purpose','Transaction Partner','Transaction Partner IBAN',
      'Transaction Foreign Currency','Transaction Foreign Amount','Transaction Currency','Transaction Amount',
      'Booking Amount','Invoice Type','Invoice Currency','Invoice Total','Invoice Number','Invoice Internal No',
      'Invoice Date','Invoice Partner Company','Invoice Partner Number','Invoice Document ID','Invoice File',
      'Invoice Tags','Transaction ID','Payment Category'
    ];
    const rows = txs.map((tx) => {
      const bDate = formatIsoToDmy(tx.booking_date || tx.date);
      const partner = (tx.partner || '').trim();
      let purpose = (tx.description || tx.text || '').trim();
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
      const fAmt = (fCurr && tx.foreign_amount_cents != null) ? formatCentsComma(tx.foreign_amount_cents) : '';
      const curr = (tx.currency || 'EUR').toUpperCase();
      const amt = tx.amount_cents != null ? formatCentsComma(tx.amount_cents) : String(tx.amountStr || '0,00').replace(/^\+/, '');
      return [
        bDate, sanitizeCsvField(purpose), sanitizeCsvField(partner), sanitizeCsvField(pIban),
        sanitizeCsvField(fCurr), fAmt, sanitizeCsvField(curr),
        amt, amt, ...new Array(13).fill('')
      ].join(';');
    });
    const csvText = headers22.join(';') + '\r\n' + rows.join('\r\n') + '\r\n';
    return {
      bytes: encodeUtf8WithBom(csvText),
      filename: 'BMD_Bankauszug_22_Demo.csv',
      mime: 'text/csv;charset=utf-8;',
      replacedCount: 0,
      csvText,
    };
  }

  if (fmt === 'bmd_ntcs' || fmt === 'bmd') {
    const bmdKonto = (defaultBankAccount && String(defaultBankAccount).trim() !== '1200')
      ? String(defaultBankAccount).trim()
      : '2800';
    const hdr = ['Satzart', 'Belegdatum', 'Konto', 'Gegenkonto', 'Betrag', 'Währung', 'Text', 'Belegnummer']
      .map(csvQuoteAllLanding).join(';');
    const rows = txs.map((tx, i) => {
      const bDate = formatIsoToDmy(tx.booking_date || tx.date);
      const p = (tx.partner || '').trim();
      const d = (tx.description || tx.text || '').trim();
      const fullTxt = (p && d && !d.includes(p)) ? `${p} - ${d}` : (d || p);
      const cleanTxt = sanitizeCsvTextLanding(fullTxt).slice(0, 120);
      const cleanRef = sanitizeCsvTextLanding(tx.reference || `DEMO-${i + 1}`).slice(0, 30);
      const contra = (tx.contra_account || '').trim();
      const curr = (tx.currency || 'EUR').trim();
      const amt = tx.amount_cents != null ? formatCentsComma(tx.amount_cents) : String(tx.amountStr || '0,00').replace(/^\+/, '');
      return [
        '0', bDate, bmdKonto, contra, amt, curr, cleanTxt, cleanRef
      ].map(csvQuoteAllLanding).join(';');
    });
    const csvText = hdr + '\r\n' + rows.join('\r\n') + '\r\n';
    const enc = encodeWindows1252(csvText);
    return {
      bytes: enc.bytes,
      filename: 'BMD_Bankauszug_Demo.csv',
      mime: 'text/csv;charset=windows-1252;',
      replacedCount: enc.replacedCount,
      csvText,
    };
  }

  const datevKonto = (defaultBankAccount && String(defaultBankAccount).trim()) ? String(defaultBankAccount).trim() : '1200';
  const years = txs.map(t => formatDmyToIsoLanding(t.booking_date || t.date)).filter(Boolean).map(s => s.slice(0, 4)).sort();
  const yr = years[0] || String(new Date().getFullYear());
  const nowStr = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14) + '000';
  const extfLine1 = `"EXTF";700;21;"Buchungsstapel";12;${nowStr};;"";"";"";1001;10001;${yr}0101;4;${yr}0101;${yr}1231;"Statement2Muster";"";1;;0;"EUR"`;
  const extfLine2 = [
    'Umsatz (ohne Soll/Haben-Kz)', 'Soll/Haben-Kennzeichen', 'WKZ Umsatz', 'Kurs',
    'Basis-Umsatz', 'WKZ Basis-Umsatz', 'Konto', 'Gegenkonto (ohne BU-Schlüssel)',
    'BU-Schlüssel', 'Belegdatum', 'Belegfeld 1', 'Belegfeld 2', 'Skonto', 'Buchungstext'
  ].map(csvQuoteAllLanding).join(';');
  const rows = txs.map((tx, i) => {
    const cents = tx.amount_cents != null ? Number(tx.amount_cents) : Math.round((Number(tx.numericVal) || 0) * 100);
    const sh = cents >= 0 ? 'S' : 'H';
    const absAmt = formatCentsComma(Math.abs(cents));
    const curr = (tx.currency || 'EUR').trim();
    const contra = (tx.contra_account || '').trim();
    const dmy = formatIsoToDmy(tx.booking_date || tx.date);
    const ttmm = dmy.length >= 5 ? dmy.slice(0, 2) + dmy.slice(3, 5) : '0000';
    const p = (tx.partner || '').trim();
    const d = (tx.description || tx.text || '').trim();
    const fullTxt = (p && d && !d.includes(p)) ? `${p} - ${d}` : (d || p);
    const cleanRef = sanitizeCsvTextLanding(tx.reference || `DEMO-${i + 1}`).slice(0, 36);
    const cleanTxt = sanitizeCsvTextLanding(fullTxt).slice(0, 60);
    return [
      absAmt, sh, curr, '', '', '',
      datevKonto, contra, '', ttmm, cleanRef, '', '', cleanTxt
    ].map(csvQuoteAllLanding).join(';');
  });
  const csvText = extfLine1 + '\r\n' + extfLine2 + '\r\n' + rows.join('\r\n') + '\r\n';
  const enc = encodeWindows1252(csvText);
  return {
    bytes: enc.bytes,
    filename: 'EXTF_Buchungsstapel_Demo.csv',
    mime: 'text/plain;charset=windows-1252;',
    replacedCount: enc.replacedCount,
    csvText,
  };
}

function buildSampleExport(fmt) {
  const canonicalSampleTxs = SAMPLE_TRANSACTIONS.map((t, i) => ({
    booking_date: formatDmyToIsoLanding(t.date),
    partner: null,
    partner_iban: null,
    description: t.text,
    amount_cents: Math.round((Number(t.numericVal) || 0) * 100),
    currency: 'EUR',
    reference: `DEMO-${i + 1}`,
    contra_account: '',
  }));
  const out = buildLandingCanonicalExport(canonicalSampleTxs, fmt);
  currentDemoBytes = out.bytes;
  currentDemoFilename = out.filename;
  currentDemoMime = out.mime;
  if (btnDownloadDemoCsv) btnDownloadDemoCsv.disabled = false;
  return out;
}

async function fetchLandingExportBytes(fmt, expectedOpGen = null) {
  syncLandingFormatUI(fmt);
  if (isSampleMode) {
    const out = buildSampleExport(fmt);
    if (out.replacedCount > 0) {
      showDemoWarnings([`${out.replacedCount} Sonderzeichen außerhalb Windows-1252 wurden durch '?' ersetzt.`], false);
    } else {
      showDemoWarnings([]);
    }
    return true;
  }
  if (!currentOperationId) return false;

  const opGen = expectedOpGen !== null ? expectedOpGen : activeLandingOpGen;
  const expGen = ++activeLandingExportGen;
  landingExportSeq++;
  if (activeLandingExportCtrl) {
    try { activeLandingExportCtrl.abort('superseded'); } catch (_) {}
    activeLandingExportCtrl = null;
  }
  currentDemoBytes = null;
  if (btnDownloadDemoCsv) btnDownloadDemoCsv.disabled = true;

  const token = sessionStorage.getItem('s2m_access_token');
  if (!token) {
    showDemoWarnings(['Sitzung abgelaufen. Bitte erneut anmelden.'], true);
    return false;
  }

  const timeoutMs = window.__LANDING_TIMEOUT_MS || 30000;
  const controller = new AbortController();
  activeLandingExportCtrl = controller;
  const timeoutId = setTimeout(() => {
    try { controller.abort('timeout'); } catch (_) {}
  }, timeoutMs);

  try {
    const resp = await fetch(`${apiBaseUrl}/api/v1/operations/${encodeURIComponent(currentOperationId)}/export?format=${encodeURIComponent(fmt)}`, {
      method: 'GET',
      headers: { Authorization: `Bearer ${token}` },
      signal: controller.signal
    });
    if (opGen !== activeLandingOpGen || expGen !== activeLandingExportGen) return false;

    if (!resp.ok) {
      const errJson = await resp.json().catch(() => ({}));
      if (opGen !== activeLandingOpGen || expGen !== activeLandingExportGen) return false;
      const detail = errJson.detail || `Exportfehler (${resp.status})`;
      if (resp.status === 410) {
        currentOperationId = null;
      }
      showDemoWarnings([detail], true);
      if (btnDownloadDemoCsv) btnDownloadDemoCsv.disabled = true;
      return false;
    }

    const buf = await resp.arrayBuffer();
    if (opGen !== activeLandingOpGen || expGen !== activeLandingExportGen) return false;
    currentDemoBytes = new Uint8Array(buf);
    const disp = resp.headers.get('Content-Disposition') || '';
    const fnMatch = disp.match(/filename="?([^";]+)"?/);
    currentDemoFilename = (fnMatch && fnMatch[1]) || (fmt === 'bmd_bankauszug' ? 'BMD_Bankauszug_22.csv' : fmt === 'bmd_ntcs' ? 'BMD_Bankauszug.csv' : 'EXTF_Buchungsstapel.csv');
    currentDemoMime = resp.headers.get('Content-Type') || (fmt === 'bmd_bankauszug' ? 'text/csv;charset=utf-8;' : 'text/csv;charset=windows-1252;');
    if (btnDownloadDemoCsv) btnDownloadDemoCsv.disabled = false;
    showDemoWarnings(currentCanonicalData?.warnings || [], false);
    return true;
  } catch (err) {
    if (opGen !== activeLandingOpGen || expGen !== activeLandingExportGen) return false;
    if (controller.signal.aborted && controller.signal.reason === 'timeout') {
      showDemoWarnings([`Zeitüberschreitung beim Export (${timeoutMs / 1000}s).`], true);
    } else {
      showDemoWarnings([err.message || 'Export konnte nicht geladen werden.'], true);
    }
    if (btnDownloadDemoCsv) btnDownloadDemoCsv.disabled = true;
    return false;
  } finally {
    clearTimeout(timeoutId);
    if (activeLandingExportCtrl === controller) activeLandingExportCtrl = null;
  }
}

// ==========================================================================
// 1. Live Demo & Converter
// ==========================================================================

// Drag & Drop
if (landingDropzone) {
  landingDropzone.addEventListener('click', () => landingFileInput.click());
  landingDropzone.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      landingFileInput.click();
    }
  });

  ['dragenter', 'dragover'].forEach(name => {
    landingDropzone.addEventListener(name, (e) => {
      e.preventDefault();
      landingDropzone.classList.add('dragover');
    });
  });

  ['dragleave', 'drop'].forEach(name => {
    landingDropzone.addEventListener(name, (e) => {
      e.preventDefault();
      landingDropzone.classList.remove('dragover');
    });
  });

  landingDropzone.addEventListener('drop', (e) => {
    const files = Array.from(e.dataTransfer.files);
    if (files && files.length > 0) {
      processUploadedFiles(files);
    }
  });

  landingFileInput.addEventListener('change', (e) => {
    const files = Array.from(e.target.files);
    if (files && files.length > 0) {
      processUploadedFiles(files);
    }
  });
}

// 1-Click Sample Loader & Format Sync
document.querySelectorAll('input[name="landing-export-format"]').forEach(radio => {
  radio.addEventListener('change', (e) => {
    const fmt = e.target.value;
    syncLandingFormatUI(fmt);
    if (isSampleMode || currentOperationId) {
      fetchLandingExportBytes(fmt);
    }
  });
});

if (demoResultFormatSelect) {
  demoResultFormatSelect.addEventListener('change', (e) => {
    const fmt = e.target.value;
    syncLandingFormatUI(fmt);
    if (isSampleMode || currentOperationId) {
      fetchLandingExportBytes(fmt);
    }
  });
}

if (landingValutaCheckbox) {
  landingValutaCheckbox.addEventListener('change', () => {
    const hadOp = Boolean(currentOperationId || currentCanonicalData);
    invalidateLandingOperations('valuta_changed');
    if (hadOp && !isSampleMode) {
      showDemoWarnings(['Datumsoption geändert — bitte Datei erneut hochladen, um das Ergebnis neu zu berechnen.'], false);
    }
  });
}

if (btnLoadSample) {
  btnLoadSample.addEventListener('click', () => {
    invalidateLandingOperations('sample_clicked');
    const opGen = activeLandingOpGen;
    const fmt = getSelectedLandingFormat();
    showDemoStatus('Lade Musterdaten...');
    isSampleMode = true;
    currentCanonicalData = null;
    setTimeout(() => {
      if (opGen !== activeLandingOpGen) return;
      syncLandingFormatUI(fmt);
      const out = buildSampleExport(fmt);
      updateLandingReconBadge('BALANCED');
      if (out.replacedCount > 0) {
        showDemoWarnings([`${out.replacedCount} Sonderzeichen außerhalb Windows-1252 wurden durch '?' ersetzt.`], false);
      } else {
        showDemoWarnings([]);
      }
      renderDemoTable(SAMPLE_TRANSACTIONS);
      hideDemoStatus();
    }, 250);
  });
}

function mapCanonicalTxToDemoRow(tx) {
  const displayDate = tx.booking_date
    ? formatIsoToDmy(tx.booking_date)
    : (tx.value_date ? `${formatIsoToDmy(tx.value_date)} (Valuta)` : '—');
  const partnerPrefix = tx.partner && !String(tx.description || '').toLowerCase().startsWith(String(tx.partner).toLowerCase())
    ? `${tx.partner} — `
    : '';
  const cents = Number(tx.amount_cents) || 0;
  return {
    date: displayDate,
    text: `${partnerPrefix}${tx.description || ''}`.trim() || tx.partner || 'Buchung',
    amountStr: formatCentsComma(cents),
    numericVal: cents / 100,
    isCredit: cents >= 0,
    currency: tx.currency || 'EUR',
  };
}

async function processUploadedFiles(files) {
  invalidateLandingOperations('upload');
  const opGen = activeLandingOpGen;
  currentCanonicalData = null;
  isSampleMode = false;
  if (demoResult) demoResult.classList.add('hidden');
  showDemoStatus(`Analysiere ${files.length} Datei(en) in-memory...`);

  const formData = new FormData();
  for (const f of files) {
    formData.append('files', f);
  }
  const selectedFormat = getSelectedLandingFormat();
  const useValuta = Boolean(landingValutaCheckbox && landingValutaCheckbox.checked);

  const timeoutMs = window.__LANDING_TIMEOUT_MS || 30000;
  const controller = new AbortController();
  activeLandingConvertCtrl = controller;
  const timeoutId = setTimeout(() => {
    try { controller.abort('timeout'); } catch (_) {}
  }, timeoutMs);

  try {
    const token = sessionStorage.getItem('s2m_access_token');
    if (!token) {
      showAuthModal();
      showDemoStatus('Bitte melden Sie sich an, bevor Sie einen Auszug hochladen.');
      return;
    }
    const response = await fetch(
      `${apiBaseUrl}/api/v1/convert?format=json&target_format=${encodeURIComponent(selectedFormat)}&use_valuta_as_booking_date=${useValuta ? 'true' : 'false'}`,
      {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: formData,
        signal: controller.signal
      }
    );
    if (opGen !== activeLandingOpGen) return;

    if (response.status === 422) {
      const errJson = await response.json().catch(() => ({}));
      if (opGen !== activeLandingOpGen) return;
      if (errJson && errJson.result) {
        currentCanonicalData = errJson.result;
        currentOperationId = null;
        currentDemoBytes = null;
        const blockedRows = (errJson.result.transactions || []).map(mapCanonicalTxToDemoRow);
        updateLandingReconBadge(errJson.result.overall_reconciliation || 'UNVERIFIED');
        renderDemoTable(blockedRows);
        if (btnDownloadDemoCsv) btnDownloadDemoCsv.disabled = true;
        const blocks = errJson.export_blocks && errJson.export_blocks.length ? errJson.export_blocks : [errJson.detail || 'Export blockiert'];
        showDemoWarnings([...(errJson.result.warnings || []), ...blocks], true);
        hideDemoStatus();
        return;
      }
      throw new Error(errJson.detail || 'Validierungsfehler (422)');
    }

    if (!response.ok) {
      if (response.status === 401) {
        sessionStorage.removeItem('s2m_access_token');
        if (btnOpenLogin) btnOpenLogin.textContent = 'Anmelden';
        showAuthModal();
        throw new Error('Ihre Sitzung ist abgelaufen. Bitte melden Sie sich erneut an.');
      }
      const errJson = await response.json().catch(() => ({}));
      throw new Error(errJson.detail || `Fehler beim Konvertieren: ${response.statusText}`);
    }

    const data = await response.json();
    if (opGen !== activeLandingOpGen) return;

    currentCanonicalData = data;
    currentOperationId = data.operation_id || null;

    const transactions = (data.transactions || []).map(mapCanonicalTxToDemoRow);
    updateLandingReconBadge(data.overall_reconciliation || 'UNVERIFIED');
    renderDemoTable(transactions);
    hideDemoStatus();

    if (currentOperationId && !(data.export_blocks && data.export_blocks.length)) {
      await fetchLandingExportBytes(selectedFormat, opGen);
    } else if (data.export_blocks && data.export_blocks.length) {
      if (btnDownloadDemoCsv) btnDownloadDemoCsv.disabled = true;
      showDemoWarnings([...(data.warnings || []), ...data.export_blocks], true);
    } else if (data.warnings && data.warnings.length) {
      showDemoWarnings(data.warnings, false);
    }
  } catch (err) {
    if (opGen !== activeLandingOpGen) return;
    console.error('Konvertierungsfehler:', err);
    currentDemoBytes = null;
    if (demoResult) demoResult.classList.add('hidden');
    const msg = (controller.signal.aborted && controller.signal.reason === 'timeout')
      ? `Zeitüberschreitung: Server hat nicht innerhalb von ${timeoutMs / 1000}s geantwortet.`
      : (err.message || 'Die Datei konnte nicht verarbeitet werden. Bitte prüfen Sie das Format.');
    showDemoStatus(msg);
    setTimeout(() => {
      if (opGen === activeLandingOpGen) hideDemoStatus();
    }, 5000);
  } finally {
    clearTimeout(timeoutId);
    if (activeLandingConvertCtrl === controller) activeLandingConvertCtrl = null;
  }
}

function showDemoStatus(msg) {
  if (demoStatus) {
    demoStatus.classList.remove('hidden');
    demoStatusText.textContent = msg;
  }
}

function hideDemoStatus() {
  if (demoStatus) demoStatus.classList.add('hidden');
}

function renderDemoTable(items) {
  if (!demoTableBody) return;
  demoTableBody.innerHTML = '';

  let sumCents = 0;

  items.forEach(item => {
    sumCents += Math.round((item.numericVal || 0) * 100);
    const isCredit = item.isCredit;
    const amountClass = isCredit ? 'td-amount-demo is-credit' : 'td-amount-demo';
    // amountStr may already carry a sign ("+2450,00" / "-74,10"): print exactly one
    const unsigned = String(item.amountStr).replace(/^[+-−]/, '');
    const displayAmount = `${isCredit ? '+' : '−'}${unsigned} €`;

    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td class="td-date-demo">${escapeHtml(item.date)}</td>
      <td class="td-text-demo">${escapeHtml(item.text)}</td>
      <td class="${amountClass}">${escapeHtml(displayAmount)}</td>
    `;

    // Floating Popover Loupe
    tr.addEventListener('mouseenter', (e) => {
      if (!landingPopover) return;
      const activeFmt = getSelectedLandingFormat();
      const fmtLabel = activeFmt === 'bmd_bankauszug'
        ? 'BMD Bankauszug (22 Sp.)'
        : activeFmt === 'bmd_ntcs'
          ? 'BMD NTCS (8 Sp.)'
          : 'DATEV EXTF';
      landingPopover.innerHTML = `
        <div class="s2m-pop__head">
          <span class="s2m-num s2m-muted">${escapeHtml(item.date)}</span>
          <span class="${amountClass}">${escapeHtml(displayAmount)}</span>
        </div>
        <div class="s2m-pop__text">${escapeHtml(item.text)}</div>
        <div class="s2m-pop__foot"><span>${escapeHtml(fmtLabel)}</span><span>Währung: ${escapeHtml(item.currency || 'EUR')}</span></div>
      `;
      landingPopover.classList.remove('hidden');
      landingPopover.classList.add('visible');
      positionPopover(e);
    });

    tr.addEventListener('mousemove', positionPopover);

    tr.addEventListener('mouseleave', () => {
      if (!landingPopover) return;
      landingPopover.classList.remove('visible');
      setTimeout(() => landingPopover.classList.add('hidden'), 150);
    });

    demoTableBody.appendChild(tr);
  });

  if (demoCount) demoCount.textContent = items.length;
  if (demoSum) {
    const sum = sumCents / 100;
    const sign = sum > 0 ? '+' : sum < 0 ? '−' : '';
    demoSum.textContent = sign + Math.abs(sum).toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' €';
  }
  if (demoResult) demoResult.classList.remove('hidden');
}

function positionPopover(e) {
  if (!landingPopover) return;
  const popoverWidth = 320;
  const popoverHeight = 120;
  const margin = 16;

  let x = e.clientX + margin;
  let y = e.clientY - (popoverHeight / 2);

  if (x + popoverWidth > window.innerWidth - 10) {
    x = e.clientX - popoverWidth - margin;
  }
  if (y + popoverHeight > window.innerHeight - 10) {
    y = window.innerHeight - popoverHeight - 10;
  }

  landingPopover.style.left = `${Math.max(10, x)}px`;
  landingPopover.style.top = `${Math.max(10, y)}px`;
}

// Download Button
if (btnDownloadDemoCsv) {
  btnDownloadDemoCsv.addEventListener('click', () => {
    if (!currentDemoBytes || !currentDemoBytes.length) {
      showDemoStatus('Keine gültige Exportdatei verfügbar. Bitte prüfen Sie Hinweise oben oder laden Sie den Auszug neu.');
      setTimeout(() => hideDemoStatus(), 3500);
      return;
    }

    const blob = new Blob([currentDemoBytes], { type: currentDemoMime || 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = currentDemoFilename || 'Statement2Muster.csv';
    a.click();
    URL.revokeObjectURL(url);
  });
}

// ==========================================================================
// 2. ROI / Savings Calculator
// ==========================================================================

const calcSlider = document.getElementById('calc-slider');
const sliderVal = document.getElementById('slider-val');
const hoursSaved = document.getElementById('hours-saved');
const moneySaved = document.getElementById('money-saved');

if (calcSlider) {
  calcSlider.addEventListener('input', () => {
    const count = parseInt(calcSlider.value, 10);
    sliderVal.textContent = `${count} Auszüge`;

    // Calculation: ~20 mins (0.33 hours) manual work saved per statement
    const hours = (count * 0.33).toFixed(1);
    // Hourly rate avg 80€/h
    const money = Math.round(hours * 80);

    hoursSaved.textContent = `${hours.replace('.', ',')} Std.`;
    moneySaved.textContent = `${money.toLocaleString('de-DE')} €`;
  });
}

// ==========================================================================
// 3. Billing Toggle (Monthly / Annual)
// ==========================================================================

const billingToggle = document.getElementById('billing-toggle');
const labelMonthly = document.getElementById('label-monthly');
const labelAnnual = document.getElementById('label-annual');
const priceStarter = document.getElementById('price-starter');
const periodStarter = document.getElementById('period-starter');
const btnLinkStarter = document.getElementById('btn-link-starter');
const pricePro = document.getElementById('price-pro');
const periodPro = document.getElementById('period-pro');

let isAnnual = false;

if (billingToggle) {
  billingToggle.addEventListener('click', () => {
    isAnnual = !isAnnual;
    billingToggle.classList.toggle('active', isAnnual);
    labelMonthly.classList.toggle('active', !isAnnual);
    labelAnnual.classList.toggle('active', isAnnual);

    if (isAnnual) {
      if (priceStarter) priceStarter.textContent = '4.08';
      if (periodStarter) periodStarter.textContent = '/ Monat (49 € / Jahr)';
      if (btnLinkStarter) btnLinkStarter.setAttribute('data-plan', 'starter-annual');

      if (pricePro) pricePro.textContent = '24';
      if (periodPro) periodPro.textContent = '/ Monat (290 € / Jahr)';
    } else {
      if (priceStarter) priceStarter.textContent = '4.90';
      if (periodStarter) periodStarter.textContent = '/ Monat';
      if (btnLinkStarter) btnLinkStarter.setAttribute('data-plan', 'starter-monthly');

      if (pricePro) pricePro.textContent = '29';
      if (periodPro) periodPro.textContent = '/ Monat';
    }
  });
}

// ==========================================================================
// 4. FAQ Accordion
// ==========================================================================

document.querySelectorAll('.faq-question').forEach(btn => {
  btn.addEventListener('click', () => {
    const item = btn.parentElement;
    const isActive = item.classList.contains('active');
    document.querySelectorAll('.faq-item').forEach(i => i.classList.remove('active'));
    if (!isActive) item.classList.add('active');
  });
});

// ==========================================================================
// 5. Account sign-in
// ==========================================================================

const authModal = document.getElementById('auth-modal');
const btnOpenLogin = document.getElementById('btn-open-login');
const btnCloseModal = document.getElementById('btn-close-modal');
const magicLinkForm = document.getElementById('magic-link-form');
const authEmail = document.getElementById('auth-email');
const authCode = document.getElementById('auth-code');
const authCodeGroup = document.getElementById('auth-code-group');
const authSubmit = document.getElementById('auth-submit');
const authStatus = document.getElementById('auth-status');
let authStage = 'email';
let oauthPopup = null;
let pendingSocialToken = null;

function setAuthStatus(message, error = false) {
  if (!authStatus) return;
  authStatus.textContent = message;
  authStatus.classList.toggle('is-error', Boolean(error));
}

function showAuthModal() {
  if (!authModal) return;
  authModal.classList.remove('hidden');
  authEmail?.focus();
}

async function setSignedIn(token) {
  if (pendingSocialToken) {
    const response = await fetch(`${apiBaseUrl}/api/v1/auth/oauth/link`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ pending_token: pendingSocialToken })
    });
    if (!response.ok) throw new Error('Das soziale Profil konnte nicht verknüpft werden. Bitte beginnen Sie die Anmeldung erneut.');
    pendingSocialToken = null;
    authEmail.readOnly = false;
  }
  sessionStorage.setItem('s2m_access_token', token);
  invalidateLandingOperations('login');
  if (btnOpenLogin) btnOpenLogin.textContent = 'Abmelden';
  if (authModal) authModal.classList.add('hidden');
  setAuthStatus('');
}

async function signOut() {
  invalidateLandingOperations('logout');
  currentCanonicalData = null;
  const token = sessionStorage.getItem('s2m_access_token');
  sessionStorage.removeItem('s2m_access_token');
  if (btnOpenLogin) btnOpenLogin.textContent = 'Anmelden';
  if (token) {
    try {
      await fetch(`${apiBaseUrl}/api/v1/auth/logout`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      });
    } catch (_) { /* The local session has already been cleared. */ }
  }
}

if (sessionStorage.getItem('s2m_access_token') && btnOpenLogin) {
  btnOpenLogin.textContent = 'Abmelden';
}

btnOpenLogin?.addEventListener('click', () => {
  if (sessionStorage.getItem('s2m_access_token')) signOut();
  else showAuthModal();
});

document.querySelectorAll('.btn-open-checkout, .btn-open-auth-trigger').forEach(btn => {
  btn.addEventListener('click', event => {
    event.preventDefault();
    showAuthModal();
  });
});

btnCloseModal?.addEventListener('click', () => authModal?.classList.add('hidden'));

magicLinkForm?.addEventListener('submit', async event => {
  event.preventDefault();
  const email = authEmail.value.trim().toLowerCase();
  if (!email) return;
  authSubmit.disabled = true;
  setAuthStatus('Bitte warten…');

  try {
    if (authStage === 'email') {
      const response = await fetch(`${apiBaseUrl}/api/v1/auth/request-code`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email })
      });
      if (!response.ok) throw new Error(response.status === 429 ? 'Zu viele Versuche. Bitte warten Sie einige Minuten.' : 'Der Code konnte nicht zugestellt werden. Bitte prüfen Sie die Adresse.');
      authStage = 'code';
      authCodeGroup.classList.remove('hidden');
      authCode.required = true;
      authSubmit.textContent = 'Code bestätigen';
      setAuthStatus('Wir haben Ihnen einen sechsstelligen Code geschickt. Er ist 10 Minuten gültig.');
      authCode.focus();
    } else {
      const response = await fetch(`${apiBaseUrl}/api/v1/auth/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, code: authCode.value.trim() })
      });
      if (!response.ok) throw new Error(response.status === 429 ? 'Zu viele Versuche. Bitte später erneut versuchen.' : 'Der Code ist ungültig oder abgelaufen.');
      const result = await response.json();
      if (!result.access_token) throw new Error('Die Anmeldung konnte nicht abgeschlossen werden.');
      await setSignedIn(result.access_token);
      authCode.value = '';
      authCode.required = false;
      authCodeGroup.classList.add('hidden');
      authSubmit.textContent = 'Code per E-Mail senden';
      authStage = 'email';
    }
  } catch (error) {
    setAuthStatus(error.message || 'Die Anmeldung ist fehlgeschlagen.', true);
  } finally {
    authSubmit.disabled = false;
  }
});

// Google is always offered; LinkedIn and Facebook only once the server has credentials for them.
// Until a provider is configured on the server, its button explains that instead of opening a broken popup.
const SOCIAL_PROVIDER_NAMES = { google: 'Google', linkedin: 'LinkedIn', facebook: 'Facebook' };
let configuredSocialProviders = null; // null = not known yet

function startSocialLogin(provider) {
  if (configuredSocialProviders && !configuredSocialProviders.has(provider)) {
    setAuthStatus(`Die Anmeldung mit ${SOCIAL_PROVIDER_NAMES[provider]} ist in Kürze verfügbar. Bitte nutzen Sie bis dahin den E-Mail-Code.`);
    return;
  }
  const url = `${apiBaseUrl}/api/v1/auth/oauth/${provider}/start`;
  oauthPopup = window.open(url, `s2m-${provider}-login`, 'popup,width=520,height=680');
  if (!oauthPopup) setAuthStatus('Bitte erlauben Sie Pop-up-Fenster und versuchen Sie es erneut.', true);
}

document.getElementById('btn-google-login')?.addEventListener('click', () => startSocialLogin('google'));
document.getElementById('btn-linkedin-login')?.addEventListener('click', () => startSocialLogin('linkedin'));
document.getElementById('btn-facebook-login')?.addEventListener('click', () => startSocialLogin('facebook'));

const OPTIONAL_SOCIAL_PROVIDERS = ['linkedin', 'facebook'];

function renderSocialButtons() {
  for (const provider of OPTIONAL_SOCIAL_PROVIDERS) {
    const button = document.getElementById(`btn-${provider}-login`);
    if (button) button.style.display = configuredSocialProviders?.has(provider) ? '' : 'none';
  }
  document.getElementById('social-auth-stack')?.style.setProperty('display', '');
  document.getElementById('social-auth-divider')?.style.setProperty('display', '');
}

async function showConfiguredSocialProviders() {
  renderSocialButtons();
  try {
    const response = await fetch(`${apiBaseUrl}/api/v1/auth/oauth/providers`);
    if (!response.ok) return;
    const data = await response.json();
    configuredSocialProviders = new Set(data.providers || []);
    renderSocialButtons();
  } catch (_) { /* Provider status unknown: buttons stay; the server answers if a provider is missing. */ }
}
showConfiguredSocialProviders();

window.addEventListener('message', async event => {
  if (event.origin !== new URL(apiBaseUrl).origin || event.source !== oauthPopup) return;
  const data = event.data;
  if (!data || data.type !== 'statement2muster:oauth') return;
  try {
    if (data.access_token) await setSignedIn(data.access_token);
    else if (data.pending_token && data.email) {
      pendingSocialToken = data.pending_token;
      authEmail.value = data.email;
      authEmail.readOnly = true;
      authStage = 'email';
      authCodeGroup.classList.add('hidden');
      authSubmit.textContent = 'Code per E-Mail senden';
      showAuthModal();
      setAuthStatus('Bestätigen Sie einmalig Ihre E-Mail-Adresse, um das Profil zu verknüpfen.');
    } else setAuthStatus(data.error || 'Die Anmeldung konnte nicht abgeschlossen werden.', true);
  } catch (error) { setAuthStatus(error.message, true); }
  oauthPopup = null;
});

// ==========================================================================
// 6. Legal Modal (Impressum / Datenschutz / AGB / AVV)
// ==========================================================================

const legalModal = document.getElementById('legal-modal');
const btnCloseLegal = document.getElementById('btn-close-legal');
const legalContent = document.getElementById('legal-content');

const LEGAL_TEXTS = {
  impressum: `
    <h2>Impressum</h2>
    <p><strong>Angaben gemäß § 5 E-Commerce-Gesetz (ECG) und § 25 Mediengesetz (MedienG):</strong></p>
    
    <h3>Diensteanbieter / Medieninhaber:</h3>
    <p>
      <strong>Grecciani Labs</strong><br>
      Statement2Muster Software Project<br>
      Roseggergasse 37<br>
      3400 Klosterneuburg (Kierling)<br>
      Österreich
    </p>

    <h3>Elektronische Kontaktaufnahme:</h3>
    <p>
      E-Mail: <a href="mailto:support@statement2muster.com" style="color: var(--primary); text-decoration: underline;">support@statement2muster.com</a><br>
      Kontakt: <a href="mailto:kontakt@statement2muster.com" style="color: var(--primary); text-decoration: underline;">kontakt@statement2muster.com</a><br>
      Web: <a href="https://statement2muster.com" target="_blank" style="color: var(--primary); text-decoration: underline;">https://statement2muster.com</a><br>
      <small style="color: var(--text-muted);">(Schnelle elektronische Kontaktaufnahme; Antwortzeit in der Regel &lt; 24h)</small>
    </p>

    <h3>Projekt- und Unternehmensgegenstand:</h3>
    <p>Entwicklung, Bereitstellung und Betrieb von browserbasierten Softwarewerkzeugen und B2B-Cloud-Diensten für das Finanz- und Rechnungswesen.</p>

    <h3>Haftungsausschluss:</h3>
    <p>Die Inhalte dieses Webangebots und der Software wurden mit größter Sorgfalt erstellt. Für die Richtigkeit, Vollständigkeit und Aktualität der bereitgestellten Inhalte und Vorlagen wird keine Gewähr übernommen.</p>
  `,

  datenschutz: `
    <h2>Datenschutzerklärung (DSGVO)</h2>
    <p>Der Schutz Ihrer persönlichen und geschäftlichen Daten ist uns ein besonderes Anliegen. Verantwortlicher für die Datenverarbeitung ist <strong>Vitali Grecciani (Einzelunternehmer, Grecciani Labs)</strong> (Roseggergasse 37, 3400 Klosterneuburg, Österreich, E-Mail: support@statement2muster.com). Wir verarbeiten Daten streng nach DSGVO und TKG 2021.</p>
    
    <h3>1. In-Memory-Verarbeitung & Speicherdauer (Zero Durable Storage)</h3>
    <p>Statement2Muster verarbeitet Auszüge flüchtig im RAM und Linux-<code>tmpfs</code>. Ein temporärer In-Memory-Cache (Standard-TTL: <strong>600 Sekunden / 10 Minuten ab Zwischenspeicherung</strong>) dient der idempotenten Wiederholung desselben Ergebnisses bei Verbindungsabbrüchen. Danach wird der Cache freigegeben. Keine dauerhafte Speicherung auf Festplatten/SSDs des Servers.</p>

    <h3>2. Serverstandort & Hosting (Hetzner)</h3>
    <p>Auszugsverarbeitung ausschließlich bei der <strong>Hetzner Online GmbH</strong> in einem ISO/IEC-27001-zertifizierten Rechenzentrum in <strong>Frankfurt am Main, Deutschland</strong>. Transportverschlüsselung via TLS 1.3 / TLS 1.2 mit Perfect Forward Secrecy.</p>

    <h3>3. E-Mail-OTP & Kommunikation (Resend, ImprovMX & Google)</h3>
    <p>Für Login-Einmalcodes nutzen wir <strong>Plus Five Five, Inc. (dba Resend, USA)</strong> (Übermittlung von E-Mail und 10-Min-Code; Resend DPA Stand 27.08.2026, EU-Standardvertragsklauseln nach Art. 46 DSGVO). Support-Anfragen an <code>support@statement2muster.com</code> werden über <strong>ImprovMX Inc. (USA)</strong> (abgesichert über ImprovMX DPA vom 09.09.2026 inkl. EU-SCCs) an das Postfach des Verantwortlichen (gehostet bei <strong>Google Ireland Ltd. / Google LLC</strong>, Data Privacy Framework) weitergeleitet.</p>

    <h3>4. Zahlungsabwicklung (Stripe)</h3>
    <p>Abrechnungen über <strong>Stripe Payments Europe, Ltd. (Irland)</strong> über PCI-DSS-Level-1-Infrastrukturen (nur kaufmännische Referenz-IDs, keine Auszugsdaten an Stripe).</p>

    <h3>5. Keine Tracking-Cookies & Lokale Erweiterungs-Historie</h3>
    <p>Keine Werbecookies oder Tracking-Pixel. Webbrowser speichert nur das kryptografisch signierte Sitzungs-Token (RS256 / RSA-2048). Die Chrome-Erweiterung speichert die Historie der letzten bis zu 15 Konvertierungen (inkl. Betragssumme und erzeugtem CSV-Text) <strong>ausschließlich lokal auf Ihrem Endgerät</strong> (<code>chrome.storage.local</code>) und kann jederzeit per Klick geleert werden.</p>

    <h3>6. Ihre Rechte & Aufsichtsbehörde</h3>
    <p>Ihnen stehen Auskunft, Berichtigung, Löschung, Einschränkung und Widerspruch zu (<a href="mailto:support@statement2muster.com" style="color: var(--primary);">support@statement2muster.com</a>). Zuständige Aufsichtsbehörde: <strong>Österreichische Datenschutzbehörde (DSB)</strong>, Barichgasse 40-42, 1030 Wien (<a href="https://www.dsb.gv.at" target="_blank" rel="noopener" style="color: var(--primary);">dsb.gv.at</a>).</p>
  `,

  avv: `
    <h2>Auftragsverarbeitungsvertrag (AVV nach Art. 28 DSGVO)</h2>
    <p>Für Steuerberater, Wirtschaftsprüfer und Unternehmen bieten wir gemäß Art. 28 Abs. 3 DSGVO einen standardisierten Auftragsverarbeitungsvertrag an.</p>
    <p>Flüchtige In-Memory-Verarbeitung (Zero Durable Storage) in RAM/<code>tmpfs</code> mit begrenztem 10-Minuten-Cache. Lokale Browser-Erweiterung speichert bis zu 15 Verläufe rein lokal auf dem Client-Gerät.</p>
    <p><strong>Genehmigte Subprozessoren:</strong></p>
    <ul>
      <li><strong>Hetzner Online GmbH (Deutschland):</strong> ISO 27001-Hosting in Frankfurt am Main (Auszugsverarbeitung & RAM-Cache).</li>
      <li><strong>Stripe Payments Europe, Ltd. (Irland / EU):</strong> Zahlungsabwicklung & Lizenzabrechnung (keine Auszugsinhalte).</li>
      <li><strong>Plus Five Five, Inc. / Resend (Delaware, USA):</strong> Transaktionale OTP-Zustellung (Resend DPA 27.08.2026, Art. 46 DSGVO SCCs).</li>
      <li><strong>ImprovMX Inc. (Delaware, USA) & Google Ireland Ltd. (Irland / EU):</strong> MX-Routing und Hosting des Support-Zielpostfachs (ImprovMX DPA 09.09.2026, Google DPF / SCCs).</li>
    </ul>
    <p>Vollständiger Vertragstext: <a href="/avv" style="color: var(--primary);" target="_blank">statement2muster.com/avv</a></p>
  `,

  agb: `
    <h2>Allgemeine Geschäftsbedingungen (AGB)</h2>
    <h3>1. Geltungsbereich</h3>
    <p>Diese AGB gelten für alle Dienstleistungen und Abonnements von Statement2Muster gegenüber Unternehmern im Sinne des § 1 UGB (B2B) und Verbrauchern.</p>
    <h3>2. Leistungsumfang</h3>
    <p>Statement2Muster stellt eine webbasierte Software zur Konvertierung von PDF/CSV-Auszügen in standardisierte DATEV- und BMD-Musterformate bereit.</p>
    <h3>3. Kündigung & Zahlungsmodalitäten</h3>
    <p>Monatliche Abonnements sind jederzeit zum Ende des jeweiligen Abrechnungsmonats kündbar. Jährliche Abonnements verlängern sich um ein weiteres Jahr, sofern sie nicht vor Ablauf gekündigt werden.</p>
  `,

  widerruf: `
    <h2>Widerrufsbelehrung & Refund Policy</h2>
    <div class="s2m-note" style="display:block">
      <strong>14 Tage Geld-zurück-Garantie</strong>
      <p style="margin: 4px 0 0;">Sollte ein unterstütztes Dateiformat technisch nicht wie versprochen in das DATEV/BMD-Muster konvertiert werden können, erstatten wir innerhalb von 14 Tagen 100% des Kaufpreises zurück.</p>
    </div>
    <h3>1. Widerrufsrecht für Verbraucher</h3>
    <p>Sie haben das Recht, binnen vierzehn Tagen ohne Angabe von Gründen diesen Vertrag zu widerrufen. Um Ihr Widerrufsrecht auszuüben, senden Sie eine E-Mail an: <a href="mailto:support@statement2muster.com" style="color: var(--primary);">support@statement2muster.com</a>.</p>
    <h3>2. Rückerstattungsablauf</h3>
    <p>Rückzahlungen werden innerhalb von 24–48 Stunden geprüft und über die ursprüngliche Zahlungsmethode (Stripe) ohne Bearbeitungsgebühren erstattet.</p>
  `
};

document.querySelectorAll('.legal-link').forEach(link => {
  link.addEventListener('click', (e) => {
    e.preventDefault();
    const type = link.getAttribute('data-legal');
    if (LEGAL_TEXTS[type]) {
      legalContent.innerHTML = LEGAL_TEXTS[type];
      legalModal.classList.remove('hidden');
    }
  });
});

if (btnCloseLegal) {
  btnCloseLegal.addEventListener('click', () => {
    legalModal.classList.add('hidden');
  });
}

// Close modals when clicking backdrop
[authModal, legalModal].forEach(modal => {
  if (modal) {
    modal.addEventListener('click', (e) => {
      if (e.target === modal) modal.classList.add('hidden');
    });
  }
});

function escapeHtml(text) {
  return (text || '')
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// ==========================================================================
// Illustration panels: cards follow the pointer (parallax), each at its own depth
// ==========================================================================

(function initPanelParallax() {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  if (!window.matchMedia('(hover: hover) and (pointer: fine)').matches) return;

  const depths = [14, 26, 20, 32];
  document.querySelectorAll('.s2m-panel').forEach(panel => {
    const layers = panel.querySelectorAll('.s2m-scene > .s2m-float, .s2m-scene > .s2m-chip');
    if (!layers.length) return;
    layers.forEach((el, i) => el.style.setProperty('--d', depths[i % depths.length]));
    panel.classList.add('is-live');

    let frame = 0;
    panel.addEventListener('pointermove', (e) => {
      if (e.pointerType !== 'mouse') return;
      const rect = panel.getBoundingClientRect();
      const mx = ((e.clientX - rect.left) / rect.width - 0.5).toFixed(3);
      const my = ((e.clientY - rect.top) / rect.height - 0.5).toFixed(3);
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        panel.style.setProperty('--mx', mx);
        panel.style.setProperty('--my', my);
      });
    });
    panel.addEventListener('pointerleave', () => {
      cancelAnimationFrame(frame);
      panel.style.setProperty('--mx', 0);
      panel.style.setProperty('--my', 0);
    });
  });
})();
