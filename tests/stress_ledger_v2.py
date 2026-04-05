import sqlite3
import time
import multiprocessing
import os
import random
from datetime import datetime

# 模拟配置
DB_PATH = "stress_test_ledger.db"
TOTAL_RECORDS = 100000
CONCURRENT_PROCESSES = 10
RECORDS_PER_PROCESS = TOTAL_RECORDS // CONCURRENT_PROCESSES

def setup_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # 启用 WAL 模式与性能优化
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    
    # 根据 Architect 规格书 (Phase6_LedgerStorage_Spec.md) 建立表结构
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id TEXT PRIMARY KEY,
            action TEXT,
            status TEXT,
            checkpoint TEXT,
            created_at INTEGER,
            updated_at INTEGER,
            accio_ref TEXT,
            metadata TEXT,
            last_error TEXT
        )
    """)
    cursor.execute("CREATE INDEX idx_created_at ON audit_log(created_at);")
    cursor.execute("CREATE INDEX idx_accio_ref ON audit_log(accio_ref);")
    conn.commit()
    conn.close()

def worker_write(proc_id):
    """模拟单个进程的高频并发写入"""
    # 增加 busy_timeout (5000ms) 应对并发竞争，匹配规格书
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    cursor = conn.cursor()
    
    start_time = time.time()
    success_count = 0
    fail_count = 0
    
    statuses = ["pending", "running", "completed", "failed"]
    actions = ["DISK_CLEANUP", "HEALTH_CHECK", "SERVICE_RESTART", "BACKUP"]
    
    for i in range(RECORDS_PER_PROCESS):
        try:
            entry_id = f"entry-{proc_id}-{i}-{random.getrandbits(32)}"
            action = random.choice(actions)
            status = random.choice(statuses)
            checkpoint = '{"step": 1, "retry": 0}'
            now_ms = int(time.time() * 1000)
            accio_ref = f"task-{random.randint(1000, 9999)}"
            metadata = '{"source": "stress-test", "version": "2.0"}'
            
            cursor.execute(
                """INSERT INTO audit_log 
                   (id, action, status, checkpoint, created_at, updated_at, accio_ref, metadata, last_error) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (entry_id, action, status, checkpoint, now_ms, now_ms, accio_ref, metadata, None)
            )
            
            # 每 100 条提交一次以平衡性能与原子性
            if i % 100 == 0:
                conn.commit()
            success_count += 1
        except Exception as e:
            # print(f"Proc {proc_id} Error: {e}")
            fail_count += 1
    
    conn.commit()
    conn.close()
    
    duration = time.time() - start_time
    print(f"Process {proc_id} finished: {success_count} success, {fail_count} fails in {duration:.2f}s")

def run_stress_test():
    print(f"Starting 100k records stress test (SQLite WAL Mode)...")
    setup_db()
    
    start_total = time.time()
    processes = []
    for i in range(CONCURRENT_PROCESSES):
        p = multiprocessing.Process(target=worker_write, args=(i,))
        processes.append(p)
        p.start()
        
    for p in processes:
        p.join()
        
    end_total = time.time()
    total_duration = end_total - start_total
    
    # 最终结果审计
    conn = sqlite3.connect(DB_PATH)
    count = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    conn.close()
    
    print("-" * 30)
    print(f"Total Count in DB: {count}")
    print(f"Total Duration: {total_duration:.2f}s")
    print(f"Average Throughput: {count / total_duration:.2f} records/s")
    print(f"DB File Size: {os.path.getsize(DB_PATH) / 1024 / 1024:.2f} MB")
    
    if count == TOTAL_RECORDS:
        print("[AUDIT PASS] Data integrity verified.")
    else:
        print(f"[AUDIT FAIL] Data loss detected! Expected {TOTAL_RECORDS}, got {count}")

if __name__ == "__main__":
    run_stress_test()
