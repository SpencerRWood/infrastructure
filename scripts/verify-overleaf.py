#!/usr/bin/env python3
"""Bounded infrastructure smoke test; report/PDF acceptance belongs to wood-reports."""
import argparse
import base64
import json
import os
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

MAX_RESPONSE = 20 * 1024 * 1024
USER_AGENT = 'Wood-Infrastructure-Verification/1.0'
SOURCE = r"""\documentclass{article}
\usepackage{fontspec,tabularray,graphicx,xcolor}
\begin{document}Infrastructure compiler smoke test.
\begin{tblr}{ll}Compiler & LuaLaTeX\\Status & Ready\end{tblr}
\end{document}
"""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def credentials(path):
    info = path.stat()
    if (not stat.S_ISREG(info.st_mode) or path.is_symlink()
            or info.st_uid != 0 or info.st_gid != 0
            or stat.S_IMODE(info.st_mode) != 0o600):
        raise ValueError('credentials must be a root-owned mode 0600 regular file')
    values = {}
    for line in path.read_text().splitlines():
        key, separator, value = line.partition('=')
        if not separator or key in values or not value:
            raise ValueError('invalid credentials')
        values[key] = value
    if set(values) != {'CLSI_USERNAME', 'CLSI_PASSWORD'}:
        raise ValueError('invalid credential keys')
    if ':' in values['CLSI_USERNAME']:
        raise ValueError('invalid username')
    return values


def read_bounded(response):
    body = response.read(MAX_RESPONSE + 1)
    if len(body) > MAX_RESPONSE:
        raise ValueError('response exceeded the smoke-test limit')
    return body


def verify(values, *, opener=None):
    opener = opener or urllib.request.build_opener(
        urllib.request.ProxyHandler({}), NoRedirect()
    )
    base = 'https://clsi.woodhost.cloud'
    auth = 'Basic ' + base64.b64encode(
        (values['CLSI_USERNAME'] + ':' + values['CLSI_PASSWORD']).encode()
    ).decode()

    def request(url, *, method='GET', body=None, authenticated=True):
        headers = {'User-Agent': USER_AGENT}
        if authenticated:
            headers['Authorization'] = auth
        if body is not None:
            headers['Content-Type'] = 'application/json'
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        with opener.open(req, timeout=180 if method == 'POST' else 10) as response:
            if response.status != 200:
                raise ValueError('unexpected endpoint status')
            return read_bounded(response)

    # TLS validation is enabled; no insecure switch or credential-bearing redirect.
    editor = urllib.request.Request('https://overleaf.woodhost.cloud/login',
                                    headers={'User-Agent': USER_AGENT})
    with opener.open(editor, timeout=10) as response:
        if response.status != 200:
            raise ValueError('editor endpoint is not ready')
    for path in ('/status', '/project/000000000000000000000000/compile',
                 '/project/000000000000000000000000/build/test/output/output.pdf'):
        try:
            request(base + path, authenticated=False,
                    method='POST' if path.endswith('/compile') else 'GET',
                    body=b'{}' if path.endswith('/compile') else None)
        except urllib.error.HTTPError as error:
            code = error.code
            error.close()
            if code != 401:
                raise ValueError('unauthenticated compiler request was not rejected') from None
        else:
            raise ValueError('unauthenticated compiler access is possible')
    request(base + '/status')
    project = uuid.uuid4().hex[:24]
    try:
        result = json.loads(request(
            base + '/project/' + project + '/compile', method='POST',
            body=json.dumps({'compile': {
                'options': {'compiler': 'lualatex', 'timeout': 60},
                'rootResourcePath': 'main.tex',
                'resources': [{'path': 'main.tex', 'content': SOURCE}],
            }}).encode(),
        ))
        if result['compile']['status'] != 'success':
            raise ValueError('LuaLaTeX smoke compilation failed')
        files = [item for item in result['compile']['outputFiles'] if item['type'] == 'pdf']
        if len(files) != 1:
            raise ValueError('smoke compilation did not produce one PDF')
        url = urllib.parse.urlsplit(files[0]['url'])
        if (url.scheme != 'https' or url.netloc != 'clsi.woodhost.cloud'
                or not url.path.startswith('/project/' + project + '/')
                or url.query or url.fragment):
            raise ValueError('compiler returned an unexpected output origin')
        if not request(files[0]['url']).startswith(b'%PDF-'):
            raise ValueError('compiler output is not a PDF')
    finally:
        # Remove only the generated smoke-test project, including failed builds.
        req = urllib.request.Request(base + '/project/' + project,
                                     headers={'Authorization': auth, 'User-Agent': USER_AGENT},
                                     method='DELETE')
        with opener.open(req, timeout=10) as response:
            if response.status not in (200, 204):
                raise ValueError('smoke project cleanup failed')
    return {'status': 'passed', 'editor_tls': True, 'compiler_tls': True,
            'unauthenticated_access': 'denied', 'lualatex': 'passed', 'cleanup': 'passed'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credentials', type=Path, required=True)
    args = parser.parse_args()
    try:
        if os.geteuid() != 0:
            raise ValueError('root is required')
        print(json.dumps(verify(credentials(args.credentials))))
    except Exception:
        # Upstream bodies, URLs and exceptions may contain credentials or source.
        print(json.dumps({'status': 'failed', 'reason': 'Overleaf/CLSI smoke verification failed'}))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
