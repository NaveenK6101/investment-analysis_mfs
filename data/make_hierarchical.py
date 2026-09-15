"""Replace the flat per-fund model with a proper hierarchical one.

Why: the flat model let each fund's mean be estimated from its own data alone,
against a prior (Normal(0, 0.05) monthly = +-60%/yr) so diffuse it constrained
nothing. On a window starting at the COVID bottom that produced 20-32%/yr medians
for the established funds, and a fund with 6 observations claiming 50%/yr.

Three changes:

1. PARTIAL POOLING. Every fund's mean is now drawn from a shared distribution,
   mu_k = mu_global + tau * offset_k, so funds borrow strength from each other.
   A fund with 164 months barely moves; a fund with 6 months collapses toward the
   group mean, which is the correct answer when you have almost no data.

2. INFORMATIVE PRIOR on the group mean. mu_global ~ Normal(0.0094, 0.003) monthly
   is centred on ~12%/yr (long-run Indian equity, in log terms) with an 89%
   interval of roughly 6-18%/yr. Wide enough to let data speak, tight enough that
   six months of a bull run cannot claim 50%/yr.

3. FULL HISTORY FOR THE MEANS. The joint MvNormal still runs on the common
   79-month window (correlations need overlapping observations), but each
   long-history fund additionally contributes its PRE-window returns through a
   univariate likelihood sharing the same mu and sigma. That brings 2013-2019 back
   in - including the 2018-19 small-cap drawdown the COVID-onwards window omits.

Non-centred parameterisation throughout, to avoid the funnel geometry that
otherwise produces divergences in hierarchical models.
"""

from __future__ import annotations

import sys
from pathlib import Path

import nbformat

NB = Path(r"C:\Users\Naveen\Desktop\Naveen_imp\investment\old-vahdam-files\mf_leveraged_strategy.ipynb")

# ---------------------------------------------------------------- cell 4
JOINT_MATRIX = '''established_returns = pd.concat(
    [fund_returns[k].rename(k) for k in established_keys],
    axis=1,
    join="inner",
).dropna()

mf_log_return = established_returns.values          # (n_months, K) common window
K_established = mf_log_return.shape[1]
window_start = established_returns.index.min()

print(f"Joint (correlation) window: {established_returns.shape[0]} overlapping months "
      f"({window_start.date()} to {established_returns.index.max().date()})")

# Returns each long-history fund has BEFORE the common window. These are disjoint
# from the joint block, so they can be added as extra univariate observations on
# the same mu/sigma - this is how the older funds keep the benefit of their full
# history even though the joint window is short.
pre_window_returns = {
    k: fund_returns[k][fund_returns[k].index < window_start].values
    for k in established_keys
}
short_returns = {k: fund_returns[k].values for k in new_keys}

print("\\nExtra pre-window months contributed per fund:")
for k in established_keys:
    print(f"  {fund_display_name[k]:32s} {len(pre_window_returns[k]):4d}")
print("\\nShort-history funds (own data only, pooled toward the group mean):")
for k in new_keys:
    print(f"  {fund_display_name[k]:32s} {len(short_returns[k]):4d}")
'''

