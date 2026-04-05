import json
import sqlite3
import hashlib
import os
import sys
from typing import Dict, Any

# 确保可以导入 src 模块
sys.path.append(os.getcwd())
from src.ledger_entry import LedgerEntry

def get_jsonl_fingerprint(jsonl_path: str) -> str:
    """计算原始 JSONL 数据的条数与内容指纹"""
    if not os.path.exists(jsonl_path):
        return "N/A (File not found)"
    
    count = 0
    content_hash = hashlib.sha256()
    
    # 存储所有 entry 以便排序
    entries = []
    
    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip():
                continue
            count += 1
            data = json.loads(line)
            # 通过 LedgerEntry 进行标准化
            entry = LedgerEntry.from_record(data)
            entries.append(entry)
    
    # 排序以确保对比一致性
    entries.sort(key=lambda x: x.id)
    for entry in entries:
        # 使用标准化后的字段生成指纹
        serialized = json.dumps(entry.to_record(), sort_keys=True).encode('utf-8')
        content_hash.update(serialized)
            
    return f"Count: {count}, Hash: {content_hash.hexdigest()}"

def get_sqlite_fingerprint(db_path: str) -> str:
    """计算迁移后 SQLite 数据的条数与内容指纹"""
    if not os.path.exists(db_path):
        return "N/A (Database not found)"
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    count = cursor.execute("SELECT COUNT(*) FROM ledger").fetchone()[0]
    
    cursor.execute("SELECT * FROM ledger ORDER BY id ASC")
    
    content_hash = hashlib.sha256()
    for row in cursor.fetchall():
        d = dict(row)
        # 解析 JSON 字段
        d["checkpoint"] = json.loads(d["checkpoint"]) if d["checkpoint"] else {}
        d["metadata"] = json.loads(d["metadata"]) if d["metadata"] else {}
        
        entry = LedgerEntry.from_record(d)
        serialized = json.dumps(entry.to_record(), sort_keys=True).encode('utf-8')
        content_hash.update(serialized)
        
    conn.close()
    return f"Count: {count}, Hash: {content_hash.hexdigest()}"

def verify_migration(jsonl_path: str, db_path: str):
    print("--- OpsSentry Ledger Migration Verification ---")
    
    print(f"Reading Legacy JSONL: {jsonl_path}")
    jsonl_info = get_jsonl_fingerprint(jsonl_path)
    print(f"JSONL Status: {jsonl_info}")
    
    print(f"\nReading New SQLite: {db_path}")
    sqlite_info = get_sqlite_fingerprint(db_path)
    print(f"SQLite Status: {sqlite_info}")
    
    print("\n" + "="*40)
    if jsonl_info == sqlite_info and "N/A" not in jsonl_info:
        print("[AUDIT SUCCESS] 100% Data Integrity Verified.")
        print("Migration is safe to proceed.")
    else:
        print("[AUDIT FAIL] Data mismatch detected!")
        print("Please check for field mapping errors or encoding issues.")

if __name__ == "__main__":
    # 路径匹配 OpsLedger 默认配置 (data/ops-queue/)
    LEGACY_PATH = "data/ops-queue/ledger.jsonl.bak"
    NEW_DB_PATH = "data/ops-queue/ledger.db"
    
    verify_migration(LEGACY_PATH, NEW_DB_PATH)
