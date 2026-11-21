# Used by tests/test_config.py: loads the installer's functions without running it and checks that
# Remove-ClaudeTelemetry removes only the variables the installer set, with their value, after a backup.
param([string]$Installer)
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Installer, [ref]$tokens, [ref]$errors)
if ($errors.Count) { $errors | ForEach-Object { $_.Message }; exit 1 }
foreach ($f in $ast.FindAll({ $args[0] -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $false)) {
  . ([scriptblock]::Create($f.Extent.Text))
}
$tel = $ast.FindAll({ $args[0] -is [System.Management.Automation.Language.AssignmentStatementAst] -and
                      $args[0].Left.Extent.Text -eq '$TelemetryEnv' }, $false) | Select-Object -First 1
. ([scriptblock]::Create($tel.Extent.Text))
$Root = Join-Path ([IO.Path]::GetTempPath()) ('iam-' + [guid]::NewGuid())
$ClaudeDir = Join-Path $Root '.claude'
New-Item -ItemType Directory -Force $ClaudeDir | Out-Null
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$Force = $true
function Say($text, $color = 'Gray') { }
$settings = Join-Path $ClaudeDir 'settings.json'
function Fail($msg) { Write-Output "FAIL: $msg"; exit 1 }

'{"model":"opus","env":{"CLAUDE_CODE_ENABLE_TELEMETRY":"1","OTEL_METRICS_EXPORTER":"otlp","OTEL_EXPORTER_OTLP_ENDPOINT":"http://otro:4317","MI_VAR":"x"}}' |
  Set-Content $settings
Remove-ClaudeTelemetry
$after = Get-Content $settings -Raw | ConvertFrom-Json
$left = ($after.env.PSObject.Properties.Name | Sort-Object) -join ','
if ($left -ne 'MI_VAR,OTEL_EXPORTER_OTLP_ENDPOINT') { Fail "quedan $left" }   # a changed value is not the installer's
if ($after.model -ne 'opus') { Fail 'se perdió model' }
if (@(Get-ChildItem (Join-Path $Root 'installer/backups')).Count -ne 1) { Fail 'sin copia de seguridad' }

$json = '{"env":{' + (($TelemetryEnv.Keys | ForEach-Object { '"{0}":"{1}"' -f $_, $TelemetryEnv[$_] }) -join ',') + '}}'
Set-Content $settings $json
Remove-ClaudeTelemetry
if ((Get-Content $settings -Raw).Trim() -ne '{}') { Fail 'env vacío no se quitó' }
Remove-Item -Recurse -Force $Root
Write-Output 'ok'
