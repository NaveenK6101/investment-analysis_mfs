# Rebuilds the "compare mutual fund returns" section (original cells 110-125) of
# leaveraged_inv_strategy.ipynb into a cleaner, fund-count-agnostic version, and
# removes the unrelated Amazon ETL cells (original 154-159) that contained a
# plaintext DB password. Leaves every other cell untouched.

$nbPath = "C:\Users\Naveen\Desktop\Naveen_imp\investment\old-vahdam-files\leaveraged_inv_strategy.ipynb"
$nb = Get-Content -Raw $nbPath | ConvertFrom-Json

function New-CodeCell([string]$src) {
    [PSCustomObject]@{
        cell_type       = "code"
        execution_count = $null
        metadata        = [PSCustomObject]@{}
        outputs         = @()
        source          = @($src)
    }
}

function New-MarkdownCell([string]$src) {
    [PSCustomObject]@{
        cell_type = "markdown"
        metadata  = [PSCustomObject]@{}
        source    = @($src)
    }
}

$mdIntro = @'
### Compare mutual fund returns - rebuilt (Bayesian multivariate model)

**Funds compared:**

Established (13+ years of NAV history, used in the joint multivariate model):
1. Quant Flexi Cap Fund
2. Quant Small Cap Fund
3. Invesco India Mid Cap Fund
4. Nippon India Small Cap Fund
5. Quant Multi Asset Allocation Fund

Recently launched (fit individually, own Student-T model - not enough history for a reliable joint covariance estimate with the funds above):
6. TRUSTMF Small Cap Fund (~22 months of history)
7. Abakkus Small Cap Fund (~6 months of history)
8. Helios Small Cap Fund (~10 months of history under its current scheme code - the fund itself is older under its pre-rename BOI AXA name)

**Why two tiers?** Naively inner-joining all 8 funds' return histories would truncate *every* fund - including ones with 13 years of data - down to Abakkus's ~5 overlapping monthly observations, which would make every fund's posterior almost entirely prior-driven. Instead:
- The 5 established funds are fit **jointly** - `mu ~ Normal`, an `LKJCholeskyCov` prior on the covariance, `MvNormal` likelihood - same approach the original notebook used, so their estimated correlations are meaningful.
- Each new fund is fit **individually** on its own full history using a Student-T likelihood (fat tails, appropriate for so few observations) - the same pattern this notebook already used for a single asset early on. These funds' simulated paths do **not** share an estimated correlation with the established funds (there isn't enough overlapping data to estimate one credibly), and every result for them is flagged `low_confidence = True` - treat their numbers as rough, wide-uncertainty estimates, not the same statistical footing as the older funds.

**Strategy compared, same as before:** plain SIP vs. self-leveraged (pledge the lumpsum, take a loan reloaned every `RELOAN_MONTHS`, EMI paid from salary - not a drag on the invested corpus - only the *interest paid* reduces terminal wealth).

NAV data is fetched from `mfapi.in` (free public API for Indian mutual fund NAVs) and cached locally under `../data/nav/` - no more hardcoded paths to a different machine.
'@

$codeConfig = @'
import math
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import requests
import pymc as pm
import arviz as az

# -----------------------------
# Fund universe
# -----------------------------
# scheme_code = mfapi.in scheme code for the Direct Plan - Growth option
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

# Funds with fewer months of history than this are fit individually (Student-T),
# not folded into the joint multivariate model with the long-history funds.
NEW_FUND_MONTHS_THRESHOLD = 36

# -----------------------------
# Strategy parameters
# -----------------------------
INITIAL_CAPITAL = 1_000_000
LTV = 0.65
LOAN_RATE_ANNUAL = 0.10
R_M = LOAN_RATE_ANNUAL / 12
RELOAN_MONTHS = 36
TOTAL_MONTHS = 180  # 15 years
loan_amt = LTV * INITIAL_CAPITAL

DATA_DIR = Path("../data/nav")
DATA_DIR.mkdir(parents=True, exist_ok=True)
'@

