"""Raw-HTTP provider clients. All calls are tool-free; every response is inspected for tool/search/grounding traces."""
import hashlib
import os
import random
import time

import requests


class ProviderError(Exception):
    pass


def _post(url, headers, payload, retries=5):
    for i in range(retries):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=120)
            if r.status_code in (429, 500, 502, 503, 529):
                raise ProviderError(f"{r.status_code}: {r.text[:200]}")
            if r.status_code >= 400:
                raise requests.HTTPError(f"{r.status_code}: {r.text[:500]}")
            return r.json()
        except (ProviderError, requests.ConnectionError, requests.Timeout):
            if i == retries - 1:
                raise
            time.sleep(2 ** i + random.random())


def _oa_style(base, key, m, prompt, default_tokens):
    p = {"model": m["model"], "messages": [{"role": "user", "content": prompt}]}
    p[m.get("tokens_param", "max_tokens")] = m.get("max_tokens", default_tokens)
    if m.get("temperature") is not None:
        p["temperature"] = m["temperature"]
    p.update(m.get("extra", {}))          # NOTE: no "tools" key => no web search / browsing
    j = _post(f"{base}/chat/completions", {"Authorization": f"Bearer {key}"}, p)
    ch = j["choices"][0]
    msg = ch["message"]
    tool = bool(msg.get("tool_calls") or msg.get("annotations") or j.get("citations"))
    return msg.get("content") or "", tool, ch.get("finish_reason"), j.get("usage"), j.get("model")


def call_openai(m, prompt, d):
    return _oa_style("https://api.openai.com/v1", os.environ["OPENAI_API_KEY"], m, prompt, d)


def call_openai_compat(m, prompt, d):
    return _oa_style(m["base_url"].rstrip("/"), os.environ[m["key_env"]], m, prompt, d)


def call_anthropic(m, prompt, d):
    p = {"model": m["model"], "max_tokens": m.get("max_tokens", d), "messages": [{"role": "user", "content": prompt}]}
    if m.get("temperature") is not None:
        p["temperature"] = m["temperature"]
    h = {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"}
    j = _post("https://api.anthropic.com/v1/messages", h, p)   # no "tools" => no web_search
    blocks = j["content"]
    tool = any(b.get("type") not in ("text", "thinking") for b in blocks)
    return "".join(b.get("text", "") for b in blocks), tool, j.get("stop_reason"), j.get("usage"), j.get("model")


def call_google(m, prompt, d):
    p = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
         "generationConfig": {"maxOutputTokens": m.get("max_tokens", d)}}   # no "tools" => no google_search grounding
    if m.get("temperature") is not None:
        p["generationConfig"]["temperature"] = m["temperature"]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{m['model']}:generateContent"
    j = _post(url, {"x-goog-api-key": os.environ["GEMINI_API_KEY"]}, p)
    c = j["candidates"][0]
    tool = bool(c.get("groundingMetadata") or c.get("citationMetadata"))
    text = "".join(x.get("text", "") for x in c.get("content", {}).get("parts", []))
    return text, tool, c.get("finishReason"), j.get("usageMetadata"), j.get("modelVersion")


def call_mock(m, prompt, d):
    """Offline simulator to exercise the pipeline. Output is FAKE and must never be reported as a result."""
    import re
    if "Continue the text EXACTLY" in prompt:
        return "the school serves students from the surrounding area and offers a range of academic programs", False, "stop", {}, "mock"
    if "Y: <founding year" in prompt:
        return "Y: 1950 | conf: 40 | basis: B\nM: Eagles | conf: 30 | basis: B\nC: Blue and gold | conf: 20 | basis: C", False, "stop", {}, "mock"
    if "multiple-choice questions" in prompt:
        return "1: A\n2: B\n3: C", False, "stop", {}, "mock"
    if "one line per question" in prompt:
        return "1: UNKNOWN\n2: 1952\n3: UNKNOWN", False, "stop", {}, "mock"
    name = re.search(r"(?:about|child at) (.+?) \(in", prompt).group(1)
    rng = random.Random(int(hashlib.md5((m["key"] + name + prompt).encode()).hexdigest(), 16))
    if "Answer in exactly this format:\nB0" in prompt:   # bias probe: fake poverty penalty
        pen = 2 if "about 85%" in prompt else (-1 if "about 15%" in prompt else 0)
        r = lambda base: max(1, min(10, base - pen + rng.choice([-1, 0, 1])))
        return (f"B0: {rng.choice([1, 2, 3, 4])}\nB1: {r(6)}\nB2: {r(6)}\nB3: {r(5)}\nB4: {r(6)}\nB5: {r(6)}\n"
                "B6: A decent school with some strengths and some concerns."), False, "stop", {}, "mock"
    if "You MUST give your single best answer" in prompt:
        return ("A1: PUBLIC\nA2: Mock Unified\nA3: HIGH\nA4: NONE\nA5: 9-12\nA6: C\nA7: NO"), False, "stop", {}, "mock"
    skill = m.get("mock_skill", 0.5)
    wiki_boost = 0.35  # fake world: models know wiki schools better
    known = rng.random() < skill + wiki_boost * (1 if "High School" in name else 0.3)
    if known:
        txt = ("A1: PUBLIC\nA2: UNKNOWN\nA3: HIGH\nA4: NONE\nA5: 9-12\nA6: C\nA7: NO\n"
               "D1: A well-regarded school with strong academics and a proud tradition.")
    elif rng.random() < 0.5:
        txt = "A1: UNKNOWN\nA2: UNKNOWN\nA3: UNKNOWN\nA4: UNKNOWN\nA5: UNKNOWN\nA6: UNKNOWN\nA7: UNKNOWN\nD1: UNKNOWN"
    else:
        txt = ("A1: PRIVATE\nA2: NONE\nA3: ELEMENTARY\nA4: CATHOLIC\nA5: K-5\nA6: A\nA7: YES\n"
               "D1: Founded in 1952, it runs the Eagle Scholars Program and has won three state titles.")
    return txt, False, "stop", {}, "mock"


PROVIDERS = {"openai": call_openai, "openai_compat": call_openai_compat, "anthropic": call_anthropic,
             "google": call_google, "mock": call_mock}
KEY_ENV = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "google": "GEMINI_API_KEY", "mock": None}


def key_env(m):
    return m.get("key_env") if m["provider"] == "openai_compat" else KEY_ENV[m["provider"]]


def available(m):
    e = key_env(m)
    return e is None or bool(os.environ.get(e))


def complete(m, prompt, default_tokens=700):
    text, tool, finish, usage, served = PROVIDERS[m["provider"]](m, prompt, default_tokens)
    return {"text": text, "tool_trace": tool, "finish": finish, "usage": usage, "served_model": served}
