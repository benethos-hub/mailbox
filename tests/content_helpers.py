"""What never belongs in a versioned file, as rules for one line, and
lines that show each rule.

``test_repo_content.py`` holds every tracked file to the rules, and
``test_pre_commit.py`` holds the hook in ``.githooks/`` to the same
lines of credentials, so the two cannot drift apart. CREDENTIAL, NAMED
and REFERENCE follow the patterns of ``.githooks/pre-commit``. A change
to one changes the other.

The lines are put together here, so this file holds none of them."""

from __future__ import annotations

import re

ALLOW = "pragma: allowlist secret"

# A user's folder on Windows, macOS and Linux, a drive as WSL and Git Bash
# mount it, and any drive path but the programs' folders, which a script
# may name on purpose. A letter after a backslash is a regular expression,
# as \d:\d, and one after a dot the end of a name, as caddy.d:/etc.
PATH = re.compile(
    r"[A-Za-z]:[\\/]+Users[\\/]|(?<![\w.])/Users/\w|(?<![\w.])/home/\w"
    r"|(?<![\w.])/mnt/[a-z]/"
    r"|(?<![\w.])/[A-Za-z]/(?:Users|home|projects)/\w"
    r"|(?<![\w\\.])[A-Za-z]:[\\/]+(?!Program Files|Windows\b)\w"
)
# An id as the service makes it: three letters, an underscore and 64 hex
# digits. Documents and tests write short ones, such as acc_1.
SERVICE_ID = re.compile(r"\b[a-z]{3}_[0-9a-f]{32,}\b")
CREDENTIAL = re.compile(
    # A token of the service and a signing secret of a webhook.
    r"mbx_[A-Za-z0-9]{16,}|whsec_[A-Za-z0-9_-]{16,}"
    # A Google client secret, access token and refresh token, and a
    # Microsoft client secret.
    r"|GOCSPX-[A-Za-z0-9_-]{16,}|ya29\.[A-Za-z0-9_-]{20,}|1//0[A-Za-z0-9_-]{30,}"
    r"|[A-Za-z0-9_~.-]{3}[0-9]Q~[A-Za-z0-9_~.-]{30,}"
    r"|Bearer [A-Za-z0-9._-]{16,}|gh[pousr]_[A-Za-z0-9]{16,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|BEGIN (?:RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY"
    # A name that ends in TOKEN, SECRET, PASSWORD or _KEY, maybe with more
    # parts such as _ENV, then the value. _KEYWORD is no such name. A
    # value that starts with / is a path.
    r"|(?:TOKEN|SECRET|PASSWORD|_KEY)(?:_[A-Z]+)*\s*[:=]\s*[\"']?"
    r"[A-Za-z0-9+_-][A-Za-z0-9+/_.-]{11,}"
)
# The same in any case, as JSON and YAML write it: a quoted value, or a
# bare one that ends the line or a word. A bare value with a dot or a
# bracket is code, such as token = base64.b64encode(raw).
NAMED = re.compile(
    r"(?:^|[^a-z0-9])[\"']?[a-z0-9_]*(?:token|secret|password|passwd|_key)[\"']?"
    r"\s*[:=]\s*"
    r"(?:[\"'][A-Za-z0-9+_-][A-Za-z0-9+/_.-]{11,}"
    r"|[A-Za-z0-9+_-][A-Za-z0-9+/_-]{11,}(?:\s|$))",
    re.IGNORECASE,
)
# What such a name is given in code without being a value: the path of a
# *_FILE setting, a constant or the name of an environment variable, the
# name of a field in quotes, a type and an attribute.
REFERENCE = re.compile(
    r"_FILE[\"']?\s*[:=]"
    r"|[:=]\s*[\"']?[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$"
    r"|[:=]\s*[\"'][a-z]+(?:_[a-z]+)+$"
    r"|[:=]\s*[A-Z][a-z]+(?:[A-Z][a-z]+)+$"
    r"|[:=]\s*[a-z_]+(?:\.[a-z_]+)+$"
)


