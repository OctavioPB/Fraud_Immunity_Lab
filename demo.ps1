#Requires -Version 5.1
<#
.SYNOPSIS
    Fraud Immunity Lab - one-command launcher (Docker Compose).

.DESCRIPTION
    1.  Verifies Docker Desktop is installed and running.
    2.  Creates .env from .env.example if missing and fills in safe dev defaults
        for any blank required variables (secret keys, passwords, Fernet key).
    3.  Runs  docker compose up --build  (pulls + builds images on first run).
    4.  Waits for the FastAPI /health endpoint (depends on Kafka, Redis, Neo4j).
    5.  Runs the seed container - Kafka topics, Neo4j constraints, Pinecone indexes.
    6.  Waits for the Next.js Dashboard to respond.
    7.  Opens the browser at http://localhost:3000 and prints a service summary.

.PARAMETER NoSeed
    Skip the seed step (use if topics/constraints already exist from a prior run).

.PARAMETER NoBuild
    Skip rebuilding Docker images (faster restart when code has not changed).

.EXAMPLE
    .\demo.ps1              # full start: build + seed
    .\demo.ps1 -NoSeed      # restart without re-seeding
    .\demo.ps1 -NoBuild     # restart without rebuilding images
#>

param(
    [switch]$NoSeed  = $false,
    [switch]$NoBuild = $false
)

$RepoRoot = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
Set-Location $RepoRoot

# ---- Helpers -----------------------------------------------------------------

function Write-Step { param([string]$Msg)
    Write-Host ""
    Write-Host "  >>  $Msg" -ForegroundColor Cyan
}
function Write-Ok   { param([string]$Msg) Write-Host "  OK  $Msg" -ForegroundColor Green  }
function Write-Warn { param([string]$Msg) Write-Host "  !!  $Msg" -ForegroundColor Yellow }
function Write-Fail { param([string]$Msg) Write-Host "  XX  $Msg" -ForegroundColor Red    }

function Exit-Script {
    param([string]$Reason)
    Write-Fail $Reason
    Read-Host "`n  Press Enter to exit"
    exit 1
}

function New-FernetKey {
    # 32 random bytes encoded as URL-safe base64 (Fernet spec)
    $bytes = New-Object byte[] 32
    $rng   = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    $b64 = [Convert]::ToBase64String($bytes)
    return $b64.Replace('+', '-').Replace('/', '_')
}

function Wait-Http {
    param([string]$Url, [string]$Label, [int]$MaxAttempts = 50)
    Write-Host "      waiting for $Label ..." -ForegroundColor DarkGray
    for ($i = 1; $i -le $MaxAttempts; $i++) {
        try {
            $r = Invoke-WebRequest -Uri $Url -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
            if ($r.StatusCode -lt 500) { return $true }
        } catch { }
        Write-Host "      attempt $i / $MaxAttempts ..." -ForegroundColor DarkGray
        Start-Sleep 4
    }
    return $false
}

# ---- Banner ------------------------------------------------------------------

Write-Host ""
Write-Host "  ============================================================" -ForegroundColor DarkCyan
Write-Host "     Fraud Immunity Lab  --  Docker Compose Launcher          " -ForegroundColor Cyan
Write-Host "     Kafka . Neo4j . Redis . Airflow . FastAPI . Next.js      " -ForegroundColor DarkCyan
Write-Host "  ============================================================" -ForegroundColor DarkCyan
Write-Host ""

# ---- 1. Check Docker ---------------------------------------------------------

Write-Step "Checking Docker"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Exit-Script "Docker not found. Install Docker Desktop and retry."
}

docker info 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Exit-Script "Docker daemon is not running. Start Docker Desktop and retry."
}

$clientVer = (docker version --format "{{.Client.Version}}" 2>$null).Trim()
Write-Ok "Docker $clientVer"

docker compose version 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Exit-Script "'docker compose' plugin not found. Update Docker Desktop to v4.x or later."
}
Write-Ok "docker compose plugin detected"

# ---- 2. Ensure .env ----------------------------------------------------------

Write-Step "Preparing .env"

