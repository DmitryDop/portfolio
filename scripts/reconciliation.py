"""Read-only production observation and owner-signed metadata reconciliation.

No uploads, local shell execution, key generation or trust bootstrap. The public write
APIs require an SSHSIG receipt from an independently provisioned owner key.
"""
import concurrent.futures
import contextlib
import copy
import json
import os
import shlex
import stat
import subprocess
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

from scripts import production as p

SIGNERS = Path('/etc/portfolio-production/allowed_signers')
OWNER = 'portfolio-owner'
NAMESPACE = 'portfolio-production-'
PENDING = 'reconciliation-pending.json'
METADATA = ('history.json', 'production-current', 'production-previous')
MAX_AGE = timedelta(minutes=10)


def now():
    return datetime.now(timezone.utc)


def timestamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Timezone required')
    return result


def seal(body):
    return {**body, 'hash': p.digest(p.canonical(body))}


def check_seal(value):
    if value.get('hash') != seal({k: v for k, v in value.items() if k != 'hash'})['hash']:
        raise ValueError('Plan/journal hash mismatch')


def fingerprints(values):
    return {n: p.digest(b) if b is not None else None for n, b in values.items()}


def check_metadata_paths(repo):
    base = Path(repo) / '.deploy'
    if base.is_symlink() or any((base / n).is_symlink() for n in (*METADATA, PENDING)):
        raise ValueError('Metadata symlinks are forbidden')


def metadata_result(result):
    history, current, previous = result
    return {'history.json': p.canonical(history) + b'\n',
            'production-current': (current + '\n').encode(),
            'production-previous': (previous + '\n').encode() if previous else b''}


def prepare_plan(repo, revision, reason):
    """Only reads Git and existing metadata. Does not observe or reconcile."""
    repo = Path(repo)
    check_metadata_paths(repo)
    original = p.metadata_bytes(repo)
    history, current, previous = p.load_history(repo)
    if not history['events'] or not current:
        raise ValueError('Reconciliation requires nonempty valid history; use baseline for empty state')
    sha = p.git(repo, 'rev-parse', '--verify', revision + '^{commit}').decode().strip()
    files, manifest = p.commit_manifest(repo, sha)
    if not reason.strip() or p.missing_references(files):
        raise ValueError('Reason required; missing references block reconciliation')
    if manifest == p.commit_manifest(repo, current)[1]:
        raise ValueError('No production drift: target content already recorded')
    if p.metadata_bytes(repo) != original:
        raise ValueError('Metadata changed while preparing plan')
    return seal({'operation': 'reconciliation', 'operation_id': str(uuid.uuid4()),
                 'repo': str(repo.resolve()), 'commit': sha, 'manifest': manifest,
                 'manifest_sha256': p.digest(p.canonical(manifest)),
                 'target': p.REMOTE, 'url': p.URL, 'before': current,
                 'recorded_previous': previous, 'previous': '', 'reason': reason,
                 'history_tip': history['events'][-1]['hash'],
                 'metadata_sha256': fingerprints(original)})


def check_plan(repo, plan):
    check_metadata_paths(repo)
    check_seal(plan)
    if (plan['operation'] != 'reconciliation' or plan['target'] != p.REMOTE
            or plan['url'] != p.URL or plan['repo'] != str(Path(repo).resolve())
            or plan['previous'] != '' or not plan['reason'].strip()):
        raise ValueError('Invalid reconciliation plan or target')
    uuid.UUID(plan['operation_id'])
    history, current, previous = p.load_history(repo)
    if (not history['events'] or plan['history_tip'] != history['events'][-1]['hash']
            or plan['before'] != current or plan['recorded_previous'] != previous
            or fingerprints(p.metadata_bytes(repo)) != plan['metadata_sha256']):
        raise ValueError('Metadata changed since plan preparation')
    files, manifest = p.commit_manifest(repo, plan['commit'])
    if (manifest != plan['manifest'] or p.digest(p.canonical(manifest)) != plan['manifest_sha256']
            or p.missing_references(files) or manifest == p.commit_manifest(repo, current)[1]):
        raise ValueError('Manifest mismatch, missing references or no production drift')
    return history, current, previous


