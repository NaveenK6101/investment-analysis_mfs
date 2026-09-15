# Pulls real monthly prices so we can hand-walk the arithmetic behind the
# relative-strength numbers, at three levels: sector, sub-sector, single stock.
# Nothing here is a derived/rounded output - these are the raw prices the
# earlier scripts computed from.

$ua = @{ "User-Agent" = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" }

function Get-MonthlyCloses($symbol, $range) {
    $uri = "https://query1.finance.yahoo.com/v8/finance/chart/$symbol" + "?interval=1mo&range=$range"
    $r = Invoke-RestMethod -Uri $uri -Headers $ua -TimeoutSec 25
    $res = $r.chart.result[0]
    $ts = $res.timestamp; $close = $res.indicators.quote[0].close
    $map = @{}
    for ($i = 0; $i -lt $ts.Count; $i++) {
        if ($null -ne $close[$i]) {
            $d = ([datetimeoffset]::FromUnixTimeSeconds($ts[$i])).ToString("yyyy-MM")
            $map[$d] = [double]$close[$i]
        }
    }
    return $map
}

Write-Output "############################################################"
Write-Output "# PART A: the railway numbers you already saw, from raw prices"
Write-Output "############################################################"

$rail = @{
    "IRFC"    = Get-MonthlyCloses "IRFC.NS" "6y"
    "RVNL"    = Get-MonthlyCloses "RVNL.NS" "6y"
    "IRCTC"   = Get-MonthlyCloses "IRCTC.NS" "6y"
    "RailTel" = Get-MonthlyCloses "RAILTEL.NS" "6y"
}
$nifty = Get-MonthlyCloses "^NSEI" "6y"

$anchors = @("2021-02","2023-05","2024-05","2025-02","2026-09")

Write-Output ""
Write-Output "-- Raw closing prices (Rs) --"
$table = foreach ($d in $anchors) {
    $row = [ordered]@{ date = $d }
    foreach ($k in $rail.Keys) { $row[$k] = $rail[$k][$d] }
    $row["Nifty50"] = $nifty[$d]
    [PSCustomObject]$row
}
$table | Format-Table -AutoSize

Write-Output "-- Step 1: rebase EACH stock to 100 at 2021-02 (price_t / price_2021-02 * 100) --"
$base = @{}
foreach ($k in $rail.Keys) { $base[$k] = $rail[$k]["2021-02"] }
$reb = foreach ($d in $anchors) {
    $row = [ordered]@{ date = $d }
    foreach ($k in $rail.Keys) { $row[$k] = [math]::Round(($rail[$k][$d] / $base[$k]) * 100, 1) }
    [PSCustomObject]$row
}
$reb | Format-Table -AutoSize

Write-Output "-- Step 2: the 'basket' number = simple AVERAGE of the 4 rebased stocks, that month --"
foreach ($d in $anchors) {
    $vals = $rail.Keys | ForEach-Object { ($rail[$_][$d] / $base[$_]) * 100 }
    $avg = ($vals | Measure-Object -Average).Average
    $show = ($vals | ForEach-Object { [math]::Round($_,0) }) -join " + "
    Write-Output ("  {0}:  ({1}) / 4  =  {2}" -f $d, $show, [math]::Round($avg,1))
}

Write-Output ""
Write-Output "-- Step 3: rebase Nifty50 to 100 at 2021-02 the same way --"
$niftyBase = $nifty["2021-02"]
foreach ($d in $anchors) {
    $r = [math]::Round(($nifty[$d] / $niftyBase) * 100, 1)
    Write-Output ("  {0}:  {1} / {2} * 100  =  {3}" -f $d, $nifty[$d], $niftyBase, $r)
}

Write-Output ""
Write-Output "-- Step 4: relative = 100 * basket / nifty_rebased (this IS the number you saw) --"
foreach ($d in $anchors) {
    $vals = $rail.Keys | ForEach-Object { ($rail[$_][$d] / $base[$_]) * 100 }
    $basket = ($vals | Measure-Object -Average).Average
    $niftyR = ($nifty[$d] / $niftyBase) * 100
    $rel = 100 * $basket / $niftyR
    Write-Output ("  {0}:  100 * {1} / {2}  =  {3}" -f $d, [math]::Round($basket,1), [math]::Round($niftyR,1), [math]::Round($rel,1))
}

Write-Output ""
Write-Output "############################################################"
Write-Output "# PART B: PHARMA, three levels, same method, real numbers"
Write-Output "############################################################"

$niftyPharma = Get-MonthlyCloses "^CNXPHARMA" "10y"
$nifty10y    = Get-MonthlyCloses "^NSEI" "10y"
$divis       = Get-MonthlyCloses "DIVISLAB.NS" "10y"
$laurus      = Get-MonthlyCloses "LAURUSLABS.NS" "10y"

$pAnchors = @("2016-12","2019-09","2021-09","2023-09","2026-09")
Write-Output "(Level 1 rebases from 2016-12; Laurus Labs only listed then, so Levels 2-3 use the same 2016-12 base so all three levels line up on one chart)"
Write-Output ""

Write-Output "-- LEVEL 1: WHOLE SECTOR - Nifty Pharma vs Nifty 50 --"
Write-Output "Raw index levels:"
foreach ($d in $pAnchors) {
    Write-Output ("  {0}   NiftyPharma={1,9:N1}   Nifty50={2,9:N1}" -f $d, $niftyPharma[$d], $nifty10y[$d])
}
$phBase = $niftyPharma["2016-12"]; $n50Base = $nifty10y["2016-12"]
Write-Output ""
Write-Output "Rebased to 100 at 2016-12, then relative = 100 * pharma_rebased / nifty_rebased:"
foreach ($d in $pAnchors) {
    $phR = ($niftyPharma[$d] / $phBase) * 100
    $n5R = ($nifty10y[$d] / $n50Base) * 100
    $rel = 100 * $phR / $n5R
    Write-Output ("  {0}   pharma_rebased={1,7:N1}   nifty_rebased={2,7:N1}   relative={3,7:N1}" -f $d, $phR, $n5R, $rel)
}

Write-Output ""
Write-Output "-- LEVEL 2: SUB-SECTOR - a 2-stock CDMO basket (Divi's + Laurus) vs Nifty Pharma --"
Write-Output "Raw prices (Rs):"
foreach ($d in $pAnchors) {
    Write-Output ("  {0}   Divis={1,9:N1}   Laurus={2,9:N1}   NiftyPharma={3,9:N1}" -f $d, $divis[$d], $laurus[$d], $niftyPharma[$d])
}
$divBase = $divis["2016-12"]; $lauBase = $laurus["2016-12"]
Write-Output ""
Write-Output "Rebased & averaged into a CDMO basket, then relative to Nifty Pharma (not Nifty50 this time):"
foreach ($d in $pAnchors) {
    $dR = ($divis[$d] / $divBase) * 100
    $lR = ($laurus[$d] / $lauBase) * 100
    $basket = ($dR + $lR) / 2
    $phR = ($niftyPharma[$d] / $phBase) * 100
    $rel = 100 * $basket / $phR
    Write-Output ("  {0}   Divis_reb={1,7:N1}  Laurus_reb={2,7:N1}  CDMO_basket={3,7:N1}  vs Pharma_reb={4,7:N1}  ->  relative={5,7:N1}" -f `
        $d, $dR, $lR, $basket, $phR, $rel)
}

Write-Output ""
Write-Output "-- LEVEL 3: SINGLE STOCK - Laurus Labs alone vs its own sub-sector and the sector --"
foreach ($d in $pAnchors) {
    $lR = ($laurus[$d] / $lauBase) * 100
    $dR = ($divis[$d] / $divBase) * 100
    $cdmo = ($lR + $dR) / 2
    $phR = ($niftyPharma[$d] / $phBase) * 100
    Write-Output ("  {0}   Laurus_rebased={1,7:N1}   vs CDMO basket={2,7:N1} (ratio {3,5:N2})   vs Pharma sector={4,7:N1} (ratio {5,5:N2})" -f `
        $d, $lR, $cdmo, ($lR/$cdmo), $phR, ($lR/$phR))
}

Write-Output ""
Write-Output "Sanity check - Laurus's own price, unrebased, at first and last anchor:"
Write-Output ("  2016-12: Rs {0}   2026-09: Rs {1}   raw multiple = {2}x" -f $laurus["2016-12"], $laurus["2026-09"], [math]::Round($laurus["2026-09"]/$laurus["2016-12"],1))
