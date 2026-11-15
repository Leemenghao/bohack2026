import tempfile
import unittest
from pathlib import Path

from research_agent.conversation_store import ConversationStore
from research_agent.runview import save_run


class ConversationStoreTest(unittest.TestCase):
    def test_import_reopen_and_retry_in_one_session(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_id, stopped_id, retry_id = "000000000001", "000000000002", "000000000003"
            first = dict(question="基线", task="classification", status="complete", created_at="2026-11-14T00:00:00")
            stopped = dict(first, parent_id=first_id, question="为什么？", status="running",
                           created_at="2026-11-14T00:01:00", mode="chat")
            save_run(root / first_id, first)
            save_run(root / stopped_id, stopped)

            store = ConversationStore(root)
            self.assertEqual([turn["status"] for turn in store.thread(first_id)], ["complete", "interrupted"])
            self.assertTrue(store.has_follow_up(first_id))
            store.save(retry_id, dict(stopped, parent_id=stopped_id, status="complete",
                                      created_at="2026-11-14T00:02:00"), answer="因为误报增加。")
            self.assertTrue(store.update_session(first_id, title="分类对照", archived=True))

            reopened = ConversationStore(root)
            self.assertEqual(len(reopened.history()), 3)
            self.assertTrue(all(row["title"] == "分类对照" and row["archived"] for row in reopened.history()))
            self.assertEqual(reopened.thread(first_id)[-1]["answer"], "因为误报增加。")
