# Adds Invesco India Small Cap, Bandhan Small Cap, Bank of India Small Cap and
# ITI Small Cap to the rebuilt MF comparison section, and refreshes the intro
# markdown to describe all 12 funds.

$nbPath = "C:\Users\Naveen\Desktop\Naveen_imp\investment\old-vahdam-files\leaveraged_inv_strategy.ipynb"
$nb = Get-Content -Raw $nbPath | ConvertFrom-Json

$oldConfig = @'
FUND_CONFIG = [
    {"key": "quant_flexi",   "scheme_code": 120843, "name": "Quant Flexi Cap"},
    {"key": "quant_small",   "scheme_code": 120828, "name": "Quant Small Cap"},
    {"key": "invesco_mid",   "scheme_code": 120403, "name": "Invesco India Mid Cap"},
    {"key": "nippon_small",  "scheme_code": 118778, "name": "Nippon India Small Cap"},
    {"key": "quant_multi",   "scheme_code": 120821, "name": "Quant Multi Asset Allocation"},
    {"key": "trustmf_small", "scheme_code": 152939, "name": "TRUSTMF Small Cap"},
    {"key": "abakkus_small", "scheme_code": 154215, "name": "Abakkus Small Cap"},
    {"key": "helios_small",  "scheme_code": 153912, "name": "Helios Small Cap"},
]
'@

$newConfig = @'
FUND_CONFIG = [
    {"key": "quant_flexi",   "scheme_code": 120843, "name": "Quant Flexi Cap"},
    {"key": "quant_small",   "scheme_code": 120828, "name": "Quant Small Cap"},
    {"key": "invesco_mid",   "scheme_code": 120403, "name": "Invesco India Mid Cap"},
    {"key": "nippon_small",  "scheme_code": 118778, "name": "Nippon India Small Cap"},
    {"key": "quant_multi",   "scheme_code": 120821, "name": "Quant Multi Asset Allocation"},
    {"key": "invesco_small", "scheme_code": 145137, "name": "Invesco India Small Cap"},
    {"key": "bandhan_small", "scheme_code": 147946, "name": "Bandhan Small Cap"},
    {"key": "boi_small",     "scheme_code": 145678, "name": "Bank of India Small Cap"},
    {"key": "iti_small",     "scheme_code": 147919, "name": "ITI Small Cap"},
    {"key": "trustmf_small", "scheme_code": 152939, "name": "TRUSTMF Small Cap"},
    {"key": "abakkus_small", "scheme_code": 154215, "name": "Abakkus Small Cap"},
    {"key": "helios_small",  "scheme_code": 153912, "name": "Helios Small Cap"},
]
'@

$newMarkdown = @'
### Compare mutual fund returns - rebuilt (Bayesian multivariate model)

**Funds compared (12):**

Long-history funds, fit **jointly** in the multivariate model (the tier split is decided automatically by `NEW_FUND_MONTHS_THRESHOLD = 36` months of history):
1. Quant Flexi Cap (13.7 yrs)
2. Quant Small Cap (13.7 yrs)
3. Invesco India Mid Cap (13.7 yrs)
4. Nippon India Small Cap (13.7 yrs)
5. Quant Multi Asset Allocation (13.7 yrs)
6. Invesco India Small Cap (7.8 yrs)
7. Bank of India Small Cap (7.7 yrs)
8. Bandhan Small Cap (6.6 yrs)
9. ITI Small Cap (6.6 yrs)

Recently launched, fit **individually** with their own Student-T model and flagged `low_confidence = True` everywhere:
10. TRUSTMF Small Cap (~22 months)
11. Helios Small Cap (~10 months under its current scheme code - the fund is older under its pre-rename BOI AXA name)
12. Abakkus Small Cap (~6 months)

**Why two tiers?** Naively inner-joining all 12 funds' return histories would truncate *every* fund - including ones with 13+ years of data - down to Abakkus's ~5 overlapping monthly observations, which would make every fund's posterior almost entirely prior-driven. Instead:
- The 9 long-history funds are fit **jointly** - `mu ~ Normal`, an `LKJCholeskyCov` prior on the covariance, `MvNormal` likelihood - same approach the original notebook used, so their estimated correlations are meaningful. Note this joint fit still inner-joins those 9, so the common estimation window is set by the shortest of them (Bandhan/ITI, from Feb 2020): roughly 79 overlapping months, not the full 13.7 years the five oldest funds have individually. The cell that builds the joint matrix prints the exact window it used.
- Each recently launched fund is fit **individually** on its own full history using a Student-T likelihood (fat tails, appropriate for so few observations) - the same pattern this notebook already used for a single asset early on. These funds' simulated paths do **not** share an estimated correlation with the long-history funds (there isn't enough overlapping data to estimate one credibly), and every result for them is flagged `low_confidence = True` - treat their numbers as rough, wide-uncertainty estimates, not the same statistical footing as the older funds.

**Strategy compared, same as before:** plain SIP vs. self-leveraged (pledge the lumpsum, take a loan reloaned every `RELOAN_MONTHS`, EMI paid from salary - not a drag on the invested corpus - only the *interest paid* reduces terminal wealth).

NAV data is fetched from `mfapi.in` (free public API for Indian mutual fund NAVs) and cached locally under `../data/nav/` - no more hardcoded paths to a different machine.
'@

$configPatched = $false
$mdPatched = $false

for ($i = 0; $i -lt $nb.cells.Count; $i++) {
    $src = $nb.cells[$i].source -join ''

    if ($src.Contains('FUND_CONFIG = [')) {
        if (-not $src.Contains($oldConfig)) { throw "FUND_CONFIG block in cell $i did not match expected text" }
        $nb.cells[$i].source = @($src.Replace($oldConfig, $newConfig))
        $configPatched = $true
        Write-Output "Patched FUND_CONFIG in cell $i"
    }

    if ($src.StartsWith('### Compare mutual fund returns')) {
        $nb.cells[$i].source = @($newMarkdown)
        $mdPatched = $true
        Write-Output "Replaced intro markdown in cell $i"
    }
}

if (-not $configPatched) { throw "FUND_CONFIG cell not found" }
if (-not $mdPatched) { throw "Intro markdown cell not found" }

$json = $nb | ConvertTo-Json -Depth 60
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($nbPath, $json, $utf8NoBom)

$check = Get-Content -Raw $nbPath | ConvertFrom-Json
Write-Output "Re-parsed OK. Cell count: $($check.cells.Count)"
$bytes = [System.IO.File]::ReadAllBytes($nbPath)
Write-Output ("First byte: {0:x2} (should be 7b)" -f $bytes[0])
