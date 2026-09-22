# Vereinbarung zur Auftragsverarbeitung (AVV nach Art. 28 DSGVO)
## Muster-Vorlage für Pilot-Kanzleien & Kanzleikunden

---

### Vertragsparteien

Zwischen

**1. Dem Auftraggeber (Verantwortlicher gem. Art. 4 Nr. 7 DSGVO):**

* Kanzlei / Unternehmen: `[Name der Steuerberatungskanzlei / des Unternehmens]`
* Anschrift: `[Straße, Hausnummer, PLZ, Ort, Land]`
* Gesetzlich vertreten durch: `[Name(n) der vertretungsberechtigten Person(en)]`
* E-Mail für Datenschutzbelange: `[datenschutz@kanzlei-beispiel.at / .de]`
* (nachfolgend **„Auftraggeber“** oder **„Verantwortlicher“**)

und

**2. Dem Auftragnehmer (Auftragsverarbeiter gem. Art. 4 Nr. 8 DSGVO):**

* Unternehmen: **Vitali Grecciani (Grecciani Labs)**
* Anschrift: Roseggergasse 37, 3400 Klosterneuburg, Österreich
* E-Mail: `support@statement2muster.com`
* (nachfolgend **„Auftragnehmer“** oder **„Auftragsverarbeiter“**)

(nachfolgend einzeln auch „Partei“ und gemeinsam „Parteien“ genannt)

---

### Präambel

Der Auftraggeber nutzt oder evaluiert im Rahmen eines Pilotbetriebs die Softwarelösung **Statement2Muster / BankSync DACH** zur automatisierten Strukturierung, Normalisierung und Konvertierung digitaler Bank- und Kreditkartenauszüge in berufsübliche Zielformate des Rechnungswesens (DATEV Format EXTF, BMD NTCS). Im Rahmen dieser Tätigkeit kann nicht ausgeschlossen werden, dass der Auftragnehmer mit personenbezogenen Daten von Mandanten oder Geschäftspartnern des Auftraggebers in Berührung kommt. Zur Einhaltung der gesetzlichen Bestimmungen der Verordnung (EU) 2016/679 (Datenschutz-Grundverordnung – DSGVO), insbesondere des Art. 28 DSGVO, schließen die Parteien diese vertragliche Vereinbarung.

---

### § 1 Gegenstand, Zweck und Dauer der Auftragsverarbeitung

(1) **Gegenstand:** Der Auftragnehmer erbringt für den Auftraggeber Konvertierungs- und Strukturierungsdienstleistungen für digitale Kontoauszugsdateien über die Cloud-Plattform und Browser-Erweiterung Statement2Muster.
(2) **Zweck:** Zweck der Verarbeitung ist ausschließlich die technische Extraktion und Transformation von Banktransaktionen in normierte Buchungssätze zur Weiterverarbeitung in der Finanzbuchhaltung des Auftraggebers.
(3) **Dauer:** Die Vereinbarung gilt für die Dauer der Pilotierungsphase bzw. der vertraglichen Nutzung der Software und endet automatisch mit Beendigung der Inanspruchnahme des Dienstes.

---

### § 2 Art der verarbeiteten Daten und Kategorien betroffener Personen

(1) **Kategorien betroffener Personen:**
* Mandanten, Kunden, Lieferanten, Beschäftigte und sonstige Geschäftspartner des Auftraggebers, die als Zahlungsbeteiligte, Empfänger oder Kontoinhaber in den verarbeiteten Auszügen aufgeführt sind.
* Autorisierte Kanzleimitarbeiter / Nutzer des Auftraggebers.

(2) **Arten personenbezogener Daten:**
* **Flüchtige Bank- und Finanztransaktionsdaten:** Buchungsdatum, Valutadatum, Betrag, Währung, IBAN, BIC, Zahlungsbeteiligte (Name/Firma), Verwendungszweck-Texte, Rechnungs- und Belegnummern.
* **Nutzer- und Authentifizierungsdaten:** Geschäftliche E-Mail-Adresse des Kanzleimitarbeiters, temporärer 6-stelliger Einmalcode (OTP, Gültigkeit 10 Minuten), asymmetrisch signiertes Sitzungstoken (RS256 JWT, Gültigkeit 10 Minuten).
* **Abrechnungsmetadaten:** Stripe Customer ID, Stripe Subscription ID, Lizenz- und Quota-Status (keine Speicherung von Kreditkarten- oder Bankverbindungsdaten auf den Servern des Auftragnehmers).

