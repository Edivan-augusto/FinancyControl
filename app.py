import csv
import io
import os
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple

from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
    flash,
)

import pdfplumber

try:
    import pytesseract  # type: ignore
    from pdf2image import convert_from_bytes  # type: ignore
except Exception:  # pragma: no cover - optional OCR
    pytesseract = None  # type: ignore
    convert_from_bytes = None  # type: ignore


DATABASE_PATH = os.path.join(os.path.dirname(__file__), "data.db")


app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key")


@dataclass
class Transaction:
    date: datetime
    description_full: str
    merchant_normalized: str
    txn_type: str  # "credit" or "debit"
    amount: float
    category: Optional[str] = None


def strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            description_full TEXT NOT NULL,
            merchant_normalized TEXT NOT NULL,
            txn_type TEXT NOT NULL,
            amount REAL NOT NULL,
            category TEXT,
            created_at TEXT NOT NULL
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS merchant_category (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            merchant_normalized TEXT UNIQUE NOT NULL,
            category TEXT NOT NULL
        );
        """
    )

    conn.commit()
    conn.close()


NORMALIZATION_PREFIXES = [
    "PIX ENVIADO",
    "PIX RECEBIDO",
    "PAGAMENTO DE BOLETO",
    "PAGAMENTO BOLETO",
    "PAGTO BOLETO",
    "CREDITO DE SALARIO",
    "DEBITO AUT.",
    "COMPRA CARTAO",
]


def normalize_merchant(description: str) -> str:
    text = re.sub(r"\s+", " ", description).strip()
    upper = text.upper()
    for prefix in NORMALIZATION_PREFIXES:
        if upper.startswith(prefix):
            trimmed = upper[len(prefix) :].strip(" -:/")
            return re.sub(r"\s+", " ", trimmed)
    return re.sub(r"\s+", " ", upper)


def parse_brl_amount(raw: str) -> Optional[float]:
    if not raw:
        return None
    txt = raw.strip()
    txt = txt.replace("R$", "").strip()
    is_negative = "-" in txt
    txt = txt.replace("-", "")
    txt = txt.replace(".", "").replace(",", ".")
    try:
        value = float(txt)
    except ValueError:
        return None
    if is_negative:
        value = -value
    return value


def parse_date(raw: str) -> Optional[datetime]:
    raw = raw.strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def extract_tables_from_pdf(file_bytes: bytes) -> List[List[str]]:
    tables: List[List[str]] = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            page_tables = page.extract_tables() or []
            for table in page_tables:
                for row in table:
                    if row and any(cell is not None for cell in row):
                        tables.append([cell or "" for cell in row])
    return tables


def extract_text_lines_from_pdf(file_bytes: bytes) -> List[str]:
    lines: List[str] = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            lines.extend(text.splitlines())
    return lines


def extract_text_with_ocr(file_bytes: bytes) -> List[str]:
    if pytesseract is None or convert_from_bytes is None:
        return []
    lines: List[str] = []
    images = convert_from_bytes(file_bytes)
    for img in images:
        text = pytesseract.image_to_string(img, lang="por")
        lines.extend(text.splitlines())
    return lines


def parse_transactions_from_tables(tables: List[List[str]]) -> List[Transaction]:
    if not tables:
        return []

    header_row_index = None
    for idx, row in enumerate(tables):
        header_join = " ".join((cell or "").upper() for cell in row)
        header_norm = strip_accents(header_join)
        if "DATA" in header_norm and "DESCRI" in header_norm and "CREDITO" in header_norm:
            header_row_index = idx
            break

    if header_row_index is None:
        return []

    header = tables[header_row_index]
    col_map: dict[str, int] = {}
    for i, col in enumerate(header):
        col_upper = (col or "").upper()
        col_norm = strip_accents(col_upper)
        if "DATA" in col_norm:
            col_map["date"] = i
        elif "DESCRI" in col_norm:
            col_map["description"] = i
        elif "CREDITO" in col_norm:
            col_map["credit"] = i
        elif "DEBITO" in col_norm:
            col_map["debit"] = i

    required_cols = {"date", "description", "credit", "debit"}
    if not required_cols.issubset(col_map.keys()):
        return []

    transactions: List[Transaction] = []

    for row in tables[header_row_index + 1 :]:
        if len(row) < len(header):
            continue
        date_raw = row[col_map["date"]] or ""
        description_raw = row[col_map["description"]] or ""
        credit_raw = row[col_map["credit"]] or ""
        debit_raw = row[col_map["debit"]] or ""

        if not date_raw or not description_raw:
            continue

        date = parse_date(date_raw)
        if not date:
            continue

        credit = parse_brl_amount(credit_raw)
        debit = parse_brl_amount(debit_raw)

        if credit is None and debit is None:
            continue

        description_full = re.sub(r"\s+", " ", description_raw).strip()
        merchant = normalize_merchant(description_full)

        if debit is not None and abs(debit) > 0:
            transactions.append(
                Transaction(
                    date=date,
                    description_full=description_full,
                    merchant_normalized=merchant,
                    txn_type="debit",
                    amount=abs(debit),
                )
            )
        if credit is not None and abs(credit) > 0:
            transactions.append(
                Transaction(
                    date=date,
                    description_full=description_full,
                    merchant_normalized=merchant,
                    txn_type="credit",
                    amount=credit,
                )
            )

    return transactions


def parse_transactions_from_text_lines(lines: List[str]) -> List[Transaction]:
    transactions: List[Transaction] = []

    money_pattern = re.compile(r"-?\d{1,3}(?:\.\d{3})*,\d{2}")

    for line in lines:
        raw = line.strip()
        if not raw:
            continue

        m_date = re.match(r"(\d{2}/\d{2}/\d{4})\s+(.*)", raw)
        if not m_date:
            continue

        date_raw, rest = m_date.groups()
        date = parse_date(date_raw)
        if not date:
            continue

        upper_norm_rest = strip_accents(rest.upper())
        if upper_norm_rest.startswith("DATA "):
            continue

        money_matches = list(money_pattern.finditer(raw))
        if len(money_matches) < 2:
            continue

        first_money_start = money_matches[0].start()
        description_raw = raw[len(date_raw) : first_money_start].strip()

        money_values = [raw[m.start() : m.end()] for m in money_matches]

        credit_raw = ""
        debit_raw = ""

        if len(money_values) >= 3:
            credit_raw = money_values[-3]
            debit_raw = money_values[-2]
        else:
            candidate = money_values[-2]
            desc_upper = strip_accents(description_raw.upper())
            if any(
                key in desc_upper
                for key in ["CREDITO", "PIX RECEBIDO", "DEPOSITO"]
            ):
                credit_raw = candidate
            else:
                debit_raw = candidate

        credit = parse_brl_amount(credit_raw) if credit_raw else None
        debit = parse_brl_amount(debit_raw) if debit_raw else None

        if credit is None and debit is None:
            continue

        description_full = re.sub(r"\s+", " ", description_raw).strip()
        merchant = normalize_merchant(description_full)

        if debit is not None and abs(debit) > 0:
            transactions.append(
                Transaction(
                    date=date,
                    description_full=description_full,
                    merchant_normalized=merchant,
                    txn_type="debit",
                    amount=abs(debit),
                )
            )
        if credit is not None and abs(credit) > 0:
            transactions.append(
                Transaction(
                    date=date,
                    description_full=description_full,
                    merchant_normalized=merchant,
                    txn_type="credit",
                    amount=credit,
                )
            )

    return transactions


def parse_transactions_from_pdf(file_bytes: bytes) -> List[Transaction]:
    tables = extract_tables_from_pdf(file_bytes)
    transactions = parse_transactions_from_tables(tables)
    if transactions:
        return transactions

    lines = extract_text_lines_from_pdf(file_bytes)
    transactions = parse_transactions_from_text_lines(lines)
    if transactions:
        return transactions

    ocr_lines = extract_text_with_ocr(file_bytes)
    if not ocr_lines:
        return []
    return parse_transactions_from_text_lines(ocr_lines)


def save_transactions(transactions: List[Transaction]) -> None:
    if not transactions:
        return
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT merchant_normalized, category FROM merchant_category;")
    known = {row["merchant_normalized"]: row["category"] for row in cur.fetchall()}

    now = datetime.utcnow().isoformat()
    for txn in transactions:
        category = known.get(txn.merchant_normalized)
        cur.execute(
            """
            INSERT INTO transactions (
                date, description_full, merchant_normalized,
                txn_type, amount, category, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (
                txn.date.date().isoformat(),
                txn.description_full,
                txn.merchant_normalized,
                txn.txn_type,
                txn.amount,
                category,
                now,
            ),
        )

    conn.commit()
    conn.close()


