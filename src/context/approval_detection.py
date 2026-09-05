"""Dangerous-command detection for the approval gate — hermes port.

Port of hermes ``tools/approval_detection.py`` (module docstring verbatim):
*Pure command classification for the approval gate — no approval state,
config reads, or prompting live here.* Pulse's SafetyGuard keeps the state
and the prompting; this module answers ONE question: does this command sit
below the hardline floor (never run), or in the dangerous tier (human in
the loop asks first)?

Two tiers, hermes' names:
- HARDLINE: never runnable via the agent, regardless of any policy — only
  things with no recovery path (root wipe, raw block device writes,
  shutdown, fork bomb, kill -1). Recoverable operations (``git reset
  --hard``, ``chmod -R 777``, ``curl | sh``) stay in DANGEROUS.
- DANGEROUS: requires a human approval before running — the Windows tier
  (Remove-Item -Recurse/-Force, del /s /q, taskkill /F, format, cipher /w,
  icacls, vssadmin, reg delete, sc stop/delete), remote-content-to-shell
  (curl | sh, iwr | iex, decode pipes), world-writable permissions,
  sensitive-file writes (~/.ssh, shell rc, /etc, .env), SQL without WHERE,
  git force/reset/clean/-D, xargs rm / find -exec rm, sudo privilege
  flags, container daemon redirects and lifecycle.

Dropped from hermes' table as dead coverage here (hermes product rules
with no pulse analogue): hermes gateway lifecycle/launchctl/self-
termination rules, ``hermes update``, ``$HERMES_HOME`` config paths.
Keeping them would be coverage that only looks like coverage.

Detection-time normalizations ported: _CMDPOS anchoring so quoted prose
(``echo "does this use mkfs?"``) cannot trip command-name rules, and
quote-masking for the positionless redirect/fork-bomb rules.
"""
from __future__ import annotations

import re

_RE_FLAGS = re.IGNORECASE | re.DOTALL

# ---- Sensitive write targets (hermes verbatim, minus $HERMES_HOME forms) ----
_SSH_SENSITIVE_PATH = r'(?:~|\$home|\$\{home\})/\.ssh(?:/|$)'
_PROJECT_ENV_PATH = r'(?:(?:/|\.{1,2}/)?(?:[^\s/"\'`]+/)*\.env(?:\.[^/\s"\'`]+)*)'
_PROJECT_CONFIG_PATH = r'(?:(?:/|\.{1,2}/)?(?:[^\s/"\'`]+/)*config\.yaml)'
_SHELL_RC_FILES = r'(?:~|\$home|\$\{home\})/\.' r'(?:bashrc|zshrc|profile|bash_profile|zprofile)\b'
_CREDENTIAL_FILES = r'(?:~|\$home|\$\{home\})/\.' r'(?:netrc|pgpass|npmrc|pypirc)\b'
# macOS: /etc, /var, /tmp, /home are symlinks to /private/* — match both forms.
_MACOS_PRIVATE_SYSTEM_PATH = r'/private/(?:etc|var|tmp|home)/'
_SYSTEM_CONFIG_PATH = rf'(?:/etc/|{_MACOS_PRIVATE_SYSTEM_PATH})'
_SENSITIVE_WRITE_TARGET = (
    rf'(?:{_SYSTEM_CONFIG_PATH}|/dev/sd|{_SSH_SENSITIVE_PATH}|'
    rf'{_SHELL_RC_FILES}|{_CREDENTIAL_FILES})'
)
_USER_SENSITIVE_WRITE_TARGET = rf'(?:{_SSH_SENSITIVE_PATH}|{_SHELL_RC_FILES}|{_CREDENTIAL_FILES})'
_PROJECT_SENSITIVE_WRITE_TARGET = rf'(?:{_PROJECT_ENV_PATH}|{_PROJECT_CONFIG_PATH})'
# cp/mv/install: the sensitive path is a write target only as the LAST argument (destination).
_COMMAND_TAIL = r'(?:\s*(?:&&|\|\||;).*)?$'
# `>`/`>>`/tee: the path is ALWAYS a write target, so require a real boundary.
_WRITE_TARGET_BOUNDARY = r'(?=[\s;&|<>"\']|$)'

