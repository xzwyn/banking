import pytest
import sqlite3
from fastapi.testclient import TestClient
from main import app, get_db_connection

TEST_DATABASE_URL = "file:memdb1?mode=memory&cache=shared"

test_conn = sqlite3.connect(TEST_DATABASE_URL, check_same_thread=False)
test_conn.row_factory = sqlite3.Row

def override_get_db_connection():
    try:
        yield test_conn
    finally:
        pass

app.dependency_overrides[get_db_connection] = override_get_db_connection

client = TestClient(app)

@pytest.fixture(autouse=True, scope="function")
def setup_and_teardown_database():
    cursor = test_conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS accounts")
    cursor.execute("""
    CREATE TABLE accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_number TEXT UNIQUE NOT NULL,
        account_holder TEXT NOT NULL,
        balance REAL NOT NULL
    )
    """)
    test_conn.commit()
    yield
    cursor.execute("DROP TABLE IF EXISTS accounts")
    test_conn.commit()

def test_create_account_successfully():
    response = client.post(
        "/accounts/",
        json={"account_holder": "Aswin", "initial_deposit": 100.0}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["account_holder"] == "Aswin"
    assert data["balance"] == 100.0
    assert "account_number" in data

def test_create_account_negative_deposit():
    response = client.post(
        "/accounts/",
        json={"account_holder": "Sreerag", "initial_deposit": -50.0}
    )
    assert response.status_code == 400
    assert "Initial deposit cannot be negative" in response.json()["detail"]

def test_check_balance():
    create_response = client.post("/accounts/", json={"account_holder": "Ashwin", "initial_deposit": 500.0})
    account_number = create_response.json()["account_number"]

    balance_response = client.get(f"/accounts/{account_number}/balance")
    assert balance_response.status_code == 200
    data = balance_response.json()
    assert data["account_holder"] == "Ashwin"
    assert data["balance"] == 500.0

def test_check_balance_not_found():
    response = client.get("/accounts/9999999999/balance")
    assert response.status_code == 404
    assert "Account not found" in response.json()["detail"]

def test_deposit_successfully():
    create_response = client.post("/accounts/", json={"account_holder": "David", "initial_deposit": 200.0})
    account_number = create_response.json()["account_number"]

    deposit_response = client.post(f"/accounts/{account_number}/deposit", json={"amount": 150.0})
    assert deposit_response.status_code == 200
    data = deposit_response.json()
    assert data["balance"] == 350.0

def test_withdraw_successfully():
    create_response = client.post("/accounts/", json={"account_holder": "Dev", "initial_deposit": 1000.0})
    account_number = create_response.json()["account_number"]

    withdraw_response = client.post(f"/accounts/{account_number}/withdraw", json={"amount": 300.0})
    assert withdraw_response.status_code == 200
    assert withdraw_response.json()["balance"] == 700.0

def test_withdraw_insufficient_funds():
    create_response = client.post("/accounts/", json={"account_holder": "Deven", "initial_deposit": 100.0})
    account_number = create_response.json()["account_number"]

    withdraw_response = client.post(f"/accounts/{account_number}/withdraw", json={"amount": 200.0})
    assert withdraw_response.status_code == 400
    assert "Insufficient funds" in withdraw_response.json()["detail"]

def test_transfer_successfully():
    sender_res = client.post("/accounts/", json={"account_holder": "Joel", "initial_deposit": 1000.0})
    receiver_res = client.post("/accounts/", json={"account_holder": "Wilson", "initial_deposit": 500.0})
    sender_num = sender_res.json()["account_number"]
    receiver_num = receiver_res.json()["account_number"]

    transfer_response = client.post(
        "/transfer/",
        json={"from_account_number": sender_num, "to_account_number": receiver_num, "amount": 200.0}
    )
    assert transfer_response.status_code == 200
    assert transfer_response.json()["message"] == "Transfer successful"

    sender_balance_res = client.get(f"/accounts/{sender_num}/balance")
    assert sender_balance_res.json()["balance"] == 800.0

    receiver_balance_res = client.get(f"/accounts/{receiver_num}/balance")
    assert receiver_balance_res.json()["balance"] == 700.0

def test_transfer_insufficient_funds():
    sender_res = client.post("/accounts/", json={"account_holder": "Sid", "initial_deposit": 100.0})
    receiver_res = client.post("/accounts/", json={"account_holder": "Zayn", "initial_deposit": 500.0})
    sender_num = sender_res.json()["account_number"]
    receiver_num = receiver_res.json()["account_number"]

    transfer_response = client.post(
        "/transfer/",
        json={"from_account_number": sender_num, "to_account_number": receiver_num, "amount": 200.0}
    )
    assert transfer_response.status_code == 400
    assert "Insufficient funds" in transfer_response.json()["detail"]


def test_create_account_with_default_deposit():
    response = client.post("/accounts/", json={"account_holder": "Felix"})
    assert response.status_code == 201
    data = response.json()
    assert data["account_holder"] == "Felix"
    assert data["balance"] == 0.0

def test_withdraw_zero_or_negative_amount():
    create_response = client.post("/accounts/", json={"account_holder": "Anargha", "initial_deposit": 100.0})
    account_number = create_response.json()["account_number"]

    response_zero = client.post(f"/accounts/{account_number}/withdraw", json={"amount": 0.0})
    assert response_zero.status_code == 400
    assert "Withdrawal amount must be positive" in response_zero.json()["detail"]

    response_negative = client.post(f"/accounts/{account_number}/withdraw", json={"amount": -50.0})
    assert response_negative.status_code == 400
    assert "Withdrawal amount must be positive" in response_negative.json()["detail"]

def test_transfer_to_same_account():
    res = client.post("/accounts/", json={"account_holder": "Gaadha", "initial_deposit": 100.0})
    acc_num = res.json()["account_number"]
    
    response = client.post(
        "/transfer/",
        json={"from_account_number": acc_num, "to_account_number": acc_num, "amount": 50.0}
    )
    assert response.status_code == 400
    assert "Cannot transfer funds to the same account" in response.json()["detail"]

def test_transfer_from_non_existent_account():
    res = client.post("/accounts/", json={"account_holder": "Hercules", "initial_deposit": 100.0})
    receiver_num = res.json()["account_number"]

    response = client.post(
        "/transfer/",
        json={"from_account_number": "9999999999", "to_account_number": receiver_num, "amount": 50.0}
    )
    assert response.status_code == 404
    assert "Sender account not found" in response.json()["detail"]

def test_transfer_negative_amount():
    sender_res = client.post("/accounts/", json={"account_holder": "Ravi", "initial_deposit": 100.0})
    receiver_res = client.post("/accounts/", json={"account_holder": "Raushan", "initial_deposit": 100.0})
    sender_num = sender_res.json()["account_number"]
    receiver_num = receiver_res.json()["account_number"]

    response = client.post(
        "/transfer/",
        json={"from_account_number": sender_num, "to_account_number": receiver_num, "amount": -50.0}
    )
    assert response.status_code == 400
    assert "Transfer amount must be positive" in response.json()["detail"]
