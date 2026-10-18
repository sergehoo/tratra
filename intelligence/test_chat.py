"""Dialogue avec outils et streaming : lecture des flux DeepSeek (format OpenAI) et Anthropic, conversion des messages, repli, échéance.
Aucun appel réseau : `requests.post` est remplacé par un faux flux."""
import json
import time

import pytest

from intelligence import ai, chat
from intelligence.models import AIRun

pytestmark = pytest.mark.django_db


class FakeResponse:
    def __init__(self, lines, status=200):
        self.status_code, self._lines = status, lines

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_lines(self, chunk_size=None):
        for line in self._lines:
            yield line.encode("utf-8")


def data(obj):
    return "data: " + json.dumps(obj)


@pytest.fixture(autouse=True)
def keys(settings):
    settings.AI_PROVIDERS = "deepseek,anthropic"
    settings.AI_DEEPSEEK_API_KEY, settings.AI_ANTHROPIC_API_KEY = "ds-test-key", "an-test-key"


def patch_post(monkeypatch, *responses):
    sent = []
    queue = list(responses)

    def post(url, **kwargs):
        sent.append({"url": url, **kwargs})
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
    monkeypatch.setattr(chat.requests, "post", post)
    return sent


TOOLS = [{"name": "bookings_overview", "description": "Réservations", "parameters": {"type": "object", "properties": {"days": {"type": "integer"}}, "required": []}}]


def collect(**kw):
    return list(chat.stream_chat("test", "système", [{"role": "user", "content": "Bonjour"}], TOOLS, **kw))


def test_deepseek_text_tool_calls_and_usage_are_assembled_from_the_stream(monkeypatch):
    lines = [": keep-alive", "", data({"choices": [{"delta": {"role": "assistant", "content": "Je regar"}}]}), "", data({"choices": [{"delta": {"content": "de."}}]}),
             data({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1", "type": "function", "function": {"name": "bookings_overview", "arguments": ""}}]}}]}),
             data({"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '{"days"'}}]}}]}),
             data({"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": ": 7}"}}]}, "finish_reason": "tool_calls"}]}),
             data({"choices": [], "usage": {"prompt_tokens": 50, "completion_tokens": 9}}), "data: [DONE]"]
    sent = patch_post(monkeypatch, FakeResponse(lines))
    events = collect(max_tokens=300)
    assert [e["type"] for e in events] == ["delta", "delta", "usage", "tool_calls", "end"]
    assert "".join(e["text"] for e in events if e["type"] == "delta") == "Je regarde."
    call = events[3]["calls"][0]
    assert (call.id, call.name, call.arguments, call.invalid) == ("call_1", "bookings_overview", {"days": 7}, False)
    assert events[2] == {"type": "usage", "tokens_in": 50, "tokens_out": 9} and events[-1] == {"type": "end", "provider": "deepseek"}
    body = sent[0]["json"]
    assert body["stream"] is True and body["stream_options"] == {"include_usage": True} and body["max_tokens"] == 300
    assert body["tools"] == [{"type": "function", "function": {"name": "bookings_overview", "description": "Réservations", "parameters": TOOLS[0]["parameters"]}}]
    assert body["messages"][0] == {"role": "system", "content": "système"} and sent[0]["timeout"][0] == chat.CONNECT_TIMEOUT
    assert sent[0]["headers"]["Authorization"] == "Bearer ds-test-key" and sent[0]["stream"] is True