def query_transactions(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    txn_type: Optional[str] = None,
    merchant: Optional[str] = None,
    category: Optional[str] = None,
) -> List[sqlite3.Row]:
    conn = get_db_connection()
    cur = conn.cursor()

    query = "SELECT * FROM transactions WHERE 1=1"
    params: List[object] = []

    if start_date:
        query += " AND date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND date <= ?"
        params.append(end_date)
    if txn_type in ("credit", "debit"):
        query += " AND txn_type = ?"
        params.append(txn_type)
    if merchant:
        query += " AND merchant_normalized LIKE ?"
        params.append(f"%{merchant}%")
    if category:
        query += " AND IFNULL(category, '') = ?"
        params.append(category)

    query += " ORDER BY date ASC, id ASC"

    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()
    return rows


def aggregate_totals(rows: List[sqlite3.Row]) -> Tuple[float, float]:
    total_spent = 0.0
    total_received = 0.0
    for row in rows:
        if row["txn_type"] == "debit":
            total_spent += float(row["amount"])
        elif row["txn_type"] == "credit":
            total_received += float(row["amount"])
    return total_spent, total_received


def aggregate_by_merchant(rows: List[sqlite3.Row]) -> List[Tuple[str, float]]:
    agg: dict[str, float] = {}
    for row in rows:
        if row["txn_type"] != "debit":
            continue
        merchant = row["merchant_normalized"]
        agg[merchant] = agg.get(merchant, 0.0) + float(row["amount"])
    sorted_items = sorted(agg.items(), key=lambda x: x[1], reverse=True)
    return sorted_items


