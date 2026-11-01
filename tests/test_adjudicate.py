"""Phase 3 without network: a fake client stands in for the Anthropic SDK."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from say_my_name import adjudicate as adj
from say_my_name.generator import write_dataset
from say_my_name.matcher import PairResult, match


def response(payload=None, stop_reason="end_turn", text=None, model="claude-haiku-5-5"):
    body = text if text is not None else json.dumps(payload)
    return SimpleNamespace(
        model=model, stop_reason=stop_reason,
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=body)],
        usage=SimpleNamespace(input_tokens=400, output_tokens=200,
                              cache_creation_input_tokens=0, cache_read_input_tokens=900))


class FakeMessages:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.answer(kwargs)


class FakeClient:
    def __init__(self, answer):
        self.messages = FakeMessages(answer)
        self.beta = SimpleNamespace(messages=FakeMessages(answer))


UNSURE = {"decision": "needs_external_check", "confidence": "low", "pattern": "unclear",
          "evidence": ["ORT01 differs"], "explanation": "Cannot tell from the records."}
PAIR = PairResult("ERP_A/KNA1/1", "ERP_B/LFA1/2", "REVIEW", 0.8, "same tax ID, different province", 0.9, 0.5, 0.0)
REC_A = {"RECORD_ID": "ERP_A/KNA1/1", "SYSTEM": "ERP_A", "TABLE": "KNA1", "NAME1": "Talvora, S.L.", "NAME2": "",
         "STRAS": "Calle Mayor, 1", "PSTLZ": "38001", "ORT01": "Santa Cruz de Tenerife", "REGIO": "38",
         "STCD1": "B12345674", "STCEG": ""}
REC_B = {**REC_A, "RECORD_ID": "ERP_B/LFA1/2", "SYSTEM": "ERP_B", "TABLE": "LFA1", "NAME1": "TALVORA SL",
         "STCD1": "B12845674", "ORT01": "SEVILLA", "REGIO": "41", "PSTLZ": "41001"}


class RequestTest(unittest.TestCase):
    def test_haiku_request(self):
        req = adj.build_request("claude-haiku-5-5", "low", "hi")
        self.assertEqual(req["output_config"]["effort"], "low")
        self.assertEqual(req["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(req["system"][0]["cache_control"], {"type": "ephemeral"})
        self.assertNotIn("fallbacks", req)  # Haiku 5.5 has no server-side fallback
        self.assertNotIn("thinking", req)  # adaptive thinking is the default

    def test_sonnet_request_has_fallback(self):
        req = adj.build_request("claude-sonnet-5-5", "medium", "hi")
        self.assertEqual((req["betas"], req["fallbacks"]), (["server-side-fallback-2026-07-01"], "default"))

    def test_prompt_shows_check_digit_status_not_identifiers(self):
        text = adj.pair_prompt(PAIR, REC_A, REC_B)
        payload = json.loads(text.split("\n\n", 1)[1])
        self.assertEqual(payload["record_a"]["tax_id_status"], {"STCD1": "passes check digit"})
        self.assertEqual(payload["record_b"]["tax_id_status"], {"STCD1": "fails check digit"})
        self.assertNotIn("RECORD_ID", payload["record_a"])

    def test_prompt_hash_changes_with_effort(self):
        self.assertNotEqual(adj.prompt_hash("m", "low", "x"), adj.prompt_hash("m", "high", "x"))


class ParseTest(unittest.TestCase):
    def base(self):
        return adj.Decision(pair_id="a|b", a="a", b="b", reason="r", decision="failed")

    def test_valid_answer(self):
        d = adj.parse_response(response(UNSURE), self.base(), "claude-haiku-5-5")
        self.assertEqual((d.decision, d.pattern, d.evidence), ("needs_external_check", "unclear", ["ORT01 differs"]))
        # 400 input * 0.10 + 900 cache reads * 0.01 + 200 output * 0.50, per million
        self.assertAlmostEqual(d.cost_usd, (400 * 0.10 + 900 * 0.01 + 200 * 0.50) / 1e6)

    def test_unusable_answers_go_to_people(self):
        cases = [response(stop_reason="refusal", text=""), response(stop_reason="max_tokens", text="{"),
                 response(text="not json"), response({**UNSURE, "decision": "maybe"})]
        for r in cases:
            self.assertEqual(adj.parse_response(r, self.base(), "claude-haiku-5-5").decision, "failed")

    def test_fallback_model_is_priced_as_requested(self):
        d = adj.parse_response(response(UNSURE, model="claude-sonnet-5"), self.base(), "claude-sonnet-5-5")
        self.assertEqual(d.model, "claude-sonnet-5")
        self.assertGreater(d.cost_usd, 0)


class RunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        records, _ = write_dataset(self.root / "data" / "t", seed=5, n_entities=300)
        match(records, self.root / "out" / "t")

    def tearDown(self):
        self.tmp.cleanup()

    def test_unsure_llm_equals_rules_only_and_people_reach_the_ceiling(self):
        client = FakeClient(lambda kw: response(UNSURE))
        m = adj.run("t", "haiku", "low", client=client, root=self.root)
        self.assertEqual(m["decided"], m["review_pairs"])
        self.assertEqual(m["handed_to_people"], m["review_pairs"])
        s = m["scenarios"]
        self.assertEqual(s["rules only"]["pairwise"], s["rules + LLM (hand-offs left unmerged)"]["pairwise"])
        self.assertEqual(s["rules + LLM + people decide the hand-offs perfectly"]["pairwise"]["f1"],
                         s["ceiling: every REVIEW pair decided perfectly"]["pairwise"]["f1"])
        self.assertTrue((self.root / "out" / "t" / "llm-haiku-low" / "report.md").exists())

    def test_answers_are_cached(self):
        client = FakeClient(lambda kw: response(UNSURE))
        adj.run("t", "haiku", "low", client=client, root=self.root)
        first = len(client.messages.calls)
        adj.run("t", "haiku", "low", client=client, root=self.root)
        self.assertGreater(first, 0)
        self.assertEqual(len(client.messages.calls), first)

    def test_failed_answers_are_retried(self):
        client = FakeClient(lambda kw: response(text="not json"))
        adj.run("t", "haiku", "low", limit=5, client=client, root=self.root)
        adj.run("t", "haiku", "low", limit=5, client=client, root=self.root)
        self.assertEqual(len(client.messages.calls), 10)

    def test_sonnet_goes_through_the_beta_endpoint(self):
        client = FakeClient(lambda kw: response(UNSURE, model="claude-sonnet-5-5"))
        adj.run("t", "sonnet", "low", limit=3, client=client, root=self.root)
        self.assertEqual(len(client.beta.messages.calls), 3)
        self.assertEqual(len(client.messages.calls), 0)


if __name__ == "__main__":
    unittest.main()
