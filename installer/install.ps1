<#
.SYNOPSIS
  Instala IA-metrics: elige qué medir (Claude Code, OpenCode o ambos), genera .env, configura la
  telemetría de Claude Code si hace falta, migra las pilas antiguas y arranca la pila.
  Con -Update la actualiza y con -Uninstall la desinstala.

.EXAMPLE
  .\install.ps1                         # interactivo
  .\install.ps1 -Tools claude,opencode  # sin preguntas sobre herramientas
  .\install.ps1 -Tools opencode -NoStart
  .\install.ps1 -Update                 # código (git pull, si se puede), imágenes y arranque
  .\install.ps1 -Uninstall              # contenedores, variables de settings.json y acceso directo
  .\install.ps1 -Uninstall -RemoveData  # además, borra el historial (volúmenes de Docker)
  .\install.ps1 -Uninstall -Force       # sin preguntas (el historial solo se borra con -RemoveData)
#>
[CmdletBinding()]
param(
  [ValidateSet('claude', 'opencode')]
  [string[]]$Tools,
  [switch]$NoStart,
  [switch]$SkipClaudeSettings,
  [switch]$SkipMigration,
  [switch]$NoShortcut,
  [switch]$Update,
  [switch]$Uninstall,
  [switch]$RemoveData,
  [switch]$Force
)

# 'Continue': en Windows PowerShell 5.1, con 'Stop' la salida de error de docker redirigida aborta el script.
# Los fallos se comprueban con $LASTEXITCODE y -ErrorAction Stop donde importa.
$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $Root '.env'
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Say($text, $color = 'Gray') { Write-Host $text -ForegroundColor $color }
function Ask-YesNo($question, [bool]$default = $true) {
  $suffix = if ($default) { '[S/n]' } else { '[s/N]' }
  $a = Read-Host "$question $suffix"
  if ([string]::IsNullOrWhiteSpace($a)) { return $default }
  return $a.Trim().ToLower().StartsWith('s') -or $a.Trim().ToLower().StartsWith('y')
}

function Confirm-Step($question, [bool]$default = $true) {
  # Con -Force no se pregunta: se hace el paso
  if ($Force) { return $true }
  return (Ask-YesNo $question $default)
}

function Backup-Settings($settings) {
  if (-not (Test-Path $settings)) { return }
  $bk = Join-Path $Root 'installer\backups'
  New-Item -ItemType Directory -Force $bk | Out-Null
  $copy = Join-Path $bk ('settings.json.{0:yyyyMMdd-HHmmss}.bak' -f (Get-Date))
  Copy-Item $settings $copy -ErrorAction Stop
  Say "Copia guardada en $copy"
}

# ------------------------------------------------------------------ .env
function Read-EnvFile {
  $map = [ordered]@{}
  if (Test-Path $EnvFile) {
    foreach ($line in [IO.File]::ReadAllLines($EnvFile)) {
      if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') { $map[$Matches[1]] = $Matches[2] }
    }
  }
  return $map
}

function Set-EnvValue($key, $value) {
  # Cambia o añade una clave conservando el resto del fichero (comentarios incluidos)
  # La lista se crea aparte: asignada desde un if, PowerShell la convierte en un array de tamaño fijo y Add falla
  $src = if (Test-Path $EnvFile) { $EnvFile } else { Join-Path $Root '.env.example' }
  $lines = New-Object 'System.Collections.Generic.List[string]'
  $lines.AddRange([string[]][IO.File]::ReadAllLines($src))
  $done = $false
  for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match "^\s*#?\s*$key\s*=") {
      if (-not $done) { $lines[$i] = "$key=$value"; $done = $true }
    }
  }
  if (-not $done) { $lines.Add("$key=$value") }
  [IO.File]::WriteAllLines($EnvFile, $lines, $Utf8NoBom)
}

function New-Password {
  $chars = 'abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789'
  $bytes = New-Object byte[] 20
  [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  -join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] })
}

