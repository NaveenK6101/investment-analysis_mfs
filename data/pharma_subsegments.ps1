# "Pharma" is not one theme. Split the names these funds hold into sub-segments and
# compare run-lengths, so it's visible which sub-cycles already played out and which
# may still be early.

$ua = @{ "User-Agent" = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" }

$universe = @(
    @{ s="DIVISLAB.NS";   n="Divi's Labs";        seg="CDMO/CRAMS" }
    @{ s="LAURUSLABS.NS"; n="Laurus Labs";        seg="CDMO/CRAMS" }
    @{ s="SAILIFE.NS";    n="Sai Life Sciences";  seg="CDMO/CRAMS" }
    @{ s="NEULANDLAB.NS"; n="Neuland Labs";       seg="CDMO/CRAMS" }
    @{ s="ACUTAAS.NS";    n="Acutaas Chemicals";  seg="CDMO/CRAMS" }
    @{ s="GRANULES.NS";   n="Granules India";     seg="API/Generics" }
    @{ s="ALIVUS.NS";     n="Alivus Life Sci";    seg="API/Generics" }
    @{ s="JUBLPHARMA.NS"; n="Jubilant Pharmova";  seg="API/Generics" }
    @{ s="APLLTD.NS";     n="Alembic Pharma";     seg="API/Generics" }
    @{ s="TORNTPHARM.NS"; n="Torrent Pharma";     seg="Domestic brands" }
    @{ s="GLAXO.NS";      n="GSK Pharma";         seg="Domestic brands" }
    @{ s="SANOFI.NS";     n="Sanofi India";       seg="Domestic brands" }
    @{ s="PPLPHARMA.NS";  n="Piramal Pharma";     seg="Domestic brands" }
    @{ s="LALPATHLAB.NS"; n="Dr Lal PathLabs";    seg="Hospitals/Diag" }
    @{ s="RAINBOW.NS";    n="Rainbow Childrens";  seg="Hospitals/Diag" }
    @{ s="KIMS.NS";       n="KIMS";               seg="Hospitals/Diag" }
    @{ s="ASTERDM.NS";    n="Aster DM";           seg="Hospitals/Diag" }
    @{ s="HCG.NS";        n="HealthCare Global";  seg="Hospitals/Diag" }
    @{ s="FORTIS.NS";     n="Fortis Healthcare";  seg="Hospitals/Diag" }
    @{ s="INDGN.NS";      n="Indegene";           seg="Hospitals/Diag" }
)

$rows = @()
foreach ($u in $universe) {
    $c = @()
    try {
        $uri = "https://query1.finance.yahoo.com/v8/finance/chart/$($u.s)" + "?interval=1mo&range=6y"
        $r = Invoke-RestMethod -Uri $uri -Headers $ua -TimeoutSec 25
        foreach ($v in $r.chart.result[0].indicators.quote[0].close) {
            if ($null -ne $v) { $c += [double]$v }
        }
    } catch {
        Write-Output "  $($u.n): fetch failed"
    }

    if ($c.Count -lt 13) {
        $rows += [PSCustomObject]@{ segment=$u.seg; stock=$u.n; hist_mo=$c.Count; r1Y=$null; r3Y=$null; r5Y=$null; fromPeak=$null }
        continue
    }

    $last = $c[$c.Count - 1]
    $peak = ($c | Measure-Object -Maximum).Maximum

    $r1 = $null; $r3 = $null; $r5 = $null
    if ($c.Count -gt 12) { $r1 = [math]::Round((($last / $c[$c.Count - 13]) - 1) * 100, 0) }
    if ($c.Count -gt 36) { $r3 = [math]::Round((($last / $c[$c.Count - 37]) - 1) * 100, 0) }
    if ($c.Count -gt 60) { $r5 = [math]::Round((($last / $c[$c.Count - 61]) - 1) * 100, 0) }

    $rows += [PSCustomObject]@{
        segment  = $u.seg
        stock    = $u.n
        hist_mo  = $c.Count
        r1Y      = $r1
        r3Y      = $r3
        r5Y      = $r5
        fromPeak = [math]::Round((($last / $peak) - 1) * 100, 0)
    }
    Start-Sleep -Milliseconds 150
}

$rows | Sort-Object segment, stock | Format-Table -AutoSize

Write-Output "=== Segment averages (%) ==="
$rows | Where-Object { $null -ne $_.r1Y } | Group-Object segment | ForEach-Object {
    $g = $_.Group
    [PSCustomObject]@{
        segment    = $_.Name
        stocks     = $g.Count
        avg_1Y     = [math]::Round((($g | ForEach-Object { $_.r1Y }) | Measure-Object -Average).Average, 0)
        avg_3Y     = [math]::Round((($g | Where-Object { $null -ne $_.r3Y } | ForEach-Object { $_.r3Y }) | Measure-Object -Average).Average, 0)
        avg_5Y     = [math]::Round((($g | Where-Object { $null -ne $_.r5Y } | ForEach-Object { $_.r5Y }) | Measure-Object -Average).Average, 0)
        avg_frompk = [math]::Round((($g | ForEach-Object { $_.fromPeak }) | Measure-Object -Average).Average, 0)
    }
} | Format-Table -AutoSize
