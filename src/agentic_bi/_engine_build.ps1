# Build a Tabular model in the running Desktop RS engine from a spec JSON and
# export its canonical DataModel via Server.ImageSave.
#
# Spec JSON:
# { "database":"name", "tables":[{"name","columns":[{"name","type","values"}]}],
#   "measures":[{"table","name","expression"}] }
# Types: int64 | double | string | date
param(
  [Parameter(Mandatory=$true)][string]$Spec,
  [Parameter(Mandatory=$true)][string]$Out,
  [int]$Port = 0
)
$ErrorActionPreference = 'Stop'
# Desktop binary directory: override with PBI_RS_BIN, else prefer the RS build
# and fall back to the regular Desktop.
$bin = if ($env:PBI_RS_BIN) { $env:PBI_RS_BIN } else {
  $rsBin = 'C:\Program Files\Microsoft Power BI Desktop RS\bin'
  if (Test-Path (Join-Path $rsBin 'Microsoft.PowerBI.Tabular.dll')) { $rsBin }
  else { 'C:\Program Files\Microsoft Power BI Desktop\bin' }
}
[System.Reflection.Assembly]::LoadFrom((Join-Path $bin 'Microsoft.PowerBI.Amo.Core.dll')) | Out-Null
$amo = [System.Reflection.Assembly]::LoadFrom((Join-Path $bin 'Microsoft.PowerBI.Amo.dll'))
$tom = [System.Reflection.Assembly]::LoadFrom((Join-Path $bin 'Microsoft.PowerBI.Tabular.dll'))

# AS workspace root: override with PBI_RS_WS_ROOT, else prefer the RS build and
# fall back to the regular Desktop.
$wsRoot = if ($env:PBI_RS_WS_ROOT) { $env:PBI_RS_WS_ROOT } else {
  $rsWs = "$env:LOCALAPPDATA\Microsoft\Power BI Desktop SSRS\AnalysisServicesWorkspaces"
  if (Test-Path $rsWs) { $rsWs }
  else { "$env:LOCALAPPDATA\Microsoft\Power BI Desktop\AnalysisServicesWorkspaces" }
}
# Port resolution: the caller (engine_host.wait_port) already knows the *live*
# engine port. Picking the newest workspace by mtime here would race: Desktop
# leaves a just-closed workspace with a fresh timestamp whose port is dead, so an
# mtime-based pick connects to a stopped engine ("server is not running"). Honor
# -Port; fall back to the newest workspace whose port actually listens.
if ($Port -gt 0) {
  $port = $Port
} else {
  $candidates = Get-ChildItem $wsRoot -Directory -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending
  $port = $null
  foreach ($w in $candidates) {
    $pf = Join-Path $w.FullName 'Data\msmdsrv.port.txt'
    if (-not (Test-Path $pf)) { continue }
    $p = ((Get-Content $pf -Raw) -replace [char]0, '').Trim()
    if ($p -notmatch '^\d+$') { continue }
    $alive = $false
    try {
      $c = [System.Net.Sockets.TcpClient]::new()
      $c.Connect('127.0.0.1', [int]$p); $alive = $c.Connected; $c.Close()
    } catch { $alive = $false }
    if ($alive) { $port = $p; break }
  }
  if (-not $port) { throw "no live engine port found under $wsRoot" }
}

$specObj = Get-Content $Spec -Raw -Encoding UTF8 | ConvertFrom-Json
$dbName = $specObj.database

# --- build with TOM (Tabular.Server) ---
$Server = $tom.GetType('Microsoft.AnalysisServices.Tabular.Server')
$srv = [Activator]::CreateInstance($Server)
$srv.Connect("localhost:$port")
Write-Output "connected $port"

$old = $srv.Databases | Where-Object { $_.Name -eq $dbName }
if ($old) { $old.Drop(); Write-Output "dropped old $dbName" }

$db = [Activator]::CreateInstance($tom.GetType('Microsoft.AnalysisServices.Tabular.Database'))
$db.Name = $dbName
$db.CompatibilityLevel = 1567
$model = [Activator]::CreateInstance($tom.GetType('Microsoft.AnalysisServices.Tabular.Model'))
$db.Model = $model