def trusted_signers():
    """Fixed OS-admin trust store, never a key supplied by the repo or caller."""
    resolved = SIGNERS.resolve(strict=True)
    for path in (resolved, *resolved.parents):
        info = path.stat()
        if info.st_uid != 0 or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise PermissionError('Owner trust store must be root-owned and not group/world writable')
    if not resolved.is_file():
        raise PermissionError('Owner trust store must be a regular file')
    return resolved


def check_claims(plan, receipt, at=None):
    claims = receipt['claims']
    if (set(claims) != {'purpose', 'plan_hash', 'operation_id', 'receipt_id', 'issued_at', 'expires_at'}
            or claims['purpose'] != plan['operation'] or claims['plan_hash'] != plan['hash']
            or claims['operation_id'] != plan['operation_id']):
        raise PermissionError('Owner receipt is not bound to this exact plan')
    uuid.UUID(claims['receipt_id'])
    issued, expires = timestamp(claims['issued_at']), timestamp(claims['expires_at'])
    if expires <= issued or expires - issued > MAX_AGE:
        raise PermissionError('Invalid owner receipt lifetime')
    if at is not None and not issued <= at < expires:
        raise PermissionError('Owner receipt expired or not yet valid')


def require_owner_confirmation(plan, receipt):
    """Verify an external owner signature; no flags, env or callback approvals."""
    check_claims(plan, receipt, now())
    verify_owner_signature(plan, receipt)


def verify_owner_signature(plan, receipt):
    """Verify archived signatures without treating their expired consent as new."""
    check_claims(plan, receipt)
    try:
        signers = trusted_signers()
    except (OSError, PermissionError) as exc:
        raise PermissionError('Trusted owner confirmation unavailable') from exc
    signature = receipt['signature']
    if not isinstance(signature, str) or len(signature) > 16384:
        raise PermissionError('Invalid owner signature')
    with tempfile.TemporaryDirectory(prefix='portfolio-owner-verify-') as directory:
        sig = Path(directory) / 'receipt.sig'
        sig.write_text(signature)
        result = subprocess.run(
            ['/usr/bin/ssh-keygen', '-Y', 'verify', '-f', str(signers), '-I', OWNER,
             '-n', NAMESPACE + plan['operation'], '-s', str(sig)],
            input=p.canonical(receipt['claims']), capture_output=True, timeout=15)
    if result.returncode:
        raise PermissionError('Owner signature verification failed')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('Production redirects are forbidden')


# Literal, fixed remote root. Names arrive over stdin, never in shell source.
REMOTE_READER = r'''
import hashlib,json,pathlib,stat,sys
root=pathlib.Path('/home/l/linebaru/dopler/public_html')
if root.is_symlink(): raise ValueError('Production root is a symlink')
names=json.load(sys.stdin)
hashes={}
for name in names:
 path=root/name
 for component in (path,*path.parents):
  if component==root: break
  if component.is_symlink(): raise ValueError('Managed symlink: '+name)
 if not stat.S_ISREG(path.stat().st_mode): raise ValueError('Not a regular file: '+name)
 hashes[name]=hashlib.sha256(path.read_bytes()).hexdigest()
extras=[]; protected={}
for path in root.rglob('*'):
 name=path.relative_to(root).as_posix()
 if path.is_symlink():
  if name not in names: extras.append(name)
 elif path.is_file():
  if name not in names: extras.append(name)
  if name=='.htaccess' or name.startswith('.well-known/'):
   protected[name]=hashlib.sha256(path.read_bytes()).hexdigest()
print(json.dumps({'hashes':hashes,'extra_paths':sorted(extras),'protected':protected}))
'''


