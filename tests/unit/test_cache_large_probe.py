"""Guard the realistic long-input cache probe before any paid run."""

from __future__ import annotations

from scripts.cache_large_probe import (
    _is_deepseek_endpoint,
    build_case,
    save_probe_progress,
    score_answer,
)


def test_large_probe_uses_same_facts_and_authorized_tools_for_both_layouts():
    case = build_case("W01")
    old, new = case.legacy_messages, case.optimized_messages

    assert len(case.tools) == 9
    assert all(tool.effect == "read" for tool in case.tools)
    assert old[-1] == new[-1]
    assert [message.role for message in old] == ["system", "user"]
    assert [message.role for message in new] == ["system", "system", "system", "system", "user"]
    assert case.facts_chars > 12_000
    assert "synthetic_probe" in old[0].content and "synthetic_probe" in new[-2].content
    result = case.fixture
    assert result["ok"] is True
    assert len(result["data"]["records"]) == 36
    assert case.expected == {"P103": 12, "P118": 17, "P131": 9}
    assert {row["part_id"]: row["shortage"] for row in result["data"]["records"] if row["shortage"]} == case.expected
    assert old[0].content != new[0].content
    assert new[0].content in old[0].content
    assert case.template_id.startswith("ta-v2-base-1:")


def test_long_probe_oracle_rejects_missing_or_extra_shortages_and_tool_calls():
    expected = {"P103": 12, "P118": 17, "P131": 9}
    correct = "W01：P103 缺口 12 个；P118 缺口 17 个；P131 缺口 9 个。"
    assert score_answer(correct, [], expected)
    assert score_answer("P103：12 个；P118：17 个；P131：9 个。", [], expected)
    assert not score_answer("W01：P103 缺口 12 个；P118 缺口 17 个。", [], expected)
    assert not score_answer(correct + " P105 也要补货。", [], expected)
    assert not score_answer(correct, ["inventory_page"], expected)


def test_live_probe_requires_the_exact_https_deepseek_host():
    assert _is_deepseek_endpoint("https://api.deepseek.com")
    assert not _is_deepseek_endpoint("http://api.deepseek.com")
    assert not _is_deepseek_endpoint("https://api.deepseek.com.example.org")


def test_probe_keeps_answer_text_out_of_the_numeric_report(tmp_path):
    numeric = tmp_path / "reports" / "probe.json"
    local_answers = tmp_path / "private" / "answers.json"
    save_probe_progress(numeric, local_answers, {"rows": [{"oracle_passed": False}]},
                        [{"answer": "P103 缺口 12 个"}])
    assert "P103" not in numeric.read_text(encoding="utf-8")
    assert "P103" in local_answers.read_text(encoding="utf-8")
