# db.py (updated)
import os
import json
import logging
from typing import List, Dict, Any, Optional
import mysql.connector
from mysql.connector import pooling, Error as MySQLError
import bcrypt
from contextlib import contextmanager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("medguardian.db")

# ---------- Configuration (from environment, fallback defaults) ----------
DB_HOST = os.environ.get("DB_HOST", "medguardian.cvg6ukmcac8i.eu-north-1.rds.amazonaws.com")
DB_PORT = int(os.environ.get("DB_PORT", "3306"))
DB_USER = os.environ.get("DB_USER", "admin")
DB_PASS = os.environ.get("DB_PASS", "")      # set in env, do NOT hardcode
DB_NAME = os.environ.get("DB_NAME", "medguardian")
DB_POOL_NAME = os.environ.get("DB_POOL_NAME", "medguardian_pool")
DB_POOL_SIZE = int(os.environ.get("DB_POOL_SIZE", "5"))
DB_SSL_CA = os.environ.get("DB_SSL_CA", "")  # path to rds-combined-ca-bundle.pem if required
DB_CONNECT_TIMEOUT = int(os.environ.get("DB_CONNECT_TIMEOUT", "10"))

# Build base connect args
_base_connect_args = {
    "host": DB_HOST,
    "port": DB_PORT,
    "user": DB_USER,
    "password": DB_PASS,
    "database": DB_NAME,
    "connection_timeout": DB_CONNECT_TIMEOUT,
}

if DB_SSL_CA:
    _base_connect_args["ssl_ca"] = DB_SSL_CA
    logger.info("DB SSL CA configured: %s", DB_SSL_CA)

# Create pool
POOL = None
try:
    pool_args = {
        "pool_name": DB_POOL_NAME,
        "pool_size": DB_POOL_SIZE,
        **_base_connect_args
    }
    POOL = pooling.MySQLConnectionPool(**pool_args)
    logger.info("DB pool created: name=%s size=%s", DB_POOL_NAME, DB_POOL_SIZE)
except Exception as e:
    logger.exception("Could not create DB pool, will fallback to direct connect: %s", e)
    POOL = None


def get_conn():
    """
    Get a new connection from pool if available, otherwise create a direct connection.
    Caller must close the connection.
    """
    if POOL:
        try:
            return POOL.get_connection()
        except MySQLError as e:
            logger.exception("Pool get_connection failed, trying direct connect: %s", e)
    # fallback direct
    try:
        return mysql.connector.connect(**_base_connect_args)
    except Exception as e:
        logger.exception("Direct DB connect failed: %s", e)
        raise


@contextmanager
def conn_cursor(dictionary: bool = False):
    """
    Context manager: yields (conn, cur) and ensures close on exit.
    Usage:
      with conn_cursor(dictionary=True) as (conn, cur):
          cur.execute(...)
    """
    conn = get_conn()
    cur = conn.cursor(dictionary=dictionary)
    try:
        yield conn, cur
    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

# ------------------- User functions -------------------
def create_user(username: str, password: str, full_name: str = None, phone: str = None) -> bool:
    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    with conn_cursor(dictionary=False) as (conn, cur):
        try:
            cur.execute(
                "INSERT INTO users (username, password_hash, full_name, phone) VALUES (%s,%s,%s,%s)",
                (username, pw_hash, full_name, phone)
            )
            conn.commit()
            return True
        except mysql.connector.errors.IntegrityError as e:
            conn.rollback()
            # duplicate username likely
            logger.info("create_user: IntegrityError (likely duplicate): %s", e)
            return False
        except Exception:
            conn.rollback()
            logger.exception("create_user failed")
            raise

def authenticate_user(username: str, password: str):
    with conn_cursor(dictionary=True) as (conn, cur):
        cur.execute("SELECT id, username, password_hash, full_name FROM users WHERE username = %s", (username,))
        row = cur.fetchone()
    if not row:
        return None
    try:
        if bcrypt.checkpw(password.encode(), row["password_hash"].encode()):
            return {"id": row["id"], "username": row["username"], "full_name": row.get("full_name")}
    except Exception:
        logger.exception("Password check failed")
        return None
    return None