def credentials(line: str) -> list[str]:
    """What in ``line`` looks like a credential, each cut to its start."""
    found = [m.group(0).rstrip() for m in CREDENTIAL.finditer(line)]
    found += [m.group(0).rstrip() for m in NAMED.finditer(line)]
    starts = [text[:12] for text in found if not REFERENCE.search(text)]
    return list(dict.fromkeys(starts))


def problems(line: str) -> list[str]:
    """What is wrong with one line, each named by its rule."""
    if ALLOW in line:
        return []
    found = [f"path {m.group(0)}" for m in PATH.finditer(line)]
    found += [f"service id {m.group(0)[:8]}..." for m in SERVICE_ID.finditer(line)]
    found += [f"credential {start}..." for start in credentials(line)]
    return found


# -- lines for both tests, split so no file of the repository holds one.

_RANDOM = "Zq7xW2pL9mN4vB8k"

# A credential, in the forms the rules know.
CREDENTIALS = {
    "service-token": "token = " + "mbx" + "_" + "A1b2C3d4E5f6G7h8I9",
    "json-token": '{"token": "' + "mbx" + "_" + 'abcdefghijklmnop1234"}',
    "webhook-secret": "secret " + "whsec" + "_" + "A1b2C3d4E5f6G7h8I9",
    "google-client-secret": "GOCSPX" + "-" + "A1b2C3d4E5f6G7h8I9j0",
    "google-access-token": "ya29" + "." + "a0AfH6SMBxA1b2C3d4E5f6G7h8",
    "google-refresh-token": "1/" + "/0" + "gA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6",
    "microsoft-client-secret": "abc8" + "Q~" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7",
    "bearer": "Authorization: " + "Bearer " + "abcdefghijklmnop1234",
    "github-token": "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0",
    "private-key": "-----" + "BEGIN " + "OPENSSH PRIVATE KEY-----",
    "env-bare": "MAILBOX_SERVICE_TOKEN" + "=" + _RANDOM,
    "env-spaced-quoted": "LIVE_IMAP_PASSWORD = " + '"' + _RANDOM + '"',
    "env-app-password": "LIVE_IMAP_PASSWORD" + "=" + "abcdefghijklmnop",
    "client-secret": "MAILBOX_SERVICE_OAUTH_GOOGLE_CLIENT_SECRET" + "=" + _RANDOM,
    "master-key": "MAILBOX_SERVICE_KEY" + ": " + _RANDOM + "x9",
    "yaml-quoted": "SERVICE_TOKEN: " + "'" + "abcdefghijklmnop1234" + "'",
    "json-lower-case": '{"password": "' + 'Tr0ub4dor3xyzabc"}',
    "yaml-lower-case": "token: " + "abcdefghijklmnopq",
    "mixed-case": "Master_Key = " + "abcdefghijklmnopq",
    "python-literal": "password = " + '"' + "hunter2-but-longer" + '"',
}

# A name that is given something else than a value.
REFERENCES = [
    "MAILBOX_SERVICE_KEY_FILE=/run/secrets/master_key",
    "MAILBOX_SERVICE_OAUTH_GOOGLE_CLIENT_SECRET_FILE=config/google_client_secret",
    "MAILBOX_SERVICE_TOKEN: ${MAILBOX_SERVICE_TOKEN}",
    'headers={"Authorization": f"Bearer {token}"}',
    "token = base64.b64encode(raw).decode()",
    "tokens_in=calls.tokens_in",
    'ADD_KEYWORD = "add_keyword_long_value"',
    'TOKEN_ENV = "MAILBOX_SERVICE_TOKEN"',
    "    MIN_PASSWORD=MIN_PASSWORD,",
    "secret = SECRET_PREFIX + secret_values.token()",
    '    APP_PASSWORD = "app_password"',
    'REFRESH_TOKEN = "refresh_token"',
    "credentials = {REFRESH_TOKEN: tokens.refresh_token}",
    "    idempotency_key: IdempotencyKey = None,",
    "password: str | None = None",
    'token = os.environ.get("MAILBOX_SERVICE_TOKEN")',
    "a token mbx_…a1 and a secret whsec_new",
]
