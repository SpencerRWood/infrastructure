"""Authorize only a released Events image-pin update for automatic dev deployment."""

import argparse
import json
from pathlib import Path
import re
import subprocess

import yaml


IMAGE = re.compile(
    r'ghcr[.]io/spencerrwood/events-service:v(\d+)[.](\d+)[.](\d+)@sha256:[0-9a-f]{64}'
)


def image_only(before, after):
    if not isinstance(before, dict) or not isinstance(after, dict):
        return False
    old, new = before.get('events_service_image_ref'), after.get('events_service_image_ref')
    if not isinstance(old, str) or not isinstance(new, str):
        return False
    previous, current = IMAGE.fullmatch(old), IMAGE.fullmatch(new)
    return bool(
        previous and current
        and tuple(map(int, current.groups())) > tuple(map(int, previous.groups()))
        and after.get('services', {}).get('events_service') is True
        and {k: v for k, v in before.items() if k != 'events_service_image_ref'}
        == {k: v for k, v in after.items() if k != 'events_service_image_ref'}
    )


def git(root, *args):
    return subprocess.run(
        ['git', *args], cwd=root, text=True, capture_output=True,
        timeout=30, check=True,
    ).stdout.strip()


def observe(root, revision):
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('invalid_release_revision')
    if git(root, 'rev-parse', 'HEAD') != revision:
        raise ValueError('release_checkout_mismatch')
    if git(root, 'diff', '--name-only', 'HEAD^', 'HEAD').splitlines() != ['environments/dev.yml']:
        return {'approved': False, 'reason': 'not_an_events_pin_only_change'}
    before = yaml.safe_load(git(root, 'show', 'HEAD^:environments/dev.yml'))
    after = yaml.safe_load(git(root, 'show', 'HEAD:environments/dev.yml'))
    if not image_only(before, after):
        return {'approved': False, 'reason': 'events_pin_scope_or_version_mismatch'}
    tags = [tag for tag in git(root, 'tag', '--points-at', 'HEAD').splitlines()
            if re.fullmatch(r'v\d+[.]\d+[.]\d+', tag)]
    if len(tags) != 1:
        raise ValueError('unique_published_release_tag_required')
    return {'approved': True, 'reason': 'released_events_pin_only_change',
            'release_tag': tags[0], 'image_ref': after['events_service_image_ref']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--github-output', type=Path, required=True)
    args = parser.parse_args()
    result = observe(Path.cwd(), args.revision)
    with args.github_output.open('a') as stream:
        stream.write(f"approved={str(result['approved']).lower()}\n")
        if result['approved']:
            stream.write(f"release_tag={result['release_tag']}\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