def collect_observation(repo, plan, challenge):
    """Actual read-only SSH + TLS-verified HTTPS; never invokes rsync."""
    started = now().isoformat()
    files, manifest = p.commit_manifest(repo, plan['commit'])
    if manifest != plan['manifest']:
        raise ValueError('Collector manifest changed')
    command = ['/usr/bin/ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
               '-o', 'ConnectTimeout=15', 'lineba', 'python3 -c ' + shlex.quote(REMOTE_READER)]
    def remote():
        result = subprocess.run(command, input=json.dumps(list(manifest)), text=True,
                                capture_output=True, timeout=120)
        if result.returncode:
            raise ValueError('SSH verification failed: ' + result.stderr)
        return json.loads(result.stdout), {'command': command, 'exit': result.returncode,
                                           'stdout': result.stdout, 'stderr': result.stderr}
    first, first_log = remote()
    def fetch(name):
        url = p.URL + quote(name, safe='/')
        # The default TLS context verifies certificates; no proxy or TLS override.
        with build_opener(NoRedirect).open(Request(url, headers={
                'Accept-Encoding': 'identity', 'Cache-Control': 'no-cache'}), timeout=30) as response:
            body = response.read(len(files[name or 'index.html']) + 1)
            if response.headers.get('Content-Encoding', 'identity') not in ('identity', ''):
                raise ValueError('Unexpected HTTP content encoding')
            return name, response.status, p.digest(body)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(fetch, [*manifest, '']))
    second, second_log = remote()
    if first != second:
        raise ValueError('Production changed during observation')
    root = next((status, sha) for name, status, sha in rows if not name)
    evidence = {'kind': 'observation', 'started_at': started, 'verified_at': now().isoformat(),
                'challenge': challenge, 'target': p.REMOTE, 'url': p.URL,
                'http_status': root[0], 'root_sha256': root[1],
                'remote_sha256': second['hashes'],
                'http_sha256': {n: h for n, s, h in rows if n},
                'http_statuses': {n: s for n, s, h in rows if n},
                'extra_paths': second['extra_paths'], 'protected': second['protected'],
                'transcript': json.dumps({'ssh_before': first_log, 'http': rows, 'ssh_after': second_log})}
    p.verify_evidence(manifest, evidence, 'observation')
    return evidence


def check_observation(plan, evidence, challenge, started):
    p.verify_evidence(plan['manifest'], evidence, 'observation')
    end = now()
    if (evidence['challenge'] != challenge
            or not started <= timestamp(evidence['started_at']) <= timestamp(evidence['verified_at']) <= end
            or end - started > MAX_AGE):
        raise ValueError('Stale or replayed observation')
    if (not isinstance(evidence['extra_paths'], list)
            or evidence['extra_paths'] != sorted(set(evidence['extra_paths']))
            or not isinstance(evidence['protected'], dict)):
        raise ValueError('Missing server inventory')


def validate_event(repo, event, prefix, before, old_previous):
    """Historical validation is structural; signature was checked at write time.

    As with legacy uploads, a hash chain is not an independent trust anchor.
    Expired receipts must remain auditable without rewriting old events.
    """
    plan, receipt = event['plan'], event['owner_receipt']
    check_seal(plan)
    check_claims(plan, receipt, timestamp(event['evidence']['started_at']))
    if (not prefix['events'] or plan['operation'] != 'reconciliation'
            or event['id'] != plan['operation_id'] or event['commit'] != plan['commit']
            or event['manifest'] != plan['manifest'] or plan['before'] != before
            or plan['recorded_previous'] != old_previous or plan['previous'] != ''
            or plan['history_tip'] != prefix['events'][-1]['hash']
            or plan['target'] != p.REMOTE or plan['url'] != p.URL
            or plan['manifest_sha256'] != p.digest(p.canonical(event['manifest']))
            or not plan['reason'].strip()
            or event['manifest'] == p.commit_manifest(repo, before)[1]
            or 'before_evidence' in event):
        raise ValueError('Invalid reconciliation event')
    for old in prefix['events']:
        if old.get('owner_receipt', {}).get('claims', {}).get('receipt_id') == receipt['claims']['receipt_id']:
            raise ValueError('Owner receipt replay')
    evidence = event['evidence']
    if (timestamp(evidence['verified_at']) < timestamp(evidence['started_at'])
            or timestamp(evidence['verified_at']) - timestamp(evidence['started_at']) > MAX_AGE
            or not evidence['challenge'] or not isinstance(evidence['extra_paths'], list)
            or not isinstance(evidence['protected'], dict)):
        raise ValueError('Invalid reconciliation observation')


