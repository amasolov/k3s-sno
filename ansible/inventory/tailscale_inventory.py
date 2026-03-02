#!/usr/bin/env python3
"""Tailscale dynamic inventory for Ansible / AWX.

Queries the Tailscale API for all devices in the tailnet and groups them
by ACL tag.  Tags are mapped to Ansible groups by stripping the ``tag:``
prefix and replacing hyphens with underscores (e.g. ``tag:ha-server`` →
group ``ha_server``).

Uses OAuth client credentials (no expiration) rather than API keys
(which expire after 90 days).

Environment variables
---------------------
TS_OAUTH_CLIENT_ID      (required)  OAuth client ID.
TS_OAUTH_CLIENT_SECRET  (required)  OAuth client secret.
TAILSCALE_TAILNET       (optional)  Tailnet name; defaults to ``-``.
"""

import base64
import json
import os
import sys
import urllib.parse
import urllib.request
import urllib.error

TOKEN_URL = "https://api.tailscale.com/api/v2/oauth/token"
DEVICES_URL = "https://api.tailscale.com/api/v2/tailnet/{tailnet}/devices"


def get_oauth_token():
    client_id = os.environ.get("TS_OAUTH_CLIENT_ID", "")
    client_secret = os.environ.get("TS_OAUTH_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        sys.exit("TS_OAUTH_CLIENT_ID and TS_OAUTH_CLIENT_SECRET are required")

    creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()

    req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    req.add_header("Authorization", f"Basic {creds}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())["access_token"]
    except urllib.error.HTTPError as e:
        sys.exit(f"OAuth token error: {e.code} {e.reason}")


def get_devices(token):
    tailnet = os.environ.get("TAILSCALE_TAILNET", "-")
    url = DEVICES_URL.format(tailnet=tailnet)

    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())["devices"]
    except urllib.error.HTTPError as e:
        sys.exit(f"Tailscale API error: {e.code} {e.reason}")


def build_inventory(devices):
    inventory = {"_meta": {"hostvars": {}}}

    for device in devices:
        if not device.get("authorized", False):
            continue

        hostname = device["hostname"]
        fqdn = device.get("name", "")
        tags = device.get("tags", [])

        hostvars = {
            "ansible_host": fqdn,
            "ansible_user": "amasolov",
            "tailscale_ip": device["addresses"][0] if device.get("addresses") else None,
            "tailscale_os": device.get("os", ""),
            "tailscale_online": device.get("online", False),
        }

        inventory["_meta"]["hostvars"][hostname] = hostvars

        for tag in tags:
            group = tag.removeprefix("tag:").replace("-", "_")
            inventory.setdefault(group, {"hosts": []})
            inventory[group]["hosts"].append(hostname)

    return inventory


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "--list":
        token = get_oauth_token()
        devices = get_devices(token)
        print(json.dumps(build_inventory(devices), indent=2))
    elif len(sys.argv) == 2 and sys.argv[1] == "--host":
        print(json.dumps({}))
    else:
        print(json.dumps({"_meta": {"hostvars": {}}}))


if __name__ == "__main__":
    main()
