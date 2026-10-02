from fastapi import HTTPException, status, Depends
from typing import List, Callable
from .jwt_handler import decode_access_token, oauth2_scheme

class RoleChecker:
    def __init__(self, allowed_roles: List[str]):
        self.allowed_roles = allowed_roles

    def __call__(self, token: str = Depends(oauth2_scheme)):
        payload = decode_access_token(token)
        role = payload.get("role")
        tenant_id = payload.get("tenant_id")
        sub = payload.get("sub")
        
        if not role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Role not found in token"
            )
            
        if role not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation not permitted for role: {role}"
            )
            
        # Return user context for the route handler
        return {
            "sub": sub,
            "tenant_id": tenant_id,
            "role": role
        }

# Pre-defined dependencies for route protection
require_fleet_admin = RoleChecker(["fleet_admin"])
require_operator = RoleChecker(["fleet_admin", "operator"])
require_auditor = RoleChecker(["fleet_admin", "auditor"])
require_driver = RoleChecker(["fleet_admin", "driver"])