# ------------------------------------------------------------------ zona horaria
# Windows usa sus propios nombres de zona; los colectores necesitan el nombre IANA (ADR 0002).
$WindowsToIana = @{
  'Romance Standard Time' = 'Europe/Madrid'; 'W. Europe Standard Time' = 'Europe/Berlin'
  'Central Europe Standard Time' = 'Europe/Budapest'; 'Central European Standard Time' = 'Europe/Warsaw'
  'GMT Standard Time' = 'Europe/London'; 'Greenwich Standard Time' = 'Atlantic/Reykjavik'
  'Canary Standard Time' = 'Atlantic/Canary'; 'E. Europe Standard Time' = 'Europe/Chisinau'
  'FLE Standard Time' = 'Europe/Kiev'; 'GTB Standard Time' = 'Europe/Bucharest'
  'Eastern Standard Time' = 'America/New_York'; 'Central Standard Time' = 'America/Chicago'
  'Mountain Standard Time' = 'America/Denver'; 'Pacific Standard Time' = 'America/Los_Angeles'
  'Central Standard Time (Mexico)' = 'America/Mexico_City'; 'SA Pacific Standard Time' = 'America/Bogota'
  'Argentina Standard Time' = 'America/Argentina/Buenos_Aires'; 'Pacific SA Standard Time' = 'America/Santiago'
  'E. South America Standard Time' = 'America/Sao_Paulo'; 'UTC' = 'UTC'
}

function Get-IanaTimeZone {
  $id = [System.TimeZoneInfo]::Local.Id
  $iana = $null
  try {  # .NET 6+ (PowerShell 7)
    $m = [System.TimeZoneInfo].GetMethod('TryConvertWindowsIdToIanaId', [type[]]@([string], [string].MakeByRefType()))
    if ($m) { $args2 = @($id, $null); if ($m.Invoke($null, $args2)) { $iana = $args2[1] } }
  } catch { }
  if (-not $iana -and $WindowsToIana.ContainsKey($id)) { $iana = $WindowsToIana[$id] }
  if (-not $iana -and $id -match '^[A-Za-z]+/[A-Za-z_/+-]+$') { $iana = $id }
  return $iana
}

# ------------------------------------------------------------------ Docker
function Test-Docker { docker info *> $null; return ($LASTEXITCODE -eq 0) }

function Start-DockerIfNeeded {
  if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'No se encuentra Docker. Instala Docker Desktop (o Rancher Desktop / Podman con docker compose) y vuelve a ejecutar el instalador.'
  }
  if (Test-Docker) { return }
  $dd = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
  if (Test-Path $dd) { Say 'Docker no está en marcha. Iniciando Docker Desktop...'; Start-Process $dd }
  for ($n = 1; $n -le 36; $n++) {
    Start-Sleep -Seconds 5
    if (Test-Docker) { return }
    Say "Esperando a Docker... ($n/36)"
  }
  throw 'Docker no arrancó a tiempo. Ábrelo a mano y vuelve a ejecutar el instalador.'
}

# ------------------------------------------------------------------ detección
$HomeDir = $env:USERPROFILE; if (-not $HomeDir) { $HomeDir = $HOME }
$ClaudeDir = Join-Path $HomeDir '.claude'
$OpenCodeDb = Join-Path $HomeDir '.local\share\opencode\opencode.db'

function Select-Tools {
  $hasClaude = Test-Path (Join-Path $ClaudeDir 'projects')
  $hasOpen = Test-Path $OpenCodeDb
  Say ''
  Say '¿Qué quieres medir?' 'Cyan'
  Say ("  1) Claude Code   {0}" -f $(if ($hasClaude) { '(detectado)' } else { '(no detectado)' }))
  Say ("  2) OpenCode      {0}" -f $(if ($hasOpen) { '(detectado)' } else { '(no detectado)' }))
  Say  '  3) Ambos'
  $def = if ($hasClaude -and $hasOpen) { '3' } elseif ($hasOpen) { '2' } else { '1' }
  $a = Read-Host "Elige 1, 2 o 3 [$def]"
  if ([string]::IsNullOrWhiteSpace($a)) { $a = $def }
  switch ($a.Trim()) {
    '1' { return @('claude') }
    '2' { return @('opencode') }
    '3' { return @('claude', 'opencode') }
    default { throw "Opción no válida: $a" }
  }
}

# ------------------------------------------------------------------ Claude Code: telemetría
$TelemetryEnv = [ordered]@{
  CLAUDE_CODE_ENABLE_TELEMETRY                      = '1'
  OTEL_METRICS_EXPORTER                             = 'otlp'
  OTEL_LOGS_EXPORTER                                = 'otlp'
  OTEL_EXPORTER_OTLP_PROTOCOL                       = 'grpc'
  OTEL_EXPORTER_OTLP_ENDPOINT                       = 'http://localhost:4317'
  OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE = 'cumulative'
}

