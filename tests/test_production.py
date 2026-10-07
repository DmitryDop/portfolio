import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import production as p


class ProductionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Local test')
        self.git('config', 'user.email', 'local-test@example.invalid')
        (self.repo / 'index.html').write_text('<link href="style.css"><p>A</p>')
        (self.repo / 'style.css').write_text('body { color: red; }')
        (self.repo / 'AGENTS.md').write_text('never upload')
        self.a = self.commit('A')
        (self.repo / 'index.html').write_text('<link href="style.css"><p>B</p>')
        self.b = self.commit('B')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], stderr=subprocess.STDOUT)

    def commit(self, message):
        self.git('add', '.')
        self.git('commit', '-qm', message)
        return self.git('rev-parse', 'HEAD').decode().strip()

    def evidence(self, sha):
        _, manifest = p.commit_manifest(self.repo, sha)
        return {'verified_at': '2026-10-08T12:00:00Z', 'target': p.REMOTE,
                'url': p.URL, 'rsync_exit': 0, 'http_status': 200,
                'remote_sha256': manifest.copy(), 'http_sha256': manifest.copy(),
                'root_sha256': manifest['index.html'],
                'http_statuses': {name: 200 for name in manifest},
                'transcript': 'Synthetic evidence for local tests only; no upload performed'}

    def deploy(self, state, sha, identifier):
        history, current, previous = state
        return p.transition(self.repo, history, current, previous, sha,
                            self.evidence(sha), 'deploy', identifier)

    def first(self):
        return self.deploy((p.empty_history(), '', ''), self.a, 'first')

    def observation(self, sha):
        evidence = self.evidence(sha)
        del evidence['rsync_exit']
        evidence['kind'] = 'observation'
        return evidence

    def baseline(self):
        return p.baseline_candidate(self.repo, p.prepare_baseline_plan(self.repo, self.a),
                                    self.observation(self.a), 'baseline-A')

    def test_baseline_plan_read_only_and_pinned(self):
        before = p.metadata_bytes(self.repo)
        plan = p.prepare_baseline_plan(self.repo, self.a)
        self.assertEqual(plan['commit'], self.a)
        self.assertEqual(self.git('rev-parse', 'HEAD').decode().strip(), self.b)
        self.assertEqual(plan['manifest'], p.commit_manifest(self.repo, self.a)[1])
        self.assertEqual(p.metadata_bytes(self.repo), before)
        self.assertFalse((self.repo / '.deploy').exists())

    def test_baseline_observation_is_not_historical_deploy(self):
        history, current, previous = self.baseline()
        self.assertEqual((current, previous), (self.a, ''))
        event = history['events'][0]
        self.assertEqual(event['operation'], 'baseline')
        self.assertNotIn('rsync_exit', event['evidence'])
        self.assertEqual(event['evidence']['kind'], 'observation')

    def test_baseline_only_empty_history_and_metadata(self):
        history, current, previous = self.first()
        with self.assertRaises(ValueError):
            p.transition(self.repo, history, current, previous, self.a,
                         self.observation(self.a), 'baseline', 'not-first')
        base = self.repo / '.deploy'; base.mkdir()
        (base / 'production-current').write_text(self.a)
        with self.assertRaises(ValueError):
            p.prepare_baseline_plan(self.repo, self.a)

    def test_baseline_rejected_by_validator_after_existing_event(self):
        history, current, previous = self.first()
        duplicate = copy.deepcopy(self.baseline()[0]['events'][0])
        duplicate['before'] = current
        duplicate['parent'] = history['events'][-1]['hash']
        duplicate['hash'] = p.digest(p.canonical({k: v for k, v in duplicate.items() if k != 'hash'}))
        history['events'].append(duplicate)
        with self.assertRaisesRegex(ValueError, 'Baseline requires empty'):
            p.validate_history(self.repo, history, current, previous)

    def test_baseline_refuses_upload_evidence_and_upload_refuses_observation(self):
        with self.assertRaises(ValueError):
            p.transition(self.repo, p.empty_history(), '', '', self.a,
                         self.evidence(self.a), 'baseline', 'bad')
        with self.assertRaises(ValueError):
            p.transition(self.repo, p.empty_history(), '', '', self.a,
                         self.observation(self.a), 'deploy', 'bad')

    def test_baseline_rejects_failed_files_and_http(self):
        plan = p.prepare_baseline_plan(self.repo, self.a)
        for field, value in [('remote_sha256', {}), ('http_sha256', {}),
                             ('http_status', 500), ('http_statuses', {}),
                             ('root_sha256', '0' * 64)]:
            evidence = self.observation(self.a); evidence[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                p.baseline_candidate(self.repo, plan, evidence, 'bad')
        self.assertFalse((self.repo / '.deploy').exists())

    def test_baseline_changed_metadata_blocks_candidate(self):
        plan = p.prepare_baseline_plan(self.repo, self.a)
        base = self.repo / '.deploy'; base.mkdir()
        (base / 'production-previous').write_text(self.b)
        with self.assertRaisesRegex(ValueError, 'Metadata changed'):
            p.baseline_candidate(self.repo, plan, self.observation(self.a), 'bad')

    def test_baseline_tampered_plan_sha_or_manifest_rejected(self):
        for field, value in [('commit', self.b), ('manifest', {})]:
            plan = p.prepare_baseline_plan(self.repo, self.a); plan[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                p.check_baseline_plan(self.repo, plan)

    def test_baseline_rehashed_wrong_manifest_rejected(self):
        plan = p.prepare_baseline_plan(self.repo, self.a)
        plan['manifest']['index.html'] = '0' * 64
        plan['hash'] = p.digest(p.canonical({k: v for k, v in plan.items() if k != 'hash'}))
        with self.assertRaisesRegex(ValueError, 'manifest differs'):
            p.check_baseline_plan(self.repo, plan)

    def test_baseline_no_confirmation_means_no_write_or_live_call(self):
        from unittest.mock import Mock, patch
        import os
        plan = p.prepare_baseline_plan(self.repo, self.a)
        verifier = Mock()
        # Strings supplied by the agent cannot enable the unavailable owner channel.
        with patch.dict(os.environ, {'DEPLOY': '1', 'BASELINE_APPROVED': plan['hash']}):
            with self.assertRaisesRegex(PermissionError, 'trusted owner confirmation unavailable'):
                p.save_baseline(self.repo, plan, verifier, 'no-consent')
        verifier.assert_not_called()
        with self.assertRaises(PermissionError):
            p.save_history(self.repo, self.baseline(), p.metadata_bytes(self.repo))
        self.assertFalse((self.repo / '.deploy').exists())

    def test_baseline_requires_fresh_live_current_before_deploy(self):
        state = self.baseline()
        with self.assertRaisesRegex(ValueError, 'Missing live verification'):
            self.deploy(state, self.b, 'missing-before')
        wrong = self.observation(self.b)
        with self.assertRaises(ValueError):
            p.transition(self.repo, *state, self.b, self.evidence(self.b),
                         'deploy', 'wrong-current', live_current=wrong)
        next_state = p.transition(self.repo, *state, self.b, self.evidence(self.b),
                                  'deploy', 'B', live_current=self.observation(self.a))
        self.assertEqual(next_state[1:], (self.b, self.a))

    def test_baseline_repeat_same_version_has_no_false_previous(self):
        state = self.baseline()
        repeated = p.transition(self.repo, *state, self.a, self.evidence(self.a),
                                'deploy', 'repeat', live_current=self.observation(self.a))
        self.assertEqual(repeated[1:], (self.a, ''))

    def test_baseline_without_previous_cannot_rollback(self):
        with self.assertRaisesRegex(ValueError, 'Unconfirmed rollback target'):
            p.transition(self.repo, *self.baseline(), self.b, self.evidence(self.b),
                         'rollback', 'bad')

    def test_baseline_reverification_inside_lock_before_storage(self):
        plan = p.prepare_baseline_plan(self.repo, self.a)
        first = self.baseline()
        calls = []
        def fresh():
            self.assertTrue((self.repo / '.deploy/metadata.lock').exists())
            calls.append('fresh observation')
            return p.baseline_candidate(self.repo, plan, self.observation(self.a), 'fresh')
        # Internal persistence is tested ONLY in this disposable repo, without
        # fabricating owner consent or invoking the disabled public adoption API.
        p._persist_history(self.repo, None, p.metadata_bytes(self.repo), baseline_refresh=fresh)
        self.assertEqual(calls, ['fresh observation'])
        self.assertEqual(p.load_history(self.repo)[0]['events'][0]['id'], 'fresh')
        self.assertNotEqual(first[0]['events'][0]['id'], 'fresh')

    def test_baseline_repeat_verification_failure_keeps_history_empty(self):
        plan = p.prepare_baseline_plan(self.repo, self.a)
        p.baseline_candidate(self.repo, plan, self.observation(self.a), 'initial-check')
        original = p.metadata_bytes(self.repo)
        def no_longer_matches():
            evidence = self.observation(self.a)
            evidence['remote_sha256']['index.html'] = '0' * 64
            return p.baseline_candidate(self.repo, plan, evidence, 'repeat-check')
        with self.assertRaises(ValueError):
            p._persist_history(self.repo, None, original, baseline_refresh=no_longer_matches)
        self.assertEqual(p.metadata_bytes(self.repo), original)

    def test_baseline_cli_plan_never_launches_rsync_or_writes(self):
        import contextlib
        import io
        import sys
        from unittest.mock import patch
        original = p.metadata_bytes(self.repo)
        output = io.StringIO()
        with patch.object(sys, 'argv', ['production.py', '--repo', str(self.repo),
                                       'baseline-plan', self.a]), contextlib.redirect_stdout(output):
            p.main()
        plan = json.loads(output.getvalue())
        self.assertEqual(plan['operation'], 'baseline')
        self.assertEqual(plan['commit'], self.a)
        self.assertEqual(p.metadata_bytes(self.repo), original)
        self.assertFalse((self.repo / '.deploy').exists())

    def test_baseline_metadata_mutation_during_verification_rejected(self):
        original = p.metadata_bytes(self.repo)
        def changed():
            result = self.baseline()
            (self.repo / '.deploy/production-current').write_text(self.b)
            return result
        with self.assertRaisesRegex(ValueError, 'changed during live'):
            p._persist_history(self.repo, None, original, baseline_refresh=changed)
        self.assertFalse((self.repo / '.deploy/history.json').exists())

    def test_baseline_integration_local_content_and_persistence(self):
        production = self.root / 'local-production'; production.mkdir()
        def publish_local(sha):
            files, manifest = p.commit_manifest(self.repo, sha)
            for name, data in files.items():
                path = production / name; path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            return manifest
        def read_observation(sha):
            manifest = p.commit_manifest(self.repo, sha)[1]
            actual = {name: p.digest((production / name).read_bytes()) for name in manifest}
            result = self.observation(sha)
            result['remote_sha256'] = actual
            result['http_sha256'] = actual.copy()  # explicitly simulated local HTTP bodies
            result['root_sha256'] = actual['index.html']
            result['transcript'] = 'LOCAL INTEGRATION: filesystem observations; HTTP simulation; no owner consent'
            return result
        publish_local(self.a)  # existing content, not a historical deployment claim
        plan = p.prepare_baseline_plan(self.repo, self.a)
        old = p.metadata_bytes(self.repo)
        p._persist_history(self.repo, None, old, baseline_refresh=lambda:
            p.baseline_candidate(self.repo, plan, read_observation(self.a), 'observed-A'))
        self.assertEqual(p.load_history(self.repo)[1:], (self.a, ''))
        for operation, sha, expected in [('deploy', self.b, (self.b, self.a)),
                                         ('rollback', self.a, (self.a, self.b))]:
            state = p.load_history(self.repo)
            prior = read_observation(state[1])
            old = p.metadata_bytes(self.repo)
            release_dir = self.root / operation
            release = p.prepare(self.repo, sha, release_dir)
            self.assertEqual(release['commit'], sha)
            p.check_snapshot(release_dir, release)
            command = p.rsync_preview(release_dir)
            command[1] = '-rvzc'; command[-1] = str(production) + '/'
            uploaded = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(uploaded.returncode, 0, uploaded.stderr)
            after = read_observation(sha)
            after['kind'] = 'upload'; after['rsync_exit'] = uploaded.returncode
            after['transcript'] += '\n' + uploaded.stdout
            result = p.transition(self.repo, *state, sha, after, operation,
                                  operation, live_current=prior)
            p.save_history(self.repo, result, old)
            self.assertEqual(p.load_history(self.repo)[1:], expected)
            self.assertEqual(result[0]['events'][-1]['manifest'], release['manifest'])
            files, _ = p.commit_manifest(self.repo, sha)
            for name, data in files.items():
                self.assertEqual((production / name).read_bytes(), data)
        events = json.loads((self.repo / '.deploy/history.json').read_text())['events']
        self.assertEqual([event['operation'] for event in events], ['baseline', 'deploy', 'rollback'])

    def test_first_deploy(self):
        history, current, previous = self.first()
        self.assertEqual((current, previous), (self.a, ''))
        self.assertEqual(len(history['events']), 1)

    def test_repeat_first_version_no_previous(self):
        history, current, previous = self.deploy(self.first(), self.a, 'repeat')
        self.assertEqual((current, previous), (self.a, ''))
        self.assertEqual(len(history['events']), 2)

    def test_two_versions_and_repeat(self):
        state = self.deploy(self.first(), self.b, 'second')
        self.assertEqual(state[1:], (self.b, self.a))
        self.assertEqual(self.deploy(state, self.b, 'repeat')[1:], (self.b, self.a))

    def test_rollback_confirmed_target(self):
        history, current, previous = self.deploy(self.first(), self.b, 'second')
        result = p.transition(self.repo, history, current, previous, self.a,
                              self.evidence(self.a), 'rollback', 'rollback')
        self.assertEqual(result[1:], (self.a, self.b))

    def test_rollback_before_previous_rejected(self):
        history, current, previous = self.first()
        with self.assertRaises(ValueError):
            p.transition(self.repo, history, current, previous, self.b,
                         self.evidence(self.b), 'rollback', 'bad')

    def test_sha_without_evidence_rejected(self):
        with self.assertRaises(ValueError):
            p.validate_history(self.repo, p.empty_history(), self.a, '')

    def test_missing_metadata_is_unknown(self):
        self.assertEqual(p.load_history(self.repo)[1:], ('', ''))

    def test_empty_metadata_is_unknown(self):
        base = self.repo / '.deploy'
        base.mkdir()
        (base / 'production-current').write_text('')
        (base / 'production-previous').write_text('')
        self.assertEqual(p.load_history(self.repo)[1:], ('', ''))

    def test_history_and_mirrors_reload(self):
        history, current, previous = self.deploy(self.first(), self.b, 'second')
        base = self.repo / '.deploy'
        base.mkdir()
        (base / 'history.json').write_text(json.dumps(history))
        (base / 'production-current').write_text(current + '\n')
        (base / 'production-previous').write_text(previous + '\n')
        self.assertEqual(p.load_history(self.repo), (history, current, previous))
        (base / 'production-previous').write_text(current)
        with self.assertRaises(ValueError):
            p.load_history(self.repo)

    def test_failed_verification_never_changes_state(self):
        history, current, previous = self.first()
        saved = copy.deepcopy(history)
        for field, value in [('rsync_exit', 1), ('http_status', 500),
                             ('remote_sha256', {}), ('http_sha256', {}),
                             ('root_sha256', '0' * 64), ('http_statuses', {}),
                             ('transcript', '')]:
            with self.subTest(field=field):
                evidence = self.evidence(self.b)
                evidence[field] = value
                with self.assertRaises(ValueError):
                    p.transition(self.repo, history, current, previous, self.b,
                                 evidence, 'deploy', 'failed')
                self.assertEqual(history, saved)

    def test_history_tampering_rejected(self):
        history, current, previous = self.first()
        history['events'][0]['evidence']['http_status'] = 500
        with self.assertRaises(ValueError):
            p.validate_history(self.repo, history, current, previous)

    def test_invalid_manifest_even_with_rehashed_event(self):
        history, current, previous = self.first()
        event = history['events'][0]
        event['manifest']['index.html'] = '0' * 64
        event['hash'] = p.digest(p.canonical({k: v for k, v in event.items() if k != 'hash'}))
        with self.assertRaises(ValueError):
            p.validate_history(self.repo, history, current, previous)

    def test_duplicate_operation_rejected(self):
        with self.assertRaises(ValueError):
            self.deploy(self.first(), self.b, 'first')

    def test_commit_missing_rejected(self):
        with self.assertRaises(subprocess.CalledProcessError):
            p.commit_manifest(self.repo, '0' * 40)

    def test_snapshot_uses_pinned_commit_not_worktree_or_head(self):
        (self.repo / 'index.html').write_text('working changes must not upload')
        (self.repo / 'assets').mkdir()
        (self.repo / 'assets' / 'untracked.txt').write_text('private')
        destination = self.root / 'release'
        release = p.prepare(self.repo, self.a, destination)
        self.assertEqual(release['commit'], self.a)
        self.assertIn('<p>A</p>', (destination / 'payload/index.html').read_text())
        self.assertFalse((destination / 'payload/AGENTS.md').exists())
        self.assertFalse((destination / 'payload/assets/untracked.txt').exists())
        p.check_snapshot(destination, release)

    def test_same_size_and_mtime_content_change_detected(self):
        import os
        destination = self.root / 'release'
        release = p.prepare(self.repo, self.a, destination)
        path = destination / 'payload/index.html'
        original = path.stat()
        path.chmod(0o644)
        path.write_bytes(path.read_bytes().replace(b'<p>A', b'<p>Z'))
        os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
        self.assertEqual(path.stat().st_size, original.st_size)
        self.assertEqual(path.stat().st_mtime_ns, original.st_mtime_ns)
        with self.assertRaises(ValueError):
            p.check_snapshot(destination, release)

    def test_missing_font_blocks_prepare_without_creating_release(self):
        (self.repo / 'style.css').write_text("@font-face {src:url('fonts/PPNeueMontreal-Regular.woff2')}")
        sha = self.commit('missing font')
        destination = self.root / 'release'
        with self.assertRaisesRegex(ValueError, 'PPNeueMontreal'):
            p.prepare(self.repo, sha, destination)
        self.assertFalse(destination.exists())

    def test_css_url_inside_comment_passes(self):
        files = {'style.css': b'''/* Old font example:
            @font-face { src: url('fonts/missing.woff2'); }
        */ body { color: red; }'''}
        self.assertEqual(p.missing_references(files), [])

    def test_css_active_missing_url_fails(self):
        files = {'style.css': b"@font-face {src: url('fonts/missing.woff2')}"}
        self.assertEqual(p.missing_references(files), [('style.css', 'fonts/missing.woff2')])

    def test_css_active_existing_url_passes(self):
        files = {'style.css': b"@font-face {src: url('fonts/existing.woff2')}",
                 'fonts/existing.woff2': b'local test font'}
        self.assertEqual(p.missing_references(files), [])

    def test_css_comments_and_active_urls_checked_together(self):
        files = {'style.css': b'''/* url('ignored-before.png') */
            @font-face {src: url(/* note */ 'fonts/existing.woff2')}
            /* @font-face {src: url('ignored-font.woff2')} */
            body {background: url('assets/missing.png')}
            /* url('ignored-after.png') */''',
                 'fonts/existing.woff2': b'local test font'}
        self.assertEqual(p.missing_references(files), [('style.css', 'assets/missing.png')])

    def test_symlink_rejected(self):
        (self.repo / 'assets').mkdir()
        (self.repo / 'assets/link').symlink_to('../AGENTS.md')
        sha = self.commit('symlink')
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            p.commit_manifest(self.repo, sha)

    def test_preview_is_checksum_dry_run_and_protected(self):
        command = p.rsync_preview(self.root / 'release')
        self.assertIn('-rvzcn', command)
        self.assertEqual(command[-1], p.REMOTE)
        self.assertTrue(command[-2].endswith('/payload/'))
        self.assertIn('--exclude=.deploy/', command)
        self.assertIn('--exclude=.htaccess', command)
        self.assertNotIn('--delete', command)
        self.assertNotIn('-a', command)

    def test_persist_first_repeat_two_versions_and_rollback(self):
        state = (p.empty_history(), '', '')
        for sha, identifier in [(self.a, 'first'), (self.a, 'repeat'), (self.b, 'second')]:
            original = p.metadata_bytes(self.repo)
            state = self.deploy(state, sha, identifier)
            p.save_history(self.repo, state, original)
            self.assertEqual(p.load_history(self.repo), state)
        self.assertEqual(state[1:], (self.b, self.a))
        original = p.metadata_bytes(self.repo)
        state = p.transition(self.repo, *state, self.a, self.evidence(self.a), 'rollback', 'back')
        p.save_history(self.repo, state, original)
        self.assertEqual(p.load_history(self.repo)[1:], (self.a, self.b))

    def test_changed_metadata_cannot_be_overwritten(self):
        original = p.metadata_bytes(self.repo)
        base = self.repo / '.deploy'
        base.mkdir()
        (base / 'production-current').write_text(self.b)
        with self.assertRaisesRegex(ValueError, 'changed'):
            p.save_history(self.repo, self.first(), original)
        self.assertEqual((base / 'production-current').read_text(), self.b)

    def test_existing_lock_blocks_metadata_write(self):
        base = self.repo / '.deploy'
        base.mkdir()
        (base / 'metadata.lock').write_text('another operation')
        with self.assertRaises(FileExistsError):
            p.save_history(self.repo, self.first(), p.metadata_bytes(self.repo))
        self.assertFalse((base / 'history.json').exists())

    def test_interrupted_write_is_detected_and_not_replayed(self):
        from unittest.mock import patch
        original = p.metadata_bytes(self.repo)
        real_replace = p.os.replace
        calls = []
        def interrupt(source, destination):
            calls.append(str(destination))
            if len(calls) == 2:
                raise OSError('simulated crash between history and mirrors')
            real_replace(source, destination)
        with patch.object(p.os, 'replace', side_effect=interrupt):
            with self.assertRaises(OSError):
                p.save_history(self.repo, self.first(), original)
        with self.assertRaises(ValueError):
            p.load_history(self.repo)
        with self.assertRaises(ValueError):
            p.save_history(self.repo, self.first(), original)

    def test_saved_history_cannot_be_rewritten(self):
        p.save_history(self.repo, self.first(), p.metadata_bytes(self.repo))
        with self.assertRaisesRegex(ValueError, 'append'):
            p.save_history(self.repo, self.first(), p.metadata_bytes(self.repo))

    def test_local_rsync_preview_detects_equal_size_equal_mtime_change(self):
        import os
        import shutil
        if not shutil.which('rsync'):
            self.skipTest('rsync is unavailable')
        source, target = self.root / 'source', self.root / 'target'
        source.mkdir()
        target.mkdir()
        (source / 'index.html').write_bytes(b'AAAA')
        (target / 'index.html').write_bytes(b'BBBB')
        for folder in (source, target):
            os.utime(folder / 'index.html', ns=(1000000000, 1000000000))
        output = subprocess.check_output(['rsync', '-rvzcn', '--itemize-changes',
                                          str(source) + '/', str(target) + '/']).decode()
        self.assertIn('index.html', output)
        self.assertEqual((target / 'index.html').read_bytes(), b'BBBB')


if __name__ == '__main__':
    unittest.main()
