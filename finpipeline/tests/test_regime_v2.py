import numpy as np
import pandas as pd

from src.regime_v2 import FEATURES, expanding_zscores, rank_similar_periods, regime_from_zscore


def test_expanding_standardization_is_unchanged_by_future_data():
    index = pd.date_range("2020-01-31", periods=30, freq="ME")
    frame = pd.DataFrame(
        {feature: np.arange(30, dtype=float) + offset for offset, feature in enumerate(FEATURES)},
        index=index,
    )
    before = expanding_zscores(frame)
    future = pd.DataFrame(
        {feature: [1_000_000.0] for feature in FEATURES},
        index=[pd.Timestamp("2030-01-31")],
    )
    after = expanding_zscores(pd.concat([frame, future])).loc[index]
    pd.testing.assert_frame_equal(before, after, check_freq=False)


def test_ranker_excludes_current_and_future_and_is_deterministic():
    index = pd.date_range("2020-01-31", periods=5, freq="ME")
    frame = pd.DataFrame(
        np.array([
            [1] * 10, [2] * 10, [-1] * 10, [3] * 10, [999] * 10
        ], dtype=float),
        index=index,
        columns=FEATURES,
    )
    ranked = rank_similar_periods(frame, index[3], limit=3)
    assert all(item["date"] < index[3] for item in ranked)
    assert [item["date"] for item in ranked[:2]] == [index[1], index[0]]


def test_regime_labels_use_signed_feature_contributions():
    contractionary = pd.Series([0, 1, 1, 1, 1, 1, 1, 1, -1, -1], index=FEATURES)
    expansionary = -contractionary
    assert regime_from_zscore(contractionary)[0] == "contractionary"
    assert regime_from_zscore(expansionary)[0] == "expansionary"