$tblType = $tom.GetType('Microsoft.AnalysisServices.Tabular.Table')
$dcType = $tom.GetType('Microsoft.AnalysisServices.Tabular.DataColumn')
$partType = $tom.GetType('Microsoft.AnalysisServices.Tabular.Partition')
$cpType = $tom.GetType('Microsoft.AnalysisServices.Tabular.CalculatedPartitionSource')

$tableSpecs = @($specObj.tables)
foreach ($ts in $tableSpecs) {
  $t = [Activator]::CreateInstance($tblType)
  $t.Name = $ts.name
  $colDefs = @()
  foreach ($c in $ts.columns) {
    $col = [Activator]::CreateInstance($dcType)
    $col.Name = $c.name
    $col.SourceColumn = $c.name
    switch ($c.type) {
      'int64'  { $col.DataType = [Microsoft.AnalysisServices.Tabular.DataType]::Int64 }
      'double' { $col.DataType = [Microsoft.AnalysisServices.Tabular.DataType]::Double }
      'date'   { $col.DataType = [Microsoft.AnalysisServices.Tabular.DataType]::DateTime }
      default  { $col.DataType = [Microsoft.AnalysisServices.Tabular.DataType]::String }
    }
    $t.Columns.Add($col)
    $colDefs += ,($c)
  }
  $declParts = @()
  foreach ($cd in $colDefs) {
    $ty = switch ($cd.type) { 'int64' {'INTEGER'} 'double' {'DOUBLE'} 'date' {'DATETIME'} default {'STRING'} }
    $declParts += ('"' + $cd.name + '", ' + $ty)
  }
  $decl = $declParts -join ', '
  $rows = @()
  $n = 0
  foreach ($cd in $colDefs) { if ($cd.values.Count -gt $n) { $n = $cd.values.Count } }
  for ($i = 0; $i -lt $n; $i++) {
    $vals = @()
    foreach ($cd in $colDefs) {
      $v = $cd.values[$i]
      if ($null -eq $v) { $vals += 'BLANK()' }
      elseif ($cd.type -eq 'string') { $vals += ('"' + ([string]$v).Replace('"','""') + '"') }
      elseif ($cd.type -eq 'date') { $vals += ('dt"' + $v + '"') }
      else { $vals += [string]$v }
    }
    $rows += ('{' + ($vals -join ',') + '}')
  }
  $expr = 'DATATABLE(' + $decl + ', {' + ($rows -join ',') + '})'
  $p = [Activator]::CreateInstance($partType)
  $p.Name = 'P1'
  $p.Mode = [Microsoft.AnalysisServices.Tabular.ModeType]::Import
  $src = [Activator]::CreateInstance($cpType)
  $src.Expression = $expr
  $p.Source = $src
  $t.Partitions.Add($p)
  $model.Tables.Add($t)
  Write-Output ("table $($ts.name): cols=$($t.Columns.Count) rows=$n")
}

foreach ($m in @($specObj.measures)) {
  if (-not $m) { continue }
  $mt = $model.Tables[$m.table]
  if ($mt) {
    $msr = [Activator]::CreateInstance($tom.GetType('Microsoft.AnalysisServices.Tabular.Measure'))
    $msr.Name = $m.name
    $msr.Expression = $m.expression
    $mt.Measures.Add($msr)
  }
}

$srv.Databases.Add($db)
Write-Output 'db added'
$db.Update()
Write-Output 'db.Update OK'
$db.Model.SaveChanges()
Write-Output 'model saved'

# refresh via TOM (best-effort)
foreach ($t in $db.Model.Tables) {
  try { $t.RequestRefresh([Microsoft.AnalysisServices.Tabular.RefreshType]::Full); $db.Model.SaveChanges(); Write-Output ("refreshed " + $t.Name) } catch { Write-Output ("refresh err " + $_.Exception.Message) }
}
$srv.Disconnect()

# --- export via AMO ImageSave ---
$asType = $amo.GetType('Microsoft.AnalysisServices.Server')
$asrv = [Activator]::CreateInstance($asType)
$asrv.Connect("localhost:$port")
$adb = $asrv.Databases | Where-Object { $_.Name -eq $dbName } | Select-Object -First 1
Write-Output ('imagesave db id=' + $adb.ID)
$ms = [System.IO.MemoryStream]::new()
$asrv.ImageSave($adb.ID, $ms)
[System.IO.File]::WriteAllBytes($Out, $ms.ToArray())
Write-Output ("imagesave " + $ms.Length + " B -> " + $Out)
$asrv.Disconnect()
Write-Output DONE