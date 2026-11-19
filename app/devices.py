"""Ses giriş/çıkış cihazı seçimi.

FM_MIC / FM_SPEAKER: cihaz adının bir parçası (büyük/küçük harf fark etmez) ya da `start.bat devices` listesindeki numara.
Boşsa ya da cihaz bulunamazsa Windows'un varsayılan cihazı kullanılır (bulunamazsa bir kez uyarı yazılır).
"""
import config as C

# Aynı mikrofon birkaç Windows ses altyapısında tekrar listelenir. DirectSound tam adı verir ve 16 kHz'e kendisi
# dönüştürür; MME adları 31 karakterde kesilir; WASAPI cihazın kendi hızını ister; WDM-KS sorunlu -> kullanılmaz.
_HOSTAPI_ORDER = ["Windows DirectSound", "MME", "Windows WASAPI"]
_SKIP = ("sound mapper", "primary sound")
_warned: set[str] = set()


def _warn(msg: str):
    if msg not in _warned:
        _warned.add(msg)
        print(f"  [ses] {msg}")


def input_devices(devices: list[dict], apis: list[dict]) -> list[tuple[int, str]]:
    """Kullanılabilir mikrofonlar: (sounddevice indeksi, ad). Her cihaz bir kez, tercih edilen altyapıdan."""
    best: dict[str, tuple[int, int, str]] = {}   # ad(küçük) -> (öncelik, indeks, ad)
    for i, d in enumerate(devices):
        if d.get("max_input_channels", 0) <= 0:
            continue
        api = apis[d["hostapi"]]["name"]
        if api not in _HOSTAPI_ORDER or any(x in d["name"].lower() for x in _SKIP):
            continue
        prio = _HOSTAPI_ORDER.index(api)
        key = d["name"].lower()[:31].strip()      # MME kesik (31 karakter) adlarıyla eşleşsin
        if key not in best or prio < best[key][0]:
            best[key] = (prio, i, d["name"])
    return sorted(((i, n) for _, i, n in best.values()), key=lambda x: x[0])


def pick_input(devices: list[dict], apis: list[dict], query: str) -> int | None:
    """query: ad parçası ya da indeks. Bulunamazsa None (= varsayılan)."""
    query = (query or "").strip()
    if not query:
        return None
    cands = input_devices(devices, apis)
    if query.isdigit():
        idx = int(query)
        return idx if any(i == idx for i, _ in cands) else None
    q = query.lower()
    return next((i for i, n in cands if q in n.lower()), None)


def mic_device() -> int | None:
    """InputStream(device=...) için. Her kayıttan önce çağrılır (cihaz listesi tazelenir: sonradan takılan kulaklık)."""
    if not C.MIC:
        return None
    import sounddevice as sd
    try:
        sd._terminate()
        sd._initialize()
    except Exception:
        pass
    idx = pick_input(list(sd.query_devices()), list(sd.query_hostapis()), C.MIC)
    if idx is None:
        _warn(f"FM_MIC='{C.MIC}' bulunamadı, Windows varsayılan mikrofonu kullanılıyor")
    return idx


def output_names() -> list[str]:
    """SDL (pygame) çıkış cihazı adları."""
    import pygame
    import pygame._sdl2.audio as sdl_audio
    started = pygame.mixer.get_init() is None
    if started:
        pygame.mixer.init()
    try:
        return list(sdl_audio.get_audio_device_names(False))
    finally:
        if started:
            pygame.mixer.quit()


def pick_output(names: list[str], query: str) -> str | None:
    query = (query or "").strip()
    if not query:
        return None
    if query.isdigit():
        i = int(query)
        return names[i] if 0 <= i < len(names) else None
    q = query.lower()
    return next((n for n in names if q in n.lower()), None)


def speaker_name() -> str | None:
    """pygame.mixer.init(devicename=...) için; None = varsayılan."""
    if not C.SPEAKER:
        return None
    try:
        name = pick_output(output_names(), C.SPEAKER)
    except Exception as e:
        _warn(f"çıkış cihazları okunamadı ({e}), varsayılan kullanılıyor")
        return None
    if name is None:
        _warn(f"FM_SPEAKER='{C.SPEAKER}' bulunamadı, Windows varsayılan çıkışı kullanılıyor")
    return name


def describe() -> tuple[str, str]:
    """(mikrofon, hoparlör) için okunur açıklama (check / devices komutları)."""
    import sounddevice as sd
    devs, apis = list(sd.query_devices()), list(sd.query_hostapis())
    mi = pick_input(devs, apis, C.MIC) if C.MIC else None
    mic = devs[mi]["name"] if mi is not None else f"Windows varsayılanı ({sd.query_devices(kind='input')['name']})"
    if C.MIC and mi is None:
        mic += f"  [FM_MIC='{C.MIC}' bulunamadı]"
    try:
        sp = pick_output(output_names(), C.SPEAKER) if C.SPEAKER else None
    except Exception:
        sp = None
    spk = sp or "Windows varsayılanı"
    if C.SPEAKER and sp is None:
        spk += f"  [FM_SPEAKER='{C.SPEAKER}' bulunamadı]"
    return mic, spk
