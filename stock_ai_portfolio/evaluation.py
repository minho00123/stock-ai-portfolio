"""Arithmetic on documented summaries, not a rerun of historical model validation."""
import math


def uncertainty(mean_pp: float, sd_pp: float, n: int) -> dict:
    if type(n) is not int or n < 2:
        raise ValueError("at least two periods required")
    if not math.isfinite(mean_pp) or not math.isfinite(sd_pp) or sd_pp <= 0:
        raise ValueError("finite mean and positive standard deviation required")
    se = sd_pp / math.sqrt(n)
    return {"standard_error_pp": round(se, 4), "t_statistic": round(mean_pp / se, 4),
            "normal_approx_interval_95_pp": [round(mean_pp - 1.96 * se, 4),
                                              round(mean_pp + 1.96 * se, 4)],
            "interval_includes_zero": mean_pp - 1.96 * se <= 0 <= mean_pp + 1.96 * se}
