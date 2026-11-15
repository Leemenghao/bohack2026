import json
import tempfile
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch

import httpx

from research_agent import web_server
from research_agent.conversation_store import ConversationStore
from research_agent.deletion import delete_experiment, delete_session
from research_agent.runview import load_run, save_run


class DeletionTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'runs'
        self.first, self.follow, self.other = [f'{i:012x}' for i in (1, 2, 3)]
        for run_id in (self.first, self.follow, self.other):
            save_run(self.root / run_id, dict(question='test', task='kernel', status='complete',
                created_at=run_id, **({'parent_id': self.first} if run_id == self.follow else {})))
            (self.root / run_id / 'report.md').write_text('Historical report')
        self.store = ConversationStore(self.root)
        self.store.update_session(self.first, shared=True)
        self.store.save_summary(self.first, self.follow, 'summary', 'today', 'test')
        self.folder = self.root / self.first
        for index in (1, 2):
            (self.folder / f'experiment-{index:08x}.json').write_text(json.dumps(
                {'experiment_id': f'{index:08x}', 'status': 'completed', 'summary': {'correct': True}}))
            (self.folder / f'candidate-{index:08x}.py').write_text('candidate')
        (self.folder / 'resources.json').write_text(json.dumps({'summary': {'experiments': 2},
            'entries': [{'experiment_id': '00000001', 'estimated_cost_cny': 0, 'cpu_seconds': 1, 'result': {}, 'configuration': {'code': 'private candidate'}}]}))

    def test_delete_session_removes_all_turns_and_shared_digest_without_resurrection(self):
        delete_session(self.store, self.first)
        reopened = ConversationStore(self.root)
        self.assertEqual([row['id'] for row in reopened.history()], [self.other])
        self.assertEqual(reopened.search_summaries('', self.other), [])
        self.assertIsNone(reopened.session_summary(self.first))
        self.assertFalse((self.root / self.follow).exists())
        self.assertTrue(list((self.root / '.trash').glob('session-*/*/report.md')))

    def test_delete_one_experiment_preserves_other_evidence_and_actual_usage(self):
        delete_experiment(self.store, self.first, '00000001')
        self.assertFalse((self.folder / 'experiment-00000001.json').exists())
        self.assertFalse((self.folder / 'candidate-00000001.py').exists())
        self.assertTrue((self.folder / 'experiment-00000002.json').exists())
        ledger = json.loads((self.folder / 'resources.json').read_text())
        self.assertEqual(ledger['summary']['experiments'], 2)
        self.assertEqual(ledger['entries'][0]['cpu_seconds'], 1)
        self.assertTrue(ledger['entries'][0]['record_deleted'])
        events = load_run(self.folder, include_detail=True)['events']
        self.assertEqual({e['experiment_id'] for e in events}, {'00000002'})
        self.assertIn('已于', (self.root / self.follow / 'report.md').read_text())
        self.assertIsNone(self.store.session_summary(self.first)['content'])
        self.assertEqual(len(self.store.history()), 3)

    def test_http_deletion_checks_origin_active_run_and_id(self):
        with patch.object(web_server, 'store', self.store), patch.object(web_server, 'runs', {}), patch.object(web_server.Handler, 'log_message'), ThreadingHTTPServer(('127.0.0.1', 0), web_server.Handler) as server:
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f'http://127.0.0.1:{server.server_port}'
                url = base + '/api/sessions/' + self.first
                with httpx.Client(trust_env=False) as client:
                    self.assertEqual(client.delete(url, headers={'Origin': 'https://foreign.example'}).status_code, 403)
                    with patch.object(web_server, 'runs', {self.other: {'status': 'running'}}):
                        self.assertEqual(client.delete(url).status_code, 409)
                    self.assertEqual(client.delete(base + '/api/sessions/not-an-id').status_code, 404)
                    self.assertEqual(client.delete(url).status_code, 200)
                    self.assertEqual(client.delete(url).status_code, 404)
            finally:
                server.shutdown()
                thread.join()
