"""LLM sağlayıcıları. ask(prompt, task) -> JSON (dict). Sağlayıcılar config.PROVIDERS sırasıyla denenir."""
import json
import re
import time

import requests

import config as C


class LLMError(Exception):
    pass


_mock_handler = None   # testler: set_mock(lambda prompt, task: {...})


def set_mock(fn):
    global _mock_handler
    _mock_handler = fn


_http = requests.Session()   # bağlantıyı açık tut (her çağrıda TLS el sıkışması olmasın)


def _post(url, **kw):
    try:
        r = _http.post(url, timeout=C.LLM_TIMEOUT, **kw)
    except requests.ConnectionError:
        # sunucu boşta kalan bağlantıyı kapatmış olabilir ("Remote end closed connection"): yeni bağlantıyla bir kez daha
        r = _http.post(url, timeout=C.LLM_TIMEOUT, **kw)
    if r.status_code == 429:
        raise LLMError(f"kota/oran sınırı (429): {r.text[:200]}")
    if r.status_code >= 400:
        raise LLMError(f"HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


_cooldown: dict[str, float] = {}   # model -> bu zamana kadar atla (yoğunluk/zaman aşımı)


def _gemini(prompt: str) -> str:
    if not C.GEMINI_KEY:
        raise LLMError("GEMINI_API_KEY yok")
    models = [C.GEMINI_MODEL] + [m for m in C.GEMINI_FALLBACK_MODELS if m != C.GEMINI_MODEL]
    now = time.time()
    ready = [m for m in models if _cooldown.get(m, 0) <= now] or models   # hepsi beklemedeyse yine de dene
    last = None
    for model in ready:
        try:
            d = _post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": C.GEMINI_KEY, "Content-Type": "application/json"},
                json={"contents": [{"parts": [{"text": prompt}]}],
                      "generationConfig": {"responseMimeType": "application/json", "temperature": 0.8}},
            )
            if model != C.GEMINI_MODEL:
                print(f"  [llm] gemini yedek model: {model}")
            return d["candidates"][0]["content"]["parts"][0]["text"]
        except requests.Timeout as e:
            last = LLMError(f"{model}: zaman aşımı ({C.LLM_TIMEOUT:g} sn)")
            _cooldown[model] = time.time() + C.MODEL_COOLDOWN
        except LLMError as e:
            last = LLMError(f"{model}: {e}")
            # model yok (404), yoğunluk (500/503) veya model kotası (429): sıradaki modeli dene
            if not re.search(r"\b(404|429|500|503)\b", str(e)):
                raise last
            _cooldown[model] = time.time() + (86400 if re.search(r"\b404\b", str(e)) else C.MODEL_COOLDOWN)
    raise last


def _openai(prompt: str) -> str:
    if not C.OPENAI_KEY:
        raise LLMError("OPENAI_API_KEY/GROQ_API_KEY yok")
    d = _post(
        f"{C.OPENAI_BASE}/chat/completions",
        headers={"Authorization": f"Bearer {C.OPENAI_KEY}"},
        json={"model": C.OPENAI_MODEL, "temperature": 0.8,
              "response_format": {"type": "json_object"},
              "messages": [{"role": "user", "content": prompt}]},
    )
    return d["choices"][0]["message"]["content"]


def _ollama(prompt: str) -> str:
    d = _post(f"{C.OLLAMA_URL}/api/chat",
              json={"model": C.OLLAMA_MODEL, "stream": False, "format": "json",
                    "messages": [{"role": "user", "content": prompt}]})
    return d["message"]["content"]


def parse_json(text: str):
    m = re.search(r"[\[{].*[\]}]", text, re.S)
    return json.loads(m.group(0) if m else text)


def ask(prompt: str, task: str = "") -> dict:
    """Prompt gönderir, JSON parse edilmiş cevabı döndürür. Tüm sağlayıcılar başarısızsa LLMError."""
    errors = []
    for p in C.PROVIDERS:
        t0 = time.time()
        try:
            if p == "mock":
                if _mock_handler is None:
                    raise LLMError("mock tanımlı değil")
                return _mock_handler(prompt, task)
            text = {"gemini": _gemini, "openai": _openai, "ollama": _ollama}[p](prompt)
            out = parse_json(text)
            print(f"  [llm] {p} {task} {time.time() - t0:.1f} sn")
            return out
        except KeyError:
            errors.append(f"{p}: bilinmeyen sağlayıcı")
        except (LLMError, requests.RequestException, ValueError) as e:
            errors.append(f"{p}: {e}")
    raise LLMError(" | ".join(errors) or "sağlayıcı yok")


def list_gemini_models() -> list[str]:
    r = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                     headers={"x-goog-api-key": C.GEMINI_KEY}, timeout=20)
    r.raise_for_status()
    return [m["name"].split("/")[-1] for m in r.json().get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])]


def warm_up():
    """Açılışta bir kez: bağlantıyı aç, çalışmayan modelleri bekleme listesine al (ilk soru gecikmesin)."""
    t0 = time.time()
    try:
        ask('Sadece JSON döndür: {"ok": true}', task="ısınma")
    except Exception as e:
        print(f"  [llm] ısınma başarısız: {e}")
        return
    print(f"  [llm] hazır ({time.time() - t0:.1f} sn)")
