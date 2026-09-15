# Fetches full NAV history for the funds used in the leveraged-investment-strategy notebook
# from mfapi.in (public, free Indian MF NAV API) and caches each as a CSV under data/nav/.
# Re-run any time to refresh the cache with the latest NAVs.

$funds = @(
    @{ key = "quant_flexi";  code = 120843; name = "Quant Flexi Cap Fund" }
    @{ key = "quant_small";  code = 120828; name = "Quant Small Cap Fund" }
    @{ key = "invesco_mid";  code = 120403; name = "Invesco India Mid Cap Fund" }
    @{ key = "nippon_small"; code = 118778; name = "Nippon India Small Cap Fund" }
    @{ key = "quant_multi";  code = 120821; name = "Quant Multi Asset Allocation Fund" }
    @{ key = "trustmf_small"; code = 152939; name = "TRUSTMF Small Cap Fund" }
    @{ key = "abakkus_small"; code = 154215; name = "Abakkus Small Cap Fund" }
    @{ key = "helios_small";  code = 153912; name = "Helios Small Cap Fund" }
    @{ key = "invesco_small"; code = 145137; name = "Invesco India Small Cap Fund" }
    @{ key = "bandhan_small"; code = 147946; name = "Bandhan Small Cap Fund" }
    @{ key = "boi_small";     code = 145678; name = "Bank of India Small Cap Fund" }
    @{ key = "iti_small";     code = 147919; name = "ITI Small Cap Fund" }
)

$outDir = Join-Path $PSScriptRoot "nav"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$summary = @()

foreach ($f in $funds) {
    Write-Output "Fetching $($f.name) (code $($f.code))..."
    try {
        $r = Invoke-RestMethod -Uri "https://api.mfapi.in/mf/$($f.code)" -TimeoutSec 30
        $rows = $r.data | ForEach-Object {
            [PSCustomObject]@{
                date = [datetime]::ParseExact($_.date, "dd-MM-yyyy", $null).ToString("yyyy-MM-dd")
                nav  = [double]$_.nav
            }
        } | Sort-Object date

        $csvPath = Join-Path $outDir "$($f.key).csv"
        $rows | Export-Csv -Path $csvPath -NoTypeInformation -Encoding utf8

        $start = $rows[0].date
        $end = $rows[-1].date
        $months = ((Get-Date $end).Year - (Get-Date $start).Year) * 12 + ((Get-Date $end).Month - (Get-Date $start).Month)

        $summary += [PSCustomObject]@{
            key            = $f.key
            scheme_code    = $f.code
            scheme_name    = $r.meta.scheme_name
            n_daily_points = $rows.Count
            start_date     = $start
            end_date       = $end
            approx_months  = $months
        }
    } catch {
        Write-Output "FAILED for $($f.name): $($_.Exception.Message)"
    }
}

$summaryPath = Join-Path $PSScriptRoot "nav_summary.csv"
$summary | Export-Csv -Path $summaryPath -NoTypeInformation -Encoding utf8
$summary | Format-Table -AutoSize