# Start-of-command position: start of string, newline, subshell opener, optionally
# consuming sudo/env/exec/nohup/setsid/time wrappers (hermes _CMDPOS verbatim).
_CMDPOS = (
    r'(?:^|[\n`]|\$\()' r'\s*'
    r'(?:sudo\s+(?:-[^\s]+\s+)*)?' r'(?:env\s+(\w+=\S*\s+)*)?'
    r'(?:(?:exec|nohup|setsid|time)\s+)*' r'\s*'
)

_HARDLINE_RM_FLAG_PREFIX = r'\brm\s+(?:-[^\s]+\s+)*'
_HARDLINE_SYSTEM_DIRS = r'/(?:bin|boot|dev|etc|home|lib|proc|root|sbin|srv|sys|usr|var)\b(?:/|\*|\s|$)'


def _hardline_rm_path(path_alt: str, tail: str = r'(?:\s|$|[)`;|&])') -> str:
    return rf'{_HARDLINE_RM_FLAG_PREFIX}(?:["\']?{path_alt}["\']?){tail}'


# ---- Hardline (unconditional) blocklist — hermes verbatim minus product rules ----
HARDLINE_PATTERNS: list[tuple[str, str]] = [
    (_hardline_rm_path(r'/(?:(?:\.\.?)?/)*(?:\.\.?)?\**|/ \*'), "recursive delete of root filesystem"),
    (_hardline_rm_path(_HARDLINE_SYSTEM_DIRS), "recursive delete of system directory"),
    (_hardline_rm_path(r'(?:~|\$\{?HOME\}?)(?:/?|/\*)?'), "recursive delete of home directory"),
    (_CMDPOS + r'mkfs(\.[a-z0-9]+)?\b', "format filesystem (mkfs)"),
    (_CMDPOS + r'dd\b[^\n]*\bof=/dev/(sd|nvme|hd|mmcblk|vd|xvd)[a-z0-9]*', "dd to raw block device"),
    (r'>\s*/dev/(sd|nvme|hd|mmcblk|vd|xvd)[a-z0-9]*\b', "redirect to raw block device"),
    (r':\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:', "fork bomb"),
    (_CMDPOS + r'kill\s+(-[^\s]+\s+)*-1\b', "kill all processes"),
    (_CMDPOS + r'(shutdown|reboot|halt|poweroff)\b', "system shutdown/reboot"),
    (_CMDPOS + r'init\s+[06]\b', "init 0/6 (shutdown/reboot)"),
    (_CMDPOS + r'systemctl\s+(poweroff|reboot|halt|kexec)\b', "systemctl poweroff/reboot"),
    (_CMDPOS + r'telinit\s+[06]\b', "telinit 0/6 (shutdown/reboot)"),
    # Windows shutdown/reboot siblings (hermes runs the same host classes).
    (_CMDPOS + r'(?:shutdown|logoff)\s+(?:/[a-z]\s+)*/[ry]\b', "Windows shutdown/restart (shutdown /r|/s)"),
]

HARDLINE_COMPILED = [(re.compile(p, _RE_FLAGS), d) for p, d in HARDLINE_PATTERNS]

# Positionless hardline rules matched against quote-masked variants.
_QUOTE_MASKED_HARDLINE = {"redirect to raw block device", "fork bomb"}


def _mask_quoted_prose(command: str) -> str:
    """Blank out single/double-quoted segments (hermes _mask_quoted_prose)."""
    return re.sub(r'"[^"\n]*"|\'[^\'\n]*\'', '""', command)


