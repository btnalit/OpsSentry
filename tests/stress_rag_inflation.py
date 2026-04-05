import os
import shutil
import time
import random
from pathlib import Path
import sys

# Add src to path
sys.path.append(os.getcwd())

from src.knowledge_core import KnowledgeCore

STRESS_KNOWLEDGE_PATH = Path("data/knowledge_stress")
NUM_DOCS = 1000

def generate_mock_docs():
    if STRESS_KNOWLEDGE_PATH.exists():
        shutil.rmtree(STRESS_KNOWLEDGE_PATH)
    STRESS_KNOWLEDGE_PATH.mkdir(parents=True)

    print(f"Generating {NUM_DOCS} mock runbooks...")
    for i in range(NUM_DOCS):
        action = random.choice(["DISK_CLEANUP", "RESTART_SERVICE", "UPDATE_CERT", "BACKUP_DB"])
        content = f"""# Auto Runbook {i} for {action}
priority_score: 0.5

In this automated runbook for {action}, we learned that step {random.randint(1, 100)} was effective.
This is unique data for document {i}.
"""
        (STRESS_KNOWLEDGE_PATH / f"auto_runbook_{i}.md").write_text(content, encoding="utf-8")

    # Add one manual doc to check ranking in high inflation
    manual_content = """# Critical Security Fix (Manual)
priority_score: 1.0

This manual document contains the core security logic for OpsSentry.
Essential for system safety.
"""
    (STRESS_KNOWLEDGE_PATH / "manual_security.md").write_text(manual_content, encoding="utf-8")

def run_inflation_stress():
    print("--- Starting RAG Knowledge Inflation Stress Test ---")
    generate_mock_docs()

    # Time Index Rebuild
    start_index = time.time()
    core = KnowledgeCore(STRESS_KNOWLEDGE_PATH)
    duration_index = time.time() - start_index
    print(f"KnowledgeCore Index Rebuild (1000+ docs): {duration_index:.4f}s")

    # Time Search
    start_search = time.time()
    results = core.search("security fix", limit=5)
    duration_search = time.time() - start_search
    print(f"RAG Search Latency: {duration_search*1000:.2f}ms")

    if not results:
        print("[AUDIT FAIL] No results found in 1000+ docs.")
        return

    top_hit = results[0]
    print(f"Top Result: {top_hit.chunk.source_path} (Score: {top_hit.score:.4f})")

    if "manual_security.md" in top_hit.chunk.source_path:
        print("[AUDIT PASS] Manual security fix correctly ranked at Top 1 among 1000 auto-runbooks.")
    else:
        print("[AUDIT FAIL] Manual document was buried by automated noise.")

    # Cleanup
    shutil.rmtree(STRESS_KNOWLEDGE_PATH)

if __name__ == "__main__":
    run_inflation_stress()
