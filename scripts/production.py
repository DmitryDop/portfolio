"""Local release preparation and history validation. Never connects to production."""
import argparse
import hashlib
import json
import os
import posixpath
import re
import shlex
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

REMOTE = 'lineba:/home/l/linebaru/dopler/public_html/'
URL = 'https://dopler.lineband.ru/'
EXCLUDES = ('.git/', '.gitignore', '.agents/', '.claude/', '.deploy/',
            '.env', '.env.*', '.DS_Store', 'CLAUDE.md', 'AGENTS.md', 'docs/',
            'tmp/', 'PLAN.md', '.well-known/', '.htaccess', 'scripts/', 'tests/')


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.PIPE)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def production_path(name):
    p = PurePosixPath(name)
    return (not p.is_absolute() and '..' not in p.parts
            and not any(part.startswith('.') for part in p.parts)
            and (name in ('index.html', 'style.css')
                 or p.parts[0] in ('cases', 'js', 'assets', 'fonts')))


def commit_manifest(repo, sha):
    if not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise ValueError('Expected full commit SHA')
    if git(repo, 'rev-parse', sha + '^{commit}').decode().strip() != sha:
        raise ValueError('Not an existing commit')
    files = {}
    for entry in git(repo, 'ls-tree', '-rz', sha).split(b'\0'):
        if not entry:
            continue
        meta, raw_name = entry.split(b'\t', 1)
        mode, kind, blob = meta.split()
        name = raw_name.decode()
        if not production_path(name):
            continue
        if mode not in (b'100644', b'100755') or kind != b'blob':
            raise ValueError('Symlink/submodule not allowed: ' + name)
        files[name] = git(repo, 'cat-file', 'blob', blob.decode())
    if not {'index.html', 'style.css'} <= files.keys():
        raise ValueError('Missing index.html/style.css')
    return files, {name: digest(data) for name, data in sorted(files.items())}


