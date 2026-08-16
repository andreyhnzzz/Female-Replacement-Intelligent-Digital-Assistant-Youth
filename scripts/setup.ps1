<#
    F.R.I.D.A.Y OS — instalacion
    Crea el venv con Python 3.12 e instala todo lo local.
    Uso:  .\scripts\setup.ps1
#>

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host ""
Write-Host "  F.R.I.D.A.Y OS - instalacion" -ForegroundColor Yellow
Write-Host "  ============================" -ForegroundColor DarkYellow
Write-Host ""

# --- 1. Python 3.12 -------------------------------------------------
$py = $null
foreach ($v in @("3.12", "3.11", "3.13")) {
    try {
        $probe = & py "-$v" -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $probe) { $py = @("py", "-$v"); $ver = $v; break }
    } catch {}
}
if (-not $py) {
    Write-Host "  No encontre Python 3.11-3.13." -ForegroundColor Red
    Write-Host "  faster-whisper todavia no tiene wheels para 3.14." -ForegroundColor DarkGray
    Write-Host "  Instala 3.12 desde https://www.python.org/downloads/" -ForegroundColor DarkGray
    exit 1
}
Write-Host "  [ok] Python $ver" -ForegroundColor Green

# --- 2. venv --------------------------------------------------------
if (-not (Test-Path "$root\.venv")) {
    Write-Host "  creando entorno virtual..." -ForegroundColor DarkGray
    & $py[0] $py[1] -m venv "$root\.venv"
}
$vpy = "$root\.venv\Scripts\python.exe"
Write-Host "  [ok] venv listo" -ForegroundColor Green

# --- 3. dependencias -------------------------------------------------
Write-Host "  instalando dependencias (esto tarda la primera vez)..." -ForegroundColor DarkGray
& $vpy -m pip install --upgrade pip --quiet
& $vpy -m pip install -r "$root\requirements.txt"
if ($LASTEXITCODE -ne 0) {
    Write-Host "  Algo fallo. Reintenta sin piper:" -ForegroundColor Yellow
    Write-Host "  .venv\Scripts\python -m pip install aiohttp psutil numpy sounddevice pynput faster-whisper pyttsx3" -ForegroundColor DarkGray
    exit 1
}
Write-Host "  [ok] dependencias" -ForegroundColor Green

# --- 4. modelo de Whisper (una sola descarga) -----------------------
Write-Host ""
Write-Host "  Bajando el modelo de STT (una vez, despues es 100% offline)..." -ForegroundColor DarkGray
& $vpy -c @'
from faster_whisper import WhisperModel
m = WhisperModel("small", device="cpu", compute_type="int8")
print("modelo listo en cache local")
'@
if ($LASTEXITCODE -eq 0) { Write-Host "  [ok] modelo whisper small" -ForegroundColor Green }

# --- 5. voz de Piper (opcional) --------------------------------------
$piperDir = "$root\models\piper"
if (-not (Get-ChildItem $piperDir -Filter *.onnx -ErrorAction SilentlyContinue)) {
    Write-Host ""
    Write-Host "  TTS: usara las voces de Windows (SAPI5), ya son locales." -ForegroundColor DarkGray
    Write-Host "  Para voz neuronal, baja un modelo Piper es_MX a:" -ForegroundColor DarkGray
    Write-Host "    $piperDir" -ForegroundColor DarkGray
    Write-Host "    https://huggingface.co/rhasspy/piper-voices/tree/main/es/es_MX" -ForegroundColor DarkGray
}

# --- 6. diagnostico ---------------------------------------------------
Write-Host ""
& $vpy "$root\friday.py" --check

Write-Host ""
Write-Host "  Listo. Arranca con:" -ForegroundColor Yellow
Write-Host "    .\scripts\run.ps1" -ForegroundColor White
Write-Host ""
