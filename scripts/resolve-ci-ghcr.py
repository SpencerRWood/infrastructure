#!/usr/bin/env python3
"""Resolve the CI-only GHCR credential for the privileged deploy process."""

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BOOTSTRAP = Path('/srv/infrastructure/secrets/bootstrap/infisical-ci-ghcr.json')
PROJECT = '33c5aed5-165f-4ef3-845a-2f9d0f9c06d5'
BASE = 'https://dev-infisical.woodhost.cloud'
KEY = 'WEBSITE_PORTFOLIO_GHCR_TOKEN'


def fail() -> None:
    print('CI GHCR secret resolution failed', file=sys.stderr)
    raise SystemExit(1)


def select_credential(result: dict) -> str:
    """Select the registry key without rejecting other CI credentials."""
    matches = [item for item in result['secrets'] if item['secretKey'] == KEY]
    if len(matches) != 1:
        raise ValueError('expected one registry credential')
    value = matches[0]['secretValue']
    if not isinstance(value, str) or not value or '\n' in value or '\r' in value:
        raise ValueError('invalid registry credential')
    return value


def request(url: str, *, payload: dict[str, str] | None = None,
            access_token: str | None = None) -> dict:
    headers = {'Content-Type': 'application/json', 'User-Agent': 'ci-ghcr-resolver'}
    if access_token:
        headers['Authorization'] = f'Bearer {access_token}'
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers=headers,
        method='POST' if payload is not None else 'GET',
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=15) as response:
        return json.load(response)


def main() -> None:
    try:
        bootstrap = json.loads(BOOTSTRAP.read_text())
        if bootstrap['api_url'] != BASE or bootstrap['project_id'] != PROJECT:
            fail()
        login = request(
            BASE + '/api/v1/auth/universal-auth/login',
            payload={
                'clientId': bootstrap['client_id'],
                'clientSecret': bootstrap['client_secret'],
            },
        )
        query = urllib.parse.urlencode({
            'projectId': PROJECT,
            'environment': 'ci',
            'secretPath': '/github',
            'expandSecretReferences': 'false',
            'include_imports': 'false',
        })
        result = request(BASE + '/api/v4/secrets?' + query,
                         access_token=login['accessToken'])
        sys.stdout.write(select_credential(result))
    except (OSError, KeyError, TypeError, ValueError, urllib.error.URLError):
        fail()


if __name__ == '__main__':
    main()
