"""
Browser Security Subsystem Package.
Phase 9.5: MCP Ecosystem & Browser Agent Security.
"""

from src.security.browser.browser_security import (
    BrowserActionType,
    BrowserSessionConfig,
    BrowserSecurityController,
)
from src.security.browser.file_transfer_security import (
    FileTransferSecurityManager,
    QuarantinedDownload,
    UploadValidationResult,
    PROHIBITED_UPLOAD_PATTERNS,
    EXECUTABLE_EXTENSIONS,
)

__all__ = [
    "BrowserActionType",
    "BrowserSessionConfig",
    "BrowserSecurityController",
    "FileTransferSecurityManager",
    "QuarantinedDownload",
    "UploadValidationResult",
    "PROHIBITED_UPLOAD_PATTERNS",
    "EXECUTABLE_EXTENSIONS",
]