def strip_css_comments(source):
    # Preserve quoted strings: comment delimiters inside a URL are literal text.
    tokens = r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|/\*[\s\S]*?(?:\*/|$)'''
    return re.sub(tokens, lambda match: ' ' if match.group().startswith('/*')
                  else match.group(), source)


def missing_references(files):
    missing = []
    for name, data in files.items():
        if not name.endswith(('.html', '.css', '.js')):
            continue
        source = data.decode('utf-8')
        if name.endswith('.css'):
            source = strip_css_comments(source)
        refs = re.findall(r'''(?:src|href)\s*=\s*["']([^"']+)["']''', source)
        refs += re.findall(r'''url\(\s*["']?([^\s)"']+)''', source)
        if name.endswith('.js'):
            refs += re.findall(r'''(?:fetch|import)\(\s*["']([^"']+)["']''', source)
        for ref in refs:
            u = urlsplit(ref)
            if u.scheme or u.netloc or not u.path:
                continue
            target = posixpath.normpath(unquote(u.path).lstrip('/') if u.path.startswith('/')
                                         else posixpath.join(posixpath.dirname(name), unquote(u.path)))
            if target not in files:
                missing.append((name, ref))
    return sorted(set(missing))


def prepare(repo, revision, destination):
    # Resolve once. All subsequent reads use this SHA, never HEAD or working files.
    sha = git(repo, 'rev-parse', '--verify', revision + '^{commit}').decode().strip()
    files, manifest = commit_manifest(repo, sha)
    missing = missing_references(files)
    if missing:
        raise ValueError('Missing references: ' + repr(missing))
    destination = Path(destination)
    destination.mkdir(exist_ok=False, parents=True)
    payload = destination / 'payload'
    payload.mkdir()
    for name, data in files.items():
        path = payload / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(0o444)
    release = {'commit': sha, 'manifest': manifest}
    (destination / 'release.json').write_bytes(canonical(release) + b'\n')
    return release


def check_snapshot(directory, release):
    payload = Path(directory) / 'payload'
    actual = {p.relative_to(payload).as_posix(): digest(p.read_bytes())
              for p in payload.rglob('*') if p.is_file() and not p.is_symlink()}
    if any(p.is_symlink() for p in payload.rglob('*')) or actual != release['manifest']:
        raise ValueError('Snapshot changed')


def rsync_preview(directory):
    return ['rsync', '-rvzcn', '--itemize-changes',
            *['--exclude=' + name for name in EXCLUDES],
            str(Path(directory).resolve() / 'payload') + '/', REMOTE]


def empty_history():
    return {'schema': 1, 'events': []}


def pointers(history):
    current = previous = ''
    for event in history['events']:
        if event['commit'] != current:
            previous, current = current, event['commit']
    return current, previous


def verify_evidence(manifest, evidence, operation='deploy'):
    timestamp = datetime.fromisoformat(evidence['verified_at'].replace('Z', '+00:00'))
    if timestamp.tzinfo is None:
        raise ValueError('Verification timestamp requires timezone')
    if (evidence['target'] != REMOTE or evidence['url'] != URL
            or evidence['http_status'] != 200
            or evidence['remote_sha256'] != manifest
            or evidence['http_sha256'] != manifest
            or evidence['http_statuses'] != {name: 200 for name in manifest}
            or evidence['root_sha256'] != manifest['index.html']
            or not evidence['transcript'].strip()):
        raise ValueError('Incomplete or failed production verification')
    if operation in ('baseline', 'observation'):
        if evidence.get('kind') != 'observation' or 'rsync_exit' in evidence:
            raise ValueError('Observation must not claim an upload result')
    elif evidence.get('kind', 'upload') != 'upload' or evidence.get('rsync_exit') != 0:
        raise ValueError('Upload evidence requires successful rsync')


def validate_history(repo, history, current, previous):
    if history.get('schema') != 1 or not isinstance(history.get('events'), list):
        raise ValueError('Invalid history schema')
    head = ''
    prefix = empty_history()
    ids = set()
    for event in history['events']:
        body = {k: v for k, v in event.items() if k != 'hash'}
        if event['parent'] != head or event['hash'] != digest(canonical(body)):
            raise ValueError('Broken history chain')
        if event['id'] in ids or not event['id']:
            raise ValueError('Duplicate/empty operation id')
        ids.add(event['id'])
        before, old_previous = pointers(prefix)
        if event['before'] != before or event['operation'] not in ('baseline', 'deploy', 'rollback'):
            raise ValueError('Invalid history transition')
        if event['operation'] == 'baseline' and (prefix['events'] or before or old_previous):
            raise ValueError('Baseline requires empty history and metadata')
        if event['operation'] == 'rollback' and (not old_previous or event['commit'] != old_previous):
            raise ValueError('Unconfirmed rollback target')
        _, expected = commit_manifest(repo, event['commit'])
        if event['manifest'] != expected:
            raise ValueError('Manifest differs from Git commit')
        verify_evidence(expected, event['evidence'], event['operation'])
        if 'before_evidence' in event:
            if not before:
                raise ValueError('No current version to observe')
            _, before_manifest = commit_manifest(repo, before)
            verify_evidence(before_manifest, event['before_evidence'], 'observation')
        # Existing upload events remain valid without rewriting their hashes.
        # Every new upload after a baseline must include observation of old current.
        elif event['operation'] != 'baseline' and any(e['operation'] == 'baseline' for e in prefix['events']):
            raise ValueError('Missing live verification of baseline-derived current')
        prefix['events'].append(event)
        head = event['hash']
    if pointers(history) != (current, previous):
        raise ValueError('Metadata differs from verified history; SHA alone is not evidence')
    return pointers(history)


def transition(repo, history, current, previous, sha, evidence, operation, operation_id,
               live_current=None):
    """Pure function: return candidate history only; no metadata is written."""
    validate_history(repo, history, current, previous)
    if operation not in ('baseline', 'deploy', 'rollback'):
        raise ValueError('Unknown operation')
    if operation == 'baseline' and (history['events'] or current or previous):
        raise ValueError('Baseline requires empty history and metadata')
    if operation == 'rollback' and (not previous or sha != previous):
        raise ValueError('Unconfirmed rollback target')
    files, manifest = commit_manifest(repo, sha)
    if missing_references(files):
        raise ValueError('Target has missing references')
    verify_evidence(manifest, evidence, operation)
    event = {'id': operation_id, 'operation': operation, 'commit': sha,
             'before': current, 'manifest': manifest, 'evidence': evidence,
             'parent': history['events'][-1]['hash'] if history['events'] else ''}
    if current and any(e['operation'] == 'baseline' for e in history['events']):
        if live_current is None:
            raise ValueError('Missing live verification of current')
    if live_current is not None:
        if not current:
            raise ValueError('No current version to observe')
        _, current_manifest = commit_manifest(repo, current)
        verify_evidence(current_manifest, live_current, 'observation')
        event['before_evidence'] = live_current
    event['hash'] = digest(canonical(event))
    result = {'schema': 1, 'events': [*history['events'], event]}
    new_current, new_previous = pointers(result)
    validate_history(repo, result, new_current, new_previous)
    return result, new_current, new_previous


def load_history(repo):
    base = Path(repo) / '.deploy'
    def read(name):
        path = base / name
        return path.read_text().strip() if path.exists() else ''
    current, previous = read('production-current'), read('production-previous')
    path = base / 'history.json'
    history = json.loads(path.read_text()) if path.exists() else empty_history()
    validate_history(repo, history, current, previous)
    return history, current, previous


def metadata_bytes(repo):
    base = Path(repo) / '.deploy'
    return {name: (base / name).read_bytes() if (base / name).exists() else None
            for name in ('history.json', 'production-current', 'production-previous')}


def prepare_baseline_plan(repo, revision):
    """Read-only pinned adoption plan. Does not verify live production or adopt it."""
    original = metadata_bytes(repo)
    history, current, previous = load_history(repo)
    if history['events'] or current or previous:
        raise ValueError('Baseline requires empty history and metadata')
    sha = git(repo, 'rev-parse', '--verify', revision + '^{commit}').decode().strip()
    files, manifest = commit_manifest(repo, sha)
    if missing_references(files):
        raise ValueError('Target has missing references')
    if metadata_bytes(repo) != original:
        raise ValueError('Metadata changed during plan preparation')
    plan = {'operation': 'baseline', 'commit': sha, 'manifest': manifest,
            'target': REMOTE, 'url': URL,
            'expected_metadata': {name: data.hex() if data is not None else None
                                  for name, data in original.items()}}
    plan['hash'] = digest(canonical(plan))
    return plan


def check_baseline_plan(repo, plan):
    body = {key: value for key, value in plan.items() if key != 'hash'}
    if (plan['hash'] != digest(canonical(body)) or plan['operation'] != 'baseline'
            or plan['target'] != REMOTE or plan['url'] != URL):
        raise ValueError('Baseline plan changed or targets another production')
    expected = {name: bytes.fromhex(data) if data is not None else None
                for name, data in plan['expected_metadata'].items()}
    if metadata_bytes(repo) != expected:
        raise ValueError('Metadata changed since baseline preparation')
    history, current, previous = load_history(repo)
    if history['events'] or current or previous:
        raise ValueError('Baseline requires empty history and metadata')
    _, manifest = commit_manifest(repo, plan['commit'])
    if manifest != plan['manifest']:
        raise ValueError('Baseline manifest differs from pinned commit')
    return expected


def baseline_candidate(repo, plan, observation, operation_id):
    """Pure candidate only. A successful observation does not authorize adoption."""
    check_baseline_plan(repo, plan)
    return transition(repo, empty_history(), '', '', plan['commit'], observation,
                      'baseline', operation_id)


def require_baseline_owner_confirmation(plan):
    # No trusted owner channel is installed. Never accept agent-provided flags,
    # environment variables, plan hashes or arbitrary local approval text.
    raise PermissionError('Baseline adoption disabled: trusted owner confirmation unavailable')


def save_baseline(repo, plan, live_verifier, operation_id):
    """Fail closed without owner confirmation. No production client is built in.

    A future protected approval adapter must bind owner consent to the complete plan.
    live_verifier must collect NEW SSH/HTTP observations after confirmation, under
    the metadata lock immediately before writing; callers must not replay old evidence.
    """
    check_baseline_plan(repo, plan)
    require_baseline_owner_confirmation(plan)
    expected = check_baseline_plan(repo, plan)
    pending = {}
    def reverify():
        check_baseline_plan(repo, plan)
        observation = live_verifier(plan)
        result = baseline_candidate(repo, plan, observation, operation_id)
        pending['result'] = result
        return result
    _persist_history(repo, None, expected, baseline_refresh=reverify)
    return pending['result']


def save_history(repo, result, expected_bytes):
    """Persist one verified extension; only call after real successful verification.

    History is authoritative. An interrupted mirror update deliberately fails closed.
    """
    if result[0]['events'][-1]['operation'] == 'baseline':
        raise PermissionError('Use save_baseline with separate owner confirmation and fresh verification')
    return _persist_history(repo, result, expected_bytes)


def _persist_history(repo, result, expected_bytes, baseline_refresh=None):
    """Internal storage, NOT an authorization boundary; isolated tests may exercise it."""
    if result is not None:
        validate_history(repo, *result)
    base = Path(repo) / '.deploy'
    base.mkdir(exist_ok=True)
    lock = base / 'metadata.lock'
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        if metadata_bytes(repo) != expected_bytes:
            raise ValueError('Metadata changed since preflight')
        if baseline_refresh is not None:
            result = baseline_refresh()
        if metadata_bytes(repo) != expected_bytes:
            raise ValueError('Metadata changed during live verification')
        history, current, previous = result
        validate_history(repo, history, current, previous)
        old_history, _, _ = load_history(repo)
        if (history['events'][:-1] != old_history['events']
                or len(history['events']) != len(old_history['events']) + 1):
            raise ValueError('Only one append is allowed; history cannot be rewritten')
        updates = {'history.json': canonical(history) + b'\n',
                   'production-current': (current + '\n').encode() if current else b'',
                   'production-previous': (previous + '\n').encode() if previous else b''}
        for name, data in updates.items():
            tmp_fd, tmp_name = tempfile.mkstemp(prefix='.metadata-', dir=base)
            try:
                with os.fdopen(tmp_fd, 'wb') as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(tmp_name, base / name)
            finally:
                if os.path.exists(tmp_name):
                    os.unlink(tmp_name)
        dir_fd = os.open(base, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        load_history(repo)
    finally:
        lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', default='.')
    commands = parser.add_subparsers(dest='command', required=True)
    prepare_parser = commands.add_parser('prepare')
    prepare_parser.add_argument('revision')
    prepare_parser.add_argument('destination')
    commands.add_parser('inspect')
    check_parser = commands.add_parser('check')
    check_parser.add_argument('revision', nargs='?', default='HEAD')
    baseline_parser = commands.add_parser('baseline-plan')
    baseline_parser.add_argument('revision', nargs='?', default='HEAD')
    args = parser.parse_args()
    if args.command == 'inspect':
        _, current, previous = load_history(args.repo)
        print(json.dumps({'current': current or None, 'previous': previous or None}))
    elif args.command == 'baseline-plan':
        print(json.dumps(prepare_baseline_plan(args.repo, args.revision), indent=2))
    elif args.command == 'check':
        sha = git(args.repo, 'rev-parse', '--verify', args.revision + '^{commit}').decode().strip()
        files, _ = commit_manifest(args.repo, sha)
        missing = missing_references(files)
        print(json.dumps({'commit': sha, 'missing_references': missing}, indent=2))
        if missing:
            raise SystemExit(1)
    else:
        release = prepare(args.repo, args.revision, args.destination)
        check_snapshot(args.destination, release)
        print(json.dumps(release, indent=2))
        print(shlex.join(rsync_preview(args.destination)))


if __name__ == '__main__':
    main()
