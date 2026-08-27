"""security_audit module router — endpoints land here; see this module's GitHub issues."""
from fastapi import APIRouter

router = APIRouter(prefix="/security-audit", tags=["security_audit"])