---

### § 3 Weisungsgebundenheit des Auftragnehmers

(1) Der Auftragnehmer verarbeitet die personenbezogenen Daten ausschließlich auf dokumentierte Weisung des Auftraggebers, es sei denn, er ist durch das Recht der Union oder der Mitgliedstaaten, dem er unterliegt, zu einer anderweitigen Verarbeitung verpflichtet.
(2) Die Weisungserteilung erfolgt im Regelfall durch die softwareseitige Übergabe der Auszugsdateien und die Anforderung des gewünschten Zielformats (DATEV / BMD). Ergänzende Weisungen bedürfen der Schrift- oder Textform.
(3) Der Auftragnehmer informiert den Auftraggeber unverzüglich, wenn er der Auffassung ist, dass eine Weisung gegen die DSGVO oder andere Datenschutzvorschriften der Union oder der Mitgliedstaaten verstößt.

---

### § 4 Vertraulichkeit und Berufsgeheimnis

(1) Der Auftragnehmer gewährleistet, dass sich die mit der Datenverarbeitung befassten Personen zur Vertraulichkeit verpflichtet haben oder einer angemessenen gesetzlichen Verschwiegenheitspflicht unterliegen.
(2) Soweit der Auftraggeber Berufsgeheimnisträger im Sinne der berufsrechtlichen Vorschriften (z. B. § 43 WTBG für Wirtschaftstreuhänder in Österreich bzw. § 57 StBerG in Deutschland) ist, sichert der Auftragnehmer die Einhaltung berufsrechtlicher Schutzstandards im Rahmen der technischen Möglichkeiten zu.

---

### § 5 Technische und organisatorische Maßnahmen (TOMs gem. Art. 32 DSGVO)

(1) Der Auftragnehmer gewährleistet durch geeignete technische und organisatorische Maßnahmen ein dem Risiko angemessenes Schutzniveau. Die konkreten Maßnahmen sind in **Anlage 1** zu dieser Vereinbarung festgelegt.
(2) Kernpunkte des Schutzkonzepts sind:
* **Zero Durable Storage & Flüchtige Verarbeitung:** Eingehende Kontoauszugsdaten werden ausschließlich im flüchtigen Arbeitsspeicher (RAM) bzw. in temporären RAM-Dateisystemen (Linux `tmpfs`) verarbeitet. Zu keinem Zeitpunkt werden Auszugsinhalte auf Festplatten, SSDs oder Datenbanken des Servers gespeichert.
* **Idempotenter RAM-Ergebnis-Cache:** Zur Absicherung von Verbindungsabbrüchen und wiederholten Exportabrufen desselben Zielformats ohne erneuten Parsing-Aufwand und ohne Kontingentverlust wird das konvertierte Ergebnis für maximal 600 Sekunden (10 Minuten ab Zwischenspeicherung) im flüchtigen Arbeitsspeicher gehalten. Nach Ablauf dieser Frist oder bei Container-Neustart erfolgt die automatische Speicherfreigabe durch das Betriebssystem (Memory Deallocation / Garbage Collection).
* **Clientseitige Historie der Browser-Erweiterung:** Die Chrome-Erweiterung speichert die letzten bis zu 15 Konvertierungen (Metadaten, Gesamtsumme, generierter CSV-Text) **ausschließlich lokal auf dem Arbeitsplatzrechner des Nutzers** (`chrome.storage.local`). Diese Daten werden zu keinem Zeitpunkt an die Server des Auftragnehmers übertragen und können vom Kanzleimitarbeiter jederzeit über „Verlauf leeren“ gelöscht werden.
* **Transport- und Zugriffsschutz:** Durchgehend TLS 1.3 / TLS 1.2 mit Perfect Forward Secrecy; asymmetrisch signierte RS256-Sitzungstoken; Hosting in ISO/IEC 27001-zertifiziertem Rechenzentrum in Frankfurt am Main, Deutschland.

---

### § 6 Unterauftragsverhältnisse (Subprozessoren)

