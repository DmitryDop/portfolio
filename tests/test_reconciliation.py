"""Disposable Git repos, local content, synthetic network and test-only owner key.

No production server, actual metadata or installed trust store is used.
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
from unittest.mock import patch, Mock

from scripts import production as p
from scripts import reconciliation as r


class ReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.keys_temp = tempfile.TemporaryDirectory()
        cls.keys = Path(cls.keys_temp.name)
        cls.key = cls.keys / 'test-owner'
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(cls.key)], check=True)
        cls.signers = cls.keys / 'allowed_signers'
        cls.signers.write_text(r.OWNER + ' ' + cls.key.with_suffix('.pub').read_text())

    @classmethod
    def tearDownClass(cls):
        cls.keys_temp.cleanup()

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

    def receipt(self, plan):
        claims = {'purpose': plan['operation'], 'plan_hash': plan['hash'],
                  'operation_id': plan['operation_id'], 'receipt_id': str(uuid.uuid4()),
                  'issued_at': (r.now() - timedelta(seconds=2)).isoformat(),
                  'expires_at': (r.now() + timedelta(minutes=5)).isoformat()}
        return self.sign_claims(claims)

    def sign_claims(self, claims):
        file = self.root / ('claims-' + str(uuid.uuid4()))
        file.write_bytes(p.canonical(claims))
        subprocess.run(['ssh-keygen', '-Y', 'sign', '-f', str(self.key),
                        '-n', r.NAMESPACE + claims['purpose'], str(file)],
                       check=True, capture_output=True)
        return {'claims': claims, 'signature': Path(str(file) + '.sig').read_text()}

    def save(self, plan=None, receipt=None, collector=None):
        plan = plan or self.plan
        with patch.object(r, 'trusted_signers', return_value=self.signers), \
                patch.object(r, 'collect_observation', side_effect=collector or self.observation):
            return r.save_reconciliation(self.repo, plan, receipt or self.receipt(plan))

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
        with patch.object(r, 'trusted_signers', return_value=self.signers):
            return r.recover_reconciliation(self.repo, plan, self.receipt(plan))

    def test_plan_is_read_only_and_binds_metadata_manifest_repo(self):
        r.check_plan(self.repo, self.plan)
        self.assertEqual(self.plan['manifest_sha256'], p.digest(p.canonical(self.plan['manifest'])))
        self.assertEqual(self.plan['metadata_sha256'], r.fingerprints(self.old))
        self.assertEqual(p.metadata_bytes(self.repo), self.old)
        self.assertEqual(self.plan['previous'], '')
        self.assertEqual(self.plan['recorded_previous'], self.a)

    def test_owner_signature_success_and_history_immutable(self):
        state = self.save()
        self.assertEqual(state[1:], (self.c, ''))
        self.assertEqual(state[0]['events'][:-1], self.old_history['events'])
        event = state[0]['events'][-1]
        self.assertEqual(event['operation'], 'reconciliation')
        self.assertNotIn('rsync_exit', event['evidence'])
        self.assertEqual(event['parent'], self.old_history['events'][-1]['hash'])
        self.assertEqual(event['plan']['recorded_previous'], self.a)
        self.assertFalse((self.repo / '.deploy' / r.PENDING).exists())

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

    def test_trust_store_missing_or_user_controlled_is_rejected(self):
        receipt = self.receipt(self.plan)
        for path in (self.root / 'missing', self.signers):
            with patch.object(r, 'SIGNERS', path), patch.object(r, 'collect_observation') as collect:
                with self.assertRaises(PermissionError): r.save_reconciliation(self.repo, self.plan, receipt)
                collect.assert_not_called()
        self.assertEqual(p.metadata_bytes(self.repo), self.old)

    def test_forged_signature_and_boolean_flag_rejected(self):
        receipt = self.receipt(self.plan); receipt['signature'] = 'approved=true'
        with patch.dict(os.environ, {'RECONCILIATION_APPROVED': 'true', 'DEPLOY': '1'}):
            with self.assertRaises(PermissionError): self.save(receipt=receipt)
        self.assertEqual(p.metadata_bytes(self.repo), self.old)

    def test_owner_receipt_wrong_plan_purpose_future_expired_rejected(self):
        for field, value in [('plan_hash', '0' * 64), ('purpose', 'reconciliation-recovery'),
                             ('operation_id', str(uuid.uuid4())),
                             ('issued_at', (r.now() + timedelta(minutes=1)).isoformat()),
                             ('expires_at', (r.now() - timedelta(seconds=1)).isoformat())]:
            with self.subTest(field=field):
                claims = self.receipt(self.plan)['claims']; claims[field] = value
                with self.assertRaises(PermissionError): self.save(receipt=self.sign_claims(claims))
        self.assertEqual(p.metadata_bytes(self.repo), self.old)

    def test_modified_claims_without_resigning_rejected(self):
        receipt = self.receipt(self.plan)
        receipt['claims']['receipt_id'] = str(uuid.uuid4())
        with self.assertRaises(PermissionError): self.save(receipt=receipt)

    def test_bypass_via_upload_or_internal_legacy_writer_rejected(self):
        with patch.object(r, 'metadata_lock'):
            evidence = {**self.upload(self.c), 'kind': 'observation',
                        'started_at': r.now().isoformat(), 'challenge': 'test',
                        'extra_paths': [], 'protected': {}}
            del evidence['rsync_exit']
            evidence['verified_at'] = r.now().isoformat()
            result = r.candidate(self.repo, self.plan, evidence, self.receipt(self.plan))
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
        receipt = self.receipt(self.plan); self.save(receipt=receipt)
        actual = p.metadata_bytes(self.repo)
        with self.assertRaises(ValueError): self.save(receipt=receipt)
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

    def test_recovery_requires_separate_signed_plan_and_no_network(self):
        self.interrupted(3)
        plan = r.prepare_recovery_plan(self.repo)
        with patch.object(r, 'trusted_signers', return_value=self.signers), patch.object(r, 'collect_observation') as collect:
            with self.assertRaises(PermissionError):
                r.recover_reconciliation(self.repo, plan, self.receipt(self.plan))
            state = r.recover_reconciliation(self.repo, plan, self.receipt(plan))
            collect.assert_not_called()
        self.assertEqual(state[1:], (self.c, ''))

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
            count += 1
            if count == 2: raise OSError('fsync failed')
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
        event['owner_receipt']['claims']['plan_hash'] = event['plan']['hash']
        bad['events'][-1] = r.seal({k:v for k,v in event.items() if k!='hash'})
        with self.assertRaises(ValueError): p.validate_history(self.repo,bad,self.c,self.b)

    def test_metadata_symlinks_rejected(self):
        path = self.repo / '.deploy/production-current'
        external = self.root / 'external'; external.write_bytes(path.read_bytes())
        path.unlink(); path.symlink_to(external)
        with self.assertRaises(ValueError): self.save()

    def test_cli_plan_is_local_read_only(self):
        import contextlib
        import sys
        output = io.StringIO()
        with patch.object(sys,'argv',['production.py','--repo',str(self.repo),'reconciliation-plan',self.c,'--reason','audit']), \
                contextlib.redirect_stdout(output), patch.object(r,'collect_observation') as collect:
            p.main(); collect.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())['commit'],self.c)
        self.assertEqual(p.metadata_bytes(self.repo),self.old)

    def test_http_redirect_policy_blocks_all_redirects(self):
        with self.assertRaises(ValueError): r.NoRedirect().redirect_request(None,None,302,'',{},'https://other.invalid')

    def test_reused_receipt_id_rejected_even_with_new_valid_owner_signature(self):
        state = self.save()
        plan = r.prepare_plan(self.repo, self.d, 'second unrelated drift')
        receipt = self.receipt(plan)
        receipt['claims']['receipt_id'] = state[0]['events'][-1]['owner_receipt']['claims']['receipt_id']
        receipt = self.sign_claims(receipt['claims'])
        self.publish_local(self.d)
        with self.assertRaisesRegex(ValueError, 'receipt replay'): self.save(plan, receipt)

    def test_expiry_during_observation_stops_before_journal(self):
        actual = r.require_owner_confirmation
        calls = 0
        def expire(plan, receipt):
            nonlocal calls
            calls += 1
            if calls == 2: raise PermissionError('receipt expired during observation')
            actual(plan, receipt)
        with patch.object(r,'require_owner_confirmation',side_effect=expire):
            with self.assertRaises(PermissionError): self.save()
        self.assertEqual(p.metadata_bytes(self.repo),self.old)
        self.assertFalse((self.repo/'.deploy'/r.PENDING).exists())

    def test_expiry_during_candidate_validation_stops_before_journal(self):
        actual=r.require_owner_confirmation
        calls=0
        def expire(plan,receipt):
            nonlocal calls
            calls+=1
            if calls==3: raise PermissionError('expired immediately before WAL commit')
            actual(plan,receipt)
        with patch.object(r,'require_owner_confirmation',side_effect=expire):
            with self.assertRaises(PermissionError): self.save()
        self.assertEqual(p.metadata_bytes(self.repo),self.old)
        self.assertFalse((self.repo/'.deploy'/r.PENDING).exists())

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

    def test_recovery_rechecks_original_signature_not_just_journal_hash(self):
        self.interrupted(3)
        pending=self.repo/'.deploy'/r.PENDING
        journal=json.loads(pending.read_bytes())
        after=r.decode_bytes(journal['after']); history=json.loads(after['history.json'])
        event=history['events'][-1]; event['owner_receipt']['signature']='FORGED'
        history['events'][-1]=r.seal({k:v for k,v in event.items() if k!='hash'})
        after['history.json']=p.canonical(history)+b'\n'
        journal['after']=r.encode_bytes(after)
        journal=r.seal({k:v for k,v in journal.items() if k!='hash'})
        pending.write_bytes(p.canonical(journal)+b'\n')
        (self.repo/'.deploy/history.json').write_bytes(after['history.json'])
        plan=r.prepare_recovery_plan(self.repo)
        with self.assertRaises(PermissionError): self.recover(plan)
        self.assertTrue(pending.exists())


if __name__ == '__main__':
    unittest.main()