$EnvFile     = Join-Path $RepoRoot '.env'
$ExampleFile = Join-Path $RepoRoot '.env.example'

if (-not (Test-Path $EnvFile)) {
    if (Test-Path $ExampleFile) {
        Copy-Item $ExampleFile $EnvFile
        Write-Warn ".env missing - copied from .env.example"
    } else {
        Exit-Script ".env and .env.example are both missing from $RepoRoot"
    }
}

# Parse .env into a hashtable
$rawLines = Get-Content $EnvFile
$envMap   = @{}

foreach ($line in $rawLines) {
    $trimmed = $line.Trim()
    if ((-not $trimmed) -or $trimmed.StartsWith('#')) { continue }
    if ($trimmed -match '^([^=]+)=(.*)$') {
        $k = $matches[1].Trim()
        $v = $matches[2].Trim()
        # Strip surrounding quotes if present
        if (($v.StartsWith('"') -and $v.EndsWith('"')) -or
            ($v.StartsWith("'") -and $v.EndsWith("'"))) {
            $v = $v.Substring(1, $v.Length - 2)
        }
        $envMap[$k] = $v
    }
}

# Fill blank required keys with safe dev defaults
$dirty = $false

function Set-Default {
    param([string]$Key, [string]$Value, [string]$Hint)
    if ((-not $script:envMap.ContainsKey($Key)) -or
        [string]::IsNullOrWhiteSpace($script:envMap[$Key])) {
        $script:envMap[$Key] = $Value
        Write-Warn "$Key is blank - using dev default  ($Hint)"
        $script:dirty = $true
    }
}

Set-Default 'API_SECRET_KEY'                 'local-dev-secret-change-in-prod' 'insecure - dev only'
Set-Default 'DASHBOARD_ADMIN_PASSWORD'       'fraud-lab-2024'                  'dashboard login password'
Set-Default 'NEO4J_PASSWORD'                 'neo4j_local_dev'                 'Neo4j password'
Set-Default 'POSTGRES_PASSWORD'              'airflow'                         'Postgres/Airflow DB password'
Set-Default 'AIRFLOW__WEBSERVER__SECRET_KEY' 'local-airflow-webserver-secret'  'Airflow webserver key'

$fk = $envMap['AIRFLOW__CORE__FERNET_KEY']
if ((-not $fk) -or ($fk.Length -lt 32)) {
    $envMap['AIRFLOW__CORE__FERNET_KEY'] = New-FernetKey
    Write-Warn "AIRFLOW__CORE__FERNET_KEY is blank - generated a new Fernet key"
    $dirty = $true
}

# Rewrite .env preserving comments and blank lines; update matched keys in-place
if ($dirty) {
    $written  = @{}
    $outLines = @()
    foreach ($line in $rawLines) {
        $trimmed = $line.Trim()
        if ((-not $trimmed) -or $trimmed.StartsWith('#')) {
            $outLines += $line
            continue
        }
        if ($trimmed -match '^([^=]+)=') {
            $key = $matches[1].Trim()
            if ($envMap.ContainsKey($key)) {
                $outLines += "$key=$($envMap[$key])"
                $written[$key] = $true
                continue
            }
        }
        $outLines += $line
    }
    # Append any keys added that were not already in the file
    foreach ($kv in $envMap.GetEnumerator()) {
        if (-not $written.ContainsKey($kv.Key)) {
            $outLines += "$($kv.Key)=$($kv.Value)"
        }
    }
    $outLines | Set-Content $EnvFile -Encoding UTF8
    Write-Ok ".env updated with dev defaults"
} else {
    Write-Ok ".env OK"
}

# Export all vars into the current process so docker compose inherits them
foreach ($kv in $envMap.GetEnumerator()) {
    [System.Environment]::SetEnvironmentVariable($kv.Key, $kv.Value, 'Process')
}

# ---- 3. docker compose up ----------------------------------------------------

Write-Step "Starting all services via Docker Compose"
Write-Warn "  First run pulls images and builds API + Dashboard (~3-5 min)."

