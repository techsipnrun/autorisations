param(
  [string]$ProjectRoot = "C:\Users\lcalu\Desktop\git-projects\autorisations\autorisations\src",
  [string]$VenvPath    = "C:\Users\lcalu\Desktop\git-projects\autorisations\.venv"
)

$ErrorActionPreference = "Stop"
Set-Location $ProjectRoot

& "$VenvPath\Scripts\Activate.ps1"

# Variables d'env si besoin
$env:DJANGO_SETTINGS_MODULE = "autorisations.settings"
$env:DJANGO_ENV = "dev"

# Logs
$logDir  = Join-Path $ProjectRoot "logs"
if (!(Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logFile = Join-Path $logDir "mails.log"

# Anti chevauchement (en plus du réglage du Planificateur)
$mutex = New-Object System.Threading.Mutex($false, "Global\email-outbox-send")
if (-not $mutex.WaitOne(0)) {
  "[$(Get-Date -Format s)] Déjà en cours, sortie." *>> $logFile
  exit 0
}

# Execution
try {
  & "$VenvPath\Scripts\python.exe" manage.py envoi_mail *>> $logFile
}
catch {
  "[$(Get-Date -Format s)] ERREUR: $($_.Exception.Message)" *>> $logFile
  throw
}
finally {
  $mutex.ReleaseMutex() | Out-Null
}
