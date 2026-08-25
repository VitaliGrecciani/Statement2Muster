from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from typing import List, Dict, Any
import pandas as pd
import io
import json
import logging
import os

from app.parsers.amex_parser import AmexStatementParser, UniversalBankStatementParser

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("statement2muster")

app = FastAPI(title="Statement2Muster API", version="1.6.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Mixed-Accounts", "X-Accounts-Found", "X-Duplicates-Count", "Content-Disposition"]
)

amex_parser = AmexStatementParser()
universal_parser = UniversalBankStatementParser()

@app.get("/api/v1/health")
async def health_check():
    return {"status": "ok", "message": "Statement2Muster API is running"}

@app.post("/api/v1/convert")
async def convert_statements(files: List[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    logger.info(f"=== Received Batch Request: {len(files)} file(s) ===")

    all_transactions = []
    processed_accounts = {}
    processed_names = []

    for file in files:
        filename = file.filename or "statement.pdf"
        if not filename.lower().endswith(('.csv', '.pdf')):
            continue

        try:
            content = await file.read()
            if not content:
                continue
        except Exception as e:
            logger.error(f"Failed to read file {filename}: {e}")
            continue

        clean_name = filename.rsplit('.', 1)[0]
        processed_names.append(clean_name)
        logger.info(f"Processing in-memory: {filename} ({len(content)} bytes)")

        file_res = {"account_holder": "Unbekannt", "account_id": "", "transactions": []}

        if filename.lower().endswith('.pdf'):
            try:
                # 1. Choose parser based on document type / fallback chain
                if "amex" in filename.lower() or "american express" in filename.lower():
                    file_res = amex_parser.parse_with_metadata(content, filename=filename)
                    if not file_res.get("transactions"):
                        file_res = universal_parser.parse_with_metadata(content, filename=filename)
                else:
                    file_res = universal_parser.parse_with_metadata(content, filename=filename)
                    if not file_res.get("transactions"):
                        file_res = amex_parser.parse_with_metadata(content, filename=filename)

                logger.info(f"Parsed PDF '{filename}': {len(file_res['transactions'])} txs, Holder='{file_res['account_holder']}', ID='{file_res['account_id']}'")
            except Exception as e:
                logger.error(f"Error parsing PDF '{filename}': {e}", exc_info=True)
        elif filename.lower().endswith('.csv'):
            try:
                for enc in ['utf-8-sig', 'utf-8', 'windows-1252', 'latin-1']:
                    try:
                        text = content.decode(enc)
                        break
                    except UnicodeDecodeError:
                        continue
                else:
                    text = content.decode('utf-8', errors='ignore')

                df_raw = pd.read_csv(io.StringIO(text), sep=None, engine='python', on_bad_lines='skip')
                
                holder = "Wise Business" if "Wise" in filename or "TransferWise" in text else "Bank CSV"
                txs = []
                for _, row in df_raw.iterrows():
                    row_dict = row.dropna().to_dict()
                    if not row_dict:
                        continue
                    
                    date_val = str(row_dict.get('Date', row_dict.get('Datum', row_dict.get('Created on', ''))))
                    text_val = str(row_dict.get('Description', row_dict.get('Verwendungszweck', row_dict.get('Buchungstext', ''))))
                    amount_val = str(row_dict.get('Amount', row_dict.get('Betrag', row_dict.get('Total amount', '0,00'))))
                    currency_val = str(row_dict.get('Currency', row_dict.get('Währung', 'EUR')))
                    
                    if date_val and text_val:
                        txs.append({
                            "Belegdatum": date_val,
                            "Buchungstext": text_val,
                            "Betrag": amount_val,
                            "Währung": currency_val,
                            "Belegnummer": f"CSV-{len(txs)+1}",
                            "Gegenkonto/Konto": ""
                        })
                
                file_res = {
                    "account_holder": holder,
                    "account_id": "",
                    "transactions": txs
                }
                logger.info(f"Parsed CSV '{filename}': {len(txs)} txs, Holder='{holder}'")
            except Exception as e:
                logger.error(f"Error parsing CSV '{filename}': {e}")

        # Accumulate with account metadata tags
        acc_key = f"{file_res['account_holder']}_{file_res['account_id']}".strip('_') or "Standard"
        if acc_key not in processed_accounts:
            processed_accounts[acc_key] = {
                "name": file_res['account_holder'],
                "card": file_res['account_id'],
                "count": 0,
                "files": []
            }
        processed_accounts[acc_key]["count"] += len(file_res['transactions'])
        processed_accounts[acc_key]["files"].append(filename)

        for tx in file_res['transactions']:
            tx["_account_key"] = acc_key
            tx["_source_file"] = filename
            all_transactions.append(tx)

    if not all_transactions:
        raise HTTPException(status_code=422, detail="Keine Buchungssätze in den bereitgestellten Dateien gefunden.")

    # Deduplicate & Sort
    seen = set()
    unique_txs = []
    duplicate_count = 0

    for tx in all_transactions:
        key = (tx.get("Belegdatum"), tx.get("Buchungstext"), tx.get("Betrag"))
        if key in seen:
            duplicate_count += 1
        else:
            seen.add(key)
            unique_txs.append(tx)

    logger.info(f"Total parsed: {len(all_transactions)} txs | Unique: {len(unique_txs)} txs | Deduplicated: {duplicate_count}")

    is_mixed_accounts = len(processed_accounts) > 1

    # Convert to standard format
    export_txs = []
    for tx in unique_txs:
        export_txs.append({
            "Belegdatum": tx.get("Belegdatum", ""),
            "Buchungstext": tx.get("Buchungstext", ""),
            "Betrag": tx.get("Betrag", "0,00"),
            "Währung": tx.get("Währung", "EUR"),
            "Belegnummer": tx.get("Belegnummer", ""),
            "Gegenkonto/Konto": tx.get("Gegenkonto/Konto", ""),
            "_account_key": tx.get("_account_key", ""),
            "_source_file": tx.get("_source_file", "")
        })
    
    df_muster = pd.DataFrame(export_txs)
    
    try:
        df_muster['_temp_date'] = pd.to_datetime(df_muster['Belegdatum'], format='%d.%m.%Y', errors='coerce')
        df_muster = df_muster.sort_values(by='_temp_date').drop(columns=['_temp_date'])
    except Exception:
        pass

    if len(processed_names) == 1:
        out_name = f"Muster_{processed_names[0]}.csv"
    else:
        out_name = f"Muster_Sammelauszug_{len(processed_names)}_Dateien.csv"

    # We output clean CSV columns for download
    df_download = df_muster[[c for c in ["Belegdatum", "Buchungstext", "Betrag", "Währung", "Belegnummer", "Gegenkonto/Konto"] if c in df_muster.columns]]

    output = io.StringIO()
    df_download.to_csv(output, sep=';', index=False, encoding='windows-1252', decimal=',')
    csv_bytes = output.getvalue().encode('windows-1252', errors='replace')
    
    headers = {
        "Content-Disposition": f'attachment; filename="{out_name}"',
        "X-Mixed-Accounts": "true" if is_mixed_accounts else "false",
        "X-Accounts-Found": json.dumps(list(processed_accounts.values())),
        "X-Duplicates-Count": str(duplicate_count)
    }

    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers=headers
    )

# Mount Landing Page Static Files at Root
landing_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "landing"))
if os.path.exists(landing_dir):
    app.mount("/", StaticFiles(directory=landing_dir, html=True), name="landing")
