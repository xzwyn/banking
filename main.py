import sqlite3
import uvicorn
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from contextlib import contextmanager
import random
import string
import logging

DATABASE_URL = "bank.db"
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_db():
    try:
        conn = sqlite3.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_number TEXT UNIQUE NOT NULL,
            account_holder TEXT NOT NULL,
            balance REAL NOT NULL
        )
        """)
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully.")
    except sqlite3.Error as e:
        logger.error(f"Database initialization failed: {e}")
        raise

def get_db_connection():
    conn = sqlite3.connect(DATABASE_URL)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def generate_account_number():
    return ''.join(random.choices(string.digits, k=10))

class AccountCreate(BaseModel):
    account_holder: str
    initial_deposit: float = 0.0

class Account(BaseModel):
    id: int
    account_number: str
    account_holder: str
    balance: float

class Transaction(BaseModel):
    amount: float

class Transfer(BaseModel):
    from_account_number: str
    to_account_number: str
    amount: float

app = FastAPI(
    title="Simple Bank API",
    description="A simple API to manage bank accounts with deposit, withdrawal, and transfer functionality.",
    version="1.0.0"
)

@app.on_event("startup")
def on_startup():
    init_db()

def get_account_by_number(conn: sqlite3.Connection, account_number: str):
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM accounts WHERE account_number = ?", (account_number,))
        account = cursor.fetchone()
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        return dict(account)
    except sqlite3.Error as e:
        logger.error(f"Database error in get_account_by_number: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {e}")

@app.post("/accounts/", response_model=Account, status_code=201)
def create_account(account_in: AccountCreate, conn: sqlite3.Connection = Depends(get_db_connection)):
    if account_in.initial_deposit < 0:
        raise HTTPException(status_code=400, detail="Initial deposit cannot be negative.")

    account_number = generate_account_number()
    cursor = conn.cursor()

    try:
        cursor.execute(
            "INSERT INTO accounts (account_number, account_holder, balance) VALUES (?, ?, ?)",
            (account_number, account_in.account_holder, account_in.initial_deposit)
        )
        conn.commit()
        new_account_id = cursor.lastrowid
        return {
            "id": new_account_id,
            "account_number": account_number,
            "account_holder": account_in.account_holder,
            "balance": account_in.initial_deposit
        }
    except sqlite3.Error as e:
        conn.rollback()
        logger.error(f"Failed to create account: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create account due to a database error: {e}")

@app.get("/accounts/{account_number}/balance", response_model=Account)
def check_balance(account_number: str, conn: sqlite3.Connection = Depends(get_db_connection)):
    account = get_account_by_number(conn, account_number)
    return account

@app.post("/accounts/{account_number}/deposit", response_model=Account)
def deposit(account_number: str, transaction: Transaction, conn: sqlite3.Connection = Depends(get_db_connection)):
    if transaction.amount <= 0:
        raise HTTPException(status_code=400, detail="Deposit amount must be positive.")

    account = get_account_by_number(conn, account_number)
    new_balance = account['balance'] + transaction.amount

    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE accounts SET balance = ? WHERE account_number = ?",
            (new_balance, account_number)
        )
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        logger.error(f"Failed to deposit funds: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to deposit funds due to a database error: {e}")

    account['balance'] = new_balance
    return account

@app.post("/accounts/{account_number}/withdraw", response_model=Account)
def withdraw(account_number: str, transaction: Transaction, conn: sqlite3.Connection = Depends(get_db_connection)):
    if transaction.amount <= 0:
        raise HTTPException(status_code=400, detail="Withdrawal amount must be positive.")

    account = get_account_by_number(conn, account_number)

    if account['balance'] < transaction.amount:
        raise HTTPException(status_code=400, detail="Insufficient funds")

    new_balance = account['balance'] - transaction.amount

    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE accounts SET balance = ? WHERE account_number = ?",
            (new_balance, account_number)
        )
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        logger.error(f"Failed to withdraw funds: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to withdraw funds due to a database error: {e}")

    account['balance'] = new_balance
    return account

@app.post("/transfer/", status_code=200)
def transfer_funds(transfer: Transfer, conn: sqlite3.Connection = Depends(get_db_connection)):
    if transfer.from_account_number == transfer.to_account_number:
        raise HTTPException(status_code=400, detail="Cannot transfer funds to the same account.")

    if transfer.amount <= 0:
        raise HTTPException(status_code=400, detail="Transfer amount must be positive.")

    cursor = conn.cursor()

    try:
        cursor.execute("SELECT * FROM accounts WHERE account_number = ?", (transfer.from_account_number,))
        from_account = cursor.fetchone()
        if not from_account:
            raise HTTPException(status_code=404, detail="Sender account not found.")
        if from_account['balance'] < transfer.amount:
            raise HTTPException(status_code=400, detail="Insufficient funds in sender account.")

        cursor.execute("SELECT * FROM accounts WHERE account_number = ?", (transfer.to_account_number,))
        to_account = cursor.fetchone()
        if not to_account:
            raise HTTPException(status_code=404, detail="Receiver account not found.")

        from_new_balance = from_account['balance'] - transfer.amount
        to_new_balance = to_account['balance'] + transfer.amount

        cursor.execute("UPDATE accounts SET balance = ? WHERE account_number = ?", (from_new_balance, transfer.from_account_number))
        cursor.execute("UPDATE accounts SET balance = ? WHERE account_number = ?", (to_new_balance, transfer.to_account_number))

        conn.commit()

        return {
            "message": "Transfer successful",
            "from_account": transfer.from_account_number,
            "to_account": transfer.to_account_number,
            "amount": transfer.amount
        }
    except HTTPException:
        conn.rollback()
        raise
    except sqlite3.Error as e:
        conn.rollback()
        logger.error(f"An internal error occurred during the transfer: {e}")
        raise HTTPException(status_code=500, detail=f"An internal error occurred during the transfer: {e}")

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)