# ------------------- Report functions -------------------
def insert_report(user_id:int, report:Dict[str,Any]):
    with conn_cursor(dictionary=False) as (conn, cur):
        try:
            cur.execute("""
                INSERT INTO reports (
                    user_id, patient_id, patient_name, phone,
                    doctor_name, referred_by, sample_collected,
                    report_generated_by, date, condition_name, risk, raw_json
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                user_id,
                report.get("Patient ID"),
                report.get("Patient Name"),
                report.get("Phone"),
                report.get("Doctor Name"),
                report.get("Referred By"),
                report.get("Sample Collected"),
                report.get("Report Generated By"),
                report.get("Date"),
                report.get("Condition"),
                float(report.get("Risk %", 0) or 0),
                json.dumps(report, default=str)
            ))
            conn.commit()
        except Exception:
            conn.rollback()
            logger.exception("insert_report failed")
            raise

def get_reports_for_user(user_id:int, limit=1000) -> List[Dict[str,Any]]:
    with conn_cursor(dictionary=True) as (conn, cur):
        cur.execute("SELECT * FROM reports WHERE user_id = %s ORDER BY created_at DESC LIMIT %s", (user_id, limit))
        rows = cur.fetchall()
    for r in rows:
        try:
            r['raw'] = json.loads(r.get('raw_json') or '{}')
        except Exception:
            r['raw'] = {}
    return rows

def get_filtered_reports(user_id:int, condition: str = None, patient_name: str = None):
    q = "SELECT * FROM reports WHERE user_id = %s"
    params = [user_id]
    if condition:
        q += " AND condition_name = %s"
        params.append(condition)
    if patient_name:
        q += " AND patient_name = %s"
        params.append(patient_name)
    q += " ORDER BY created_at DESC"
    with conn_cursor(dictionary=True) as (conn, cur):
        cur.execute(q, tuple(params))
        rows = cur.fetchall()
    return rows

# ------------------- Delete report -------------------
def delete_report(report_id: int) -> bool:
    if not report_id:
        raise ValueError("delete_report called with empty report_id")
    with conn_cursor(dictionary=False) as (conn, cur):
        try:
            cur.execute("DELETE FROM reports WHERE id = %s", (report_id,))
            affected = cur.rowcount
            conn.commit()
            return affected > 0
        except Exception:
            conn.rollback()
            logger.exception("delete_report failed")
            raise

# ------------------- Chats -------------------
def insert_chat(user_id:int, role:str, message:str):
    with conn_cursor(dictionary=False) as (conn, cur):
        try:
            cur.execute("INSERT INTO chats (user_id, role, message) VALUES (%s,%s,%s)", (user_id, role, message))
            conn.commit()
        except Exception:
            conn.rollback()
            logger.exception("insert_chat failed")
            raise

def get_chats_for_user(user_id:int, limit=500):
    with conn_cursor(dictionary=True) as (conn, cur):
        cur.execute("SELECT * FROM chats WHERE user_id = %s ORDER BY created_at ASC LIMIT %s", (user_id, limit))
        rows = cur.fetchall()
    return rows

# ------------------- Utility / Test -------------------
def test_connection():
    """Simple connection test, prints counts for basic tables."""
    try:
        with conn_cursor(dictionary=True) as (conn, cur):
            cur.execute("SELECT DATABASE() AS db")
            db = cur.fetchone().get("db")
            cur.execute("SELECT COUNT(*) AS users_count FROM users")
            users_count = cur.fetchone().get("users_count")
            cur.execute("SELECT COUNT(*) AS reports_count FROM reports")
            reports_count = cur.fetchone().get("reports_count")
        print(f"Connected to DB: {db}  users={users_count}  reports={reports_count}")
        return True
    except Exception as e:
        logger.exception("test_connection failed: %s", e)
        return False