def aggregate_by_category(rows: List[sqlite3.Row]) -> List[Tuple[str, float]]:
    agg: dict[str, float] = {}
    for row in rows:
        if row["txn_type"] != "debit":
            continue
        cat = row["category"] or "Outros"
        agg[cat] = agg.get(cat, 0.0) + float(row["amount"])
    sorted_items = sorted(agg.items(), key=lambda x: x[1], reverse=True)
    return sorted_items


@app.route("/", methods=["GET"])
def index():
    start = request.args.get("start_date") or ""
    end = request.args.get("end_date") or ""
    txn_type = request.args.get("type") or ""
    merchant = request.args.get("merchant") or ""
    category = request.args.get("category") or ""

    rows = query_transactions(
        start_date=start or None,
        end_date=end or None,
        txn_type=txn_type or None,
        merchant=merchant or None,
        category=category or None,
    )

    total_spent, total_received = aggregate_totals(rows)
    balance = total_received - total_spent

    by_merchant = aggregate_by_merchant(rows)
    by_category = aggregate_by_category(rows)

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            t.merchant_normalized,
            SUM(t.amount) AS total,
            COALESCE(mc.category, MAX(COALESCE(t.category, ''))) AS category
        FROM transactions t
        LEFT JOIN merchant_category mc
            ON mc.merchant_normalized = t.merchant_normalized
        WHERE t.txn_type = 'debit'
        GROUP BY t.merchant_normalized
        ORDER BY total DESC;
        """
    )
    merchant_rows = cur.fetchall()

    merchant_unassigned = []
    merchant_assigned = []
    for r in merchant_rows:
        cat_value = r["category"]
        if not cat_value:
            merchant_unassigned.append(r)
        else:
            merchant_assigned.append(r)

    cur.execute(
        "SELECT DISTINCT IFNULL(category, 'Outros') AS category "
        "FROM transactions ORDER BY category;"
    )
    categories = [r["category"] for r in cur.fetchall()]
    conn.close()

    return render_template(
        "index.html",
        transactions=rows,
        total_spent=total_spent,
        total_received=total_received,
        balance=balance,
        by_merchant=by_merchant[:10],
        by_category=by_category,
        merchant_unassigned=merchant_unassigned,
        merchant_assigned=merchant_assigned,
        categories=categories,
        filters={
            "start_date": start,
            "end_date": end,
            "type": txn_type,
            "merchant": merchant,
            "category": category,
        },
    )


@app.route("/upload", methods=["POST"])
def upload():
    if "pdf_files" not in request.files:
        flash("Nenhum arquivo enviado.", "danger")
        return redirect(url_for("index"))

    files = request.files.getlist("pdf_files")
    all_transactions: List[Transaction] = []
    for f in files:
        if not f.filename.lower().endswith(".pdf"):
            flash(f"Arquivo ignorado (não é PDF): {f.filename}", "warning")
            continue
        file_bytes = f.read()
        try:
            txns = parse_transactions_from_pdf(file_bytes)
        except Exception:
            flash(f"Erro ao processar PDF: {f.filename}", "danger")
            continue
        if not txns:
            flash(f"Nenhuma transação encontrada em: {f.filename}", "warning")
        all_transactions.extend(txns)

    if all_transactions:
        save_transactions(all_transactions)
        flash(f"{len(all_transactions)} transações importadas com sucesso.", "success")
    else:
        flash("Nenhuma transação importada.", "warning")

    return redirect(url_for("index"))


@app.route("/update-category", methods=["POST"])
def update_category():
    data = request.get_json(silent=True) or {}
    merchant = data.get("merchant")
    category = data.get("category")
    if not merchant:
        return jsonify({"ok": False, "error": "Merchant obrigatório."}), 400
    if not category:
        return jsonify({"ok": False, "error": "Categoria obrigatória."}), 400

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO merchant_category (merchant_normalized, category)
        VALUES (?, ?)
        ON CONFLICT(merchant_normalized) DO UPDATE SET category=excluded.category;
        """,
        (merchant, category),
    )

    cur.execute(
        "UPDATE transactions SET category=? WHERE merchant_normalized=?;",
        (category, merchant),
    )

    conn.commit()
    conn.close()

    return jsonify({"ok": True})


