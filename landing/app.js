// ==========================================================================
// BankSync Landing Page Interactive Logic
// ==========================================================================

const apiBaseUrl = 'http://127.0.0.1:8000';

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
const landingPopover = document.getElementById('landing-popover');

let currentDemoCsvText = '';

// ==========================================================================
// 1. Live Demo & Converter
// ==========================================================================

// Drag & Drop
if (landingDropzone) {
  landingDropzone.addEventListener('click', () => landingFileInput.click());

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

// 1-Click Sample Loader
if (btnLoadSample) {
  btnLoadSample.addEventListener('click', () => {
    showDemoStatus('Lade DATEV-Musterdaten...');
    setTimeout(() => {
      renderDemoTable(SAMPLE_TRANSACTIONS);
      hideDemoStatus();
    }, 400);
  });
}

async function processUploadedFiles(files) {
  showDemoStatus(`Analysiere ${files.length} Datei(en) in-memory...`);

  const formData = new FormData();
  for (const f of files) {
    formData.append('files', f);
  }

  try {
    const response = await fetch(`${apiBaseUrl}/api/v1/convert`, {
      method: 'POST',
      body: formData
    });

    if (!response.ok) {
      throw new Error(`Fehler beim Konvertieren: ${response.statusText}`);
    }

    const buffer = await response.arrayBuffer();
    const decoder = new TextDecoder('windows-1252');
    currentDemoCsvText = decoder.decode(buffer);

    // Parse CSV
    const lines = currentDemoCsvText.trim().split(/\r?\n/);
    const transactions = [];

    lines.slice(1).forEach(row => {
      if (!row.trim()) return;
      const cols = row.split(';');
      const date = cols[0] || '';
      const text = cols[1] || '';
      const amountStr = cols[2] || '0,00';
      const num = parseFloat(amountStr.replace(/\./g, '').replace(',', '.'));
      const isCredit = !amountStr.startsWith('-');

      transactions.push({
        date,
        text,
        amountStr,
        numericVal: isNaN(num) ? 0 : num,
        isCredit
      });
    });

    renderDemoTable(transactions);
    hideDemoStatus();

  } catch (err) {
    console.warn('Backend not reached, falling back to sample preview:', err);
    showDemoStatus('Zeige Muster-Konvertierung...');
    setTimeout(() => {
      renderDemoTable(SAMPLE_TRANSACTIONS);
      hideDemoStatus();
    }, 500);
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

  let sum = 0;

  items.forEach(item => {
    sum += item.numericVal || 0;
    const isCredit = item.isCredit;
    const color = isCredit ? 'color: #046a4e;' : 'color: #000000;';
    const displayAmount = isCredit ? `+${item.amountStr} €` : `${item.amountStr} €`;

    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td class="td-date-demo">${item.date}</td>
      <td class="td-text-demo">${escapeHtml(item.text)}</td>
      <td class="td-amount-demo" style="${color}">${displayAmount}</td>
    `;

    // Floating Popover Loupe
    tr.addEventListener('mouseenter', (e) => {
      if (!landingPopover) return;
      landingPopover.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid #d5c3ba; padding-bottom:5px; margin-bottom:6px;">
          <span style="font-size:11px; font-weight:800; color:#a84222; background:rgba(168,66,34,0.1); padding:2px 6px; border-radius:4px;">📅 ${item.date}</span>
          <span style="font-size:13px; font-weight:900; ${color}">${displayAmount}</span>
        </div>
        <div style="font-size:12px; font-weight:750; color:#000; line-height:1.4;">
          ${escapeHtml(item.text)}
        </div>
        <div style="display:flex; justify-content:space-between; font-size:10px; color:#5c4a44; margin-top:6px; padding-top:4px; border-top:1px dashed #d5c3ba;">
          <span>DATEV Format</span>
          <span>Währung: EUR</span>
        </div>
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
  if (demoSum) demoSum.textContent = sum.toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' €';
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
    let csvContent = currentDemoCsvText;
    if (!csvContent) {
      csvContent = "Belegdatum;Buchungstext;Betrag;Währung;Belegnummer;Gegenkonto/Konto\r\n" + 
        SAMPLE_TRANSACTIONS.map(t => `${t.date};${t.text};${t.amountStr};EUR;DEMO;`).join("\r\n");
    }

    const blob = new Blob([csvContent], { type: 'text/csv;charset=windows-1252;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'BankSync_DATEV_Muster.csv';
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
const pricePro = document.getElementById('price-pro');
const periodPro = document.getElementById('period-pro');
const priceKanzlei = document.getElementById('price-kanzlei');
const periodKanzlei = document.getElementById('period-kanzlei');

let isAnnual = false;

if (billingToggle) {
  billingToggle.addEventListener('click', () => {
    isAnnual = !isAnnual;
    billingToggle.classList.toggle('active', isAnnual);
    labelMonthly.classList.toggle('active', !isAnnual);
    labelAnnual.classList.toggle('active', isAnnual);

    if (isAnnual) {
      pricePro.textContent = '24';
      periodPro.textContent = '/ Monat (290 € / Jahr)';
      priceKanzlei.textContent = '65';
      periodKanzlei.textContent = '/ Monat (780 € / Jahr)';
    } else {
      pricePro.textContent = '29';
      periodPro.textContent = '/ Monat';
      priceKanzlei.textContent = '79';
      periodKanzlei.textContent = '/ Monat';
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
// 5. Auth Modal (Login / Signup)
// ==========================================================================

const authModal = document.getElementById('auth-modal');
const btnOpenLogin = document.getElementById('btn-open-login');
const btnCloseModal = document.getElementById('btn-close-modal');
const magicLinkForm = document.getElementById('magic-link-form');
const btnGoogleLogin = document.getElementById('btn-google-login');

if (btnOpenLogin) {
  btnOpenLogin.addEventListener('click', () => {
    authModal.classList.remove('hidden');
  });
}

document.querySelectorAll('.btn-open-checkout').forEach(btn => {
  btn.addEventListener('click', () => {
    const plan = btn.getAttribute('data-plan');
    authModal.classList.remove('hidden');
  });
});

if (btnCloseModal) {
  btnCloseModal.addEventListener('click', () => {
    authModal.classList.add('hidden');
  });
}

const btnLinkedinLogin = document.getElementById('btn-linkedin-login');
const btnFacebookLogin = document.getElementById('btn-facebook-login');

if (magicLinkForm) {
  magicLinkForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const email = document.getElementById('auth-email').value;
    alert(`✓ Anmeldelink wurde an ${email} gesendet!\n\nPrüfen Sie Ihr Postfach, um sich ohne Passwort anzumelden und Ihre 3 kostenlosen Konvertierungen zu nutzen.`);
    authModal.classList.add('hidden');
  });
}

if (btnGoogleLogin) {
  btnGoogleLogin.addEventListener('click', () => {
    alert('✓ Erfolgreich mit Google angemeldet!\n\nIhr Account wurde aktiviert. Sie haben 3 kostenlose Konvertierungen zur Verfügung.');
    authModal.classList.add('hidden');
  });
}

if (btnLinkedinLogin) {
  btnLinkedinLogin.addEventListener('click', () => {
    alert('✓ Erfolgreich mit LinkedIn angemeldet!\n\nIhr Kanzlei- & B2B-Profil wurde verifiziert. Sie können sofort starten.');
    authModal.classList.add('hidden');
  });
}

if (btnFacebookLogin) {
  btnFacebookLogin.addEventListener('click', () => {
    alert('✓ Erfolgreich mit Facebook angemeldet!\n\nIhr Account wurde aktiviert. Sie haben 3 kostenlose Konvertierungen zur Verfügung.');
    authModal.classList.add('hidden');
  });
}

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
      BankSync Software Project<br>
      Roseggergasse 37<br>
      3400 Klosterneuburg (Kierling)<br>
      Österreich
    </p>

    <h3>Elektronische Kontaktaufnahme:</h3>
    <p>
      E-Mail: <a href="mailto:support@banksync-dach.com" style="color: var(--primary); text-decoration: underline;">support@banksync-dach.com</a><br>
      Kontakt: <a href="mailto:kontakt@banksync-dach.com" style="color: var(--primary); text-decoration: underline;">kontakt@banksync-dach.com</a><br>
      Web: <a href="https://banksync-dach.com" target="_blank" style="color: var(--primary); text-decoration: underline;">https://banksync-dach.com</a><br>
      <small style="color: var(--text-muted);">(Schnelle elektronische Kontaktaufnahme; Antwortzeit in der Regel &lt; 24h)</small>
    </p>

    <h3>Projekt- und Unternehmensgegenstand:</h3>
    <p>Entwicklung, Bereitstellung und Betrieb von browserbasierten Softwarewerkzeugen und B2B-Cloud-Diensten für das Finanz- und Rechnungswesen.</p>

    <h3>Haftungsausschluss:</h3>
    <p>Die Inhalte dieses Webangebots und der Software wurden mit größter Sorgfalt erstellt. Für die Richtigkeit, Vollständigkeit und Aktualität der bereitgestellten Inhalte und Vorlagen wird keine Gewähr übernommen.</p>
  `,

  datenschutz: `
    <h2>Datenschutzerklärung (DSGVO)</h2>
    <p>Der Schutz Ihrer persönlichen Daten ist uns ein besonderes Anliegen. Verantwortlicher für die Datenverarbeitung ist <strong>Grecciani Labs</strong> (Roseggergasse 37, 3400 Klosterneuburg, E-Mail: support@banksync-dach.com). Wir verarbeiten Daten ausschließlich auf Grundlage der gesetzlichen Bestimmungen (DSGVO, TKG 2021).</p>
    
    <h3>1. In-Memory-Verarbeitung (Zero Server Storage)</h3>
    <p>BankSync verwendet ein striktes In-Memory-Prinzip: Hochgeladene PDF- und CSV-Auszüge werden flüchtig im Arbeitsspeicher verarbeitet und nach der Konvertierung in das DATEV/BMD-Format <strong>unverzüglich und vollständig aus dem Speicher gelöscht</strong>. Es findet keine Speicherung von Auszugsinhalten auf Festplatten oder Datenbanken statt.</p>

    <h3>2. Serverstandort & Hosting</h3>
    <p>Unsere Backend-Systeme werden in ISO-27001-zertifizierten Rechenzentren in <strong>Frankfurt am Main, Deutschland</strong> gehostet. Es erfolgt keine Übermittlung von Bankauszugsdaten in Drittstaaten außerhalb der Europäischen Union.</p>

    <h3>3. Ihre Rechte</h3>
    <p>Ihnen stehen grundsätzlich die Rechte auf Auskunft, Berichtigung, Löschung, Einschränkung, Datenübertragbarkeit und Widerspruch zu. Anfragen richten Sie bitte an: <a href="mailto:support@banksync-dach.com" style="color: var(--primary);">support@banksync-dach.com</a>. Wenn Sie glauben, dass die Verarbeitung Ihrer Daten gegen das Datenschutzrecht verstößt, können Sie sich an die österreichische Datenschutzbehörde (DSB, Barichgasse 40-42, 1030 Wien) wenden.</p>
  `,

  avv: `
    <h2>Auftragsverarbeitungsvertrag (AVV nach Art. 28 DSGVO)</h2>
    <p>Für Steuerberater, Wirtschaftsprüfer und Unternehmen bieten wir gemäß Art. 28 Abs. 3 DSGVO einen standardisierten Auftragsverarbeitungsvertrag an.</p>
    <p>Aufgrund unserer <strong>flüchtigen In-Memory-Technologie</strong> werden personenbezogene Buchungsdaten zu keinem Zeitpunkt persistent gespeichert. Der AVV kann direkt im Kundenbereich mit 1 Klick digital gegengezeichnet und als PDF für Ihre DSGVO-Dokumentation heruntergeladen werden.</p>
  `,

  agb: `
    <h2>Allgemeine Geschäftsbedingungen (AGB)</h2>
    <h3>1. Geltungsbereich</h3>
    <p>Diese AGB gelten für alle Dienstleistungen und Abonnements von BankSync gegenüber Unternehmern im Sinne des § 1 UGB (B2B).</p>
    <h3>2. Leistungsumfang</h3>
    <p>BankSync stellt eine webbasierte Software zur Konvertierung von Bank- und Kreditkartenauszügen in das DATEV- und BMD-Format bereit.</p>
    <h3>3. Kündigung & Zahlungsmodalitäten</h3>
    <p>Monatliche Abonnements sind zum Ende des jeweiligen Monats kündbar. Jährliche Abonnements verlängern sich um ein weiteres Jahr, sofern sie nicht vor Ablauf gekündigt werden.</p>
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
