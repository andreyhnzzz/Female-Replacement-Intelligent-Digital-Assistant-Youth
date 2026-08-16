<#
    F.R.I.D.A.Y — arranque
      .\scripts\run.ps1               acompanante + voz
      .\scripts\run.ps1 -NoVoice      acompanante sin microfono
      .\scripts\run.ps1 -Console      sin ventana, solo terminal
      .\scripts\run.ps1 -Check        diagnostico
      .\scripts\run.ps1 -Say "hola"   una peticion y sale
      .\scripts\run.ps1 -Preview      solo la interfaz, con datos de muestra
      .\scripts\run.ps1 -Silent       sin ventana de consola detras
#>
param(
    [switch]$NoVoice,
    [switch]$Console,
    [switch]$Check,
    [switch]$Preview,
    [switch]$Silent,
    [string]$Say
)

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$vpy = "$root\.venv\Scripts\python.exe"
$vpyw = "$root\.venv\Scripts\pythonw.exe"
if (-not (Test-Path $vpy)) {
    Write-Host "  Falta el entorno. Corre primero: .\scripts\setup.ps1" -ForegroundColor Red
    exit 1
}

$env:PYTHONIOENCODING = "utf-8"

if ($Preview) {
    & $vpy "$root\scripts\ui_preview.py" waiting
    exit $LASTEXITCODE
}

$argv = @("$root\friday.py")
if ($NoVoice) { $argv += "--no-voice" }
if ($Console) { $argv += "--console" }
if ($Check)   { $argv += "--check" }
if ($Say)     { $argv += @("--say", $Say) }

# -Silent arranca sin ventana de consola: el acompanante queda solo en
# el escritorio y en la bandeja, como corresponde a algo que vive todo el dia.
if ($Silent -and -not ($Console -or $Check -or $Say)) {
    Start-Process -FilePath $vpyw -ArgumentList $argv -WorkingDirectory $root
    Write-Host "  F.R.I.D.A.Y arrancada en segundo plano. Icono en la bandeja." -ForegroundColor Yellow
    exit 0
}

& $vpy $argv