# ---- Dangerous tier: approval required — hermes table, verbatim where universal ----
DANGEROUS_PATTERNS: list[tuple[str, str]] = [
    (r'\brm\s+(-[^\s]*\s+)*/', "delete in root path"),
    (r'\brm\s+-[^\s]*r', "recursive delete"),
    (r'\brm\s+--recursive\b', "recursive delete (long flag)"),
    # GNU rm permutes options: flags may FOLLOW operands (`rm build/ -rf`).
    (r'\brm\s+(?!--(?:\s|$))(?:(?!\s--(?:\s|$))[^\n"\';|&])*\s' r'(?:-[a-z]*r[a-z]*\b|--recursive\b)',
     "recursive delete (flags after operands)"),
    # Windows cmd/powershell destructive built-ins, gated to shell execution position.
    (r'\bcmd(?:\.exe)?\s+/(?:c|k)\s+.*\b(?:del|erase|rd|rmdir)\b', "Windows cmd destructive delete"),
    (r'\b(?:powershell|pwsh)(?:\.exe)?\b(?:\s+-\S+)*\s+(?:-(?:command|c)\s+)?["\']?(?:remove-item|rmdir|erase|del|rd|ri|rm)\b',
     "Windows PowerShell destructive delete"),
    (r'\b(?:powershell|pwsh)(?:\.exe)?\b.*\s-(?:encodedcommand|enc|e)\b', "PowerShell encoded command execution"),
    (r'\bremove-item\b[^\n;|&]*\s-(?:recurse|force)\b', "PowerShell destructive delete (Remove-Item)"),
    (r'\b(?:del|erase|rd|rmdir)\s+(?:/[a-z]\s+)*/[sq]\b', "Windows destructive delete (recursive/quiet switch)"),
    (r'\b(?:iwr|invoke-webrequest|invoke-restmethod|irm|curl|wget)\b[^\n]*\|\s*(?:iex|invoke-expression)\b',
     "pipe remote content to PowerShell (iwr | iex)"),
    (r'\b(?:iex|invoke-expression)\s*\(\s*(?:iwr|invoke-webrequest|invoke-restmethod|irm)\b',
     "execute remote content via Invoke-Expression"),
    (r'\btaskkill\b[^\n]*\s/f\b', "force kill processes (taskkill /F)"),
    (r'\bstop-process\b[^\n]*\s-force\b', "force kill processes (Stop-Process -Force)"),
    (r'\bformat-volume\b', "format filesystem (Format-Volume)"),
    (r'\bclear-disk\b', "wipe disk (Clear-Disk)"),
    (r'\bdiskpart\b', "disk partitioning (diskpart)"),
    (r'\bformat(?:\.com)?\s+[a-z]:', "format drive (format.com)"),
    (r'\bcipher\s+/w\b', "wipe free space (cipher /w)"),
    (r'\bicacls\b[^\n]*\s/grant\b[^\n]*\b(?:everyone|todos|jeder|\*s-1-1-0)\b', "grant Everyone access (icacls)"),
    (r'\bicacls\b[^\n]*\s/reset\b', "reset ACLs recursively (icacls /reset)"),
    (r'\bvssadmin\b[^\n]*\bdelete\s+shadows\b', "delete volume shadow copies (vssadmin)"),
    (r'\bwbadmin\b[^\n]*\bdelete\b', "delete backups (wbadmin)"),
    (r'\bbcdedit\b[^\n]*\s/set\b', "modify boot configuration (bcdedit /set)"),
    (r'\breg(?:\.exe)?\s+delete\b', "registry delete (reg delete)"),
    (r'\bremove-itemproperty\b[^\n]*\s-force\b', "registry value delete (Remove-ItemProperty -Force)"),
    (r'\bstop-service\b[^\n]*\s-force\b', "force stop service (Stop-Service -Force)"),
    (r'\bsc(?:\.exe)?\s+(?:stop|delete)\b', "stop/delete service (sc)"),
    (r'\busers[\\/][^\\/\s]+[\\/]\.ssh\b', "access to SSH keys (Windows path)"),
    (r'\bchmod\s+(-[^\s]*\s+)*(777|666|o\+[rwx]*w|a\+[rwx]*w)\b', "world/other-writable permissions"),
    (r'\bchmod\s+--recursive\b.*(777|666|o\+[rwx]*w|a\+[rwx]*w)', "recursive world/other-writable (long flag)"),
    (r'\bchown\s+(-[^\s]*)?R\s+root', "recursive chown to root"),
    (r'\bchown\s+--recur[a-z]*\b.*root', "recursive chown to root (long flag)"),
    (_CMDPOS + r'mkfs\b', "format filesystem"),
    (_CMDPOS + r'dd\s+.*if=', "disk copy"),
    (r'>\s*/dev/sd', "write to block device"),
    (r'\bDROP\s+(TABLE|DATABASE)\b', "SQL DROP"),
    (r'\bDELETE\s+FROM\b(?![^\n]*\bWHERE\b)', "SQL DELETE without WHERE"),
    (r'\bTRUNCATE\s+(TABLE)?\s*\w', "SQL TRUNCATE"),
    (rf'>\s*{_SYSTEM_CONFIG_PATH}', "overwrite system config"),
    (r'\bsystemctl\s+(-[^\s]+\s+)*(stop|restart|disable|mask)\b', "stop/restart system service"),
    (r'\bkill\s+-9\s+-1\b', "kill all processes"),
    (r'\bpkill\s+-9\b', "force kill processes"),
    (r'\bkillall\s+(-[^\s]*\s+)*-(9|KILL|SIGKILL)\b', "force kill processes (killall -KILL)"),
    (r'\bkillall\s+(-[^\s]*\s+)*-s\s+(KILL|SIGKILL|9)\b', "force kill processes (killall -s KILL)"),
    (r'\bkillall\s+(-[^\s]*\s+)*-r\b', "kill processes by regex (killall -r)"),
    (r'\b(curl|wget)\b.*\|\s*(?:[/\w]*/)?(?:ba)?sh(?:\s|$|-c)', "pipe remote content to shell"),
    (r'\b(bash|sh|zsh|ksh)\s+<\s*<?\s*\(\s*(curl|wget)\b', "execute remote script via process substitution"),
    (r'(?:\beval\b|\bsource\b|\.)\s*(?:\$\(\s*|`\s*)(?:curl|wget)\b', "execute remote content via command substitution"),
    (r'\b(base64|base32|base16)\s+(?:-[dD]|--decode)\b.*\|\s*\b(bash|sh|zsh|ksh|dash)\b',
     "pipe decoded content to shell (possible command obfuscation)"),
    (r'\bxxd\s+-r\b.*\|\s*\b(bash|sh|zsh|ksh|dash)\b', "pipe xxd-decoded content to shell"),
    (r'\becho\b[^|]*\|\s*\btr\b[^|]*\|\s*\b(bash|sh|zsh|ksh|dash)\b', "pipe tr-transformed output to shell"),
    (r'\bopenssl\b.*\b(?:base64|enc)\b[^|]*\s+-[dD]\b[^|]*\|\s*\b(bash|sh|zsh|ksh|dash)\b',
     "pipe openssl-decoded content to shell"),
    (rf'\btee\b.*["\']?{_SENSITIVE_WRITE_TARGET}', "overwrite system file via tee"),
    (rf'>>?\s*["\']?{_SENSITIVE_WRITE_TARGET}', "overwrite system file via redirection"),
    (rf'\btee\b.*["\']?{_PROJECT_SENSITIVE_WRITE_TARGET}["\']?{_WRITE_TARGET_BOUNDARY}',
     "overwrite project env/config via tee"),
    (rf'>>?\s*["\']?{_PROJECT_SENSITIVE_WRITE_TARGET}["\']?{_WRITE_TARGET_BOUNDARY}',
     "overwrite project env/config via redirection"),
    (r'\bxargs\s+.*\brm\b', "xargs with rm"),
    (r'\bfind\b.*-exec(?:dir)?\s+(/\S*/)?rm\b', "find -exec/-execdir rm"),
    (r'\bfind\b.*-delete\b', "find -delete"),
    (r'\bdocker\s+(?:-{1,2}\S+(?:[=\s]\S+)?\s+)*(?:-h|--host)[=\s]+\S+', "docker with remote daemon redirect (-H/--host)"),
    (r'\bdocker\s+(?:-{1,2}\S+(?:[=\s]\S+)?\s+)*(?:-c|--context)[=\s]+\S+',
     "docker with daemon redirect (--context: alternate daemon)"),
    (r'\bdocker\s+context\s+use\b', "docker context use (switches default daemon for future commands)"),
    (r'\bpodman\s+(?:-{1,2}\S+(?:[=\s]\S+)?\s+)*(?:--url|--connection|--identity)[=\s]+\S+',
     "podman with remote daemon redirect (--url/--connection/--identity)"),
    (r'\bpodman\s+(?:-{1,2}\S+(?:[=\s]\S+)?\s+)*(?:-r\b|--remote\b)', "podman remote mode (-r/--remote: remote daemon)"),
    (r'\b(?:docker_host|docker_context|container_host|container_connection)=\S+',
     "docker/podman daemon redirect via environment (DOCKER_HOST/CONTAINER_HOST)"),
    (r'\bdocker(?:-compose|\s+compose)\s+(?:-{1,2}\S+(?:[=\s]\S+)?\s+)*(restart|stop|kill|down)\b',
     "docker compose restart/stop/kill/down (container lifecycle)"),
    (r'\bdocker\s+(?:-{1,2}\S+(?:[=\s]\S+)?\s+)*(restart|stop|kill)\b', "docker restart/stop/kill (container lifecycle)"),
    (rf'\b(cp|mv|install)\b.*\s{_SYSTEM_CONFIG_PATH}', "copy/move file into system config path"),
    (rf'\b(cp|mv|install)\b.*\s["\']?{_PROJECT_SENSITIVE_WRITE_TARGET}["\']?{_COMMAND_TAIL}',
     "overwrite project env/config file"),
    (rf'\b(cp|mv|install)\b.*\s["\']?{_SENSITIVE_WRITE_TARGET}[^\s"\']*["\']?{_COMMAND_TAIL}',
     "copy/move file into sensitive credential/SSH/shell-rc path"),
    (rf'\bsed\s+-[^\s]*i.*(?:{_USER_SENSITIVE_WRITE_TARGET})[^\s"\']*', "in-place edit of sensitive credential/SSH/shell-rc path"),
    (rf'\bsed\s+--in-place\b.*(?:{_USER_SENSITIVE_WRITE_TARGET})[^\s"\']*',
     "in-place edit of sensitive credential/SSH/shell-rc path (long flag)"),
    (rf'\bsed\s+-[^\s]*i.*\s{_SYSTEM_CONFIG_PATH}', "in-place edit of system config"),
    (rf'\bsed\s+--in-place\b.*\s{_SYSTEM_CONFIG_PATH}', "in-place edit of system config (long flag)"),
    (r'\b(bash|sh|zsh|ksh)\s+<<', "shell execution via heredoc"),
    # Git destructive operations (--h prefix form: --hard is the only reset mode starting with h).
    (r'\bgit\s+reset\s+--h(?:a(?:r(?:d)?)?)?\b', "git reset --hard (destroys uncommitted changes)"),
    (r'\bgit\s+push\b.*--forc[a-z]*\b', "git force push (rewrites remote history)"),
    (r'\bgit\s+push\b.*-f\b', "git force push short flag (rewrites remote history)"),
    (r'\bgit\s+clean\s+-[^\s]*f', "git clean with force (deletes untracked files)"),
    (r'\bgit\s+branch\s+-D\b', "git branch force delete"),
    (r'\bgit\s+branch\b[^;|&\n]*?(?:-d\b|--delete\b)[^;|&\n]*?(?:-f\b|--force\b)', "git branch force delete (long flags)"),
    (r'\bgit\s+branch\b[^;|&\n]*?(?:-f\b|--force\b)[^;|&\n]*?(?:-d\b|--delete\b)',
     "git branch force delete (long flags, force-first)"),
    (r'\bchmod\s+\+x\b.*[;&|]+\s*\./', "chmod +x followed by immediate execution"),
    (r'\bsudo\b[^;|&\n]*?\s+(?:-s\b|--st[a-z]*\b|-a\b|--a[a-z]*\b)', "sudo with privilege flag (stdin/askpass/shell/list)"),
    (r'\bsudo\b[^;|&\n]*?\s+-[a-z]*[sa][a-z]*\b', "sudo with combined-flag privilege escalation"),
]

DANGEROUS_COMPILED = [(re.compile(p, _RE_FLAGS), d) for p, d in DANGEROUS_PATTERNS]


def detect_hardline_command(command: str) -> str | None:
    """Description when the command is NEVER runnable (the floor), else None."""
    if not command or not command.strip():
        return None
    masked = _mask_quoted_prose(command)
    for pattern, description in HARDLINE_COMPILED:
        haystack = masked if description in _QUOTE_MASKED_HARDLINE else command
        if pattern.search(haystack):
            return description
    return None


def detect_dangerous_command(command: str) -> str | None:
    """Description when the command needs a human approval, else None."""
    if not command or not command.strip():
        return None
    for pattern, description in DANGEROUS_COMPILED:
        if pattern.search(command):
            return description
    return None
