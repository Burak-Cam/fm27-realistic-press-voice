# FM27 Sesli Basın Toplantısı - kurulum
# Kullanım (proje klasöründe PowerShell):  powershell -ExecutionPolicy Bypass -File install.ps1
#   -GameDir "D:\SteamLibrary\steamapps\common\Football Manager 27"   (Steam varsayılanı farklıysa)
# Yaptıkları: Python ortamı + paketler, eklentiyi oyuna kurma, settings.ini, (isteğe bağlı) anahtarlar, masaüstü kısayolu.
# Anahtarlar SADECE Windows kullanıcı ortam değişkenine yazılır (setx), hiçbir dosyaya yazılmaz.
param([string]$GameDir = "C:\Program Files (x86)\Steam\steamapps\common\Football Manager 27")

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$App = Join-Path $Root "app"
function Step($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Ok($t) { Write-Host "   OK  $t" -ForegroundColor Green }
function Warn($t) { Write-Host "   !!  $t" -ForegroundColor Yellow }

Step "1/6 Python 3.12"
$py = $null
try { $v = & py -3.12 --version 2>$null; if ($LASTEXITCODE -eq 0) { $py = "py -3.12"; Ok $v } } catch {}
if (-not $py) {
    Warn "Python 3.12 bulunamadı. https://www.python.org/downloads/ adresinden 3.12 kur ('py launcher' seçili), sonra betiği tekrar çalıştır."
    exit 1
}

Step "2/6 Uygulama ortamı ve paketler (birkaç dakika sürebilir)"
$venvPy = Join-Path $App ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) { & py -3.12 -m venv (Join-Path $App ".venv") }
& $venvPy -m pip install --quiet --upgrade pip
& $venvPy -m pip install --quiet -r (Join-Path $App "requirements.txt")
if ($LASTEXITCODE -ne 0) { Warn "Paket kurulumu başarısız."; exit 1 }
Ok "Paketler kuruldu"

Step "3/6 Football Manager 27 ve BepInEx"
if (-not (Test-Path (Join-Path $GameDir "fm.exe"))) {
    Warn "Oyun bulunamadı: $GameDir  ->  -GameDir ile doğru klasörü ver."
    exit 1
}
Ok "Oyun: $GameDir"
if (-not (Test-Path (Join-Path $GameDir "BepInEx\core"))) {
    Warn "BepInEx 6 (IL2CPP) kurulu değil. README 'Kurulum > BepInEx' adımını yap, oyunu bir kez açıp kapat, sonra betiği tekrar çalıştır."
    exit 1
}
Ok "BepInEx kurulu"

Step "4/6 Eklenti"
$dll = Join-Path $Root "plugin\FM27PressVoice\bin\Release\net6.0\FM27PressVoice.dll"
if (Get-Command dotnet -ErrorAction SilentlyContinue) {
    dotnet build (Join-Path $Root "plugin\FM27PressVoice\FM27PressVoice.csproj") -c Release -p:GameDir="$GameDir" --nologo -v q
    if ($LASTEXITCODE -ne 0) { Warn "Eklenti derlenemedi (oyunu bir kez açıp BepInEx interop klasörünün oluştuğundan emin ol)."; exit 1 }
} elseif (-not (Test-Path $dll)) {
    Warn ".NET SDK yok ve hazır DLL bulunamadı. GitHub Releases'ten FM27PressVoice.dll indirip '$dll' konumuna koy ya da .NET SDK kur."
    exit 1
}
if (Get-Process -Name "fm" -ErrorAction SilentlyContinue) { Warn "FM açık: eklenti kopyalanamıyor. Oyunu kapatıp betiği tekrar çalıştır."; exit 1 }
New-Item -ItemType Directory -Force (Join-Path $GameDir "BepInEx\plugins") | Out-Null
Copy-Item $dll (Join-Path $GameDir "BepInEx\plugins\") -Force
Ok "Eklenti kuruldu"

Step "5/6 Ayarlar ve anahtarlar"
$ini = Join-Path $App "settings.ini"
if (-not (Test-Path $ini)) {
    $txt = Get-Content -Raw -Encoding UTF8 (Join-Path $App "settings.example.ini")
    if ($GameDir -ne "C:\Program Files (x86)\Steam\steamapps\common\Football Manager 27") {
        $txt = $txt -replace ';oyun_klasoru = .*', ("oyun_klasoru = " + $GameDir)
    }
    [IO.File]::WriteAllText($ini, $txt, (New-Object Text.UTF8Encoding($false)))
    Ok "app\settings.ini oluşturuldu (düzenleyebilirsin)"
} else { Ok "app\settings.ini zaten var" }
foreach ($k in @(@{n="GEMINI_API_KEY"; d="Gemini (zorunlu, ücretsiz): https://aistudio.google.com/apikey"},
                 @{n="GROQ_API_KEY"; d="Groq (önerilir, ücretsiz, hızlı): https://console.groq.com/keys"})) {
    if ([Environment]::GetEnvironmentVariable($k.n, "User")) { Ok "$($k.n) tanımlı"; continue }
    Write-Host "   $($k.d)"
    $sec = Read-Host "   $($k.n) yapıştır (boş bırakırsan atlanır)" -AsSecureString
    $val = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
    if ($val) { [Environment]::SetEnvironmentVariable($k.n, $val.Trim(), "User"); Ok "$($k.n) kaydedildi (ortam değişkeni)" }
    else { Warn "$($k.n) atlandı" }
}

Step "6/6 Masaüstü kısayolu"
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "mod-toggle.ps1") -InstallShortcut
Ok "Hazır. Masaüstündeki 'FM27 Basın Modu' kısayoluyla modu aç/kapat. Yeni anahtarlar için yeni bir pencere/oturum gerekir."
