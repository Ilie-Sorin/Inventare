<#
.SYNOPSIS
    Instalează aplicația de inventariere ca serviciu Windows (NSSM + Waitress) și backup-ul zilnic.

.DESCRIPTION
    Se rulează din PowerShell pornit ca Administrator, după ce aplicația a fost copiată pe server
    și dependențele au fost instalate în .venv (vezi README.md). Scriptul:
      1. aplică migrările bazei de date;
      2. instalează (sau reinstalează) serviciul care pornește Waitress pe 127.0.0.1:<Port>,
         în spatele IIS / Caddy, cu repornire automată și jurnal rotit în logs\;
      3. creează sarcina programată pentru backup-ul zilnic;
      4. verifică faptul că aplicația răspunde.
    Cu -Simulare doar afișează ce ar face, fără să modifice nimic.

.EXAMPLE
    .\scripts\instalare_serviciu.ps1 -Nssm C:\nssm\nssm.exe -Port 8080 -DirectorBackup D:\Backup\Inventare

.EXAMPLE
    .\scripts\instalare_serviciu.ps1 -Dezinstalare
#>
[CmdletBinding()]
param(
    [string]$Nssm = "nssm.exe",
    [string]$NumeServiciu = "Inventare",
    [int]$Port = 8080,
    [int]$Fire = 8,
    [string]$DirectorBackup = "D:\Backup\Inventare",
    [string]$OraBackup = "02:00",
    [int]$PastreazaBackup = 30,
    # Fără proxy HTTPS în față (doar pentru probe): cookie-urile nu mai cer HTTPS.
    [switch]$FaraProxy,
    [switch]$Dezinstalare,
    [switch]$Simulare
)

$ErrorActionPreference = "Stop"
$Radacina = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Radacina ".venv\Scripts\python.exe"
$Waitress = Join-Path $Radacina ".venv\Scripts\waitress-serve.exe"
$NumeSarcina = "$NumeServiciu - backup zilnic"

function Pas([string]$Text) { Write-Host "==> $Text" -ForegroundColor Cyan }

function Ruleaza([string]$Exe, [string[]]$Argumente, [switch]$IgnoraEroarea) {
    if ($Simulare) {
        Write-Host "    [simulare] $Exe $($Argumente -join ' ')"
        return
    }
    & $Exe @Argumente
    if ($LASTEXITCODE -ne 0 -and -not $IgnoraEroarea) {
        throw "Comanda a eșuat (cod $LASTEXITCODE): $Exe $($Argumente -join ' ')"
    }
}

function Este-Administrator {
    $identitate = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    return $identitate.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not $Simulare -and -not (Este-Administrator)) {
    throw "Rulați scriptul dintr-un PowerShell pornit ca Administrator."
}
if (-not $Simulare -and -not (Get-Command $Nssm -ErrorAction SilentlyContinue)) {
    throw "Nu găsesc NSSM ($Nssm). Descărcați-l de la https://nssm.cc și dați calea cu -Nssm."
}

if ($Dezinstalare) {
    Pas "Opresc și șterg serviciul $NumeServiciu"
    Ruleaza $Nssm @("stop", $NumeServiciu) -IgnoraEroarea
    Ruleaza $Nssm @("remove", $NumeServiciu, "confirm") -IgnoraEroarea
    Pas "Șterg sarcina programată '$NumeSarcina'"
    if (-not $Simulare) { Unregister-ScheduledTask -TaskName $NumeSarcina -Confirm:$false -ErrorAction SilentlyContinue }
    Write-Host "Gata. Baza de date și fișierele din instance\ au rămas neatinse." -ForegroundColor Green
    return
}

foreach ($fisier in @($Python, $Waitress)) {
    if (-not (Test-Path $fisier)) { throw "Lipsește $fisier. Creați întâi mediul .venv (vezi README.md)." }
}

Pas "Aplic migrările bazei de date"
Push-Location $Radacina
try { Ruleaza $Python @("-m", "flask", "--app", "inventar", "db", "upgrade") } finally { Pop-Location }

