import numpy as np
import pandas as pd
from loguru import logger


def apply_vol_targeting(
    weights: dict[str, float],
    returns_df: pd.DataFrame,
    target_vol: float = 0.10,
    window: int = 26,
    max_scale: float = 1.0,
) -> dict[str, float]:
    """Scale portfolio exposure by realized covariance-based volatility.

    Uses a covariance matrix (not individual σ) to capture correlation spikes.
    max_scale=1.0 means no leverage — exposure is only ever reduced.

    Reference: Moreira & Muir (2017) 'Volatility-Managed Portfolios', JoF.
    """
    invest_assets = [a for a in weights if a != "Cash" and a in returns_df.columns]

    if not invest_assets:
        return weights

    w_vec = np.array([weights[a] for a in invest_assets])
    recent = returns_df[invest_assets].tail(window)

    if len(recent) < 2:
        return weights

    cov_matrix = recent.cov() * 52  # annualise weekly returns
    port_vol = float(np.sqrt(w_vec @ cov_matrix.values @ w_vec))

    if port_vol <= 0:
        return weights

    scale = min(max_scale, target_vol / port_vol)

    scaled: dict[str, float] = {}
    total_scaled = 0.0
    for asset in invest_assets:
        scaled[asset] = weights[asset] * scale
        total_scaled += scaled[asset]

    scaled["Cash"] = 1.0 - total_scaled

    logger.info(
        f"vol_targeting: port_vol={port_vol:.3f} scale={scale:.3f} "
        f"invested={total_scaled:.3f} target={target_vol}"
    )
    return scaled