$buildFlag = if ($NoBuild) { '--no-build' } else { '--build' }
docker compose up -d $buildFlag

if ($LASTEXITCODE -ne 0) {
    Exit-Script "docker compose up failed. See the output above for details."
}
Write-Ok "All containers started (detached)"

# ---- 4. Wait for FastAPI -----------------------------------------------------

Write-Step "Waiting for FastAPI to become healthy"
Write-Host "      FastAPI depends on Kafka + Redis + Neo4j. Allow ~90 s on first run." -ForegroundColor DarkGray

$apiUp = Wait-Http "http://localhost:8000/health" "FastAPI :8000" 50
if ($apiUp) {
    Write-Ok "FastAPI is up  ->  http://localhost:8000"
} else {
    Write-Warn "FastAPI health timeout. Showing recent logs:"
    docker compose logs --tail 30 api
    Write-Warn "Continuing - it may still be starting."
}

# ---- 5. Seed -----------------------------------------------------------------

if (-not $NoSeed) {
    Write-Step "Running seed container"
    Write-Host "      Creates Kafka topics, Neo4j constraints, and Pinecone indexes." -ForegroundColor DarkGray
    docker compose --profile seed run --rm seed
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "Seed exited non-zero - topics/constraints likely already exist (safe)."
    } else {
        Write-Ok "Seed complete"
    }
} else {
    Write-Warn "Seed skipped (-NoSeed flag)"
}

# ---- 6. Wait for Dashboard ---------------------------------------------------

Write-Step "Waiting for Next.js Dashboard"
Write-Host "      Dashboard is a production Next.js build. Allow ~60 s to compile." -ForegroundColor DarkGray

$dashUp = Wait-Http "http://localhost:3000" "Dashboard :3000" 50
if ($dashUp) {
    Write-Ok "Dashboard is up  ->  http://localhost:3000"
} else {
    Write-Warn "Dashboard health timeout. Showing recent logs:"
    docker compose logs --tail 30 dashboard
    Write-Warn "Continuing - try refreshing the browser in a moment."
}

# ---- 7. Open browser + summary -----------------------------------------------

Start-Process "http://localhost:3000"

$adminPwd = $envMap['DASHBOARD_ADMIN_PASSWORD']
$neo4jPwd = $envMap['NEO4J_PASSWORD']

$div = "  " + ("=" * 62)
Write-Host ""
Write-Host $div -ForegroundColor DarkCyan
Write-Host "  Service                URL                              " -ForegroundColor White
Write-Host $div -ForegroundColor DarkCyan
Write-Host "  Dashboard              http://localhost:3000            " -ForegroundColor Green
Write-Host "  FastAPI                http://localhost:8000            " -ForegroundColor Green
Write-Host "  API Docs (Swagger)     http://localhost:8000/docs       " -ForegroundColor Cyan
Write-Host "  Airflow                http://localhost:8080            " -ForegroundColor Cyan
Write-Host "  Neo4j Browser          http://localhost:7474            " -ForegroundColor Cyan
Write-Host "  Redis                  localhost:6379                   " -ForegroundColor DarkGray
Write-Host "  Kafka                  localhost:9092                   " -ForegroundColor DarkGray
Write-Host $div -ForegroundColor DarkCyan
Write-Host ""
Write-Host "  Credentials" -ForegroundColor White
Write-Host "  Dashboard login   admin / $adminPwd" -ForegroundColor Yellow
Write-Host "  Airflow login     admin / admin" -ForegroundColor Yellow
Write-Host "  Neo4j login       neo4j / $neo4jPwd" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Useful commands" -ForegroundColor White
Write-Host "  Stop stack        docker compose down" -ForegroundColor Gray
Write-Host "  View all logs     docker compose logs -f" -ForegroundColor Gray
Write-Host "  View API logs     docker compose logs -f api" -ForegroundColor Gray
Write-Host "  Wipe all data     docker compose down -v" -ForegroundColor Gray
Write-Host "  Restart (fast)    .\demo.ps1 -NoBuild -NoSeed" -ForegroundColor Gray
Write-Host $div -ForegroundColor DarkCyan
Write-Host ""
