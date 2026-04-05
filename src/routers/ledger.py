from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional
from src.ops_ledger import OpsLedger, LedgerEntry
from src.dependencies import get_ops_ledger
from src.auth import get_current_user, require_role, CurrentUser

router = APIRouter(prefix="/ops/ledger", tags=["ops", "ledger"])

@router.get("/", response_model=List[LedgerEntry])
async def list_ledger_entries(
    status: Optional[str] = Query(None, description="Filter by entry status"),
    ledger: OpsLedger = Depends(get_ops_ledger),
    user: CurrentUser = Depends(require_role(["admin", "operator", "auditor"]))
):
    """
    列出审计日志。受 RBAC 保护 (Admin, Operator, Auditor 可见)。
    """
    try:
        # TODO: 后续迭代中根据 user.org_id 过滤
        return ledger.list_entries(status=status)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{entry_id}", response_model=LedgerEntry)
async def get_ledger_entry(
    entry_id: str,
    ledger: OpsLedger = Depends(get_ops_ledger),
    user: CurrentUser = Depends(require_role(["admin", "operator", "auditor"]))
):
    try:
        return ledger.get_entry(entry_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.get("/recoverable", response_model=List[LedgerEntry])
async def list_recoverable_entries(
    ledger: OpsLedger = Depends(get_ops_ledger),
    user: CurrentUser = Depends(require_role(["admin", "operator", "auditor"]))
):
    try:
        return ledger.recoverable_entries()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
