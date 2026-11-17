# Build a Tabular model in the running Desktop RS engine from a spec JSON and
# export its canonical DataModel via Server.ImageSave.
#
# Spec JSON:
# { "database":"name", "mode":"dax|m",
#   "tables":[{"name","columns":[{"name","type","values"}],
#              "dax":"<calculated table>", "query":"<M source>"}],
#   "measures":[{"table","name","expression"}],
#   "relationships":[{"fromTable","fromColumn","toTable","toColumn",
#                     "crossFilteringBehavior"}],
#   "culture":"ru-RU" }
# Types: int64 | double | string | date
#
# `mode` chooses how inline rows are encoded:
#   dax - a calculated table with a DAX `DATATABLE` expression (the historical
#         path; works on every Desktop build, but every literal must match the
#         declared column type exactly);
#   m   - an import partition with an M `Table.FromRows` expression (needed for
#         NULLs, dates, and a caller-supplied `query`; the embedded engine of the
#         regular Desktop refused to process it on the guest, so `dax` is the
#         default and `m` is opt-in).
# A table with `query` always uses `m`, whatever the mode.
param(
  [Parameter(Mandatory=$true)][string]$Spec,
  [Parameter(Mandatory=$true)][string]$Out,
  [int]$Port = 0,
  [ValidateSet('dax', 'm')][string]$Mode = 'dax',
  # Fail when the model does not reach the processed state. On the guest the
  # embedded engine of the regular Desktop left every TOM-created database
  # Unprocessed, so the check is opt-in for engines that do process (RS/VDI).
  [switch]$RequireProcessed
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
# TOM refuses punctuation in an object name: . , ; ' ` : / \ * | ? " & % $ ! + = ( )
# [ ] { } < >. A spec is authored by hand or by an agent, so the rule is applied
# once here (the same rule as engine.core.database_name) instead of failing the
# build on the last step with "The 'Name' property cannot contain ...".
$forbidden = [char[]]@(
  0x2E, 0x2C, 0x3B, 0x27, 0x60, 0x3A, 0x2F, 0x5C, 0x2A, 0x7C, 0x3F, 0x22, 0x26,
  0x25, 0x24, 0x21, 0x2B, 0x3D, 0x28, 0x29, 0x5B, 0x5D, 0x7B, 0x7D, 0x3C, 0x3E
)
$rawName = [string]$specObj.database
$dbName = -join ($rawName.ToCharArray() | ForEach-Object {
  if ($forbidden -contains $_) { '_' } else { [string]$_ }
})
if ($dbName -ne $rawName) {
  Write-Output ('database renamed: ' + $rawName + ' -> ' + $dbName)
}

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
$calcType = $tom.GetType('Microsoft.AnalysisServices.Tabular.CalculatedPartitionSource')
$dcType = $tom.GetType('Microsoft.AnalysisServices.Tabular.DataColumn')
$partType = $tom.GetType('Microsoft.AnalysisServices.Tabular.Partition')
# An import partition must be an M source. A calculated source (DAX) here made
# every inline table a calculated table with an M expression as its DAX, so the
# model built, opened, and held no rows.
$cpType = $tom.GetType('Microsoft.AnalysisServices.Tabular.MPartitionSource')

$engineMode = $Mode
if ($specObj.PSObject.Properties['mode'] -and $specObj.mode) {
  $engineMode = [string]$specObj.mode
  if ($engineMode -notin @('dax', 'm')) {
    throw ("unknown mode '" + $engineMode + "'; expected dax or m")
  }
}
Write-Output ('mode: ' + $engineMode)
$tableSpecs = @($specObj.tables)
foreach ($ts in $tableSpecs) {
  $t = [Activator]::CreateInstance($tblType)
  $t.Name = $ts.name
  # Calculated (DAX) table: the expression belongs to a calculated partition
  # source. `Table.CalculationExpression` does not exist in this TOM build, so
  # assigning it failed the whole build on the guest.
  if ($ts.PSObject.Properties['dax'] -and $ts.dax) {
    $cp = [Activator]::CreateInstance($partType)
    $cp.Name = 'P1'
    $cp.Mode = [Microsoft.AnalysisServices.Tabular.ModeType]::Import
    $cs = [Activator]::CreateInstance($calcType)
    $cs.Expression = [string]$ts.dax
    $cp.Source = $cs
    $t.Partitions.Add($cp)
    $model.Tables.Add($t)
    Write-Output ('table ' + $ts.name + ': calculated (DAX)')
    continue
  }
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
  # Inline rows. `dax` keeps the historical calculated-table encoding (a
  # DATATABLE expression); `m` uses an import partition. See the header.
  $useM = ($engineMode -eq 'm') -or ($ts.PSObject.Properties['query'] -and $ts.query)
  $n = 0
  foreach ($cd in $colDefs) { if ($cd.values.Count -gt $n) { $n = $cd.values.Count } }
  $mColNames = @()
  foreach ($cd in $colDefs) { $mColNames += ('"' + $cd.name + '"') }
  $mRows = @()
  for ($i = 0; $i -lt $n; $i++) {
    $vals = @()
    foreach ($cd in $colDefs) {
      $v = $cd.values[$i]
      if ($null -eq $v) { $vals += 'null' }
      elseif ($cd.type -eq 'string') {
        $vals += ('"' + ([string]$v).Replace('"','""').Replace("`r",' ').Replace("`n",' ') + '"')
      }
      elseif ($cd.type -eq 'date') {
        $d = [DateTime]::Parse([string]$v, [Globalization.CultureInfo]::InvariantCulture)
        $vals += ('#datetime(' + $d.Year + ',' + $d.Month + ',' + $d.Day + ',' + $d.Hour + ',' + $d.Minute + ',' + $d.Second + ')')
      }
      else { $vals += [string]::Format([Globalization.CultureInfo]::InvariantCulture, '{0}', $v) }
    }
    $mRows += ('{' + ($vals -join ',') + '}')
  }
  $typeParts = @()
  foreach ($cd in $colDefs) {
    $ty = switch ($cd.type) { 'int64' {'Int64.Type'} 'double' {'type number'} 'date' {'type datetime'} default {'type text'} }
    # TransformColumnTypes takes a list of {name, type} pairs, not a flat list:
    # a flat list failed on the guest with an opaque M error.
    $typeParts += ('{"' + $cd.name + '", ' + $ty + '}')
  }
  $p = [Activator]::CreateInstance($partType)
  $p.Name = 'P1'
  $p.Mode = [Microsoft.AnalysisServices.Tabular.ModeType]::Import
  if ($useM) {
    if ($ts.PSObject.Properties['query'] -and $ts.query) {
      # A caller-supplied M expression (a real data source) replaces the rows.
      $mExpr = [string]$ts.query
      Write-Output ('table ' + $ts.name + ': uses custom M query')
    } else {
      if ($engineMode -eq 'm' -and ($colDefs | Where-Object { -not $_.values.Count } | Select-Object -First 1)) {
        Write-Output ('table ' + $ts.name + ': an empty column forces an empty table')
      }
      $mExpr = 'let Source = Table.FromRows({' + ($mRows -join ',') + '}, {' + ($mColNames -join ',') + '}), Typed = Table.TransformColumnTypes(Source, {' + ($typeParts -join ',') + '}) in Typed'
    }
    $src = [Activator]::CreateInstance($cpType)
    $src.Expression = $mExpr
    $p.Source = $src
  } else {
    # DAX DATATABLE. Every literal must have the declared type: a BLANK() in an
    # INTEGER column (or DATEVALUE() in a DATETIME one) is rejected, so NULL is
    # `null` and a date is DATE(..)+TIME(..).
    $daxDecl = @()
    foreach ($cd in $colDefs) {
      $daxTy = switch ($cd.type) { 'int64' {'INTEGER'} 'double' {'DOUBLE'} 'date' {'DATETIME'} default {'STRING'} }
      $daxDecl += ('"' + $cd.name + '", ' + $daxTy)
    }
    $daxRows = @()
    for ($i = 0; $i -lt $n; $i++) {
      $vals = @()
      foreach ($cd in $colDefs) {
        $v = $cd.values[$i]
        if ($null -eq $v) { $vals += 'null' }
        elseif ($cd.type -eq 'string') {
          $vals += ('"' + ([string]$v).Replace('"','""').Replace("`r",' ').Replace("`n",' ') + '"')
        }
        elseif ($cd.type -eq 'date') {
          $d = [DateTime]::Parse([string]$v, [Globalization.CultureInfo]::InvariantCulture)
          $vals += ('DATE(' + $d.Year + ',' + $d.Month + ',' + $d.Day + ')+TIME(' + $d.Hour + ',' + $d.Minute + ',' + $d.Second + ')')
        }
        else { $vals += [string]::Format([Globalization.CultureInfo]::InvariantCulture, '{0}', $v) }
      }
      $daxRows += ('{' + ($vals -join ',') + '}')
    }
    $daxExpr = 'DATATABLE(' + ($daxDecl -join ', ') + ', {' + ($daxRows -join ',') + '})'
    $src = [Activator]::CreateInstance($calcType)
    $src.Expression = $daxExpr
    $p.Source = $src
    Write-Output ('table ' + $ts.name + ': calculated DATATABLE')
  }
  $t.Partitions.Add($p)
  $model.Tables.Add($t)
  Write-Output ("table $($ts.name): cols=$($t.Columns.Count) rows=$n")
}

foreach ($m in @($specObj.measures)) {
  if (-not $m) { continue }
  $mt = $model.Tables[$m.table]
  if (-not $mt) {
    Write-Output ("measure skipped: table missing (" + $m.table + "." + $m.name + ")")
    continue
  }
  # TOM rejects a measure whose name collides with a column in the same table.
  if ($mt.Columns[$m.name]) {
    Write-Output ("measure skipped: name collides with column (" + $m.table + "." + $m.name + ")")
    continue
  }
  $msr = [Activator]::CreateInstance($tom.GetType('Microsoft.AnalysisServices.Tabular.Measure'))
  $msr.Name = $m.name
  $msr.Expression = $m.expression
  $mt.Measures.Add($msr)
}

# Optional model culture (e.g. ru-RU). Non-fatal: a bad culture must not fail
# the build, the model is still valid with the default culture.
if ($specObj.culture) {
  try { $model.Culture = [string]$specObj.culture }
  catch { Write-Output ("culture skipped: " + $_.Exception.Message) }
}

$srv.Databases.Add($db)
Write-Output 'db added'
$db.Update()
Write-Output 'db.Update OK'
$db.Model.SaveChanges()
Write-Output 'model saved'

# Relationships (many-to-one). Added AFTER the first save: TOM binds columns by
# their server IDs, which only exist once the tables are persisted.
$relType = $tom.GetType('Microsoft.AnalysisServices.Tabular.SingleColumnRelationship')
foreach ($r in @($specObj.relationships)) {
  if (-not $r) { continue }
  try {
    $ft = $model.Tables[$r.fromTable]
    $tt = $model.Tables[$r.toTable]
    if (-not $ft -or -not $tt) {
      Write-Output ("relationship skipped: table missing (" + $r.fromTable + " -> " + $r.toTable + ")")
      continue
    }
    $fc = $ft.Columns[$r.fromColumn]
    $tc = $tt.Columns[$r.toColumn]
    if (-not $fc -or -not $tc) {
      Write-Output ("relationship skipped: column missing (" + $r.fromTable + "." + $r.fromColumn + " -> " + $r.toTable + "." + $r.toColumn + ")")
      continue
    }
    $rel = [Activator]::CreateInstance($relType)
    $rel.FromColumn = $fc
    $rel.ToColumn = $tc
    $rel.FromCardinality = [Microsoft.AnalysisServices.Tabular.RelationshipEndCardinality]::Many
    $rel.ToCardinality = [Microsoft.AnalysisServices.Tabular.RelationshipEndCardinality]::One
    $cfb = 'oneDirection'
    if ($r.PSObject.Properties['crossFilteringBehavior'] -and $r.crossFilteringBehavior) {
      $cfb = [string]$r.crossFilteringBehavior
    }
    if ($cfb -eq 'bothDirections') {
      $rel.CrossFilteringBehavior = [Microsoft.AnalysisServices.Tabular.CrossFilteringBehavior]::BothDirections
    } else {
      $rel.CrossFilteringBehavior = [Microsoft.AnalysisServices.Tabular.CrossFilteringBehavior]::OneDirection
    }
    $model.Relationships.Add($rel)
    Write-Output ("relationship " + $r.fromTable + "." + $r.fromColumn + " -> " + $r.toTable + "." + $r.toColumn)
  } catch {
    Write-Output ("relationship skipped: " + $_.Exception.Message)
  }
}
if (@($specObj.relationships).Count -gt 0) {
  $db.Update()
  Write-Output 'rel.Update OK'
  $db.Model.SaveChanges()
  Write-Output 'rel saved'
}

# Refresh on the build connection: this is the sequence that processed the
# model on the guest. A refresh issued from a second connection left the
# database Unprocessed there, and an unprocessed model exports without data.
$refreshErrors = @()
foreach ($tb in $db.Model.Tables) {
  try {
    $tb.RequestRefresh([Microsoft.AnalysisServices.Tabular.RefreshType]::Full)
    $db.Model.SaveChanges()
    Write-Output ("refreshed " + $tb.Name)
  } catch {
    $ex = $_.Exception; while ($ex.InnerException) { $ex = $ex.InnerException }
    $refreshErrors += ($tb.Name + ': ' + $ex.Message)
    Write-Output ("refresh err " + $tb.Name + ': ' + $ex.Message)
  }
}
$state = [string]$db.State
Write-Output ('db state: ' + $state)
$srv.Disconnect()
# A model that kept no data produces an ImageSave that looks valid while every
# visual renders blank, so an unprocessed database fails the build instead of
# shipping it.
if ($refreshErrors.Count -gt 0) {
  throw ("refresh failed for " + $refreshErrors.Count + " table(s): " + ($refreshErrors -join '; '))
}
if ($state -and $state -ne 'Ready') {
  $message = "model stayed " + $state + " after refresh; the exported DataModel has no data"
  if ($RequireProcessed -or ($specObj.PSObject.Properties['requireProcessed'] -and $specObj.requireProcessed)) {
    throw $message
  }
  Write-Output ('WARNING: ' + $message)
}

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