def test_deepseek_arguments_that_are_not_json_are_flagged_invalid(monkeypatch):
    lines = [data({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c", "function": {"name": "bookings_overview", "arguments": "{pas du json"}}]}}]}), "data: [DONE]"]
    patch_post(monkeypatch, FakeResponse(lines))
    call = next(e for e in collect() if e["type"] == "tool_calls")["calls"][0]
    assert call.invalid is True and call.arguments == {}


def test_anthropic_stream_text_tool_use_and_usage(monkeypatch, settings):
    settings.AI_PROVIDERS = "anthropic"
    lines = ["event: message_start", data({"type": "message_start", "message": {"usage": {"input_tokens": 30}}}), "event: ping", data({"type": "ping"}),
             data({"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
             data({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Un instant"}}),
             data({"type": "content_block_stop", "index": 0}),
             data({"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "toolu_1", "name": "bookings_overview", "input": {}}}),
             data({"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"days":'}}),
             data({"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": " 14}"}}),
             data({"type": "content_block_stop", "index": 1}),
             data({"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 12}}), data({"type": "message_stop"})]
    sent = patch_post(monkeypatch, FakeResponse(lines))
    events = collect()
    assert [e["type"] for e in events] == ["delta", "usage", "tool_calls", "end"]
    assert events[1] == {"type": "usage", "tokens_in": 30, "tokens_out": 12}
    call = events[2]["calls"][0]
    assert (call.id, call.name, call.arguments) == ("toolu_1", "bookings_overview", {"days": 14})
    body = sent[0]["json"]
    assert body["stream"] is True and body["system"] == "système" and body["tools"][0]["input_schema"] == TOOLS[0]["parameters"]
    assert sent[0]["headers"]["x-api-key"] == "an-test-key" and body["messages"] == [{"role": "user", "content": "Bonjour"}]


def test_messages_are_converted_for_each_provider_including_tool_results():
    calls = [chat.ToolCall("a", "bookings_overview", {"days": 7}), chat.ToolCall("b", "platform_overview", {})]
    neutral = [{"role": "user", "content": "Q"}, {"role": "assistant", "content": "Je regarde", "tool_calls": calls},
               {"role": "tool", "tool_call_id": "a", "name": "bookings_overview", "content": "R1"}, {"role": "tool", "tool_call_id": "b", "name": "platform_overview", "content": "R2"}]
    openai = chat.to_openai_messages("sys", neutral)
    assert openai[0]["role"] == "system" and openai[2]["tool_calls"][0] == {"id": "a", "type": "function", "function": {"name": "bookings_overview", "arguments": '{"days": 7}'}}
    assert [m["role"] for m in openai] == ["system", "user", "assistant", "tool", "tool"] and openai[3] == {"role": "tool", "tool_call_id": "a", "content": "R1"}
    anthropic = chat.to_anthropic_messages(neutral)
    assert [m["role"] for m in anthropic] == ["user", "assistant", "user"]
    assert anthropic[1]["content"][0] == {"type": "text", "text": "Je regarde"} and anthropic[1]["content"][1] == {"type": "tool_use", "id": "a", "name": "bookings_overview", "input": {"days": 7}}
    assert anthropic[2]["content"] == [{"type": "tool_result", "tool_use_id": "a", "content": "R1"}, {"type": "tool_result", "tool_use_id": "b", "content": "R2"}]


def test_an_http_error_falls_back_to_the_next_provider_and_is_logged_without_content(monkeypatch):
    anthropic_ok = ["event: message_start", data({"type": "message_start", "message": {"usage": {"input_tokens": 1}}}),
                    data({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Secours"}}), data({"type": "message_stop"})]
    sent = patch_post(monkeypatch, FakeResponse([], status=429), FakeResponse(anthropic_ok))
    events = collect()
    assert "".join(e["text"] for e in events if e["type"] == "delta") == "Secours" and events[-1] == {"type": "end", "provider": "anthropic"}
    assert [s["url"].split("/")[2] for s in sent] == ["api.deepseek.com", "api.anthropic.com"]
    runs = list(AIRun.objects.order_by("id").values_list("provider", "ok", "error_code"))
    assert runs == [("deepseek", False, "http_429"), ("anthropic", True, "")]


def test_a_connection_error_after_text_is_an_interruption_not_a_fallback(monkeypatch):
    class Cut(FakeResponse):
        def iter_lines(self, chunk_size=None):
            yield data({"choices": [{"delta": {"content": "Début"}}]}).encode()
            raise ConnectionError("coupé")

    sent = patch_post(monkeypatch, Cut([]))
    got = []
    with pytest.raises(chat.ChatInterrupted):
        for e in chat.stream_chat("test", "système", [{"role": "user", "content": "Bonjour"}], TOOLS):
            got.append(e)
    assert got == [{"type": "delta", "text": "Début"}] and len(sent) == 1


def test_no_key_means_unavailable_and_no_request(monkeypatch, settings):
    settings.AI_DEEPSEEK_API_KEY = settings.AI_ANTHROPIC_API_KEY = ""
    sent = patch_post(monkeypatch)
    with pytest.raises(ai.AIUnavailable) as exc:
        collect()
    assert exc.value.code == "not_configured" and sent == [] and chat.available() is False


def test_an_expired_deadline_calls_no_provider(monkeypatch):
    sent = patch_post(monkeypatch)
    with pytest.raises(ai.AIUnavailable):
        collect(deadline=time.monotonic() - 1)
    assert sent == []


def test_the_deadline_stops_a_stream_in_progress(monkeypatch):
    lines = [data({"choices": [{"delta": {"content": "a"}}]})] * 3 + ["data: [DONE]"]
    patch_post(monkeypatch, FakeResponse(lines), FakeResponse([], status=500))
    with pytest.raises(ai.AIUnavailable):
        collect(deadline=time.monotonic() - 0.001)