function Set-ClaudeTelemetry {
  $settings = Join-Path $ClaudeDir 'settings.json'
  $obj = $null
  if (Test-Path $settings) {
    $raw = [IO.File]::ReadAllText($settings)
    if ($raw.Trim()) { $obj = $raw | ConvertFrom-Json -ErrorAction Stop }
  }
  if (-not $obj) { $obj = New-Object psobject }
  if (-not ($obj.PSObject.Properties.Name -contains 'env')) { $obj | Add-Member -NotePropertyName env -NotePropertyValue (New-Object psobject) }

  $changes = @()
  foreach ($k in $TelemetryEnv.Keys) {
    $cur = $obj.env.PSObject.Properties[$k]
    if (-not $cur) { $changes += "  + $k=$($TelemetryEnv[$k])" }
    elseif ([string]$cur.Value -ne $TelemetryEnv[$k]) { $changes += "  ~ $k=$($cur.Value)  ->  $($TelemetryEnv[$k])" }
  }
  if (-not $changes) { Say 'La telemetría de Claude Code ya está configurada.' 'Green'; return }

  Say ''
  Say "Para medir Claude Code hay que activar su telemetría en $settings :" 'Cyan'
  $changes | ForEach-Object { Say $_ }
  if (-not (Ask-YesNo '¿Aplico estos cambios? (se guarda antes una copia)')) {
    Say 'No se ha tocado settings.json. Sin telemetría no habrá coste por llamada; consulta docs/claude-code.md para hacerlo a mano.' 'Yellow'
    return
  }
  Backup-Settings $settings
  foreach ($k in $TelemetryEnv.Keys) {
    if ($obj.env.PSObject.Properties[$k]) { $obj.env.$k = $TelemetryEnv[$k] }
    else { $obj.env | Add-Member -NotePropertyName $k -NotePropertyValue $TelemetryEnv[$k] }
  }
  New-Item -ItemType Directory -Force $ClaudeDir | Out-Null
  [IO.File]::WriteAllText($settings, ($obj | ConvertTo-Json -Depth 100), $Utf8NoBom)
  Say 'Telemetría activada. Reinicia Claude Code para que empiece a enviar datos.' 'Green'
}

# Retención de las conversaciones (cleanupPeriodDays). Desde ADR 0002 el colector archiva el uso de cada
# sesión, así que borrar conversaciones ya no borra su coste del dashboard. Más días solo dan margen si la
# pila pasa mucho tiempo parada (lo que Claude Code borre antes de que el colector lo lea, se pierde).
$RetentionDays = 90

function Set-ClaudeRetention {
  $settings = Join-Path $ClaudeDir 'settings.json'
  $obj = $null
  if (Test-Path $settings) {
    $raw = [IO.File]::ReadAllText($settings)
    if ($raw.Trim()) { $obj = $raw | ConvertFrom-Json -ErrorAction Stop }
  }
  if (-not $obj) { $obj = New-Object psobject }
  $current = 30
  if ($obj.PSObject.Properties['cleanupPeriodDays']) { $current = [int]$obj.cleanupPeriodDays }
  if ($current -ge $RetentionDays) { return }
  Say ''
  Say "Claude Code borra las conversaciones de más de $current días (cleanupPeriodDays)." 'Cyan'
  Say 'IA-metrics guarda el uso de cada sesión en cuanto la lee, así que solo pierdes lo que Claude Code'
  Say "borre mientras la pila está parada. Subirlo a $RetentionDays días da más margen, pero conserva más tiempo en"
  Say 'disco el texto completo de las conversaciones (código, datos, lo que pegues en el prompt).'
  if (-not (Ask-YesNo "¿Subir cleanupPeriodDays a $RetentionDays días? (se guarda antes una copia)" $false)) { return }
  if (Test-Path $settings) {
    $bk = Join-Path $Root 'installer\backups'
    New-Item -ItemType Directory -Force $bk | Out-Null
    Copy-Item $settings (Join-Path $bk ('settings.json.{0:yyyyMMdd-HHmmss}.bak' -f (Get-Date))) -ErrorAction Stop
  }
  if ($obj.PSObject.Properties['cleanupPeriodDays']) { $obj.cleanupPeriodDays = $RetentionDays }
  else { $obj | Add-Member -NotePropertyName cleanupPeriodDays -NotePropertyValue $RetentionDays }
  New-Item -ItemType Directory -Force $ClaudeDir | Out-Null
  [IO.File]::WriteAllText($settings, ($obj | ConvertTo-Json -Depth 100), $Utf8NoBom)
  Say "cleanupPeriodDays = $RetentionDays." 'Green'
}

