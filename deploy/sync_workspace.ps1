param(
    [string]$Destination = 'C:\Users\rutil\Desktop\app',
    [switch]$Apply
)
$ErrorActionPreference = 'Stop'
$sourceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$targetRoot = [IO.Path]::GetFullPath($Destination).TrimEnd('\')
if (-not (Test-Path -LiteralPath $targetRoot -PathType Container)) { throw 'El destino debe existir.' }
if ($targetRoot -eq $sourceRoot) { throw 'Origen y destino deben ser distintos.' }
# Solo archivos del proyecto; nunca copiar .env, venvs ni material ajeno.
$files = @(& git -C $sourceRoot ls-files --cached --others --exclude-standard)
if ($LASTEXITCODE -ne 0) { throw 'No se pudo enumerar el repositorio.' }
$files = @($files | Where-Object {
    $_ -match '^(services/|data/|deploy/|docs/|e2e/|README\.md$|PENDIENTE\.md$|\.gitattributes$|\.gitignore$)' -and
    $_ -notmatch '(^|/)(\.env$|\.venv[^/]*/|__pycache__/|\.pytest_cache/|\.git/|[^/]+\.egg-info/|build/)'
})
$backupRoot = Join-Path $targetRoot ('.auth-sync-backups\' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
$changed = 0
foreach ($relative in $files) {
    $from = Join-Path $sourceRoot $relative
    $to = [IO.Path]::GetFullPath((Join-Path $targetRoot $relative))
    if (-not $to.StartsWith($targetRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Ruta fuera del destino.' }
    if (-not (Test-Path -LiteralPath $from -PathType Leaf)) { continue }
    # No atravesar enlaces/junctions en el destino.
    $ancestor = $to
    while ($ancestor -and $ancestor.StartsWith($targetRoot, [StringComparison]::OrdinalIgnoreCase)) {
        if (Test-Path -LiteralPath $ancestor) {
            if ((Get-Item -LiteralPath $ancestor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Enlace en destino: $ancestor"
            }
        }
        $ancestor = Split-Path -Parent $ancestor
    }
    if (Test-Path -LiteralPath $to -PathType Leaf) {
        if ((Get-FileHash -LiteralPath $from).Hash -eq (Get-FileHash -LiteralPath $to).Hash) { continue }
        if ($Apply) {
            $backup = Join-Path $backupRoot $relative
            New-Item -ItemType Directory -Path (Split-Path -Parent $backup) -Force | Out-Null
            Copy-Item -LiteralPath $to -Destination $backup
        }
    }
    $changed++
    if ($Apply) {
        New-Item -ItemType Directory -Path (Split-Path -Parent $to) -Force | Out-Null
        Copy-Item -LiteralPath $from -Destination $to -Force
    }
}
if ($Apply) { Write-Output "Sincronizados $changed archivos. Respaldos: $backupRoot" }
else { Write-Output "Vista previa: $changed archivos por sincronizar. Usa -Apply para copiar con respaldo." }