(1) Der Auftraggeber erteilt dem Auftragnehmer die allgemeine Genehmigung zur Hinzuziehung von Unterauftragsverarbeitern. Die zum Zeitpunkt des Vertragsschlusses genehmigten Unterauftragsverarbeiter sind in **Anlage 2** aufgeführt.
(2) Der Auftragnehmer informiert den Auftraggeber mindestens 14 Tage vorab über beabsichtigte Änderungen (Hinzuziehung oder Ersetzung). Der Auftraggeber hat das Recht, binnen 14 Tagen aus wichtigem datenschutzrechtlichem Grund Widerspruch einzulegen.
(3) Dem Unterauftragsverarbeiter werden dieselben Datenschutzpflichten auferlegt, die in dieser Vereinbarung festgelegt sind.

---

### § 7 Rechte der betroffenen Personen

(1) Der Auftragnehmer unterstützt den Auftraggeber nach Möglichkeit mit geeigneten technischen und organisatorischen Maßnahmen bei der Erfüllung der Pflichten zur Beantwortung von Anträgen auf Wahrnehmung von Betroffenenrechten (Art. 12–22 DSGVO).
(2) Da der Server-Verarbeitungspfad keine persistenten Auszugsdaten speichert (Zero Durable Retention), beschränkt sich die Auskunft im Hinblick auf Bankdaten auf den Hinweis der sofortigen flüchtigen Verarbeitung.

---

### § 8 Mitteilungspflichten bei Sicherheitsvorfällen

(1) Der Auftragnehmer benachrichtigt den Auftraggeber unverzüglich, spätestens jedoch binnen 48 Stunden nach Kenntnisnahme, über eine Verletzung des Schutzes personenbezogener Daten (Art. 33 DSGVO), die die Daten des Auftraggebers betrifft.
(2) Der Auftragnehmer stellt die zur Erfüllung der gesetzlichen Meldepflichten des Auftraggebers erforderlichen Informationen zur Verfügung.

---

### § 9 Beendigung und Löschung der Daten

(1) Nach Beendigung der Konvertierungsleistung bzw. nach Ablauf der flüchtigen Cache-Frist von 600 Sekunden oder bei Neustart des Server-Containers werden alle im Arbeitsspeicher gehaltenen Auszugs- und Ergebnisdaten systemseitig freigegeben (Deallokation im flüchtigen RAM). Die Garantie bezieht sich auf das systemseitige Erlöschen des verfügbaren Ergebnisses nach Fristablauf, nicht auf ein physikalisches Bit-Überschreiben der Hardware.
(2) Gesetzliche Aufbewahrungspflichten für abrechnungsrelevante Rechnungsbelege (BAO / HGB) bleiben unberührt.

---

### § 10 Kontrollrechte und Audits (Art. 28 Abs. 3 lit. h DSGVO)

(1) Der Auftragnehmer stellt dem Auftraggeber alle erforderlichen Informationen zum Nachweis der Einhaltung der Pflichten nach Art. 28 DSGVO zur Verfügung.
(2) Der Auftraggeber oder ein von ihm beauftragter, zur Verschwiegenheit verpflichteter Prüfer ist berechtigt, die Einhaltung der technischen und organisatorischen Maßnahmen nach vorheriger angemessener Ankündigung zu üblichen Geschäftszeiten zu überprüfen.

---

### § 11 Schlussbestimmungen

(1) Änderungen und Ergänzungen dieser Vereinbarung bedürfen der Schrift- oder Textform.
(2) Sollten einzelne Bestimmungen dieser Vereinbarung unwirksam sein oder werden, berührt dies die Wirksamkeit der übrigen Bestimmungen nicht.
(3) Diese Vereinbarung unterliegt dem Recht der Republik Österreich. Gerichtsstand für alle Streitigkeiten ist, soweit gesetzlich zulässig, Wien.

---

### Unterschriften

Ort, Datum: _______________________

Für den **Auftraggeber (Kanzlei / Pilot-Kunde):**

_________________________________________  
(Unterschrift / Name in Druckbuchstaben / Funktion)

Für den **Auftragnehmer (Grecciani Labs):**

_________________________________________  
Vitali Grecciani (Inhaber)

---

## Anlage 1: Technische und organisatorische Maßnahmen (TOMs gem. Art. 32 DSGVO)