$codeLoadFn = @'
def load_fund_nav(key: str, scheme_code: int, force_refresh: bool = False) -> pd.DataFrame:
    """Load daily NAV history for a fund: from local cache if present, else mfapi.in.

    Returns a DataFrame indexed by date with a single 'nav' column.
    """
    cache_path = DATA_DIR / f"{key}.csv"

    if cache_path.exists() and not force_refresh:
        df = pd.read_csv(cache_path, parse_dates=["date"])
    else:
        resp = requests.get(f"https://api.mfapi.in/mf/{scheme_code}", timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        df = pd.DataFrame(payload["data"])
        df["date"] = pd.to_datetime(df["date"], format="%d-%m-%Y")
        df["nav"] = df["nav"].astype(float)
        df = df.sort_values("date")
        df.to_csv(cache_path, index=False)

    return df.set_index("date").sort_index()
'@

$codeLoadClassify = @'
fund_returns = {}         # key -> monthly log-return Series
fund_history_months = {}  # key -> number of monthly observations available

for fund in FUND_CONFIG:
    nav = load_fund_nav(fund["key"], fund["scheme_code"])
    monthly_nav = nav["nav"].resample("M").last()
    monthly_ret = np.log(monthly_nav / monthly_nav.shift(1)).dropna()

    fund_returns[fund["key"]] = monthly_ret
    fund_history_months[fund["key"]] = len(monthly_ret)

established_keys = [f["key"] for f in FUND_CONFIG if fund_history_months[f["key"]] >= NEW_FUND_MONTHS_THRESHOLD]
new_keys = [f["key"] for f in FUND_CONFIG if fund_history_months[f["key"]] < NEW_FUND_MONTHS_THRESHOLD]

fund_display_name = {f["key"]: f["name"] for f in FUND_CONFIG}

summary = pd.DataFrame([
    {
        "fund": fund_display_name[k],
        "months_of_history": fund_history_months[k],
        "tier": "established (joint model)" if k in established_keys else "new (individual model, LOW_CONFIDENCE)",
    }
    for k in fund_display_name
]).sort_values("months_of_history", ascending=False)

summary
'@

$codeJointMatrix = @'
established_returns = pd.concat(
    [fund_returns[k].rename(k) for k in established_keys],
    axis=1,
    join="inner",
).dropna()

print(f"Established funds joint sample: {established_returns.shape[0]} overlapping months "
      f"({established_returns.index.min().date()} to {established_returns.index.max().date()})")

mf_log_return = established_returns.values  # shape (n_months, K_established)
K_established = mf_log_return.shape[1]
'@

$codeEda = @'
fig, axes = plt.subplots(1, K_established, figsize=(4 * K_established, 3.5), sharey=True)
for i, k in enumerate(established_keys):
    sns.kdeplot(established_returns[k], ax=axes[i], fill=True)
    axes[i].set_title(fund_display_name[k], fontsize=10)
    axes[i].set_xlabel("monthly log return")
plt.tight_layout()
plt.show()

established_returns.corr()
'@

$codeJointModelFn = @'
def build_mv_normal_model(log_returns: np.ndarray) -> pm.Model:
    """LKJ-covariance multivariate-normal model over the monthly log returns of K assets."""
    K = log_returns.shape[1]
    with pm.Model() as model:
        mu = pm.Normal("mu", mu=0.0, sigma=0.05, shape=K)
        chol_cov, corr, sigma = pm.LKJCholeskyCov(
            "chol_cov", n=K, eta=2.0, sd_dist=pm.HalfNormal.dist(0.05), compute_corr=True
        )
        pm.MvNormal("obs", mu=mu, chol=chol_cov, observed=log_returns)
    return model
'@

$codeFitJoint = @'
with build_mv_normal_model(mf_log_return) as mf_model:
    mf_trace = pm.sample(draws=2000, tune=2000, chains=4, target_accept=0.9, random_seed=42)

az.summary(mf_trace, var_names=["mu", "chol_cov_stds", "chol_cov_corr"])
'@

$codeSingleModelFn = @'
def build_student_t_model(log_returns_1d: np.ndarray) -> pm.Model:
    """Student-T model for a single fund's monthly log returns (fat tails, few observations)."""
    with pm.Model() as model:
        mu = pm.Normal("mu", mu=0.0, sigma=0.05)
        sigma = pm.HalfNormal("sigma", sigma=0.05)
        nu = pm.Exponential("nu", 1 / 10) + 2
        pm.StudentT("obs", mu=mu, sigma=sigma, nu=nu, observed=log_returns_1d)
    return model
'@

$codeFitNew = @'
new_fund_traces = {}

for k in new_keys:
    log_returns_1d = fund_returns[k].values
    print(f"\n===== {fund_display_name[k]} ({fund_history_months[k]} monthly observations) =====")
    with build_student_t_model(log_returns_1d) as model:
        trace = pm.sample(draws=2000, tune=2000, chains=4, target_accept=0.95, random_seed=42)
    new_fund_traces[k] = trace
    display(az.summary(trace, var_names=["mu", "sigma", "nu"]))
'@

$codeSimulate = @'
def simulate_established_paths(trace, months: int, seed: int = 42) -> np.ndarray:
    """Monte Carlo forward-simulate correlated monthly log-return paths from the joint posterior."""
    posterior = trace.posterior
    n_chains, n_draws = posterior.dims["chain"], posterior.dims["draw"]
    N = n_chains * n_draws
    K = posterior.dims["mu_dim_0"]

    mu_samples = posterior["mu"].values.reshape(N, K)
    std_samples = posterior["chol_cov_stds"].values.reshape(N, K)
    corr_samples = posterior["chol_cov_corr"].values.reshape(N, K, K)

    cov_samples = np.empty((N, K, K))
    for i in range(N):
        D = np.diag(std_samples[i])
        cov_samples[i] = D @ corr_samples[i] @ D
    chol_samples = np.linalg.cholesky(cov_samples)

    rng = np.random.default_rng(seed)
    Z = rng.standard_normal((N, months, K))

    paths = np.empty((N, months, K))
    for i in range(N):
        paths[i] = mu_samples[i] + Z[i] @ chol_samples[i].T
    return paths  # (N, months, K)


def simulate_single_fund_paths(trace, months: int, seed: int = 42) -> np.ndarray:
    """Monte Carlo forward-simulate a single fund's monthly log-return path from its Student-T posterior."""
    posterior = trace.posterior
    n_chains, n_draws = posterior.dims["chain"], posterior.dims["draw"]
    N = n_chains * n_draws

    mu_samples = posterior["mu"].values.reshape(N)
    sigma_samples = posterior["sigma"].values.reshape(N)
    nu_samples = posterior["nu"].values.reshape(N)

    rng = np.random.default_rng(seed)
    paths = np.empty((N, months))
    for i in range(N):
        paths[i] = mu_samples[i] + sigma_samples[i] * rng.standard_t(nu_samples[i], size=months)
    return paths  # (N, months)


paths_established = simulate_established_paths(mf_trace, TOTAL_MONTHS)
paths_new = {k: simulate_single_fund_paths(new_fund_traces[k], TOTAL_MONTHS) for k in new_keys}

print("paths_established shape:", paths_established.shape)
for k, p in paths_new.items():
    print(f"paths_new[{k}] shape:", p.shape)
'@

$codeStrategyFns = @'
def emi_amount(principal, r, n):
    return principal * r * (1 + r) ** n / ((1 + r) ** n - 1)


emi = emi_amount(loan_amt, R_M, RELOAN_MONTHS)


def unleveraged_sip(paths_asset, emi):
    N, T = paths_asset.shape
    wealth = np.zeros((N, T))
    capital = np.zeros((N, T))

    for i in range(N):
        w = INITIAL_CAPITAL
        total_cap = INITIAL_CAPITAL
        for t in range(T):
            w *= np.exp(paths_asset[i, t])
            w += emi
            total_cap += emi
            wealth[i, t] = w
            capital[i, t] = total_cap

    return wealth, capital


def self_leveraged_mf(paths_asset):
    N, T = paths_asset.shape
    wealth = np.zeros((N, T))
    capital = np.zeros((N, T))

    for i in range(N):
        invested = INITIAL_CAPITAL
        total_cap = INITIAL_CAPITAL
        total_interest_paid = 0

        for t in range(T):
            if t % RELOAN_MONTHS == 0:
                invested += loan_amt
                total_cap += loan_amt
                emi_cycle = emi_amount(loan_amt, R_M, RELOAN_MONTHS)
                total_paid = emi_cycle * RELOAN_MONTHS
                total_interest_paid += total_paid - loan_amt

            invested *= np.exp(paths_asset[i, t])
            wealth[i, t] = invested - total_interest_paid
            capital[i, t] = total_cap

    return wealth, capital


def irr_newton(cashflows, guess=0.01, tol=1e-6, max_iter=100):
    rate = guess
    for _ in range(max_iter):
        npv = sum(cf / (1 + rate) ** t for t, cf in enumerate(cashflows))
        d_npv = sum(-t * cf / (1 + rate) ** (t + 1) for t, cf in enumerate(cashflows))
        if abs(npv) < tol:
            return rate
        if d_npv == 0:
            return np.nan
        rate = rate - npv / d_npv
    return np.nan


def compute_irr_sip(final_wealth):
    cashflows = [-INITIAL_CAPITAL] + [-emi] * (TOTAL_MONTHS - 1) + [final_wealth]
    return irr_newton(cashflows)


def compute_irr_lev(final_wealth):
    cashflows = [-INITIAL_CAPITAL]
    for t in range(1, TOTAL_MONTHS):
        cashflows.append(-loan_amt if t % RELOAN_MONTHS == 0 else 0)
    cashflows.append(final_wealth)
    return irr_newton(cashflows)
'@

$codeComparison = @'
# Assemble a (N, TOTAL_MONTHS) path array per fund, regardless of which model produced it
fund_paths = {}
for i, k in enumerate(established_keys):
    fund_paths[k] = paths_established[:, :, i]
for k in new_keys:
    fund_paths[k] = paths_new[k]

rows = []
wealth_by_fund = {}  # cached for the plotting cell below

for k, asset_paths in fund_paths.items():
    w_sip, cap_sip = unleveraged_sip(asset_paths, emi)
    w_lev, cap_lev = self_leveraged_mf(asset_paths)
    wealth_by_fund[k] = {"sip": w_sip, "lev": w_lev, "cap_sip": cap_sip, "cap_lev": cap_lev}

    final_sip, final_lev = w_sip[:, -1], w_lev[:, -1]
    total_cap_sip, total_cap_lev = cap_sip[:, -1], cap_lev[:, -1]

    roic_sip = final_sip / total_cap_sip - 1
    roic_lev = final_lev / total_cap_lev - 1

    irr_sip_annual = (1 + np.array([compute_irr_sip(w) for w in final_sip])) ** 12 - 1
    irr_lev_annual = (1 + np.array([compute_irr_lev(w) for w in final_lev])) ** 12 - 1

    rows.append({
        "fund": fund_display_name[k],
        "low_confidence": k in new_keys,
        "months_of_history": fund_history_months[k],
        "p_lev_beats_sip": np.mean(final_lev > final_sip),
        "median_wealth_sip": np.median(final_sip),
        "median_wealth_lev": np.median(final_lev),
        "wealth_p05_lev": np.percentile(final_lev, 5),
        "wealth_p50_lev": np.percentile(final_lev, 50),
        "wealth_p95_lev": np.percentile(final_lev, 95),
        "median_roic_sip": np.median(roic_sip),
        "median_roic_lev": np.median(roic_lev),
        "median_irr_sip": np.nanmedian(irr_sip_annual),
        "median_irr_lev": np.nanmedian(irr_lev_annual),
        "irr_p05_lev": np.nanpercentile(irr_lev_annual, 5),
    })

results_df = pd.DataFrame(rows).sort_values("median_irr_lev", ascending=False).reset_index(drop=True)
results_df
'@

$codePlots = @'
n_funds = len(fund_paths)
ncols = 3
nrows = math.ceil(n_funds / ncols)

fig, axes = plt.subplots(nrows, ncols, figsize=(6 * ncols, 4 * nrows), squeeze=False)
for ax, k in zip(axes.flat, fund_paths):
    w = wealth_by_fund[k]
    ax.plot(w["sip"][:, ::12].mean(axis=0), label="SIP")
    ax.plot(w["lev"][:, ::12].mean(axis=0), label="Self-Leveraged")
    title = fund_display_name[k] + (" (LOW CONFIDENCE)" if k in new_keys else "")
    ax.set_title(title, fontsize=10)
    ax.set_xlabel("Years")
    ax.set_ylabel("Wealth")
    ax.legend(fontsize=8)
    ax.grid(True)

for ax in axes.flat[n_funds:]:
    ax.axis("off")

plt.tight_layout()
plt.show()
'@

$codeLtv = @'
def simulate_leveraged_wealth_for_ltv(paths_asset, ltv):
    loan = ltv * INITIAL_CAPITAL
    emi_cycle = emi_amount(loan, R_M, RELOAN_MONTHS) if loan > 0 else 0
    N, T = paths_asset.shape
    wealth = np.zeros((N, T))

    for i in range(N):
        invested = INITIAL_CAPITAL
        total_interest = 0
        for t in range(T):
            if loan > 0 and t % RELOAN_MONTHS == 0:
                invested += loan
                total_interest += emi_cycle * RELOAN_MONTHS - loan
            invested *= np.exp(paths_asset[i, t])
            wealth[i, t] = invested - total_interest

    return wealth


def compute_irr_for_ltv(final_wealth, ltv):
    loan = ltv * INITIAL_CAPITAL
    cashflows = [-INITIAL_CAPITAL]
    for t in range(1, TOTAL_MONTHS):
        cashflows.append(-loan if (loan > 0 and t % RELOAN_MONTHS == 0) else 0)
    cashflows.append(final_wealth)
    return irr_newton(cashflows)


LTV_grid = np.linspace(0, 1, 10)

# Subsample posterior draws for the LTV sweep: the full N x 10 LTVs x 8 funds
# grid is slow in a pure-Python loop, and 500 draws is plenty to see the shape
# of median-IRR-vs-LTV.
LTV_SWEEP_N_DRAWS = 500
rng = np.random.default_rng(0)

ltv_results = {}
for k, asset_paths in fund_paths.items():
    idx = rng.choice(asset_paths.shape[0], size=min(LTV_SWEEP_N_DRAWS, asset_paths.shape[0]), replace=False)
    sub_paths = asset_paths[idx]

    rows = []
    for ltv in LTV_grid:
        w = simulate_leveraged_wealth_for_ltv(sub_paths, ltv)
        final_w = w[:, -1]
        irr_annual = (1 + np.array([compute_irr_for_ltv(fw, ltv) for fw in final_w])) ** 12 - 1
        rows.append([ltv, np.nanmedian(irr_annual), np.nanpercentile(irr_annual, 5), np.mean(irr_annual < 0)])
    ltv_results[k] = np.array(rows)

n_funds = len(fund_paths)
ncols = 3
nrows = math.ceil(n_funds / ncols)

for col, title, ylabel in [(1, "Median Annual IRR vs LTV", "Median Annual IRR"),
                            (3, "P(IRR < 0) vs LTV", "Prob(IRR < 0)")]:
    fig, axes = plt.subplots(nrows, ncols, figsize=(5 * ncols, 3.5 * nrows), squeeze=False)
    for ax, k in zip(axes.flat, fund_paths):
        r = ltv_results[k]
        ax.plot(r[:, 0], r[:, col])
        fund_title = fund_display_name[k] + (" (LOW CONFIDENCE)" if k in new_keys else "")
        ax.set_title(fund_title, fontsize=10)
        ax.set_xlabel("LTV")
        ax.set_ylabel(ylabel)
        ax.grid(True)
    for ax in axes.flat[n_funds:]:
        ax.axis("off")
    fig.suptitle(title)
    plt.tight_layout()
    plt.show()
'@

$newCells = @(
    (New-MarkdownCell $mdIntro),
    (New-CodeCell $codeConfig),
    (New-CodeCell $codeLoadFn),
    (New-CodeCell $codeLoadClassify),
    (New-CodeCell $codeJointMatrix),
    (New-CodeCell $codeEda),
    (New-CodeCell $codeJointModelFn),
    (New-CodeCell $codeFitJoint),
    (New-CodeCell $codeSingleModelFn),
    (New-CodeCell $codeFitNew),
    (New-CodeCell $codeSimulate),
    (New-CodeCell $codeStrategyFns),
    (New-CodeCell $codeComparison),
    (New-CodeCell $codePlots),
    (New-CodeCell $codeLtv)
)

# Original cells: 0..109 untouched, 110..125 = old MF section (replaced),
# 126..153 untouched, 154..159 = Amazon ETL block (removed, had plaintext DB password).
$before = $nb.cells[0..109]
$middle = $nb.cells[126..153]

$nb.cells = @($before) + @($newCells) + @($middle)

Write-Output "New total cell count: $($nb.cells.Count)"

$json = $nb | ConvertTo-Json -Depth 60
Set-Content -Path $nbPath -Value $json -Encoding utf8

Write-Output "Notebook written. Validating JSON..."
$check = Get-Content -Raw $nbPath | ConvertFrom-Json
Write-Output "Re-parsed OK. Cell count: $($check.cells.Count)"
