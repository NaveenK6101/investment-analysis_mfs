# Compatibility fixes for the rebuilt MF section against the versions actually
# installed in the `hp` env: pandas 2.3.3, xarray 2026.7.0, pymc 6.3.1, arviz 1.3.0.
#
#  1. resample("M")  -> resample("ME")   ('M' is deprecated in pandas 2.2+)
#  2. posterior.dims["x"] -> posterior.sizes["x"]  (Dataset.dims mapping access is
#     deprecated in xarray; it will return a set of names in a future release)

$nbPath = "C:\Users\Naveen\Desktop\Naveen_imp\investment\old-vahdam-files\leaveraged_inv_strategy.ipynb"
$nb = Get-Content -Raw $nbPath | ConvertFrom-Json

$replacements = @(
    @{ old = 'nav["nav"].resample("M").last()'; new = 'nav["nav"].resample("ME").last()' },
    @{ old = 'n_chains, n_draws = posterior.dims["chain"], posterior.dims["draw"]'; new = 'n_chains, n_draws = posterior.sizes["chain"], posterior.sizes["draw"]' },
    @{ old = 'K = posterior.dims["mu_dim_0"]'; new = 'K = posterior.sizes["mu_dim_0"]' }
)

$applied = @{}
foreach ($r in $replacements) { $applied[$r.old] = 0 }

for ($i = 0; $i -lt $nb.cells.Count; $i++) {
    $src = $nb.cells[$i].source -join ''
    $orig = $src
    foreach ($r in $replacements) {
        if ($src.Contains($r.old)) {
            $src = $src.Replace($r.old, $r.new)
            $applied[$r.old] = $applied[$r.old] + 1
            Write-Output "cell $i : patched -> $($r.new)"
        }
    }
    if ($src -ne $orig) { $nb.cells[$i].source = @($src) }
}

foreach ($r in $replacements) {
    if ($applied[$r.old] -eq 0) { throw "Pattern never matched, notebook may have drifted: $($r.old)" }
}

$json = $nb | ConvertTo-Json -Depth 60
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($nbPath, $json, $utf8NoBom)

$check = Get-Content -Raw $nbPath | ConvertFrom-Json
Write-Output "Re-parsed OK. Cell count: $($check.cells.Count)"
