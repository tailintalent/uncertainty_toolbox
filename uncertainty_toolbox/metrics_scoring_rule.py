"""
Proper Scoring Rules for assessing the quality of predictive
uncertainty quantification.
"""

import numpy as np
from scipy import stats
import torch
from torch.distributions import Normal
from typing import Union
from uncertainty_toolbox.utils import assert_is_flat_same_shape, sum_fn, mean_fn


def nll_gaussian(
    y_pred: Union[np.ndarray, torch.Tensor],
    y_std: Union[np.ndarray, torch.Tensor],
    y_true: Union[np.ndarray, torch.Tensor],
    scaled: bool = True,
) -> float:
    """Negative log likelihood for a gaussian.

    The negative log likelihood for held out data (y_true) given predictive
    uncertainty with mean (y_pred) and standard-deviation (y_std).

    Args:
        y_pred: 1D array of the predicted means for the held out dataset.
        y_std: 1D array of the predicted standard deviations for the held out dataset.
        y_true: 1D array of the true labels in the held out dataset.
        scaled: Whether to scale the negative log likelihood by size of held out set.

    Returns:
        The negative log likelihood for the heldout set.
    """

    # Check that input arrays are flat
    assert_is_flat_same_shape(y_pred, y_std, y_true)

    # Set residuals
    residuals = y_pred - y_true

    # Compute nll
    if isinstance(y_pred, torch.Tensor):
        dist = Normal(loc=torch.tensor(0., dtype=y_pred.dtype, device=y_pred.device),
                      scale=y_std)
        nll_list = dist.log_prob(residuals)
    else:
        nll_list = stats.norm.logpdf(residuals, scale=y_std)
    nll = -1 * sum_fn(nll_list)

    # Potentially scale so that sum becomes mean
    if scaled:
        nll = nll / len(nll_list)

    return nll


def crps_gaussian(
    y_pred: Union[np.ndarray, torch.Tensor],
    y_std: Union[np.ndarray, torch.Tensor],
    y_true: Union[np.ndarray, torch.Tensor],
    scaled: bool = True,
) -> float:
    """The negatively oriented continuous ranked probability score for Gaussians.

    Computes CRPS for held out data (y_true) given predictive uncertainty with mean
    (y_pred) and standard-deviation (y_std). Each test point is given equal weight
    in the overall score over the test set.

    Negatively oriented means a smaller value is more desirable.

    Args:
        y_pred: 1D array of the predicted means for the held out dataset.
        y_std: 1D array of he predicted standard deviations for the held out dataset.
        y_true: 1D array of the true labels in the held out dataset.
        scaled: Whether to scale the score by size of held out set.

    Returns:
        The crps for the heldout set.
    """

    # Check that input arrays are flat
    assert_is_flat_same_shape(y_pred, y_std, y_true)

    # Compute crps
    y_standardized = (y_true - y_pred) / y_std
    term_1 = 1 / np.sqrt(np.pi)
    if isinstance(y_pred, torch.Tensor):
        device = y_pred.device
        dtype = y_pred.dtype
        dist = Normal(loc=torch.tensor([0.], dtype=dtype, device=device),
                      scale=torch.tensor([1.], dtype=dtype, device=device))
        term_2 = 2 * dist.log_prob(y_standardized).exp()
        term_3 = y_standardized * (2 * dist.cdf(y_standardized) - 1)
    else:
        term_2 = 2 * stats.norm.pdf(y_standardized, loc=0, scale=1) 
        term_3 = y_standardized * (2 * stats.norm.cdf(y_standardized, loc=0, scale=1) - 1)

    crps_list = -1 * y_std * (term_1 - term_2 - term_3)
    crps = sum_fn(crps_list)

    # Potentially scale so that sum becomes mean
    if scaled:
        crps = crps / len(crps_list)

    return crps


