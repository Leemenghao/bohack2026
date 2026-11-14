"""Tests for the cloud-call budget. Pure logic, no model, no network."""

import unittest

from budget import Budget


class BudgetTest(unittest.TestCase):
    def test_defaults_are_unspent(self):
        budget = Budget(calls=8)
        self.assertEqual(budget.remaining_calls, 8)
        self.assertFalse(budget.exhausted)
        self.assertTrue(budget.can_call())

    def test_spending_calls_reduces_remaining(self):
        budget = Budget(calls=3)
        self.assertTrue(budget.spend_call("plan"))
        self.assertTrue(budget.spend_call("verify"))
        self.assertEqual(budget.remaining_calls, 1)
        self.assertFalse(budget.exhausted)

    def test_last_call_exhausts_and_further_spending_fails(self):
        budget = Budget(calls=2)
        budget.spend_call()
        budget.spend_call()
        self.assertTrue(budget.exhausted)
        self.assertFalse(budget.spend_call("too late"))
        self.assertEqual(budget.used_calls, 2)
        self.assertEqual(budget.exhausted_at, "call_limit")

    def test_token_cap_exhausts_independently(self):
        budget = Budget(calls=8, tokens=1000)
        budget.spend_tokens(600)
        self.assertFalse(budget.exhausted)
        budget.spend_tokens(500)
        self.assertTrue(budget.exhausted)
        self.assertEqual(budget.exhausted_at, "token_limit")

    def test_unbounded_tokens_reports_none(self):
        budget = Budget(calls=4)
        budget.spend_tokens(999_999)
        self.assertFalse(budget.exhausted)
        self.assertIsNone(budget.snapshot()["remaining_tokens"])

    def test_zero_or_negative_spend_is_ignored(self):
        budget = Budget(calls=2, tokens=100)
        budget.spend_tokens(0)
        budget.spend_tokens(-50)
        self.assertEqual(budget.used_tokens, 0)

    def test_prompt_line_mentions_limits(self):
        line = Budget(calls=6, tokens=12_000).prompt_line()
        self.assertIn("6 次", line)
        self.assertIn("12000", line)
        self.assertIn("收尾", line)

    def test_invalid_limits_are_rejected(self):
        with self.assertRaises(ValueError):
            Budget(calls=0)
        with self.assertRaises(ValueError):
            Budget(tokens=-1)

    def test_snapshot_shape(self):
        budget = Budget(calls=5, tokens=2000)
        budget.spend_call()
        budget.spend_tokens(700)
        snap = budget.snapshot()
        self.assertEqual(snap["used_calls"], 1)
        self.assertEqual(snap["remaining_calls"], 4)
        self.assertEqual(snap["remaining_tokens"], 1300)
        self.assertFalse(snap["exhausted"])


if __name__ == "__main__":
    unittest.main()