# ------------------------------------------------------------------ migración de las pilas antiguas
function Get-ComposeProjectContainers($project) {
  $ids = docker ps -a -q --filter "label=com.docker.compose.project=$project" 2>$null
  return @($ids | Where-Object { $_ })
}

function Test-VolumeEmpty($name) {
  $out = docker run --rm -v "${name}:/v" alpine:3.20 sh -c 'ls -A /v | head -1' 2>$null
  return [string]::IsNullOrWhiteSpace($out)
}

function Copy-Volume($from, $to) {
  docker volume create $to | Out-Null
  if (-not (Test-VolumeEmpty $to)) { Say "  $to ya tiene datos: no se sobrescribe." 'Yellow'; return }
  docker run --rm -v "${from}:/from:ro" -v "${to}:/to" alpine:3.20 sh -c 'cp -a /from/. /to/'
  if ($LASTEXITCODE -ne 0) { throw "No se pudo copiar $from a $to" }
  Say "  $from -> $to"
}

function Invoke-Migration($selected) {
  $volumes = @(docker volume ls -q 2>$null)
  $old = @('claude-metrics', 'opencode-metrics') | Where-Object { (Get-ComposeProjectContainers $_).Count -gt 0 -or ($volumes -like "$_*") }
  if (-not $old) { return }

  Say ''
  Say "Se han encontrado las pilas anteriores: $($old -join ', ')." 'Cyan'
  Say 'Usan los mismos puertos que IA-metrics, así que hay que pararlas. Sus volúmenes no se borran.'
  if (-not (Ask-YesNo '¿Las paro y migro su historial a IA-metrics?')) {
    Say 'Sin parar las pilas antiguas, la nueva no podrá arrancar por conflicto de puertos.' 'Yellow'
    return
  }
  foreach ($p in $old) {
    $c = Get-ComposeProjectContainers $p
    if ($c.Count) { docker stop $c | Out-Null; Say "  Parada la pila $p" }
  }
  # Solo el historial de Claude Code merece migrarse: el de OpenCode se reconstruye desde opencode.db
  if ($selected -contains 'claude') {
    foreach ($v in @('prometheus-data', 'loki-data', 'coach-data')) {
      if ($volumes -contains "claude-metrics_$v") { Copy-Volume "claude-metrics_$v" "ia-metrics_$v" }
    }
  }
}

function Remove-ClaudeTelemetry {
  # Quita de settings.json solo las variables que puso el instalador y con el mismo valor
  $settings = Join-Path $ClaudeDir 'settings.json'
  if (-not (Test-Path $settings)) { return }
  $raw = [IO.File]::ReadAllText($settings)
  if (-not $raw.Trim()) { return }
  $obj = $raw | ConvertFrom-Json -ErrorAction Stop
  if (-not ($obj.PSObject.Properties.Name -contains 'env') -or -not $obj.env) { return }
  $keys = @($TelemetryEnv.Keys | Where-Object { $obj.env.PSObject.Properties[$_] -and [string]$obj.env.$_ -eq $TelemetryEnv[$_] })
  if (-not $keys) { Say 'settings.json no tiene las variables de telemetría del instalador.' 'Gray'; return }
  Say ''
  Say "Variables de telemetría que añadió el instalador en $settings :" 'Cyan'
  $keys | ForEach-Object { Say "  - $_" }
  if (-not (Confirm-Step '¿Las quito? (se guarda antes una copia)')) { Say 'settings.json no se ha tocado.' 'Yellow'; return }
  Backup-Settings $settings
  foreach ($k in $keys) { $obj.env.PSObject.Properties.Remove($k) }
  if (@($obj.env.PSObject.Properties).Count -eq 0) { $obj.PSObject.Properties.Remove('env') }
  [IO.File]::WriteAllText($settings, ($obj | ConvertTo-Json -Depth 100), $Utf8NoBom)
  Say 'Telemetría desactivada. Reinicia Claude Code para que deje de enviar datos.' 'Green'
  if ($obj.PSObject.Properties['cleanupPeriodDays']) {
    Say "cleanupPeriodDays sigue en $($obj.cleanupPeriodDays) días; si lo subió el instalador, el valor anterior está en installer\backups." 'Gray'
  }
}