# ---------------------------------------------------------------- cell 6
MODEL_FN = '''# Group-level prior: ~12%/yr in log terms, 89% interval roughly 6-18%/yr.
# This is the number doing the work against short-history funds - it is what stops
# six months of a bull run from being extrapolated as 50%/yr for fifteen years.
MU_GLOBAL_PRIOR_MEAN = 0.0094      # monthly log return, log(1.12)/12
MU_GLOBAL_PRIOR_SD = 0.003
TAU_PRIOR_SD = 0.004               # between-fund spread in monthly log return


def build_hierarchical_model(joint_returns, pre_window, short_data,
                             established_keys, new_keys) -> pm.Model:
    """One model over every fund, with partial pooling of the means.

    joint_returns : (n_months, K) common-window returns for the long-history funds
    pre_window    : {key: 1d array} each long-history fund's returns before that window
    short_data    : {key: 1d array} full history of each short-history fund
    """
    K = joint_returns.shape[1]

    with pm.Model() as model:
        # ---- group level ----
        mu_global = pm.Normal("mu_global", MU_GLOBAL_PRIOR_MEAN, MU_GLOBAL_PRIOR_SD)
        tau = pm.HalfNormal("tau", TAU_PRIOR_SD)

        # ---- long-history funds: non-centred offsets ----
        offset = pm.Normal("offset", 0.0, 1.0, shape=K)
        mu = pm.Deterministic("mu", mu_global + tau * offset)

        chol_cov, corr, stds = pm.LKJCholeskyCov(
            "chol_cov", n=K, eta=2.0, sd_dist=pm.HalfNormal.dist(0.05), compute_corr=True
        )

        # joint likelihood on the overlapping window (this is what identifies corr)
        pm.MvNormal("obs_joint", mu=mu, chol=chol_cov, observed=joint_returns)

        # each fund's own earlier history, on the same mu and its own sigma
        for i, k in enumerate(established_keys):
            extra = pre_window[k]
            if len(extra) > 0:
                pm.Normal(f"obs_pre_{k}", mu=mu[i], sigma=stds[i], observed=extra)

        # ---- short-history funds: pooled toward the same group mean ----
        for k in new_keys:
            off_k = pm.Normal(f"offset_{k}", 0.0, 1.0)
            mu_k = pm.Deterministic(f"mu_{k}", mu_global + tau * off_k)
            sigma_k = pm.HalfNormal(f"sigma_{k}", 0.05)
            nu_k = pm.Deterministic(f"nu_{k}", pm.Exponential(f"nu_raw_{k}", 1 / 10) + 2)
            pm.StudentT(f"obs_{k}", mu=mu_k, sigma=sigma_k, nu=nu_k, observed=short_data[k])

    return model
'''

# ---------------------------------------------------------------- cell 7
FIT = '''with build_hierarchical_model(
    mf_log_return, pre_window_returns, short_returns, established_keys, new_keys
) as mf_model:
    mf_trace = pm.sample(draws=2000, tune=2000, chains=4, nuts_sampler="nutpie",
                         target_accept=0.9, random_seed=42)

az.summary(mf_trace, var_names=["mu_global", "tau", "mu"] + [f"mu_{k}" for k in new_keys])
'''

# ---------------------------------------------------------------- cell 8
SHRINKAGE = '''# How much did pooling move each fund away from its own sample mean?
# Large moves are expected exactly where the data is thin - that is the point.
post = mf_trace.posterior
mu_joint_post = post["mu"].values.reshape(-1, K_established)

rows = []
for i, k in enumerate(established_keys):
    own = np.concatenate([mf_log_return[:, i], pre_window_returns[k]])
    rows.append({
        "fund": fund_display_name[k],
        "n_months": len(own),
        "sample_mean_ann": np.exp(own.mean() * 12) - 1,
        "posterior_mean_ann": np.exp(mu_joint_post[:, i].mean() * 12) - 1,
    })
for k in new_keys:
    own = short_returns[k]
    rows.append({
        "fund": fund_display_name[k] + " *",
        "n_months": len(own),
        "sample_mean_ann": np.exp(own.mean() * 12) - 1,
        "posterior_mean_ann": np.exp(post[f"mu_{k}"].values.mean() * 12) - 1,
    })

shrinkage = pd.DataFrame(rows)
shrinkage["shrunk_by_pp"] = (shrinkage["sample_mean_ann"] - shrinkage["posterior_mean_ann"]) * 100
shrinkage["sample_mean_ann"] = (shrinkage["sample_mean_ann"] * 100).round(1)
shrinkage["posterior_mean_ann"] = (shrinkage["posterior_mean_ann"] * 100).round(1)
shrinkage["shrunk_by_pp"] = shrinkage["shrunk_by_pp"].round(1)

g_ann = np.exp(post["mu_global"].values.mean() * 12) - 1
print(f"Group mean (mu_global): {g_ann*100:.1f}%/yr")
print(f"Between-fund spread (tau): {post['tau'].values.mean():.5f}/month\\n")
print("Sample mean vs pooled posterior mean, annualised %:")
shrinkage.sort_values("n_months", ascending=False).reset_index(drop=True)
'''

