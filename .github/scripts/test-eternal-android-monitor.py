import base64
import contextlib
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import textwrap
import unittest
from unittest.mock import patch
import urllib.error

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/workflows/eternal-android-monitor.yml'
source = WORKFLOW.read_text(encoding='utf-8').split("python - <<'PY'\n", 1)[1].rsplit('          PY', 1)[0]
CODE = compile(textwrap.dedent(source), str(WORKFLOW), 'exec')
FINGERPRINT = 'v2.0.0|v1.10.9|yt:21.30.216|music:9.30.53'


class Response:
    def __init__(self, data, status=200):
        self.data = data if isinstance(data, bytes) else json.dumps(data).encode()
        self.status = status
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self): return self.data


class MonitorTests(unittest.TestCase):
    def run_monitor(self, fingerprint='', runs=None, stable=True, missing=False, deny=False):
        dispatches = []
        def fetch(request, timeout=None):
            url = request.full_url
            if request.get_method() == 'POST':
                dispatches.append(json.loads(request.data))
                return Response({}, 204)
            if '/contents/build-state.json' in url:
                if deny: raise urllib.error.HTTPError(url, 403, 'Forbidden', {}, None)
                state = {'fingerprint': fingerprint, 'youtube': '21.30.216', 'youtube_music': '9.30.53'}
                return Response({'content': base64.b64encode(json.dumps(state).encode()).decode()})
            if '/actions/workflows/' in url:
                self.assertIn('branch=main', url)
                return Response({'workflow_runs': runs or []})
            if '/morphe-patches/releases/latest' in url: return Response({'tag_name': 'v2.0.0'})
            if '/eternal-youtube-history-patches/releases/latest' in url: return Response({'tag_name': 'v1.10.9'})
            if '/music/shared/Constants.kt' in url:
                return Response(b'AppTarget(version = "9.30.53")')
            if '/youtube/shared/Constants.kt' in url:
                return Response(('AppTarget(version = "21.30.216"' + (', isExperimental = true' if not stable else '') + ')').encode())
            if '/EternalHistoryPatch.kt' in url:
                return Response(b'AppTarget(version = "21.30.216")')
            raise AssertionError('Unexpected request: ' + url)
        output = io.StringIO()
        env = {'PRIVATE_AUTOMATION_TOKEN': '' if missing else 'private-fixture-only', 'PUBLIC_GITHUB_TOKEN': 'public-fixture-only'}
        error = None
        with patch.dict(os.environ, env), patch('urllib.request.urlopen', fetch), contextlib.redirect_stdout(output):
            try: exec(CODE, {})
            except SystemExit as stopped:
                if stopped.code not in (0, None): raise
            except (RuntimeError, urllib.error.HTTPError) as failed: error = failed
        self.assertNotIn('private-fixture-only', output.getvalue())
        return dispatches, error

    def test_unchanged_starts_zero_private_runs(self):
        sent, error = self.run_monitor(FINGERPRINT)
        self.assertEqual(sent, [])
        self.assertIsNone(error)

    def test_change_dispatches_main_once(self):
        sent, error = self.run_monitor()
        self.assertEqual(sent, [{'ref': 'main', 'inputs': {'force_build': 'false'}}])
        self.assertIsNone(error)

    def test_active_run_even_below_completed_run_blocks_dispatch(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=8)).isoformat()
        sent, error = self.run_monitor(runs=[{'status': 'completed', 'created_at': old}, {'status': 'queued'}])
        self.assertEqual(sent, [])
        self.assertIsNone(error)

    def test_recent_failed_run_observes_cooldown(self):
        sent, error = self.run_monitor(runs=[{'status': 'completed', 'conclusion': 'failure', 'created_at': datetime.now(timezone.utc).isoformat()}])
        self.assertEqual(sent, [])
        self.assertIsNone(error)

    def test_expired_cooldown_allows_single_retry(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=8)).isoformat()
        sent, error = self.run_monitor(runs=[{'status': 'completed', 'created_at': old}])
        self.assertEqual(len(sent), 1)
        self.assertIsNone(error)

    def test_unsupported_or_experimental_target_fails_closed(self):
        sent, error = self.run_monitor(stable=False)
        self.assertEqual(sent, [])
        self.assertIsNotNone(error)

    def test_missing_token_is_visible_failure(self):
        sent, error = self.run_monitor(missing=True)
        self.assertEqual(sent, [])
        self.assertIsNotNone(error)

    def test_expired_or_underprivileged_token_never_dispatches(self):
        sent, error = self.run_monitor(deny=True)
        self.assertEqual(sent, [])
        self.assertIsNotNone(error)


if __name__ == '__main__': unittest.main(verbosity=2)
