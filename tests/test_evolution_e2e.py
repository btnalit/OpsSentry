import json
import os
import sys
from pathlib import Path

# Add src to path
sys.path.append(os.getcwd())

from src.ops_ledger import OpsLedger
from src.knowledge_core import KnowledgeCore
from src.evolution_manager import EvolutionManager

def test_evolution_e2e():
    db_path = Path("data/ops-queue/ledger_evolve_test.db")
    knowledge_path = Path("data/knowledge_evolve_test")
    
    # Clean up previous test runs
    for f in db_path.parent.glob(f"{db_path.name}*"):
        try: f.unlink()
        except: pass
    if knowledge_path.exists():
        import shutil
        shutil.rmtree(knowledge_path)
    
    print(f"Initializing OpsLedger and KnowledgeCore...")
    ledger = OpsLedger(db_path)
    knowledge = KnowledgeCore(knowledge_path)
    # Use low threshold for tiny test environment
    evolution = EvolutionManager(ledger, knowledge, knowledge_path / "evolved", min_score=0.1)
    
    # 1. Create a successful entry with meaningful steps
    print("Creating successful entry...")
    entry = ledger.create_entry(
        "disk_cleanup", 
        metadata={"target": "/var/log", "summary": "Cleaned up 5GB from /var/log"},
        checkpoint={
            "steps": [
                "List all log files in /var/log",
                "Compress files older than 7 days",
                "Delete files older than 30 days",
                "Restart logrotate service"
            ]
        }
    )
    ledger.mark_running(entry.id)
    ledger.mark_completed(entry.id)
    
    # 2. Run evolution step
    print("Running evolution step...")
    processed = evolution.evolve_step()
    print(f"Processed {processed} entries.")
    assert processed == 1
    
    # 3. Verify Runbook creation
    evolved_files = list((knowledge_path / "evolved").glob("*.md"))
    print(f"Evolved files found: {[f.name for f in evolved_files]}")
    assert len(evolved_files) == 1
    
    content = evolved_files[0].read_text(encoding="utf-8")
    print(f"Content snippet: {content[:100]}...")
    assert "Runbook: Disk Cleanup" in content
    assert "priority_score: 0.5" in content
    
    # 4. Verify searchability
    print("Searching for 'disk cleanup' in RAG...")
    # KnowledgeCore rebuilds index in evolve_step if processed > 0
    hits = knowledge.search("disk cleanup")
    print(f"Search results found: {len(hits)}")
    assert len(hits) >= 1
    hit = hits[0]
    print(f"Top hit heading: {hit.chunk.heading}, Score: {hit.score}, Priority Score: {hit.chunk.priority_score}")
    print(f"Chunk content: {hit.chunk.body[:100]}...")
    assert "Disk Cleanup" in hit.chunk.heading
    assert hit.chunk.priority_score == 0.5
    
    # 5. Test deduplication/merging
    print("Testing deduplication/merging...")
    entry2 = ledger.create_entry(
        "disk_cleanup", 
        metadata={"target": "/tmp", "summary": "Cleaned up 1GB from /tmp"},
        checkpoint={
            "steps": [
                "List all log files in /var/log",
                "Compress files older than 7 days",
                "Delete files older than 30 days",
                "Restart logrotate service"
            ]
        }
    )
    ledger.mark_running(entry2.id)
    ledger.mark_completed(entry2.id)
    
    processed2 = evolution.evolve_step()
    print(f"Processed {processed2} entries for deduplication.")
    # Check if a new file was created or merged
    evolved_files_after = list((knowledge_path / "evolved").glob("*.md"))
    print(f"Evolved files count after second run: {len(evolved_files_after)}")
    assert len(evolved_files_after) == 1
    
    content_after = evolved_files_after[0].read_text(encoding="utf-8")
    assert f"Case {entry2.id}" in content_after
    print("Deduplication test passed!")
    
    print("All tests passed!")

if __name__ == "__main__":
    test_evolution_e2e()
