#!/usr/bin/env python3
"""Copy the Haaretz session from Nadav's everyday Chrome into haaretz_cookies.json
(and, with --sync, into the GitHub Actions HAARETZ_COOKIES secret).

Reusing the real browser's session means no automated login is ever needed, and
no extra "device" is registered against the subscription's device quota.

Refuses to overwrite anything unless the extracted set contains a valid,
unexpired sso_token — a bad extraction must never clobber working cookies.
"""
import hashlib, hmac, json, os, shutil, sqlite3, subprocess, sys, tempfile, time
from Crypto.Cipher import AES
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Hash import SHA1

COOKIES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "haaretz_cookies.json")
CHROME_USER_DATA_DIR = os.path.expanduser("~/Library/Application Support/Google/Chrome")
CHROME_EPOCH_OFFSET = 11644473600  # seconds between 1601-01-01 and 1970-01-01
SAMESITE_MAP = {-1: "Lax", 0: "None", 1: "Lax", 2: "Strict"}  # -1 = unspecified, browser treats as Lax


def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def _copy_db(path):
    tmp = tempfile.mktemp(suffix=".db")
    shutil.copy2(path, tmp)  # Chrome keeps the live DB locked
    return tmp


def find_chrome_cookies_db():
    """Login can live under any profile (Default, Profile 1, ...); pick the one with Haaretz cookies."""
    best_path, best_count = None, 0
    if not os.path.isdir(CHROME_USER_DATA_DIR):
        return None
    for entry in os.listdir(CHROME_USER_DATA_DIR):
        if entry != "Default" and not entry.startswith("Profile "):
            continue
        path = os.path.join(CHROME_USER_DATA_DIR, entry, "Cookies")
        if not os.path.exists(path):
            continue
        tmp = _copy_db(path)
        try:
            conn = sqlite3.connect(tmp)
            count = conn.execute(
                "SELECT COUNT(*) FROM cookies WHERE host_key LIKE '%haaretz.co.il'"
            ).fetchone()[0]
            conn.close()
        except sqlite3.Error:
            count = 0
        finally:
            os.unlink(tmp)
        if count > best_count:
            best_path, best_count = path, count
    return best_path


def get_chrome_key():
    result = subprocess.run(
        ["security", "find-generic-password", "-a", "Chrome", "-s", "Chrome Safe Storage", "-w"],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError("could not read 'Chrome Safe Storage' from the macOS Keychain")
    return PBKDF2(result.stdout.strip().encode(), b"saltysalt", dkLen=16, count=1003,
                  prf=lambda p, s: hmac.new(p, s, SHA1).digest())


def decrypt_value(encrypted_value, host_key, key, db_version):
    if not encrypted_value:
        return ""
    if not encrypted_value.startswith(b"v10"):
        return encrypted_value.decode("utf-8")
    plain = AES.new(key, AES.MODE_CBC, IV=b" " * 16).decrypt(encrypted_value[3:])
    plain = plain[:-plain[-1]]  # PKCS7
    # Cookie DB v24+ prefixes the plaintext with SHA256(host_key).
    if db_version >= 24:
        if plain[:32] != hashlib.sha256(host_key.encode()).digest():
            raise ValueError(f"domain-hash prefix mismatch for a {host_key} cookie (wrong key?)")
        plain = plain[32:]
    return plain.decode("utf-8")


def extract():
    db_path = find_chrome_cookies_db()
    if not db_path:
        raise RuntimeError("no Chrome profile has haaretz.co.il cookies — is Chrome logged in?")
    log(f"Using {db_path}")

    tmp = _copy_db(db_path)
    try:
        conn = sqlite3.connect(tmp)
        conn.row_factory = sqlite3.Row
        db_version = int(conn.execute("SELECT value FROM meta WHERE key='version'").fetchone()[0])
        rows = conn.execute("""
            SELECT host_key, name, encrypted_value, path, expires_utc, is_secure, is_httponly, samesite
            FROM cookies WHERE host_key LIKE '%haaretz.co.il'
        """).fetchall()
        conn.close()
    finally:
        os.unlink(tmp)

    key = get_chrome_key()
    cookies = []
    for row in rows:
        samesite = SAMESITE_MAP.get(row["samesite"], "Lax")
        expires = row["expires_utc"] / 1_000_000 - CHROME_EPOCH_OFFSET if row["expires_utc"] else -1
        cookies.append({
            "name": row["name"],
            "value": decrypt_value(row["encrypted_value"], row["host_key"], key, db_version),
            "domain": row["host_key"],
            "path": row["path"],
            "expires": expires,
            "httpOnly": bool(row["is_httponly"]),
            # Playwright rejects SameSite=None without Secure; Chrome's DB has legacy rows like that.
            "secure": bool(row["is_secure"]) or samesite == "None",
            "sameSite": samesite,
        })
    return cookies


def validate(cookies):
    now = time.time()
    sso = [c for c in cookies if c["name"] == "sso_token" and c["value"]]
    if not sso:
        raise RuntimeError("no sso_token in Chrome — log in to haaretz.co.il in Chrome first")
    if all(0 < c["expires"] < now for c in sso):
        raise RuntimeError("Chrome's sso_token has expired — log in to haaretz.co.il in Chrome again")
    bad = [c["name"] for c in cookies if any(not (32 <= ord(ch) < 127) for ch in c["value"])]
    if bad:
        raise RuntimeError(f"non-printable cookie values after decryption: {bad}")


def main():
    try:
        cookies = extract()
        validate(cookies)
    except Exception as e:
        log(f"✗ {e} — leaving existing cookies untouched")
        sys.exit(1)

    json.dump(cookies, open(COOKIES_FILE, "w"), ensure_ascii=False, indent=2)
    sso_exp = max(c["expires"] for c in cookies if c["name"] == "sso_token")
    log(f"✓ Saved {len(cookies)} cookies (sso_token valid until "
        f"{time.strftime('%Y-%m-%d', time.localtime(sso_exp))})")

    if "--sync" in sys.argv:
        from login_haaretz import sync_to_github_secret
        sync_to_github_secret()


if __name__ == "__main__":
    main()