### 1. Vertraulichkeit (Art. 32 Abs. 1 lit. b DSGVO)
* **Zutrittskontrolle:** ISO/IEC 27001-zertifiziertes Rechenzentrum der Hetzner Online GmbH in Frankfurt am Main (biometrische Zugangskontrollen, 24/7-Sicherheitsdienst, Videoüberwachung).
* **Zugangskontrolle:** 
  - SSH-Zugang zu Produktionsservern ausschließlich über ED25519-Schlüssel mit Passphrase; Root-Passwort-Login deaktiviert.
  - Web-Authentifizierung über passwortlose Einmalcodes (OTP, 10 Min. Gültigkeit) und asymmetrisch signierte RS256-JWT-Tokens.
* **Zugriffskontrolle:**
  - Role-Based Access Control (RBAC).
  - Keine direkten Datenbanktabellen für Finanz- oder Auszugstransaktionen (Zero Statement Retention).
* **Trennungskontrolle:**
  - Strikte funktionale Trennung der Pipelines (Kernverarbeitung und Support-Mailhosting auf Hetzner in Frankfurt am Main / Deutschland, Abrechnung bei Stripe in Irland, OTP-Mail bei Resend in USA).
  - Mandantendaten werden nicht vermischt; jede Konvertierungsanfrage läuft in einem isolierten flüchtigen Speicherbereich ab.

### 2. Integrität (Art. 32 Abs. 1 lit. b DSGVO)
* **Weitergabekontrolle:**
  - Verschlüsselte Übertragung aller Nutzdaten über TLS 1.3 bzw. TLS 1.2 mit Perfect Forward Secrecy und modernen Cipher-Suites (AES-GCM / ChaCha20-Poly1305).
  - Asymmetrisch signierte Token (RS256 / RSA-2048) verhindern Manipulation von Sitzungszuständen.
* **Eingabekontrolle:**
  - Audit-Logging administrativer Ereignisse (Login-Versuche, Token-Revocations) ohne Aufzeichnung von Auszugsinhalten.

### 3. Verfügbarkeit und Belastbarkeit (Art. 32 Abs. 1 lit. b DSGVO)
* Hochverfügbare Rechenzentrumsinfrastruktur mit redundanter Stromversorgung (USV, Dieselgeneratoren) und mehrfach redundanten Internetanbindungen.
* Automatisches Container-Monitoring mit Docker Healthchecks und Systemd-Neustart-Routinen.

### 4. Verfahren zur regelmäßigen Überprüfung und Bewertung (Art. 32 Abs. 1 lit. d DSGVO)
* Regelmäßige automatisierte Schwachstellenscans der Container-Images und Abhängigkeiten.
* Rigorose Architektur- und Compliance-Audits durch unabhängige Prüfinstanzen.
* Software-Release-Prozess mit Source-Provenance-Prüfungen und Git-Manifest-Abgleich.

---

## Anlage 2: Genehmigte Unterauftragsverarbeiter (Subprozessoren)

| Nr. | Unternehmen | Sitz | Standort der Verarbeitung | Gegenstand & Funktion | Rechtsgrundlage & Garantie |
|---|---|---|---|---|---|
| **1** | **Hetzner Online GmbH** | Industriestr. 25, 91710 Gunzenhausen, Deutschland | **Frankfurt am Main, Deutschland (EU)** | **Kernverarbeitung & Mailhosting:** Bereitstellung Cloud-Infrastruktur / Linux-Container für Parsing, Konvertierung, flüchtigen RAM-Cache (TTL 600s) sowie Mailserver für Support-Postfach | Auftragsverarbeitungsvertrag (AVV) gem. Art. 28 DSGVO; ISO/IEC 27001 zertifiziert. 100% EU/DE. |
| **2** | **Stripe Payments Europe, Ltd.** | 1 Grand Canal Street Lower, Dublin, D02 H210, Irland | Irland / EU | **Abrechnung:** Abwicklung von Lizenzzahlungen und Abonnements (verarbeitet nur kaufmännische Metadaten, keine Bankauszüge) | Stripe DPA (Stand 16.02.2024), PCI-DSS Level 1. |
| **3** | **Plus Five Five, Inc. (dba Resend)** | 2261 Market Street #5151, San Francisco, CA 94114, USA | USA / Global | **Authentifizierung:** Zustellung 6-stelliger transaktionaler Login-Einmalcodes (OTP) per E-Mail (nur E-Mail-Adresse + OTP, keine Bankauszüge) | Resend DPA (Stand: 27. August 2026) inkl. Standardvertragsklauseln der EU (SCCs) gem. Art. 46 DSGVO. |
