$ErrorActionPreference = "Stop"
$ProjectDir = $PSScriptRoot
Set-Location $ProjectDir

# Public Google Drive file IDs used only when the corresponding CSV is missing.
$HvstatDriveId = "100DQ_Pkb8uZMASgd5KQ63Rrxs02-sO42"
$MeteoDriveId = "1xvDXCJDmDUogX5ZxwPLQ8_d09FeIeIcy"

function Stop-Setup([string]$Message) {
    Write-Error "Erreur : $Message"
    exit 1
}

# Prefer the Windows Python launcher, with python.exe as a fallback.
$PythonLauncher = Get-Command py -ErrorAction SilentlyContinue
$PythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($PythonLauncher) {
    & $PythonLauncher.Source -3 --version *> $null
    if ($LASTEXITCODE -eq 0) {
        $Python = $PythonLauncher.Source
        $PythonArgs = @("-3")
    }
}
if (-not $Python -and $PythonCommand) {
    & $PythonCommand.Source --version *> $null
    if ($LASTEXITCODE -eq 0) {
        $Python = $PythonCommand.Source
        $PythonArgs = @()
    }
}
if (-not $Python) {
    Stop-Setup "Python 3 est requis. Installez-le puis relancez setup.ps1."
}

# Require Docker Compose v2 and an already-running Docker Desktop engine.
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Stop-Setup "Docker CLI est introuvable. Installez Docker Desktop puis relancez setup.ps1."
}
docker compose version *> $null
if ($LASTEXITCODE -ne 0) {
    Stop-Setup "Docker Compose v2 est requis (commande 'docker compose')."
}
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Stop-Setup "Le moteur Docker ne semble pas demarre. Demarrez Docker Desktop, puis relancez setup.ps1."
}

# Create the isolated Python environment once, then install project dependencies.
New-Item -ItemType Directory -Force -Path (Join-Path $ProjectDir "dags/data") | Out-Null
$VenvPython = Join-Path $ProjectDir ".venv/Scripts/python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "Creation de l'environnement Python..."
    & $Python @PythonArgs -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Stop-Setup "Impossible de creer .venv. Verifiez l'installation de Python 3."
    }
}
if (-not (Test-Path $VenvPython)) {
    Stop-Setup "L'interpreteur Python de .venv est introuvable."
}

Write-Host "Installation des dependances Python..."
& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { Stop-Setup "La mise a niveau de pip a echoue." }
& $VenvPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { Stop-Setup "L'installation des dependances a echoue." }

# Keep existing data untouched; download a missing CSV to the Airflow-mounted folder.
function Get-DriveCsv([string]$FileName, [string]$DriveId) {
    $Destination = Join-Path $ProjectDir "dags/data/$FileName"
    if ((Test-Path $Destination) -and (Get-Item $Destination).Length -gt 0) {
        Write-Host "CSV deja present : dags/data/$FileName"
        return
    }

    Write-Host "Telechargement depuis Google Drive : $FileName"
    & $VenvPython -c "import gdown, sys; result = gdown.download(id=sys.argv[1], output=sys.argv[2]); sys.exit(0 if result else 1)" $DriveId $Destination
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $Destination) -or (Get-Item $Destination).Length -eq 0) {
        Remove-Item $Destination -Force -ErrorAction SilentlyContinue
        Stop-Setup "Echec du telechargement de $FileName. Verifiez que le fichier Drive est accessible a toute personne disposant du lien."
    }
}

Get-DriveCsv "hvstat_africa_data_v1.0.csv" $HvstatDriveId
Get-DriveCsv "meteo_admin2_2010_2022.csv" $MeteoDriveId

# Preserve local settings and initialize the template only for a new checkout.
$EnvPath = Join-Path $ProjectDir ".env"
if (-not (Test-Path $EnvPath)) {
    Copy-Item (Join-Path $ProjectDir ".env.example") $EnvPath
    Write-Host "Fichier .env cree depuis .env.example."
}
$EnvContent = Get-Content $EnvPath -Raw
# Do not rotate a key already used to encrypt values in the Airflow database.
if ($EnvContent -notmatch '(?m)^[ \t]*FERNET_KEY[ \t]*=[ \t]*[^ \t\r\n#]+') {
    $KeyBytes = New-Object byte[] 32
    $Random = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $Random.GetBytes($KeyBytes) } finally { $Random.Dispose() }
    $FernetKey = [Convert]::ToBase64String($KeyBytes).Replace('+', '-').Replace('/', '_')
    Add-Content -Path $EnvPath -Value "`nFERNET_KEY=$FernetKey" -Encoding Ascii
    Write-Host "Cle Fernet generee et ajoutee a .env."
}

# Start Airflow and PostgreSQL after local prerequisites are ready.
Write-Host "Demarrage des services Docker Compose..."
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { Stop-Setup "Le demarrage de Docker Compose a echoue." }
Write-Host "Setup termine. Airflow est disponible sur http://localhost:8080."