def candidate(repo, plan, evidence, receipt):
    """Pure candidate, not authorization and not a persistence API."""
    history, current, previous = check_plan(repo, plan)
    event = {'id': plan['operation_id'], 'operation': 'reconciliation',
             'commit': plan['commit'], 'before': current, 'manifest': plan['manifest'],
             'evidence': copy.deepcopy(evidence), 'parent': history['events'][-1]['hash'],
             'plan': copy.deepcopy(plan), 'owner_receipt': copy.deepcopy(receipt)}
    event = seal(event)
    result = {'schema': 1, 'events': [*history['events'], event]}, plan['commit'], ''
    p.validate_history(repo, *result)
    return result


@contextlib.contextmanager
def metadata_lock(repo):
    check_metadata_paths(repo)
    base = Path(repo) / '.deploy'
    # Valid nonempty history already requires the directory to exist.
    path = base / 'metadata.lock'
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(fd, str(os.getpid()).encode())
        os.fsync(fd)
        yield
    finally:
        owned = os.fstat(fd)
        os.close(fd)
        actual = path.lstat()
        if (owned.st_dev, owned.st_ino) != (actual.st_dev, actual.st_ino):
            raise ValueError('Metadata lock was replaced; refusing to remove foreign lock')
        path.unlink()


def fsync_directory(base):
    fd = os.open(base, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(path, data):
    fd, name = tempfile.mkstemp(prefix='.reconciliation-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        fsync_directory(path.parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def encode_bytes(values):
    return {n: b.hex() if b is not None else None for n, b in values.items()}


def decode_bytes(values):
    if set(values) != set(METADATA):
        raise ValueError('Invalid transaction paths')
    return {n: bytes.fromhex(b) if b is not None else None for n, b in values.items()}


def parse_state(repo, values):
    history = json.loads(values['history.json'])
    current = (values['production-current'] or b'').decode().strip()
    previous = (values['production-previous'] or b'').decode().strip()
    p.validate_history(repo, history, current, previous)
    return history, current, previous


def _persist_transaction(repo, result, original):
    """Internal storage only. Caller owns metadata.lock and verified authority."""
    base = Path(repo) / '.deploy'
    if (base / PENDING).exists() or p.metadata_bytes(repo) != original:
        raise ValueError('Pending transaction or metadata changed')
    old = parse_state(repo, original)
    p.validate_history(repo, *result)
    if (result[0]['events'][:-1] != old[0]['events']
            or result[0]['events'][-1]['operation'] != 'reconciliation'):
        raise ValueError('Only one reconciliation append is allowed')
    updates = metadata_result(result)
    journal = seal({'schema': 1, 'operation_id': result[0]['events'][-1]['id'],
                    'before': encode_bytes(original), 'after': encode_bytes(updates)})
    event = result[0]['events'][-1]
    require_owner_confirmation(event['plan'], event['owner_receipt'])
    if p.metadata_bytes(repo) != original:
        raise ValueError('Metadata changed before transaction commit')
    # WAL is durable before the first metadata replacement. History is commit point.
    atomic_write(base / PENDING, p.canonical(journal) + b'\n')
    for name in METADATA:
        atomic_write(base / name, updates[name])
    # A pending WAL blocks normal reads/writes even if all mirrors are complete.
    actual = p.metadata_bytes(repo)
    if actual != updates or parse_state(repo, actual) != result:
        raise ValueError('Metadata verification failed; recovery required')
    (base / PENDING).unlink()
    fsync_directory(base)


def save_reconciliation(repo, plan, receipt):
    """The only public reconciliation write API. Fail closed without owner trust."""
    plan, receipt = copy.deepcopy(plan), copy.deepcopy(receipt)
    check_plan(repo, plan)
    require_owner_confirmation(plan, receipt)
    with metadata_lock(repo):
        check_plan(repo, plan)
        original = p.metadata_bytes(repo)
        started, challenge = now(), str(uuid.uuid4())
        evidence = collect_observation(repo, plan, challenge)
        check_observation(plan, evidence, challenge, started)
        require_owner_confirmation(plan, receipt)  # expiry/revocation during observation
        check_plan(repo, plan)
        result = candidate(repo, plan, evidence, receipt)
        _persist_transaction(repo, result, original)
        return p.load_history(repo)


def read_pending(repo):
    check_metadata_paths(repo)
    base = Path(repo) / '.deploy'
    raw = (base / PENDING).read_bytes()
    journal = json.loads(raw)
    check_seal(journal)
    if journal['schema'] != 1:
        raise ValueError('Unknown transaction schema')
    before, after = decode_bytes(journal['before']), decode_bytes(journal['after'])
    old, new = parse_state(repo, before), parse_state(repo, after)
    event = new[0]['events'][-1]
    if (new[0]['events'][:-1] != old[0]['events'] or event['operation'] != 'reconciliation'
            or event['id'] != journal['operation_id']
            or event['plan']['metadata_sha256'] != fingerprints(before)):
        raise ValueError('Invalid transaction history extension')
    actual = p.metadata_bytes(repo)
    if any(actual[n] not in (before[n], after[n]) for n in METADATA):
        raise ValueError('Metadata changed outside interrupted transaction')
    if actual['history.json'] == after['history.json']:
        action = 'finish-mirrors'
    elif actual == before:
        action = 'abort-uncommitted'
    else:
        raise ValueError('Invalid transaction ordering')
    return raw, before, after, actual, action, event


def prepare_recovery_plan(repo):
    """Read-only recovery decision. Never removes locks or repairs mirrors."""
    raw, before, after, actual, action, event = read_pending(repo)
    result = parse_state(repo, after if action == 'finish-mirrors' else before)
    return seal({'operation': 'reconciliation-recovery', 'operation_id': str(uuid.uuid4()),
                 'repo': str(Path(repo).resolve()), 'pending_sha256': p.digest(raw),
                 'metadata_sha256': fingerprints(actual), 'action': action,
                 'event_id': event['id'], 'commit': event['commit'],
                 'result_current': result[1], 'result_previous': result[2],
                 'manifest_sha256': p.digest(p.canonical(event['manifest'])),
                 'target': p.REMOTE, 'url': p.URL})


def recover_reconciliation(repo, plan, receipt):
    """Explicit owner-signed recovery only; no deploy, new event or live adoption."""
    plan, receipt = copy.deepcopy(plan), copy.deepcopy(receipt)
    check_seal(plan)
    if (plan['operation'] != 'reconciliation-recovery'
            or plan['repo'] != str(Path(repo).resolve())
            or plan['target'] != p.REMOTE or plan['url'] != p.URL):
        raise ValueError('Invalid recovery plan')
    require_owner_confirmation(plan, receipt)
    with metadata_lock(repo):
        raw, before, after, actual, action, event = read_pending(repo)
        result = parse_state(repo, after if action == 'finish-mirrors' else before)
        if (p.digest(raw) != plan['pending_sha256'] or fingerprints(actual) != plan['metadata_sha256']
                or action != plan['action'] or event['id'] != plan['event_id']
                or event['commit'] != plan['commit']
                or plan['result_current'] != result[1] or plan['result_previous'] != result[2]
                or plan['manifest_sha256'] != p.digest(p.canonical(event['manifest']))):
            raise ValueError('Recovery state changed since approval')
        require_owner_confirmation(plan, receipt)
        verify_owner_signature(event['plan'], event['owner_receipt'])
        require_owner_confirmation(plan, receipt)
        base = Path(repo) / '.deploy'
        if (p.metadata_bytes(repo) != actual
                or (base / PENDING).read_bytes() != raw):
            raise ValueError('Recovery state changed during owner verification')
        if action == 'finish-mirrors':
            # Never re-upload, rewrite history, append or replay reconciliation.
            for name in METADATA[1:]:
                atomic_write(base / name, after[name])
            if p.metadata_bytes(repo) != after:
                raise ValueError('Recovery metadata changed during mirror write')
            parse_state(repo, after)
        (base / PENDING).unlink()
        fsync_directory(base)
        return p.load_history(repo)
