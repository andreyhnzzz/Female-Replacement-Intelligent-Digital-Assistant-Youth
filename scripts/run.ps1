<#
    F.R.I.D.A.Y OS — arranque
      .\scripts\run.ps1              voz + HUD
      .\scripts\run.ps1 -NoVoice     solo HUD
      .\scripts\run.ps1 -Check       diagnostico
      .\scripts\run.ps1 -Say "hola"  una peticion
#>
param(
    [switch]$NoVoice,
    [switch]$NoHud,
    [switch]$Check,
    [string]$Say
)

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$vpy = "$root\.venv\Scripts\python.exe"
if (-not (Test-Path $vpy)) {
    Write-Host "  Falta el entorno. Corre primero: .\scripts\setup.ps1" -ForegroundColor Red
    exit 1
}

$argv = @("$root\friday.py")
if ($NoVoice) { $argv += "--no-voice" }
if ($NoHud)   { $argv += "--no-hud" }
if ($Check)   { $argv += "--check" }
if ($Say)     { $argv += @("--say", $Say) }

& $vpy $argv