# ------------------------------------------------------------------ actualizar y desinstalar
function Invoke-Update {
  Say '== Actualizar IA-metrics ==' 'Cyan'
  Start-DockerIfNeeded
  Push-Location $Root
  try {
    if ((Test-Path (Join-Path $Root '.git')) -and (Get-Command git -ErrorAction SilentlyContinue)) {
      $remote = git remote 2>$null
      $dirty = git status --porcelain 2>$null
      if (-not $remote) { Say 'El repositorio no tiene remoto: no se descarga código nuevo.' 'Gray' }
      elseif ($dirty) { Say 'Hay cambios locales sin commit: no se descarga código nuevo (git pull) para no mezclarlos.' 'Yellow' }
      elseif (Confirm-Step '¿Descargo la última versión del código? (git pull --ff-only)') {
        git pull --ff-only
        if ($LASTEXITCODE -ne 0) { Say 'git pull no pudo avanzar (ramas divergentes o sin red): se sigue con el código actual.' 'Yellow' }
      }
    }
    Say 'Descargando las imágenes de Docker...'
    docker compose pull
    if ($LASTEXITCODE -ne 0) { throw 'docker compose pull falló. Revisa la conexión y la salida anterior.' }
    docker compose up -d --remove-orphans
    if ($LASTEXITCODE -ne 0) { throw 'docker compose up falló. Revisa la salida anterior.' }
    Say 'Esperando a que los servicios estén listos...'
    docker compose up -d --wait --wait-timeout 180 *> $null
    if ($LASTEXITCODE -ne 0) { Say 'Algún servicio no está sano todavía. Revísalo con: docker compose ps' 'Yellow' }
  } finally { Pop-Location }
  Say 'IA-metrics actualizado. El historial se conserva.' 'Green'
}

function Invoke-Uninstall {
  Say '== Desinstalar IA-metrics ==' 'Cyan'
  Say 'Se pararán y eliminarán los contenedores de IA-metrics. La carpeta del proyecto y .env no se borran.'
  if (-not (Confirm-Step '¿Continuar?' $false)) { Say 'Cancelado.' 'Yellow'; return }
  $removeData = $RemoveData
  if (-not $removeData -and -not $Force) {
    $removeData = Ask-YesNo '¿Borrar también el historial (volúmenes de Prometheus, Loki, Grafana y coach.db)? No se puede deshacer.' $false
  }
  Start-DockerIfNeeded
  Push-Location $Root
  try {
    if ($removeData) { docker compose --profile claude --profile opencode down --remove-orphans -v }
    else { docker compose --profile claude --profile opencode down --remove-orphans }
    if ($LASTEXITCODE -ne 0) { throw 'docker compose down falló. Revisa la salida anterior.' }
  } finally { Pop-Location }
  if ($removeData) { Say 'Contenedores y volúmenes eliminados.' 'Green' }
  else { Say 'Contenedores eliminados; el historial sigue en los volúmenes ia-metrics_* (se recupera al reinstalar).' 'Green' }
  Remove-ClaudeTelemetry
  $lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'IA-metrics.lnk'
  if (Test-Path $lnk) { Remove-Item $lnk -ErrorAction SilentlyContinue; Say "Acceso directo eliminado: $lnk" }
  Say ''
  Say 'IA-metrics desinstalado. Para quitarlo del todo, borra la carpeta del proyecto.' 'Green'
}

# ------------------------------------------------------------------ acceso directo
function New-Shortcut {
  $desk = [Environment]::GetFolderPath('Desktop')
  $lnk = Join-Path $desk 'IA-metrics.lnk'
  $ws = New-Object -ComObject WScript.Shell
  $s = $ws.CreateShortcut($lnk)
  $s.TargetPath = Join-Path $Root 'Iniciar-metricas.bat'
  $s.WorkingDirectory = $Root
  $ico = Join-Path $Root 'installer\metricas.ico'
  if (Test-Path $ico) { $s.IconLocation = $ico }
  $s.Save()
  Say "Acceso directo creado en el escritorio: $lnk"
}

