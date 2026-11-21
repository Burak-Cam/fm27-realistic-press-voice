"""LLM sağlayıcıları. ask(prompt, task) -> JSON (dict). Sağlayıcılar config.PROVIDERS sırasıyla denenir."""
import json
import re
import time

import requests
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

import config as C


class LLMError(Exception):
    pass


_mock_handler = None   # testler: set_mock(lambda prompt, task: {...})


def set_mock(fn):
    global _mock_handler
    _mock_handler = fn


_http = requests.Session()   # bağlantıyı açık tut (her çağrıda TLS el sıkışması olmasın)


def _post(url, timeout: float | None = None, **kw):
    timeout = timeout or C.LLM_TIMEOUT
    try:
        r = _http.post(url, timeout=timeout, **kw)
    except requests.ConnectionError:
        # sunucu boşta kalan bağlantıyı kapatmış olabilir ("Remote end closed connection"): yeni bağlantıyla bir kez daha
        r = _http.post(url, timeout=timeout, **kw)
    if r.status_code == 429:
        raise LLMError(f"kota/oran sınırı (429): {r.text[:200]}")
    if r.status_code >= 400:
        raise LLMError(f"HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


_cooldown: dict[str, float] = {}   # model -> bu zamana kadar atla (yoğunluk/zaman aşımı)


def _gemini_one(model: str, prompt: str) -> str:
    """Tek modele istek. Zaman aşımı / yoğunluk / kota / model yok -> LLMError + bekleme listesi."""
    try:
        d = _post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": C.GEMINI_KEY, "Content-Type": "application/json"},
            json={"contents": [{"parts": [{"text": prompt}]}],
                  "generationConfig": {"responseMimeType": "application/json", "temperature": 0.8}},
        )
        return d["candidates"][0]["content"]["parts"][0]["text"]
    except requests.Timeout:
        _cooldown[model] = time.time() + C.MODEL_COOLDOWN
        raise LLMError(f"{model}: zaman aşımı ({C.LLM_TIMEOUT:g} sn)")
    except requests.ConnectionError as e:
        raise LLMError(f"{model}: bağlantı hatası ({type(e).__name__})")
    except LLMError as e:
        if re.search(r"\b(404|429|500|503)\b", str(e)):
            _cooldown[model] = time.time() + (86400 if re.search(r"\b404\b", str(e)) else C.MODEL_COOLDOWN)
        raise LLMError(f"{model}: {e}")
    except (KeyError, IndexError) as e:
        raise LLMError(f"{model}: beklenmeyen cevap ({e})")


def _gemini(prompt: str, deadline: float | None = None) -> str:
    """Modelleri paralel ve kademeli dener: ilk model LLM_HEDGE_SEC içinde cevap vermezse (ya da hata verirse) sıradaki
    modele de sorulur, ilk gelen cevap kullanılır. deadline'a kadar cevap yoksa LLMError (çağıran yedeğe düşer)."""
    if not C.GEMINI_KEY:
        raise LLMError("GEMINI_API_KEY yok")
    models = [C.GEMINI_MODEL] + [m for m in C.GEMINI_FALLBACK_MODELS if m != C.GEMINI_MODEL]
    now = time.time()
    models = [m for m in models if _cooldown.get(m, 0) <= now] or models   # hepsi beklemedeyse yine de dene
    deadline = deadline or now + C.LLM_TIMEOUT * len(models)
    pool = ThreadPoolExecutor(max_workers=len(models), thread_name_prefix="gemini")
    running: dict = {}
    errors: list[str] = []
    nxt = 0

    def launch():
        nonlocal nxt
        m = models[nxt]
        nxt += 1
        running[pool.submit(_gemini_one, m, prompt)] = m

    try:
        launch()
        hedge_at = time.time() + C.LLM_HEDGE_SEC
        while running or nxt < len(models):
            now = time.time()
            if now >= deadline:
                break
            if not running:                        # hepsi hata verdi ama sırada model var
                launch()
                hedge_at = time.time() + C.LLM_HEDGE_SEC
                continue
            wake = min(deadline, hedge_at) if nxt < len(models) else deadline
            done, _ = wait(list(running), timeout=max(0.0, wake - now), return_when=FIRST_COMPLETED)
            for f in done:
                m = running.pop(f)
                try:
                    text = f.result()
                except LLMError as e:
                    errors.append(str(e))
                    if "HTTP 400" in str(e) or "HTTP 401" in str(e) or "HTTP 403" in str(e):
                        raise                    # istek/anahtar hatası: diğer modeller de aynı hatayı verir
                    continue
                if m != models[0]:
                    print(f"  [llm] gemini yedek model: {m}")
                return text
            if nxt < len(models) and time.time() >= hedge_at:
                launch()                           # yavaş: sıradaki modele de paralel sor
                hedge_at = time.time() + C.LLM_HEDGE_SEC
        if running and time.time() >= deadline:
            errors.append(f"süre doldu ({', '.join(running.values())} cevap vermedi)")
        raise LLMError(" | ".join(errors) or "cevap yok")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _reasoning(model: str) -> dict:
    """Düşünen modellerde düşünmeyi kapat/azalt (hız). Groq: qwen3 -> none, gpt-oss -> low."""
    if "qwen3" in model:
        return {"reasoning_effort": "none"}
    if "gpt-oss" in model:
        return {"reasoning_effort": "low"}
    return {}