Pas "Instalez serviciul $NumeServiciu (Waitress pe 127.0.0.1:$Port)"
if (Get-Service -Name $NumeServiciu -ErrorAction SilentlyContinue) {
    Ruleaza $Nssm @("stop", $NumeServiciu) -IgnoraEroarea
    Ruleaza $Nssm @("remove", $NumeServiciu, "confirm")
}
# În spatele proxy-ului, Waitress preia din antetele proxy-ului local IP-ul real (pentru jurnal), schema
# (https) și numele public al gazdei. Fără gazda publică, protecția CSRF pe HTTPS ar refuza formularele
# („The referrer does not match the host”), pentru că browserul și aplicația ar vedea gazde diferite.
$parametri = "--listen=127.0.0.1:$Port --threads=$Fire --trusted-proxy=127.0.0.1 " +
             "`"--trusted-proxy-headers=x-forwarded-for x-forwarded-proto x-forwarded-host`" " +
             "--clear-untrusted-proxy-headers inventar.wsgi:app"
$jurnale = Join-Path $Radacina "logs"
if (-not $Simulare) { New-Item -ItemType Directory -Force $jurnale | Out-Null }
$cookieSecure = if ($FaraProxy) { "0" } else { "1" }

Ruleaza $Nssm @("install", $NumeServiciu, $Waitress, $parametri)
Ruleaza $Nssm @("set", $NumeServiciu, "AppDirectory", $Radacina)
Ruleaza $Nssm @("set", $NumeServiciu, "AppEnvironmentExtra", "INVENTAR_COOKIE_SECURE=$cookieSecure")
Ruleaza $Nssm @("set", $NumeServiciu, "DisplayName", "Liste de inventariere")
Ruleaza $Nssm @("set", $NumeServiciu, "Description", "Aplicația web pentru listele de inventariere (Waitress).")
Ruleaza $Nssm @("set", $NumeServiciu, "Start", "SERVICE_AUTO_START")
Ruleaza $Nssm @("set", $NumeServiciu, "AppStdout", (Join-Path $jurnale "serviciu.log"))
Ruleaza $Nssm @("set", $NumeServiciu, "AppStderr", (Join-Path $jurnale "serviciu.log"))
Ruleaza $Nssm @("set", $NumeServiciu, "AppRotateFiles", "1")
Ruleaza $Nssm @("set", $NumeServiciu, "AppRotateOnline", "1")
Ruleaza $Nssm @("set", $NumeServiciu, "AppRotateBytes", "10485760")
Ruleaza $Nssm @("set", $NumeServiciu, "AppExit", "Default", "Restart")
Ruleaza $Nssm @("set", $NumeServiciu, "AppRestartDelay", "5000")
Ruleaza $Nssm @("start", $NumeServiciu)

Pas "Creez sarcina programată '$NumeSarcina' (zilnic la $OraBackup, în $DirectorBackup)"
$argumenteBackup = "`"$(Join-Path $Radacina 'scripts\backup.py')`" --destinatie `"$DirectorBackup`" --pastreaza $PastreazaBackup"
if ($Simulare) {
    Write-Host "    [simulare] $Python $argumenteBackup"
} else {
    New-Item -ItemType Directory -Force $DirectorBackup | Out-Null
    $actiune = New-ScheduledTaskAction -Execute $Python -Argument $argumenteBackup -WorkingDirectory $Radacina
    $declansator = New-ScheduledTaskTrigger -Daily -At $OraBackup
    $cont = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    $setari = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)
    Register-ScheduledTask -TaskName $NumeSarcina -Action $actiune -Trigger $declansator -Principal $cont `
        -Settings $setari -Force | Out-Null
}

Pas "Verific că aplicația răspunde"
if (-not $Simulare) {
    $raspuns = $null
    for ($i = 0; $i -lt 15 -and -not $raspuns; $i++) {
        Start-Sleep -Seconds 1
        try { $raspuns = Invoke-WebRequest "http://127.0.0.1:$Port/autentificare" -UseBasicParsing -TimeoutSec 5 } catch { }
    }
    if (-not $raspuns -or $raspuns.StatusCode -ne 200) {
        throw "Aplicația nu răspunde pe portul $Port. Vedeți $jurnale\serviciu.log."
    }
}
Write-Host "Gata. Serviciul $NumeServiciu rulează pe http://127.0.0.1:$Port (publicat prin IIS / Caddy)." -ForegroundColor Green