# ---------------------------------------------------------------- cell 9
SIMULATE = '''def simulate_all_paths(trace, months, established_keys, new_keys, seed=42):
    """Forward-simulate monthly log-return paths for every fund from one trace.

    Long-history funds are simulated jointly, so their estimated correlations carry
    through. Short-history funds are simulated from their own Student-T marginals -
    there is not enough overlapping data to place them in the covariance credibly.
    """
    post = trace.posterior
    N = post.sizes["chain"] * post.sizes["draw"]
    K = post.sizes["mu_dim_0"]
    rng = np.random.default_rng(seed)

    mu_s = post["mu"].values.reshape(N, K)
    std_s = post["chol_cov_stds"].values.reshape(N, K)
    corr_s = post["chol_cov_corr"].values.reshape(N, K, K)

    cov = np.empty((N, K, K))
    for i in range(N):
        D = np.diag(std_s[i])
        cov[i] = D @ corr_s[i] @ D
    chol = np.linalg.cholesky(cov)

    Z = rng.standard_normal((N, months, K))
    joint_paths = np.empty((N, months, K))
    for i in range(N):
        joint_paths[i] = mu_s[i] + Z[i] @ chol[i].T

    paths = {k: joint_paths[:, :, i] for i, k in enumerate(established_keys)}

    for k in new_keys:
        m = post[f"mu_{k}"].values.reshape(N)
        s = post[f"sigma_{k}"].values.reshape(N)
        nu = post[f"nu_{k}"].values.reshape(N)      # already shifted, so df >= 2
        p = np.empty((N, months))
        for i in range(N):
            p[i] = m[i] + s[i] * rng.standard_t(nu[i], size=months)
        paths[k] = p

    return paths


fund_paths_raw = simulate_all_paths(mf_trace, TOTAL_MONTHS, established_keys, new_keys)
for k, v in fund_paths_raw.items():
    assert np.isfinite(v).all(), f"non-finite simulated returns for {k}"
print("simulated paths:", {k: v.shape for k, v in list(fund_paths_raw.items())[:3]}, "...")
'''

REPLACEMENTS = {
    4: ("established_returns = pd.concat", JOINT_MATRIX),
    6: ("def build_mv_normal_model", MODEL_FN),
    7: ("with build_mv_normal_model", FIT),
    8: ("def build_student_t_model", SHRINKAGE),
    9: ("new_fund_traces = {}", SHRINKAGE),      # placeholder, resolved below
    10: ("def simulate_established_paths", SIMULATE),
}


def main() -> int:
    nb = nbformat.read(NB, as_version=4)
    if len(nb.cells) != 19:
        raise SystemExit(f"expected 19 cells, found {len(nb.cells)}")

    def check(idx, marker):
        if marker not in nb.cells[idx].source:
            raise SystemExit(f"cell {idx} does not contain {marker!r}")

    for idx, (marker, _) in REPLACEMENTS.items():
        check(idx, marker)

    nb.cells[4].source = JOINT_MATRIX
    nb.cells[6].source = MODEL_FN
    nb.cells[7].source = FIT
    nb.cells[8].source = SHRINKAGE
    nb.cells[10].source = SIMULATE
    # cell 9 held the per-fund Student-T fitting loop, now folded into the single
    # hierarchical model - drop it
    del nb.cells[9]

    # the comparison cell built fund_paths from the old split arrays
    for i, c in enumerate(nb.cells):
        if c.cell_type == "code" and "fund_paths = {}" in c.source:
            old_block = c.source.split("rows = []")[0]
            c.source = c.source.replace(old_block, "fund_paths = fund_paths_raw\n\n")
            print(f"cell {i}: fund_paths now comes straight from the single model")
            break

    for i, c in enumerate(nb.cells):
        if c.cell_type == "code":
            for stale in ("paths_established", "paths_new", "new_fund_traces",
                          "build_mv_normal_model", "build_student_t_model"):
                if stale in c.source:
                    raise SystemExit(f"stale reference {stale!r} left in cell {i}")

    nbformat.validator.normalize(nb)
    nbformat.write(nb, NB)
    print(f"OK - hierarchical model written, {len(nb.cells)} cells")
    return 0


if __name__ == "__main__":
    sys.exit(main())
