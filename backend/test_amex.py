from app.parsers.amex_parser import AmexStatementParser, UniversalBankStatementParser

def test_amex_parser_regex():
    sample_text = """
    MSC POURIA SANGLAJI xxxx-xxxxxx-22001 07.08.26 07.09.26
    14.07 14.07 ZAHLUNG/ÜBERWEISUNG ERHALTEN BESTEN DANK 772,27 CR
    07.07 07.07 AMZN MKTP DE*3E6J35IJ5 AMZN.COM/BILL 15,12
    08.07 08.07 AMZN MKTP DE*8N9528JR5 AMZN.COM/BILL 32,76
    14.07 14.07 AMZN MKTP DE*X41CA7FS5 AMZN.COM/BILL 304,71
    14.07 15.07 AMZN MKTP DE*MG2UK5LO5 AMZN.COM/BILL 1.691,47
    15.07 15.07 OPENAI *CHATGPT SUBSCR SAN FRANCISCO 20.00 UNITED STATES DOLLAR 17,92
    Referenzwechselkurs 1.1383 + Entgelt in EUR 0,35
    06.08 06.08 AMZN MKTP DE AMZN.COM/BILL 168,06 CR
    07.08 07.08 MONATSGEBÜHR 57,50
    03.08 03.08 Entertainment Gutschrift 15,00 CR
    """
    
    import re
    line_pattern = re.compile(
        r"^(\d{2}\.\d{2})\s+(\d{2}\.\d{2})\s+(.+?)\s+([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})(?:\s+(CR))?$",
        re.MULTILINE
    )
    
    matches = []
    lines = [l.strip() for l in sample_text.strip().split('\n')]
    for line in lines:
        m = line_pattern.match(line)
        if m:
            matches.append(m.groups())
            
    assert len(matches) == 9

def test_universal_vrbank_parser():
    parser = UniversalBankStatementParser()
    sample_vr_text = """
    VR Bank Mittelhaardt eG
    Kontoauszug Nr. 06 / 2026 per 30.06.2026
    IBAN: DE12 5469 0000 0123 4567 89
    Kontoinhaber: Mustermann Webagentur GmbH
    
    Alter Kontostand: 12.450,00 EUR
    
    02.06.2026 02.06.2026 SEPA-Überweisung Amazon EU S.a.r.l.
    Rechnungsnr. 987654321
    IBAN DE99123456780000000000 120,50-
    
    05.06.2026 05.06.2026 Gehaltseingang / Kundenzahlung
    Musterkunde Projekt Relaunch
    + 4.850,00
    
    12.06.2026 12.06.2026 Kartenzahlung Shell Tankstelle 75,30 S
    
    18.06.2026 18.06.2026 Gutschrift Zinsen 12,40 H
    
    Neuer Kontostand: 17.116,60 EUR
    """
    
    txs = parser._extract_transactions(sample_vr_text, "2026", "Mustermann Webagentur GmbH", "DE12546900000123456789", "vrbank.pdf")
    assert len(txs) == 4
    
    # 1. Expense
    assert txs[0]["Belegdatum"] == "02.06.2026"
    assert txs[0]["Betrag"] == "-120,50"
    assert "Amazon" in txs[0]["Buchungstext"]
    
    # 2. Income
    assert txs[1]["Belegdatum"] == "05.06.2026"
    assert txs[1]["Betrag"] == "4850,00"
    assert "Musterkunde" in txs[1]["Buchungstext"]
    
    # 3. Debit with S
    assert txs[2]["Belegdatum"] == "12.06.2026"
    assert txs[2]["Betrag"] == "-75,30"
    
    # 4. Credit with H
    assert txs[3]["Belegdatum"] == "18.06.2026"
    assert txs[3]["Betrag"] == "12,40"
    
    print("All Universal VR Bank Parser tests passed successfully!")

if __name__ == "__main__":
    test_amex_parser_regex()
    test_universal_vrbank_parser()
    print("ALL TESTS PASSED!")
