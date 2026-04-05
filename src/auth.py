import jwt
import time
import os
import logging
from fastapi import Header, HTTPException, Depends, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import List, Optional

logger = logging.getLogger("OpsSentry.Auth")

# Constants from Specification and Tests
JWT_SECRET = os.environ.get("JWT_SECRET", "opssentry-test-secret")
ALGORITHM = "HS256"

class CurrentUser(BaseModel):
    user_id: str
    role: str
    org_id: str

security = HTTPBearer()

class JWTManager:
    @staticmethod
    def decode_token(token: str) -> dict:
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
            return payload
        except jwt.ExpiredSignatureError:
            logger.warning("JWT token expired")
            raise HTTPException(status_code=401, detail="Token expired")
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid JWT token: {e}")
            raise HTTPException(status_code=401, detail="Invalid token")

def get_current_user(auth: HTTPAuthorizationCredentials = Security(security)) -> CurrentUser:
    """FastAPI Dependency to retrieve and validate the current user from JWT."""
    token = auth.credentials
    payload = JWTManager.decode_token(token)
    
    user_id = payload.get("sub")
    role = payload.get("role")
    org_id = payload.get("org_id")
    
    if not user_id or not role or not org_id:
        raise HTTPException(status_code=401, detail="Invalid token payload: missing sub, role, or org_id")
        
    return CurrentUser(
        user_id=user_id,
        role=role,
        org_id=org_id
    )

def require_role(allowed_roles: List[str]):
    """FastAPI Dependency for RBAC checks (Phase 8 #70.1)."""
    def role_checker(user: CurrentUser = Depends(get_current_user)):
        if user.role == "admin":
            return user
        if user.role not in allowed_roles:
            logger.warning(f"User {user.user_id} with role {user.role} denied access to restricted resource")
            raise HTTPException(status_code=403, detail=f"Permission denied: role '{user.role}' not authorized")
        return user
    return role_checker

def verify_resource_ownership(resource_uid: str, user: CurrentUser = Depends(get_current_user)):
    """
    IDOR protection: Check if the current user owns the resource or is an admin (Phase 8 #70.2).
    """
    if user.role == "admin":
        return resource_uid
    if resource_uid != user.user_id:
        logger.warning(f"IDOR Alert: User {user.user_id} (org {user.org_id}) attempted to access resource belonging to {resource_uid}")
        raise HTTPException(status_code=403, detail="Access denied: Resource ownership mismatch")
    return resource_uid
