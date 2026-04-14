"""
Utilities für das Ausleihsystem.
"""
from .decorators import jwt_required, require_role, get_auth_header
from .helpers import (
    get_client_info,
    log_action,
    validate_email_domain,
    get_role_level
)
from .hardware_lock import (
    acquire_hardware_lock,
    release_hardware_lock,
    is_hardware_locked,
    acquire_scan_lock,
    release_scan_lock,
    is_scanning_locked
)
from .hardware_manager import HardwareManager

__all__ = [
    # Decorators
    'jwt_required',
    'require_role',
    'get_auth_header',
    # Helpers
    'get_client_info',
    'log_action',
    'validate_email_domain',
    'get_role_level',
    # Hardware (Legacy)
    'acquire_hardware_lock',
    'release_hardware_lock',
    'is_hardware_locked',
    'acquire_scan_lock',
    'release_scan_lock',
    'is_scanning_locked',
    # Hardware Manager (neu)
    'HardwareManager',
]
