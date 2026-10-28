"""Disposable Git repos, local content and synthetic network; no keys or production writes.

No production server or actual metadata is used.
"""
import copy
import io
import json
import os
import subprocess
import tempfile
import unittest
import uuid
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from scripts import production as p
from scripts import reconciliation as r


class ReconciliationTests(unittest.TestCase):


    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'repo'; self.repo.mkdir()
        self.git('init', '-q'); self.git('config', 'user.name', 'Local test')
        self.git('config', 'user.email', 'local-test@example.invalid')
        (self.repo / 'style.css').write_text('body {color:red}')
        self.versions = []
        for label in ['A', 'B', 'C', 'D']:
            (self.repo / 'index.html').write_text('<link href="style.css"><p>' + label + '</p>')
            self.git('add', '.'); self.git('commit', '-qm', label)
            self.versions.append(self.git('rev-parse', 'HEAD').decode().strip())
        self.a, self.b, self.c, self.d = self.versions
        state = p.empty_history(), '', ''
        for sha in (self.a, self.b):
            old = p.metadata_bytes(self.repo)
            state = p.transition(self.repo, *state, sha, self.upload(sha), 'deploy', str(uuid.uuid4()))
            p.save_history(self.repo, state, old)
        self.old = p.metadata_bytes(self.repo)
        self.old_history = copy.deepcopy(state[0])
        self.plan = r.prepare_plan(self.repo, self.c, 'Unrecorded production change; prior version unknown')
        self.site = self.root / 'site'; self.site.mkdir()
        self.publish_local(self.c)

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], stderr=subprocess.PIPE)

    def upload(self, sha):
        m = p.commit_manifest(self.repo, sha)[1]
        return {'kind': 'upload', 'rsync_exit': 0, 'verified_at': r.now().isoformat(),
                'target': p.REMOTE, 'url': p.URL, 'remote_sha256': m.copy(),
                'http_sha256': m.copy(), 'http_statuses': {n: 200 for n in m},
                'http_status': 200, 'root_sha256': m['index.html'],
                'transcript': 'LOCAL TEST ONLY: simulated historical upload'}

    def publish_local(self, sha):
        for n, b in p.commit_manifest(self.repo, sha)[0].items():
            (self.site / n).write_bytes(b)

    def observation(self, repo, plan, challenge):
        self.assertTrue((self.repo / '.deploy/metadata.lock').is_file())
        hashes = {n: p.digest((self.site / n).read_bytes()) for n in plan['manifest']}
        return {'kind': 'observation', 'started_at': r.now().isoformat(),
                'verified_at': r.now().isoformat(), 'challenge': challenge,
                'target': p.REMOTE, 'url': p.URL, 'remote_sha256': hashes,
                'http_sha256': hashes.copy(), 'http_statuses': {n: 200 for n in hashes},
                'http_status': 200, 'root_sha256': hashes['index.html'],
                'extra_paths': ['CV.pdf'], 'protected': {},
                'transcript': 'LOCAL TEST ONLY: filesystem hashes, simulated SSH/HTTPS'}


    def save(self, plan=None, statement=None, collector=None):
        plan = plan or self.plan
        if statement is None:
            statement = r.expected_confirmation(plan)
        with patch.object(r, 'collect_observation', side_effect=collector or self.observation):
            return r.save_reconciliation(self.repo, plan, statement)

    def interrupted(self, call):
        actual = r.atomic_write
        count = 0
        def fail(path, data):
            nonlocal count
            count += 1
            if count == call:
                raise OSError('LOCAL TEST simulated power loss')
            actual(path, data)
        with patch.object(r, 'atomic_write', side_effect=fail):
            with self.assertRaises(OSError): self.save()
        self.assertTrue((self.repo / '.deploy' / r.PENDING).exists())

    def recover(self, plan=None):
        plan = plan or r.prepare_recovery_plan(self.repo)
        return r.recover_reconciliation(self.repo, plan, r.expected_confirmation(plan))

    def test_plan_is_read_only_and_binds_metadata_manifest_repo(self):
        r.check_plan(self.repo, self.plan)
        self.assertEqual(self.plan['manifest_sha256'], p.digest(p.canonical(self.plan['manifest'])))
        self.assertEqual(self.plan['metadata_sha256'], r.fingerprints(self.old))
        self.assertEqual(p.metadata_bytes(self.repo), self.old)
        self.assertEqual(self.plan['previous'], '')
        self.assertEqual(self.plan['recorded_previous'], self.a)

    def test_confirmed_reconciliation_archives_metadata_and_preserves_history(self):
        state = self.save()
        self.assertEqual(state[1:], (self.c, ''))
        self.assertEqual(state[0]['events'][:-1], self.old_history['events'])
        event = state[0]['events'][-1]
        self.assertEqual(event['operation'], 'reconciliation')
        self.assertNotIn('rsync_exit', event['evidence'])
        self.assertEqual(event['parent'], self.old_history['events'][-1]['hash'])
        self.assertEqual(event['plan']['recorded_previous'], self.a)
        self.assertFalse((self.repo / '.deploy' / r.PENDING).exists())
        archive = r.backup_path(self.repo, event['id'])
        journal = json.loads(archive.read_bytes())
        self.assertEqual(r.decode_bytes(journal['before']), self.old)
        self.assertEqual(r.parse_state(self.repo, r.decode_bytes(journal['after'])), state)
        self.assertEqual(event['confirmation']['statement'], r.expected_confirmation(self.plan))
        self.assertNotIn('owner_receipt', event)

    def test_missing_wrong_or_stale_owner_confirmation_never_collects_or_writes(self):
        for statement in [None, True, 'yes', 'DEPLOY', 'RECONCILE ' + '0' * 64]:
            with self.subTest(statement=statement), patch.object(r, 'collect_observation') as collect:
                with self.assertRaises(PermissionError):
                    r.save_reconciliation(self.repo, self.plan, statement)
                collect.assert_not_called()
        changed = copy.deepcopy(self.plan)
        changed['reason'] = 'A different reviewed plan'
        changed = r.seal({k: v for k, v in changed.items() if k != 'hash'})
        with self.assertRaises(PermissionError):
            self.save(changed, r.expected_confirmation(self.plan))
        self.assertEqual(p.metadata_bytes(self.repo), self.old)

    def test_backup_failure_or_archive_reuse_cannot_change_metadata(self):
        with patch.object(r, 'write_backup', side_effect=OSError('archive unavailable')):
            with self.assertRaises(OSError): self.save()
        self.assertEqual(p.metadata_bytes(self.repo), self.old)
        self.assertFalse((self.repo / '.deploy' / r.PENDING).exists())
        # Crash after the permanent archive, before any WAL/metadata replacement.
        with patch.object(r, 'atomic_write', side_effect=OSError('WAL not written')):
            with self.assertRaises(OSError): self.save()
        archive = r.backup_path(self.repo, self.plan['operation_id'])
        original_archive = archive.read_bytes()
        with self.assertRaises(FileExistsError): self.save()
        self.assertEqual(archive.read_bytes(), original_archive)
        self.assertEqual(p.metadata_bytes(self.repo), self.old)

    def test_recovery_requires_the_original_permanent_backup(self):
        self.interrupted(3)
        archive = r.backup_path(self.repo, self.plan['operation_id'])
        original = archive.read_bytes()
        archive.write_bytes(b'corrupt backup')
        with self.assertRaises(ValueError): r.prepare_recovery_plan(self.repo)
        archive.write_bytes(original)
        self.assertEqual(self.recover()[1:], (self.c, ''))
        self.assertEqual(archive.read_bytes(), original)

    def test_empty_or_no_drift_history_cannot_reconcile(self):
        with self.assertRaisesRegex(ValueError, 'No production drift'):
            r.prepare_plan(self.repo, self.b, 'no drift')
        other = self.root / 'empty'; other.mkdir()
        with self.assertRaisesRegex(ValueError, 'nonempty'):
            r.prepare_plan(other, self.c, 'empty')

    def test_plan_tamper_and_wrong_repo_rejected(self):
        for key, value in [('commit', self.d), ('previous', self.b), ('repo', '/other'),
                           ('manifest_sha256', '0' * 64), ('target', 'other:/path')]:
            with self.subTest(key=key):
                plan = copy.deepcopy(self.plan); plan[key] = value
                with self.assertRaises(ValueError): r.check_plan(self.repo, plan)
        plan = r.seal({**self.plan, 'previous': self.b})
        with self.assertRaises(ValueError): r.check_plan(self.repo, plan)


    def test_bypass_via_upload_or_internal_legacy_writer_rejected(self):
        with patch.object(r, 'metadata_lock'):
            confirmation = r.owner_confirmation(self.plan, r.expected_confirmation(self.plan))
            evidence = {**self.upload(self.c), 'kind': 'observation',
                        'started_at': r.now().isoformat(), 'challenge': 'test',
                        'extra_paths': [], 'protected': {}}
            del evidence['rsync_exit']
            evidence['verified_at'] = r.now().isoformat()
            result = r.candidate(self.repo, self.plan, evidence, confirmation)
        with self.assertRaises(PermissionError): p.save_history(self.repo, result, self.old)
        with self.assertRaises(PermissionError): p._persist_history(self.repo, result, self.old)
        with self.assertRaises(ValueError):
            p.transition(self.repo, *p.load_history(self.repo), self.c, evidence,
                         'reconciliation', self.plan['operation_id'])
        self.assertEqual(p.metadata_bytes(self.repo), self.old)

    def test_site_drift_and_bad_network_evidence_abort_without_wal(self):
        for field, bad in [('remote_sha256', {}), ('http_sha256', {}), ('http_status', 500),
                           ('root_sha256', '0'*64), ('http_statuses', {}),
                           ('transcript', ''), ('rsync_exit', 0)]:
            def collect(*args):
                ev = self.observation(*args); ev[field] = bad; return ev
            with self.subTest(field=field), self.assertRaises(ValueError): self.save(collector=collect)
            self.assertEqual(p.metadata_bytes(self.repo), self.old)
            self.assertFalse((self.repo / '.deploy' / r.PENDING).exists())
        self.publish_local(self.d)
        with self.assertRaises(ValueError): self.save()

    def test_stale_or_replayed_observation_rejected(self):
        for field, bad in [('challenge', 'reused'), ('started_at', '2020-01-01T00:00:00Z'),
                           ('verified_at', (r.now()+timedelta(hours=1)).isoformat())]:
            def collect(*args):
                ev = self.observation(*args); ev[field] = bad; return ev
            with self.subTest(field=field), self.assertRaises(ValueError): self.save(collector=collect)
        self.assertEqual(p.metadata_bytes(self.repo), self.old)

    def test_race_before_lock_and_during_observation_rejected(self):
        current = self.repo / '.deploy/production-current'
        current.write_text(self.c)
        with self.assertRaises(ValueError): self.save()
        current.write_bytes(self.old['production-current'])
        def changed(*args):
            evidence = self.observation(*args)
            current.write_text(self.c)
            return evidence
        with self.assertRaises(ValueError): self.save(collector=changed)
        self.assertEqual((self.repo / '.deploy/history.json').read_bytes(), self.old['history.json'])

    def test_existing_lock_blocks_operation(self):
        (self.repo / '.deploy/metadata.lock').write_text('active or stale')
        with self.assertRaises(FileExistsError): self.save()
        self.assertEqual(p.metadata_bytes(self.repo), self.old)

    def test_duplicate_plan_and_operation_not_replayed(self):
        statement = r.expected_confirmation(self.plan)
        self.save(statement=statement)
        actual = p.metadata_bytes(self.repo)
        with self.assertRaises(ValueError): self.save(statement=statement)
        self.assertEqual(p.metadata_bytes(self.repo), actual)

    def test_reconciliation_then_deploy_and_rollback_require_live_current(self):
        state = self.save()
        with self.assertRaisesRegex(ValueError, 'Missing live verification'):
            p.transition(self.repo, *state, self.d, self.upload(self.d), 'deploy', 'missing')
        before = self.upload(self.c); before['kind'] = 'observation'; del before['rsync_exit']
        deployed = p.transition(self.repo, *state, self.d, self.upload(self.d), 'deploy', 'D', live_current=before)
        self.assertEqual(deployed[1:], (self.d, self.c))
        before = self.upload(self.d); before['kind'] = 'observation'; del before['rsync_exit']
        rolled = p.transition(self.repo, *deployed, self.c, self.upload(self.c), 'rollback', 'back', live_current=before)
        self.assertEqual(rolled[1:], (self.c, self.d))
        with self.assertRaisesRegex(ValueError, 'Unconfirmed rollback'):
            p.transition(self.repo, *state, self.b, self.upload(self.b), 'rollback', 'unknown')

    def test_crash_before_history_commit_aborts_only_with_owner_recovery(self):
        self.interrupted(2)
        with self.assertRaisesRegex(ValueError, 'Pending reconciliation'): p.load_history(self.repo)
        plan = r.prepare_recovery_plan(self.repo)
        self.assertEqual(plan['action'], 'abort-uncommitted')
        self.recover(plan)
        self.assertEqual(p.metadata_bytes(self.repo), self.old)

    def test_crash_after_history_commit_repairs_mirrors_without_new_event(self):
        for fail_at in [3, 4]:
            with self.subTest(fail_at=fail_at):
                self.plan = r.prepare_plan(self.repo, self.c, 'New separately reviewed recovery scenario')
                self.interrupted(fail_at)
                plan = r.prepare_recovery_plan(self.repo)
                self.assertEqual(plan['action'], 'finish-mirrors')
                history_before = (self.repo / '.deploy/history.json').read_bytes()
                state = self.recover(plan)
                self.assertEqual(state[1:], (self.c, ''))
                self.assertEqual(len(state[0]['events']), 3)
                self.assertEqual((self.repo / '.deploy/history.json').read_bytes(), history_before)
                # Reset disposable fixture, never actual production metadata.
                for n, data in self.old.items(): (self.repo / '.deploy' / n).write_bytes(data)

    def test_recovery_requires_separate_confirmation_and_no_network(self):
        self.interrupted(3)
        plan = r.prepare_recovery_plan(self.repo)
        with patch.object(r, 'collect_observation') as collect:
            with self.assertRaises(PermissionError):
                r.recover_reconciliation(self.repo, plan, r.expected_confirmation(self.plan))
            state = self.recover(plan)
            collect.assert_not_called()
        self.assertEqual(state[1:], (self.c, ''))
        recovery_audit = json.loads(r.backup_path(self.repo, plan['operation_id']).read_bytes())
        self.assertEqual(recovery_audit['confirmation']['statement'], r.expected_confirmation(plan))
        self.assertEqual(recovery_audit['recovery_of'], self.plan['operation_id'])

    def test_recovery_refuses_tampering_or_foreign_metadata(self):
        self.interrupted(3)
        pending = self.repo / '.deploy' / r.PENDING
        original = pending.read_bytes()
        document = json.loads(original); document['operation_id'] = 'tampered'
        pending.write_text(json.dumps(document))
        with self.assertRaises(ValueError): r.prepare_recovery_plan(self.repo)
        pending.write_bytes(original)
        (self.repo / '.deploy/production-current').write_text('foreign change')
        with self.assertRaises(ValueError): r.prepare_recovery_plan(self.repo)

    def test_recovery_race_or_stale_lock_stops(self):
        self.interrupted(3)
        plan = r.prepare_recovery_plan(self.repo)
        lock = self.repo / '.deploy/metadata.lock'; lock.write_text('stale lock')
        with self.assertRaises(FileExistsError): self.recover(plan)
        lock.unlink()  # disposable test only; production requires separate permission
        (self.repo / '.deploy/production-current').write_text(self.c + '\n')
        with self.assertRaises(ValueError): self.recover(plan)

    def test_interrupted_recovery_is_resumable_with_new_approval(self):
        self.interrupted(3)
        actual = r.atomic_write
        count = 0
        def fail(path, data):
            nonlocal count
            count += 1
            if count == 2: raise OSError('recovery interrupted')
            actual(path, data)
        with patch.object(r, 'atomic_write', side_effect=fail):
            with self.assertRaises(OSError): self.recover()
        self.assertEqual(self.recover()[1:], (self.c, ''))

    def test_fsync_failure_preserves_pending_and_blocks_normal_writes(self):
        actual = r.fsync_directory
        count = 0
        def fail(path):
            nonlocal count
            if path == self.repo / '.deploy':
                count += 1
                if count == 3: raise OSError('history fsync failed')
            actual(path)
        with patch.object(r, 'fsync_directory', side_effect=fail):
            with self.assertRaises(OSError): self.save()
        with self.assertRaises(ValueError): p.load_history(self.repo)
        with self.assertRaises(ValueError): p.save_history(self.repo, (self.old_history,self.b,self.a), p.metadata_bytes(self.repo))
        self.assertEqual(self.recover()[1:], (self.c, ''))

    def test_pending_cleanup_failure_after_all_writes_is_recoverable(self):
        actual=Path.unlink; pending=self.repo/'.deploy'/r.PENDING
        def fail(path,*args,**kwargs):
            if path==pending: raise OSError('LOCAL TEST interrupted before WAL cleanup')
            return actual(path,*args,**kwargs)
        with patch.object(Path,'unlink',fail):
            with self.assertRaises(OSError): self.save()
        with self.assertRaises(ValueError): p.load_history(self.repo)
        self.assertEqual(self.recover()[1:],(self.c,''))

    def test_failed_journal_creation_never_changes_metadata(self):
        with patch.object(r,'atomic_write',side_effect=OSError('journal not written')):
            with self.assertRaises(OSError): self.save()
        self.assertEqual(p.metadata_bytes(self.repo),self.old)
        self.assertFalse((self.repo/'.deploy'/r.PENDING).exists())

    def test_script_inspect_reads_reconciled_history_in_disposable_repo(self):
        import sys
        self.save()
        script=Path(p.__file__).resolve()
        result=subprocess.run([sys.executable,str(script),'--repo',str(self.repo),'inspect'],
                              capture_output=True,text=True,check=True,
                              env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
        self.assertEqual(json.loads(result.stdout),{'current':self.c,'previous':None})

    def test_history_rehash_cannot_fabricate_previous(self):
        state = self.save()
        bad = copy.deepcopy(state[0]); event = bad['events'][-1]
        event['plan']['previous'] = self.b; event['plan'] = r.seal({k:v for k,v in event['plan'].items() if k!='hash'})
        event['confirmation']['plan_hash'] = event['plan']['hash']
        event['confirmation']['statement'] = r.expected_confirmation(event['plan'])
        bad['events'][-1] = r.seal({k:v for k,v in event.items() if k!='hash'})
        with self.assertRaises(ValueError): p.validate_history(self.repo,bad,self.c,self.b)

    def test_metadata_symlinks_rejected(self):
        path = self.repo / '.deploy/production-current'
        external = self.root / 'external'; external.write_bytes(path.read_bytes())
        path.unlink(); path.symlink_to(external)
        with self.assertRaises(ValueError): self.save()

    def test_cli_plan_check_and_explicit_apply_use_the_same_workflow(self):
        import contextlib
        import sys
        output = io.StringIO()
        with patch.object(sys,'argv',['production.py','--repo',str(self.repo),'reconciliation-plan',self.c,'--reason','audit']), \
                contextlib.redirect_stdout(output), patch.object(r,'collect_observation') as collect:
            p.main(); collect.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())['commit'],self.c)
        self.assertEqual(p.metadata_bytes(self.repo),self.old)
        plan_file = self.root / 'plan.json'
        plan_file.write_text('{"operation":"wrong","operation":"reconciliation"}')
        with patch.object(sys, 'argv', ['production.py', '--repo', str(self.repo),
                                       'reconciliation-apply', str(plan_file), '--confirm',
                                       r.expected_confirmation(self.plan)]), \
                patch.object(r, 'save_reconciliation') as apply:
            with self.assertRaisesRegex(ValueError, 'Duplicate plan JSON key'):
                p.main()
            apply.assert_not_called()
        plan_file.write_text(json.dumps(self.plan))
        # The read-only network preflight uses simulated transport, not the server.
        def unlocked_observation(repo, plan, challenge):
            evidence = self.upload(self.c)
            del evidence['rsync_exit']
            evidence.update(kind='observation', challenge=challenge,
                            started_at=r.now().isoformat(), verified_at=r.now().isoformat(),
                            extra_paths=[], protected={})
            return evidence
        with patch.object(sys, 'argv', ['production.py', '--repo', str(self.repo),
                                       'reconciliation-check', str(plan_file)]), \
                contextlib.redirect_stdout(io.StringIO()), \
                patch.object(r, 'collect_observation', side_effect=unlocked_observation):
            p.main()
        self.assertEqual(p.metadata_bytes(self.repo), self.old)
        self.assertFalse((self.repo / '.deploy/backups').exists())
        with patch.object(sys, 'argv', ['production.py', '--repo', str(self.repo),
                                       'reconciliation-apply', str(plan_file), '--confirm',
                                       r.expected_confirmation(self.plan)]), \
                contextlib.redirect_stdout(io.StringIO()), \
                patch.object(r, 'collect_observation', side_effect=self.observation):
            p.main()
        self.assertEqual(p.load_history(self.repo)[1:], (self.c, ''))

    def test_legacy_signed_event_is_readable_but_cannot_be_used_for_new_write(self):
        state = self.save()
        archived = copy.deepcopy(state[0])
        event = archived['events'][-1]
        confirmed_at = event.pop('confirmation')['confirmed_at']
        plan = event['plan']
        plan.pop('confirmation_policy')
        plan.pop('backup')
        event['plan'] = r.seal({k: v for k, v in plan.items() if k != 'hash'})
        # Synthetic historical fixture only, preserving the old reader contract.
        event['owner_receipt'] = {'signature': 'ARCHIVED LOCAL TEST FIXTURE', 'claims': {
            'purpose': 'reconciliation', 'plan_hash': event['plan']['hash'],
            'operation_id': event['id'], 'receipt_id': str(uuid.uuid4()),
            'issued_at': confirmed_at,
            'expires_at': (r.timestamp(confirmed_at) + timedelta(minutes=5)).isoformat()}}
        archived['events'][-1] = r.seal({k: v for k, v in event.items() if k != 'hash'})
        original = copy.deepcopy(archived)
        p.validate_history(self.repo, archived, self.c, '')
        self.assertEqual(archived, original)
        with self.assertRaises(ValueError):
            r.save_reconciliation(self.repo, event['plan'], r.expected_confirmation(event['plan']))

    def test_http_redirect_policy_blocks_all_redirects(self):
        with self.assertRaises(ValueError): r.NoRedirect().redirect_request(None,None,302,'',{},'https://other.invalid')


    def test_changed_metadata_between_approval_and_lock_is_rejected(self):
        actual = r.require_owner_confirmation
        def mutate(plan,receipt):
            actual(plan,receipt)
            (self.repo/'.deploy/production-previous').write_text(self.c)
        with patch.object(r,'require_owner_confirmation',side_effect=mutate):
            with self.assertRaises(ValueError): self.save()
        self.assertEqual((self.repo/'.deploy/history.json').read_bytes(),self.old['history.json'])

    def test_full_collector_observes_actual_local_bytes_with_mocked_transports(self):
        snapshot=p.commit_manifest(self.repo,self.c)
        manifest = self.plan['manifest']
        hashes = {n:p.digest((self.site/n).read_bytes()) for n in manifest}
        remote = {'hashes':hashes,'extra_paths':['CV.pdf'],'protected':{}}
        def ssh(command, **kwargs):
            self.assertEqual(command[0],'/usr/bin/ssh')
            self.assertIn('StrictHostKeyChecking=yes',command)
            self.assertEqual(json.loads(kwargs['input']),list(manifest))
            return subprocess.CompletedProcess(command,0,json.dumps(remote),'')
        class Response(io.BytesIO):
            status = 200
            headers = {}
        class Opener:
            def open(inner, request, timeout):
                self.assertTrue(request.full_url.startswith(p.URL))
                name = request.full_url[len(p.URL):] or 'index.html'
                return Response((self.site/name).read_bytes())
        with patch.object(p,'commit_manifest',return_value=snapshot), \
                patch.object(r.subprocess,'run',side_effect=ssh) as transport, \
                patch.object(r,'build_opener',return_value=Opener()):
            started=r.now(); ev=r.collect_observation(self.repo,self.plan,'new challenge')
        r.check_observation(self.plan,ev,'new challenge',started)
        self.assertEqual(transport.call_count,2)
        log=json.loads(ev['transcript'])
        self.assertEqual(len(log['http']),len(manifest)+1)
        self.assertEqual(ev['remote_sha256'],hashes)
        self.assertEqual(ev['http_sha256'],hashes)

    def test_collector_ssh_failure_does_not_make_http_requests(self):
        snapshot=p.commit_manifest(self.repo,self.c)
        with patch.object(p,'commit_manifest',return_value=snapshot), \
                patch.object(r.subprocess,'run',return_value=subprocess.CompletedProcess([],1,'','SSH failure')), \
                patch.object(r,'build_opener') as http:
            with self.assertRaises(ValueError): r.collect_observation(self.repo,self.plan,'challenge')
            http.assert_not_called()

    def test_remote_reader_computes_hashes_and_rejects_managed_symlinks_locally(self):
        import sys
        source=r.REMOTE_READER.replace("'/home/l/linebaru/dopler/public_html'",repr(str(self.site)))
        def read():
            return subprocess.run([sys.executable,'-c',source],input=json.dumps(list(self.plan['manifest'])),
                                  text=True,capture_output=True)
        result=read(); self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['hashes'],self.plan['manifest'])
        (self.site/'style.css').unlink()
        (self.site/'style.css').symlink_to(self.repo/'style.css')
        result=read(); self.assertNotEqual(result.returncode,0)
        self.assertIn('Managed symlink',result.stderr)

    def test_network_collector_rejects_change_between_ssh_observations(self):
        snapshot=p.commit_manifest(self.repo,self.c)
        good={'hashes':self.plan['manifest'],'extra_paths':[],'protected':{}}
        changed=copy.deepcopy(good); changed['extra_paths']=['new-file']
        replies=[subprocess.CompletedProcess([],0,json.dumps(state),'') for state in (good,changed)]
        class Response(io.BytesIO):
            status=200
            headers={}
        class Opener:
            def open(inner,request,timeout):
                return Response((self.site/(request.full_url[len(p.URL):] or 'index.html')).read_bytes())
        with patch.object(p,'commit_manifest',return_value=snapshot), \
                patch.object(r.subprocess,'run',side_effect=replies),patch.object(r,'build_opener',return_value=Opener()):
            with self.assertRaisesRegex(ValueError,'changed during observation'):
                r.collect_observation(self.repo,self.plan,'challenge')


if __name__ == '__main__':
    unittest.main()
