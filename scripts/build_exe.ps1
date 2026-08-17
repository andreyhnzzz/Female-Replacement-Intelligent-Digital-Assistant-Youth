<#
.SYNOPSIS
    Genera FRIDAY.exe — un lanzador nativo para arrancar con doble clic.

.DESCRIPTION
    Compila un ejecutable de Windows de unos pocos KB que arranca FRIDAY con
    el interprete del venv y sin ventana de consola detras.

    NO es un bundle redistribuible. Es un lanzador: necesita este repo y su
    .venv en su sitio. La decision es deliberada — mira la seccion de abajo.

    El .exe no lleva dentro ni una linea de tus datos: solo la ruta al
    proyecto. No toca vault/, ni logs/, ni la config.

.PARAMETER Icono
    Regenera el icono desde el nucleo pintado en desktop/sprites.py.

.EXAMPLE
    .\scripts\build_exe.ps1
    .\scripts\build_exe.ps1 -Consola     # deja la consola visible, para depurar

.NOTES
    ¿Por que no PyInstaller?

    Se puede, pero no es "rapido" ni gratis en este proyecto:

      - PySide6 pesa 642 MB en disco; con CTranslate2 y ONNX Runtime el
        bundle se va facil por encima del medio giga.
      - QtQuick3D es de lo que peor congela PyInstaller: hay que arrastrar a
        mano los plugins QML, los modulos de Quick3D y los shaders.
      - desktop/geometry.py registra tipos QML con @QmlElement, que dependen
        de que el modulo sea importable en tiempo de ejecucion, y el QML se
        carga con rutas relativas a __file__ — las dos cosas hay que
        reescribirlas para sys._MEIPASS.
      - El modelo de voz se baja en el primer arranque a la cache del
        usuario, asi que el bundle tampoco te ahorra esa descarga.

    Un lanzador tarda dos segundos en compilarse, pesa 4 KB y funciona.
    Cuando haga falta distribuir de verdad, el bundle es otro trabajo y
    merece su propio .spec.
#>
[CmdletBinding()]
param(
    [switch]$Consola,
    [switch]$Icono
)

$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
$salida = Join-Path $raiz "FRIDAY.exe"
# Ojo: NO llamarla $icono. PowerShell no distingue mayusculas, asi que
# chocaria con el parametro [switch]$Icono y asignarle una ruta reventaria
# el enlace del parametro antes de ejecutar una sola linea.
$rutaIcono = Join-Path $raiz "desktop\friday.ico"

Write-Host ""
Write-Host "  Construyendo el lanzador de F.R.I.D.A.Y" -ForegroundColor Yellow
Write-Host ""

# ── comprobaciones ─────────────────────────────────────────────
$pythonw = Join-Path $raiz ".venv\Scripts\pythonw.exe"
$python = Join-Path $raiz ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonw)) {
    throw "No encuentro el venv. Corre .\scripts\setup.ps1 primero."
}

$csc = "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path $csc)) {
    throw "No encuentro csc.exe (.NET Framework 4). Es parte de Windows."
}

# ── icono ──────────────────────────────────────────────────────
# Se pinta con el mismo codigo que el icono de la bandeja, para que el
# acceso directo y la bandeja no acaben siendo dos naranjas distintas.
if ($Icono -or -not (Test-Path $rutaIcono)) {
    Write-Host "  · generando icono" -ForegroundColor DarkGray
    & $python (Join-Path $PSScriptRoot "make_icon.py") $rutaIcono
    if ($LASTEXITCODE -ne 0) { throw "Fallo al generar el icono." }
}

# ── fuente del lanzador ────────────────────────────────────────
# El interprete y el script se resuelven RELATIVOS al .exe, no se
# incrustan rutas absolutas: asi el repo se puede mover de sitio sin
# tener que recompilar, y el binario no revela donde vive tu carpeta.
$exe = if ($Consola) { $python } else { $pythonw }
$objetivo = if ($Consola) { "exe" } else { "winexe" }
$modo = if ($Consola) { "ConsoleApplication" } else { "WindowsApplication" }

$fuente = @'
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

// Lanzador de F.R.I.D.A.Y.
//
// Lo unico que hace es arrancar friday.py con el interprete del venv,
// resolviendo las rutas relativas a la posicion del propio .exe. No lee
// configuracion, no toca el vault y no guarda nada.
static class Lanzador
{
    [STAThread]
    static int Main(string[] args)
    {
        string aqui = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
        string interprete = Path.Combine(aqui, @"__INTERPRETE__");
        string guion = Path.Combine(aqui, "friday.py");

        if (!File.Exists(interprete))
        {
            Aviso("No encuentro el entorno virtual.\n\n" +
                  "Esperaba:\n" + interprete + "\n\n" +
                  "Corre scripts\\setup.ps1 para crearlo.");
            return 2;
        }
        if (!File.Exists(guion))
        {
            Aviso("No encuentro friday.py junto al ejecutable.\n\n" +
                  "Este lanzador tiene que vivir en la raiz del proyecto.");
            return 3;
        }

        var psi = new ProcessStartInfo(interprete);
        psi.Arguments = "\"" + guion + "\"" + Argumentos(args);
        psi.WorkingDirectory = aqui;   // el vault y la config son relativos
        psi.UseShellExecute = false;
        try
        {
            Process p = Process.Start(psi);
            // Sin consola el proceso se suelta y el lanzador sale; con
            // consola se espera, que es lo util para depurar.
            if (__ESPERAR__) { p.WaitForExit(); return p.ExitCode; }
            return 0;
        }
        catch (Exception e)
        {
            Aviso("No pude arrancar FRIDAY.\n\n" + e.Message);
            return 1;
        }
    }

    static string Argumentos(string[] args)
    {
        string s = "";
        foreach (string a in args) { s += " \"" + a + "\""; }
        return s;
    }

    static void Aviso(string texto)
    {
        MessageBox.Show(texto, "F.R.I.D.A.Y", MessageBoxButtons.OK,
                        MessageBoxIcon.Warning);
    }
}
'@

$relativo = if ($Consola) { ".venv\Scripts\python.exe" } else { ".venv\Scripts\pythonw.exe" }
$fuente = $fuente.Replace("__INTERPRETE__", $relativo)
$fuente = $fuente.Replace("__ESPERAR__", $(if ($Consola) { "true" } else { "false" }))

$temporal = Join-Path $env:TEMP "friday_lanzador.cs"
Set-Content -Path $temporal -Value $fuente -Encoding UTF8

# ── compilar ───────────────────────────────────────────────────
Write-Host "  · compilando ($modo)" -ForegroundColor DarkGray
$argumentos = @(
    "/nologo",
    "/target:$objetivo",
    "/optimize+",
    "/out:$salida",
    "/reference:System.dll",
    "/reference:System.Windows.Forms.dll"
)
if (Test-Path $rutaIcono) { $argumentos += "/win32icon:$rutaIcono" }
$argumentos += $temporal

& $csc $argumentos
$codigo = $LASTEXITCODE
Remove-Item $temporal -ErrorAction SilentlyContinue
if ($codigo -ne 0) { throw "csc fallo con codigo $codigo" }

$kb = [math]::Round((Get-Item $salida).Length / 1KB, 1)
Write-Host ""
Write-Host "  Listo: FRIDAY.exe ($kb KB)" -ForegroundColor Green
Write-Host "  Doble clic para arrancar. Anclalo a la barra de tareas si quieres." -ForegroundColor DarkGray
Write-Host ""
Write-Host "  No es redistribuible: necesita este repo y su .venv al lado." -ForegroundColor DarkYellow
Write-Host ""
