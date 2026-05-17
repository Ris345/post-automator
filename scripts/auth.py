"""
LinkedIn OAuth helper — run every ~55 days to rotate the access token.

Usage:
    python scripts/auth.py

Reads LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET from .env.
Opens a browser for the OAuth dance, then updates Lambda env vars and .env automatically.
LinkedIn access tokens are valid for ~60 days; re-run this script before they expire.
"""
import json
import os
import re
import subprocess
import sys
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import requests
from dotenv import load_dotenv

ENV_PATH = Path(__file__).parent.parent / ".env"
load_dotenv(ENV_PATH)

CLIENT_ID = os.environ.get("LINKEDIN_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("LINKEDIN_CLIENT_SECRET", "")
REDIRECT_URI = "http://localhost:8080/callback"
SCOPES = "openid profile w_member_social"
FUNCTION_NAME = "post-automator"

if not CLIENT_ID or not CLIENT_SECRET:
    print("Error: LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET must be set in .env")
    sys.exit(1)

_auth_code: str | None = None


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global _auth_code
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if "code" in params:
            _auth_code = params["code"][0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<h2>Auth complete &mdash; return to your terminal.</h2>")
        else:
            error = params.get("error_description", params.get("error", ["unknown"]))[0]
            print(f"\nLinkedIn returned an error: {error}")
            self.send_response(400)
            self.end_headers()
            self.wfile.write(f"<h2>Error: {error}</h2>".encode())

    def log_message(self, *_):
        pass


def _exchange_code(code: str) -> dict:
    resp = requests.post(
        "https://www.linkedin.com/oauth/v2/accessToken",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def _fetch_person_urn(access_token: str) -> str:
    resp = requests.get(
        "https://api.linkedin.com/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    resp.raise_for_status()
    sub = resp.json().get("sub", "")
    if not sub:
        raise RuntimeError(f"No sub in userinfo response: {resp.json()}")
    return f"urn:li:person:{sub}"


def _update_lambda(access_token: str, person_urn: str) -> None:
    result = subprocess.run(
        [
            "aws", "lambda", "get-function-configuration",
            "--function-name", FUNCTION_NAME,
            "--query", "Environment.Variables",
            "--output", "json",
        ],
        capture_output=True, text=True, check=True,
    )
    env = json.loads(result.stdout) if result.stdout.strip() else {}

    for key in ("LINKEDIN_REFRESH_TOKEN", "LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET"):
        env.pop(key, None)
    env["LINKEDIN_ACCESS_TOKEN"] = access_token
    env["LINKEDIN_PERSON_URN"] = person_urn

    subprocess.run(
        [
            "aws", "lambda", "update-function-configuration",
            "--function-name", FUNCTION_NAME,
            "--environment", json.dumps({"Variables": env}),
            "--query", "LastModified",
            "--output", "text",
        ],
        check=True,
    )


def _update_env_file(access_token: str, person_urn: str) -> None:
    text = ENV_PATH.read_text()
    for key, value in [("LINKEDIN_ACCESS_TOKEN", access_token), ("LINKEDIN_PERSON_URN", person_urn)]:
        if re.search(rf"^{key}=", text, re.MULTILINE):
            text = re.sub(rf"^{key}=.*$", f"{key}={value}", text, flags=re.MULTILINE)
        else:
            text = text.rstrip() + f"\n{key}={value}\n"
    ENV_PATH.write_text(text)


def main():
    auth_url = (
        "https://www.linkedin.com/oauth/v2/authorization"
        f"?response_type=code"
        f"&client_id={CLIENT_ID}"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
        f"&scope={urllib.parse.quote(SCOPES)}"
    )

    print("Opening browser for LinkedIn OAuth...")
    print(f"If the browser doesn't open, visit:\n  {auth_url}\n")
    webbrowser.open(auth_url)

    print("Waiting for callback on http://localhost:8080 ...")
    HTTPServer(("localhost", 8080), _CallbackHandler).handle_request()

    if not _auth_code:
        print("Error: no auth code received.")
        sys.exit(1)

    print("Exchanging auth code for tokens...")
    tokens = _exchange_code(_auth_code)

    access_token = tokens.get("access_token", "")
    expires_in = tokens.get("expires_in", "?")
    days = int(expires_in) // 86400 if str(expires_in).isdigit() else "?"

    if not access_token:
        print(f"Error: no access_token in response: {tokens}")
        sys.exit(1)

    print(f"Access token (expires in ~{days} days): {access_token[:20]}...")

    print("Fetching person URN...")
    person_urn = _fetch_person_urn(access_token)
    print(f"Person URN: {person_urn}")

    print("Updating Lambda env vars...")
    _update_lambda(access_token, person_urn)

    print("Updating .env...")
    _update_env_file(access_token, person_urn)

    print(f"\nDone. Token and URN are live in Lambda and .env. Re-run this script in ~{days} days.")


if __name__ == "__main__":
    main()