def _openai(prompt: str, deadline: float | None = None) -> str:
    if not C.OPENAI_KEY:
        raise LLMError("OPENAI_API_KEY/GROQ_API_KEY yok")
    models = [C.OPENAI_MODEL] + [m for m in C.OPENAI_FALLBACK_MODELS if m != C.OPENAI_MODEL]
    now = time.time()
    models = [m for m in models if _cooldown.get("oa:" + m, 0) <= now] or models
    errors = []
    for model in models:
        left = (deadline - time.time()) if deadline else C.OPENAI_TIMEOUT
        if left <= 0.3:
            break
        try:
            d = _post(
                f"{C.OPENAI_BASE}/chat/completions", timeout=min(C.OPENAI_TIMEOUT, left),
                headers={"Authorization": f"Bearer {C.OPENAI_KEY}"},
                json={"model": model, "temperature": 0.8, "response_format": {"type": "json_object"},
                      "messages": [{"role": "user", "content": prompt}], **_reasoning(model)},
            )
            if model != models[0]:
                why = "; ".join(errors) or "ana model bekleme süresinde (önceki hata)"
                print(f"  [llm] groq yedek model: {model} (sebep: {why[:200]})")
            return d["choices"][0]["message"]["content"]
        except requests.Timeout:
            _cooldown["oa:" + model] = time.time() + 60
            errors.append(f"{model}: zaman aşımı")
        except requests.ConnectionError as e:
            errors.append(f"{model}: bağlantı hatası ({type(e).__name__})")
        except LLMError as e:
            errors.append(f"{model}: {e}")
            if re.search(r"\b(404|429|500|503)\b", str(e)):
                # 404 = model yok (1 gün); 429 = Groq dakikalık token sınırı, bir dakikada açılır; diğerleri MODEL_COOLDOWN
                wait = 86400 if re.search(r"\b404\b", str(e)) else 60 if re.search(r"\b429\b", str(e)) else C.MODEL_COOLDOWN
                _cooldown["oa:" + model] = time.time() + wait
            elif re.search(r"\b(401|403)\b", str(e)):
                break
        except (KeyError, IndexError) as e:
            errors.append(f"{model}: beklenmeyen cevap ({e})")
    raise LLMError(" | ".join(errors) or "süre doldu")


def _ollama(prompt: str) -> str:
    d = _post(f"{C.OLLAMA_URL}/api/chat",
              json={"model": C.OLLAMA_MODEL, "stream": False, "format": "json",
                    "messages": [{"role": "user", "content": prompt}]})
    return d["message"]["content"]


def parse_json(text: str):
    m = re.search(r"[\[{].*[\]}]", text, re.S)
    return json.loads(m.group(0) if m else text)


def ask(prompt: str, task: str = "", budget: float | None = None) -> dict:
    """Prompt gönderir, JSON parse edilmiş cevabı döndürür. budget: toplam üst süre (sn); aşılırsa LLMError
    (çağıran yedeğe düşer). Tüm sağlayıcılar başarısızsa LLMError."""
    errors = []
    deadline = time.time() + budget if budget else None
    if "mock" in C.PROVIDERS:
        if _mock_handler is None:
            raise LLMError("mock tanımlı değil")
        return _mock_handler(prompt, task)
    # Kademeli paralel: ana sağlayıcı LLM_HEDGE_SEC içinde cevap vermezse (ya da hata verirse) sıradakine de sorulur,
    # ilk geçerli cevap kullanılır. 2026-11-21: Gemini ana (doğru), Groq qwen yedek (hızlı ama ücretsiz katmanda
    # dakikada 7000 girdi token = ~2 soru; düşünmesiz modda golleri/sonucu karıştırıyordu).
    providers = list(C.PROVIDERS)
    end = deadline or time.time() + 60
    pool = ThreadPoolExecutor(max_workers=max(1, len(providers)))
    running, started, nxt = {}, {}, 0

    def launch():
        nonlocal nxt
        p = providers[nxt]
        nxt += 1
        started[p] = time.time()
        running[pool.submit(_call_provider, p, prompt, deadline)] = p

    try:
        launch()
        hedge_at = time.time() + C.LLM_HEDGE_SEC
        while running or nxt < len(providers):
            now = time.time()
            if now >= end:
                errors.append("süre doldu")
                break
            if not running:                        # hepsi hata verdi ama sırada sağlayıcı var
                launch()
                hedge_at = time.time() + C.LLM_HEDGE_SEC
                continue
            wake = min(end, hedge_at) if nxt < len(providers) else end
            done, _ = wait(list(running), timeout=max(0.0, wake - now), return_when=FIRST_COMPLETED)
            for f in done:
                p = running.pop(f)
                try:
                    out = parse_json(f.result())
                    print(f"  [llm] {p} {task} {time.time() - started[p]:.1f} sn")
                    return out
                except KeyError:
                    errors.append(f"{p}: bilinmeyen sağlayıcı")
                except (LLMError, requests.RequestException, ValueError) as e:
                    errors.append(f"{p}: {e}")
            if not done and nxt < len(providers) and time.time() >= hedge_at:
                launch()                           # ana sağlayıcı yavaş: sıradakine de sor
                hedge_at = time.time() + C.LLM_HEDGE_SEC
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    raise LLMError(" | ".join(errors) or "sağlayıcı yok")


def _call_provider(p: str, prompt: str, deadline: float | None) -> str:
    if p == "gemini":
        return _gemini(prompt, deadline)
    if p == "openai":
        return _openai(prompt, deadline)
    return {"ollama": _ollama}[p](prompt)


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