@app.route("/clear-category", methods=["POST"])
def clear_category():
    data = request.get_json(silent=True) or {}
    merchant = data.get("merchant")
    if not merchant:
        return jsonify({"ok": False, "error": "Merchant obrigatório."}), 400

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        "DELETE FROM merchant_category WHERE merchant_normalized=?;",
        (merchant,),
    )
    cur.execute(
        "UPDATE transactions SET category=NULL WHERE merchant_normalized=?;",
        (merchant,),
    )

    conn.commit()
    conn.close()

    return jsonify({"ok": True})


@app.route("/export", methods=["GET"])
def export_csv():
    rows = query_transactions()
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(
        ["Data", "Descrição completa", "Favorecido", "Tipo", "Valor", "Categoria"]
    )
    for row in rows:
        writer.writerow(
            [
                row["date"],
                row["description_full"],
                row["merchant_normalized"],
                row["txn_type"],
                f"{float(row['amount']):.2f}".replace(".", ","),
                row["category"] or "",
            ]
        )
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        mimetype="text/csv; charset=utf-8",
        as_attachment=True,
        download_name="transacoes.csv",
    )


def run_smoke_test() -> None:
    lines = [
        "15/12/2025 CREDITO DE SALARIO ACME LTDA        000000    000000      1.350,00      0,00   1.350,00",
        "17/12/2025 PIX ENVIADO STRIPE BRASIL SOLUCOES DE 000000  000000      0,00      119,90  -2.636,87",
    ]
    txns = parse_transactions_from_text_lines(lines)
    assert len(txns) == 2

    credit = next(t for t in txns if t.txn_type == "credit")
    debit = next(t for t in txns if t.txn_type == "debit")

    assert abs(credit.amount - 1350.0) < 0.01
    assert abs(debit.amount - 119.9) < 0.01


if __name__ == "__main__":
    init_db()
    run_smoke_test()
    app.run(debug=True)

