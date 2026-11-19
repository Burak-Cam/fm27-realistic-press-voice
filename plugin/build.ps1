# Kullanım:  .\build.ps1 -GameDir "D:\SteamLibrary\steamapps\common\Football Manager 27"
param([string]$GameDir = "C:\Program Files (x86)\Steam\steamapps\common\Football Manager 27")
dotnet build "$PSScriptRoot\FM27PressVoice\FM27PressVoice.csproj" -c Release -p:GameDir="$GameDir"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
New-Item -ItemType Directory -Force "$GameDir\BepInEx\plugins" | Out-Null
Copy-Item "$PSScriptRoot\FM27PressVoice\bin\Release\net6.0\FM27PressVoice.dll" "$GameDir\BepInEx\plugins\" -Force
Write-Host "Kopyalandı. Oyunu aç, BepInEx\LogOutput.log içinde 'FM27PressVoice yüklendi.' ara."
