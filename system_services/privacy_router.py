import os
import re
import time
import logging

# ── Logging Setup ─────────────────────────────────────────────────────────────
from config.paths import LOGS_DIR  # Resolves to AppData\SentinAL\logs in prod

privacy_logger = logging.getLogger("PrivacyAudit")
privacy_logger.setLevel(logging.INFO)
if not privacy_logger.handlers:
    _handler = logging.FileHandler(
        os.path.join(LOGS_DIR, "privacy_audit.log")
    )
    _handler.setFormatter(
        logging.Formatter('%(asctime)s - [PRIVACY] - %(message)s')
    )
    privacy_logger.addHandler(_handler)


class PrivacyRouter:
    """
    Dedicated security service that scans user queries for sensitive information.
    Determines whether a prompt can be safely sent to a cloud LLM or must remain
    strictly on the local machine to protect PII / System architecture.

    V2.0 Fixes (Fix 3.3):
    - Removed 'desktop' from sensitive_folders — caused false positives for
      queries like "What is a desktop app?" (path_patterns already cover real paths)
    - All system_commands now use \\b word-boundary matching uniformly
      (prevents 'camping' matching 'cmd', 'formatting' matching 'format')
    - All routing decisions are now written to logs/privacy_audit.log
    """

    def __init__(self):
        # ── Tier 1: File Paths & Storage ─────────────────────────────────────
        self.path_patterns = [
            r'\b[a-zA-Z]:\\',           # Windows backslash paths: C:\, D:\
            r'\b[a-zA-Z]:/',            # Windows forward-slash paths: C:/
            r'\b[a-zA-Z]:\b',           # Drive letters: C:, D:
            r'\b[a-zA-Z]\s+drive\b',    # Natural language: 'c drive'
            r'/users/',                 # Unix paths
            r'/home/',
            r'%userprofile%',           # Windows Env vars
            r'%appdata%',
            r'%localappdata%',
            r'%temp%',
            r'^/(?:etc|var|usr|home|tmp|opt|root)/',  # Unix absolute paths only
            r'\.passwd\b',              # Sensitive Linux files
            r'\.shadow\b',
            r'\.bashrc\b'
        ]

        # Fix 3.3: Removed 'desktop' — path_patterns already catch real desktop paths.
        # 'What is a desktop app?' was incorrectly routing to local.
        self.sensitive_folders = [
            'documents', 'downloads', 'system32',
            'program files', 'roaming', 'windows/system'
        ]

        # ── Tier 2: System & Destructive Commands ────────────────────────────
        # Fix 3.3: All entries checked with \b word boundaries uniformly.
        # 'cmd' no longer matches 'command'.
        # 'ping' and 'netstat' removed — their word-boundary regex still matches
        # conversational contexts like 'ping pong' and 'gymnast at competition'.
        # Actual shell execution is blocked by executor._sanitize_shell_cmd.
        self.system_commands = [
            'cmd', 'powershell', 'regedit', 'taskkill', 'format',
            'rm -rf', 'del', 'format c:', 'shutdown', 'restart pc',
            'kill process', 'bootmgr', 'bios', 'ipconfig',
            'tracert', 'diskpart', 'chkdsk'
        ]

        # ── Tier 3: Personal Identifiable Information (PII) ──────────────────
        self.pii_patterns = [
            r'\b\d{3}-\d{2}-\d{4}\b',                       # SSN format
            r'\b(?:\d[ -]*?){13,16}\b',                     # Credit Card (13-16 digits)
            r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b',  # Email
            r'\b(?:\+\d{1,3}[- ]?)?\(?\d{3}\)?[- ]?\d{3}[- ]?\d{4}\b',  # Phone
            r'\b(?:\d{1,3}\.){3}\d{1,3}\b'                  # IP Address
        ]

        self.pii_keywords = [
            "my password", "my bank", "credit card", "debit card",
            "social security", "my pin", "account number", "routing number",
            "ip address", "my location", "mother's maiden name",
            "password is", "passwd is", "pass is",        # 'Password is:' patterns
            "api key", "secret key", "private key",       # Key/token fields
            "bearer token", "access token", "auth token",
        ]

        # ── Tier 4: Token / Credential Patterns ──────────────────────────────
        self.credential_patterns = [
            r'\bKey:\s*[A-Z0-9]{4}(?:-[A-Z0-9]{4})+\b',    # Key: AAAA-BBBB format
            r'\bToken:\s*\S{20,}',                           # Token: <long_value>
            r'eyJ[A-Za-z0-9-_=]+\.eyJ[A-Za-z0-9-_=]+\.[A-Za-z0-9-_.+/=]+',  # JWT
            r'\bsk-[A-Za-z0-9]{32,}',                       # OpenAI API key prefix
            r'\bgsk_[A-Za-z0-9]{32,}',                      # Groq API key prefix
        ]

    def analyze(self, query: str) -> dict:
        """
        Analyzes the string against all privacy rules.
        Returns: { "route": "cloud" | "local", "reason": "string" }
        All decisions are written to logs/privacy_audit.log.
        """
        normalized = query.lower()

        # 1. Check file path patterns
        for pattern in self.path_patterns:
            if re.search(pattern, normalized, re.IGNORECASE):
                result = {"route": "local", "reason": f"Path signature detected: '{pattern}'"}
                privacy_logger.info(f"LOCAL | {result['reason']} | query='{query[:60]}'")
                return result

        for folder in self.sensitive_folders:
            if folder in normalized:
                result = {"route": "local", "reason": f"Sensitive folder detected: '{folder}'"}
                privacy_logger.info(f"LOCAL | {result['reason']} | query='{query[:60]}'")
                return result

        # 2. Check system commands — Fix 3.3: uniform \b word boundary on all entries
        for cmd in self.system_commands:
            if re.search(rf'\b{re.escape(cmd)}\b', normalized):
                result = {"route": "local", "reason": f"System command detected: '{cmd}'"}
                privacy_logger.info(f"LOCAL | {result['reason']} | query='{query[:60]}'")
                return result

        # 3. Check PII patterns
        for pattern in self.pii_patterns:
            if re.search(pattern, query):  # case-sensitive for accuracy
                result = {"route": "local", "reason": "PII Regex match (Email/Phone/CC/ID)"}
                privacy_logger.info(f"LOCAL | {result['reason']} | query='{query[:60]}'")
                return result

        for kw in self.pii_keywords:
            if kw in normalized:
                result = {"route": "local", "reason": f"Sensitive keyword: '{kw}'"}
                privacy_logger.info(f"LOCAL | {result['reason']} | query='{query[:60]}'")
                return result

        # 4. Check credential patterns (JWT, API keys, token formats)
        for pattern in self.credential_patterns:
            if re.search(pattern, query, re.IGNORECASE):
                result = {"route": "local", "reason": "Credential/Token pattern detected"}
                privacy_logger.info(f"LOCAL | {result['reason']} | query='{query[:60]}'")
                return result

        # Default to Cloud if safe
        result = {"route": "cloud", "reason": "Clear: No sensitive architecture or PII detected."}
        privacy_logger.info(f"CLOUD | {result['reason']} | query='{query[:60]}'")
        return result


# Singleton instance for high-speed scanning
privacy_guard = PrivacyRouter()
