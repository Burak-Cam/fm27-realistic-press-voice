# FM27 Basın Modu aç/kapa. Masaüstü kısayolu bunu çalıştırır.
#   Kapalı -> açık : BepInEx'i etkinleştirir (doorstop enabled=true) ve sesli uygulamayı yeni pencerede başlatır.
#   Açık  -> kapalı: uygulamayı kapatır, BepInEx'i devre dışı bırakır (FM tamamen normal açılır).
# Kısayolu yeniden oluşturmak için: powershell -ExecutionPolicy Bypass -File mod-toggle.ps1 -InstallShortcut
param([switch]$InstallShortcut)

$ErrorActionPreference = "Stop"
# Oyun klasörü: FM_GAME_DIR > app\settings.ini (oyun_klasoru, install.ps1 -GameDir yazar) > Steam varsayılanı
function Get-GameDir {
    if ($env:FM_GAME_DIR) { return $env:FM_GAME_DIR }
    $ini = Join-Path $PSScriptRoot "app\settings.ini"
    if (Test-Path $ini) {
        $line = Get-Content -Encoding UTF8 $ini | Where-Object { $_ -match '^\s*oyun_klasoru\s*=\s*\S' } | Select-Object -First 1
        if ($line) { return ($line -replace '^\s*oyun_klasoru\s*=\s*', '').Trim() }
    }
    return "C:\Program Files (x86)\Steam\steamapps\common\Football Manager 27"
}
$GameDir  = Get-GameDir
$Doorstop = Join-Path $GameDir "doorstop_config.ini"
$AppDir   = Join-Path $PSScriptRoot "app"
$Title    = "FM27 Basın Modu"

Add-Type -AssemblyName System.Windows.Forms
function Show-Msg($text, $buttons = "OK", $icon = "Information") {
    [System.Windows.Forms.MessageBox]::Show($text, $Title, $buttons, $icon)
}

if ($InstallShortcut) {
    $lnk = Join-Path ([Environment]::GetFolderPath("Desktop")) "$Title.lnk"
    $sh = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
    $sh.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
    $sh.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$PSCommandPath`""
    $sh.WorkingDirectory = $PSScriptRoot
    $sh.IconLocation = "$env:SystemRoot\System32\SndVol.exe,0"
    $sh.Description = "FM27 sesli basın toplantısı modunu aç/kapat"
    $sh.Save()
    Write-Output "Kısayol oluşturuldu: $lnk"
    exit 0
}

function Get-ModEnabled {
    $line = Get-Content $Doorstop | Where-Object { $_ -match '^\s*enabled\s*=' } | Select-Object -First 1
    return ($line -match '=\s*true')
}

function Set-ModEnabled([bool]$on) {
    $val = if ($on) { "true" } else { "false" }
    $text = [IO.File]::ReadAllText($Doorstop)
    $text = [regex]::new('(?m)^(\s*enabled\s*=\s*)\w+').Replace($text, "`${1}$val", 1)
    [IO.File]::WriteAllText($Doorstop, $text, (New-Object Text.UTF8Encoding($false)))
}

function Get-AppProcs {
    Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -and $_.CommandLine -like "*$AppDir*" -and
        ($_.Name -eq "python.exe" -or ($_.Name -eq "cmd.exe" -and $_.CommandLine -like "*start.bat*"))
    }
}

# Derlenmiş eklenti oyundakinden yeniyse kopyala (oyun açıkken DLL kilitli olduğu için sadece FM kapalıyken).
function Update-Plugin {
    $built = Join-Path $PSScriptRoot "plugin\FM27PressVoice\bin\Release\net6.0\FM27PressVoice.dll"
    $dest = Join-Path $GameDir "BepInEx\plugins\FM27PressVoice.dll"
    if (-not (Test-Path $built)) { return "" }
    if ((Test-Path $dest) -and (Get-Item $built).LastWriteTime -le (Get-Item $dest).LastWriteTime) { return "" }
    if (Get-Process -Name "fm" -ErrorAction SilentlyContinue) { return "`n`nYeni eklenti sürümü hazır: FM kapalıyken kısayolu tekrar kullanınca kurulur." }
    New-Item -ItemType Directory -Force (Split-Path $dest) | Out-Null
    Copy-Item $built $dest -Force
    return "`n`nYeni eklenti sürümü kuruldu."
}

function Start-App {
    Start-Process -FilePath "cmd.exe" -ArgumentList "/k `"$AppDir\start.bat`"" -WorkingDirectory $AppDir
}

function Stop-App {
    # önce pencereyi alt süreçleriyle birlikte kapat, kalan python varsa onu da kapat
    Get-AppProcs | Where-Object { $_.Name -eq "cmd.exe" } | ForEach-Object { & taskkill.exe /T /F /PID $_.ProcessId 2>$null | Out-Null }
    Get-AppProcs | ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force } catch {} }
}

try {
    if (-not (Test-Path $Doorstop)) {
        Show-Msg "doorstop_config.ini bulunamadı:`n$Doorstop`n`nOyun klasörü farklıysa FM_GAME_DIR ortam değişkenini ayarla." "OK" "Error" | Out-Null
        exit 1
    }
    $gameRunning = [bool](Get-Process -Name "fm" -ErrorAction SilentlyContinue)
    $restartNote = if ($gameRunning) { "`n`nFM şu an açık: değişiklik oyunu yeniden başlatınca geçerli olur." } else { "" }

    if (Get-ModEnabled) {
        if (-not (Get-AppProcs)) {
            $r = Show-Msg "Mod AÇIK ama sesli uygulama çalışmıyor.`n`nEvet: uygulamayı başlat`nHayır: modu kapat" "YesNoCancel" "Question"
            if ($r -eq "Yes") {
                $upd = Update-Plugin
                Start-App
                if ($upd) { Show-Msg ("Uygulama başlatıldı." + $upd) | Out-Null }
                exit 0
            }
            if ($r -ne "No") { exit 0 }
        }
        Stop-App
        Set-ModEnabled $false
        Show-Msg "Mod KAPATILDI.`nFM normal (eklentisiz) açılır.$restartNote" | Out-Null
    } else {
        Set-ModEnabled $true
        $upd = Update-Plugin
        Start-App
        Show-Msg "Mod AÇILDI.`nSesli uygulama ayrı pencerede başladı; FM'yi aç.$restartNote$upd" | Out-Null
    }
} catch {
    Show-Msg "Hata: $($_.Exception.Message)" "OK" "Error" | Out-Null
    exit 1
}