# ================================================================== main
trap { Say "ERROR: $_" 'Red'; exit 1 }
if ($Update -and $Uninstall) { throw 'Usa -Update o -Uninstall, no los dos.' }
if ($RemoveData -and -not $Uninstall) { throw '-RemoveData solo vale con -Uninstall.' }
if ($Update) { Invoke-Update; exit 0 }
if ($Uninstall) { Invoke-Uninstall; exit 0 }
Say '== Instalador de IA-metrics ==' 'Cyan'
Start-DockerIfNeeded

if (-not $Tools) { $Tools = Select-Tools }
$profiles = ($Tools | Sort-Object -Unique) -join ','
Say "Herramientas: $profiles" 'Green'

$envMap = Read-EnvFile
if (-not $envMap.Contains('GRAFANA_ADMIN_PASSWORD') -or $envMap['GRAFANA_ADMIN_PASSWORD'] -in @('', 'change-me', 'change_me')) {
  $pw = New-Password
  Set-EnvValue 'GRAFANA_ADMIN_PASSWORD' $pw
  Say "Contraseña de Grafana generada (usuario admin): $pw" 'Yellow'
  Say 'Guárdala: también está en el fichero .env.'
}
Set-EnvValue 'COMPOSE_PROFILES' $profiles
$envMap = Read-EnvFile
if (-not $envMap.Contains('TZ')) {
  $tz = Get-IanaTimeZone
  if ($tz) { Set-EnvValue 'TZ' $tz; Say "Zona horaria: $tz" }
  else { Say "No se reconoce la zona horaria de Windows ($([System.TimeZoneInfo]::Local.Id)); se usa Europe/Madrid. Cámbiala con TZ en .env." 'Yellow' }
}

if ($Tools -contains 'claude') {
  if (-not (Test-Path (Join-Path $ClaudeDir 'projects'))) { Say 'Aviso: no existe ~/.claude/projects; ¿has usado Claude Code en este equipo?' 'Yellow' }
  foreach ($d in 'projects', 'commands', 'skills') { New-Item -ItemType Directory -Force (Join-Path $ClaudeDir $d) | Out-Null }
  if (-not $SkipClaudeSettings) { Set-ClaudeTelemetry; Set-ClaudeRetention }
}
if ($Tools -contains 'opencode') {
  if (-not (Test-Path $OpenCodeDb)) { Say "Aviso: no se encuentra $OpenCodeDb. Si OpenCode guarda sus datos en otra carpeta, define OPENCODE_DATA_DIR en .env." 'Yellow' }
  New-Item -ItemType Directory -Force (Join-Path $HomeDir '.config\opencode\commands') | Out-Null
  New-Item -ItemType Directory -Force (Join-Path $HomeDir '.cache\opencode') | Out-Null
}

if (-not $SkipMigration) { Invoke-Migration $Tools }
if (-not $NoShortcut) { try { New-Shortcut } catch { Say "No se pudo crear el acceso directo: $_" 'Yellow' } }

if ($NoStart) { Say 'Instalación lista. Arranca con Iniciar-metricas.bat.' 'Green'; exit 0 }

Push-Location $Root
try {
  # Quita los servicios del perfil que ya no se usa y levanta los elegidos
  docker compose --profile claude --profile opencode stop | Out-Null
  docker compose up -d --remove-orphans
  if ($LASTEXITCODE -ne 0) { throw 'docker compose up falló. Revisa la salida anterior.' }
  Say 'Esperando a que los servicios estén listos...'
  docker compose up -d --wait --wait-timeout 180 *> $null
  if ($LASTEXITCODE -ne 0) { Say 'Algún servicio no está sano todavía. Revísalo con: docker compose ps' 'Yellow' }
} finally { Pop-Location }

Say ''
Say 'Listo.' 'Green'
Say '  Grafana:            http://localhost:3000  (usuario admin)'
if ($Tools -contains 'claude') { Say '  Sesiones Claude:    http://localhost:9100/sessions' }
if ($Tools -contains 'opencode') { Say '  Sesiones OpenCode:  http://localhost:9101/sessions' }
Start-Process 'http://localhost:3000'