def check_score(
    y_pred: Union[np.ndarray, torch.Tensor],
    y_std: Union[np.ndarray, torch.Tensor],
    y_true: Union[np.ndarray, torch.Tensor],
    scaled: bool = True,
    start_q: float = 0.01,
    end_q: float = 0.99,
    resolution: int = 99,
) -> float:
    """The negatively oriented check score.

    Computes the negatively oriented check score for held out data (y_true)
    given predictive uncertainty with mean (y_pred) and standard-deviation (y_std).
    Each test point and each quantile is given equal weight in the overall score
    over the test set and list of quantiles.

    The score is computed by scanning over a sequence of quantiles of the predicted
    distributions, starting at (start_q) and ending at (end_q).

    Negatively oriented means a smaller value is more desirable.

    Args:
        y_pred: 1D array of the predicted means for the held out dataset.
        y_std: 1D array of the predicted standard deviations for the held out dataset.
        y_true: 1D array of the true labels in the held out dataset.
        scaled: Whether to scale the score by size of held out set.
        start_q: The lower bound of the quantiles to use for computation.
        end_q: The upper bound of the quantiles to use for computation.
        resolution: The number of quantiles to use for computation.

    Returns:
        The check score.
    """
    # Check that input arrays are flat
    assert_is_flat_same_shape(y_pred, y_std, y_true)

    if isinstance(y_pred, torch.Tensor):
        device = y_pred.device
        dtype = y_pred.dtype
        test_qs = torch.linspace(start_q, end_q, resolution, dtype=dtype, device=device)
    else:
        test_qs = np.linspace(start_q, end_q, resolution)

    if isinstance(y_pred, torch.Tensor):
        # Tensor operation on the batch dimension of test_qs:
        dist = Normal(loc=y_pred, scale=y_std)
        q_level = dist.icdf(test_qs[...,None])
        diff = q_level - y_true
        mask = (diff >= 0).float() - test_qs[...,None]
        score_per_q = mean_fn(mask * diff, 1)
        check_list = score_per_q
    else:
        check_list = []
        for q in test_qs:
            q_level = stats.norm.ppf(q, loc=y_pred, scale=y_std)  # pred quantile
            diff = q_level - y_true
            mask = (diff >= 0).astype(float) - q
            score_per_q = np.mean(mask * diff)
            check_list.append(score_per_q)
    check_score = sum_fn(check_list)

    if scaled:
        check_score = check_score / len(check_list)

    return check_score


def interval_score(
    y_pred: Union[np.ndarray, torch.Tensor],
    y_std: Union[np.ndarray, torch.Tensor],
    y_true: Union[np.ndarray, torch.Tensor],
    scaled: bool = True,
    start_p: float = 0.01,
    end_p: float = 0.99,
    resolution: int = 99,
) -> float:
    """The negatively oriented interval score.

    Compute the negatively oriented interval score for held out data (y_true)
    given predictive uncertainty with mean (y_pred) and standard-deviation
    (y_std). Each test point and each percentile is given equal weight in the
    overall score over the test set and list of quantiles.

    Negatively oriented means a smaller value is more desirable.

    This metric is computed by scanning over a sequence of prediction intervals. Where
    p is the amount of probability captured from a centered prediction interval,
    intervals are formed starting at p=(start_p) and ending at p=(end_p).

    Args:
        y_pred: 1D array of the predicted means for the held out dataset.
        y_std: 1D array of the predicted standard deviations for the held out dataset.
        y_true: 1D array of the true labels in the held out dataset.
        scaled: Whether to scale the score by size of held out set.
        start_p: The lower bound of probability to capture in a prediction interval.
        end_p: The upper bound of probability to capture in a prediction interval.
        resolution: The number of prediction intervals to use to compute the metric.

    Returns:
        The interval score.
    """
    # Check that input arrays are flat
    assert_is_flat_same_shape(y_pred, y_std, y_true)

    if isinstance(y_pred, torch.Tensor):
        device = y_pred.device
        dtype = y_pred.dtype
        test_ps = torch.linspace(start_p, end_p, resolution, dtype=dtype, device=device)
    else:
        test_ps = np.linspace(start_p, end_p, resolution)

    if isinstance(y_pred, torch.Tensor):
        low_ps, high_ps = 0.5 - (test_ps / 2.0), 0.5 + (test_ps / 2.0)  # p% PI
        dist = Normal(loc=y_pred, scale=y_std)
        pred_ls = dist.icdf(low_ps[...,None])
        pred_us = dist.icdf(high_ps[...,None])
        below_ls = ((pred_ls - y_true) > 0).float()
        above_us = ((y_true - pred_us) > 0).float()
        score_per_ps = (
            (pred_us - pred_ls)
            + (2.0 / (1 - test_ps[...,None])) * (pred_ls - y_true) * below_ls
            + (2.0 / (1 - test_ps[...,None])) * (y_true - pred_us) * above_us
        )
        mean_score_per_ps = mean_fn(score_per_ps, 1)
        int_list = mean_score_per_ps
    else:
        int_list = []
        for p in test_ps:
            low_p, high_p = 0.5 - (p / 2.0), 0.5 + (p / 2.0)  # p% PI
            pred_l = stats.norm.ppf(low_p, loc=y_pred, scale=y_std)
            pred_u = stats.norm.ppf(high_p, loc=y_pred, scale=y_std)

            below_l = ((pred_l - y_true) > 0).astype(float)
            above_u = ((y_true - pred_u) > 0).astype(float)

            score_per_p = (
                (pred_u - pred_l)
                + (2.0 / (1 - p)) * (pred_l - y_true) * below_l
                + (2.0 / (1 - p)) * (y_true - pred_u) * above_u
            )
            mean_score_per_p = np.mean(score_per_p)
            int_list.append(mean_score_per_p)
    int_score = sum_fn(int_list)

    if scaled:
        int_score = int_score / len(int_list)

    return int_score