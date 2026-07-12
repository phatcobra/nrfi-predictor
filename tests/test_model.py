import numpy as np
import pandas as pd

from nrfi.config import TrainConfig
from nrfi.model import ALL_FEATURES, NRFIModel, fit_model, trainable_rows


def synthetic_feature_frame(n: int = 4000, seasons=(2018, 2019, 2020, 2021, 2022), seed: int = 7) -> pd.DataFrame:
    """Synthetic training frame with one real signal feature."""
    rng = np.random.default_rng(seed)
    frame = pd.DataFrame({col: rng.normal(0.5, 0.15, n) for col in ALL_FEATURES})
    season_arr = np.sort(rng.choice(seasons, n))
    frame["season"] = season_arr.astype(float)
    day_of_year = rng.integers(90, 270, n)
    frame["game_date"] = [
        (pd.Timestamp(f"{int(s)}-01-01") + pd.Timedelta(days=int(d))).date().isoformat()
        for s, d in zip(season_arr, day_of_year, strict=True)
    ]
    frame["game_pk"] = np.arange(n)
    frame["home_probable_pitcher_id"] = 500001.0
    frame["away_probable_pitcher_id"] = 500002.0
    frame["home_team_name"] = "Testville Alphas"
    frame["away_team_name"] = "Mockington Betas"
    signal = frame["hp_fi_yrfi_allowed_shrunk"]
    p = 1.0 / (1.0 + np.exp(-(signal - 0.5) * 6.0))
    frame["yrfi"] = (rng.random(n) < p).astype(float)
    frame["label_valid"] = True
    frame["league_yrfi_rate"] = float(frame["yrfi"].mean())
    return frame


def test_trainable_rows_filters_invalid_and_missing_pitchers():
    frame = synthetic_feature_frame(n=100)
    frame.loc[0, "label_valid"] = False
    frame.loc[1, "yrfi"] = np.nan
    frame.loc[2, "home_probable_pitcher_id"] = np.nan
    rows = trainable_rows(frame)
    assert len(rows) == 97
    assert 0 not in rows.index and 1 not in rows.index and 2 not in rows.index


def test_fit_predict_save_load_roundtrip(tmp_path):
    frame = synthetic_feature_frame()
    model = fit_model(frame, TrainConfig())
    probs = model.predict_yrfi_proba(frame.head(200))
    assert probs.shape == (200,)
    assert np.all(probs >= 0.02) and np.all(probs <= 0.98)
    # Signal check: the model must order by the known signal feature.
    hi = frame[frame["hp_fi_yrfi_allowed_shrunk"] > 0.65]
    lo = frame[frame["hp_fi_yrfi_allowed_shrunk"] < 0.35]
    assert model.predict_yrfi_proba(hi).mean() > model.predict_yrfi_proba(lo).mean()

    model.save(tmp_path)
    loaded = NRFIModel.load(tmp_path)
    reloaded_probs = loaded.predict_yrfi_proba(frame.head(200))
    assert np.allclose(probs, reloaded_probs)
    assert loaded.metadata["n_trainable_rows"] == model.metadata["n_trainable_rows"]
    assert loaded.features == ALL_FEATURES


def test_fit_model_refuses_tiny_datasets():
    frame = synthetic_feature_frame(n=100)
    try:
        fit_model(frame, TrainConfig())
        raise AssertionError("expected ValueError for tiny dataset")
    except ValueError:
        pass


def test_model_handles_missing_feature_values():
    frame = synthetic_feature_frame()
    model = fit_model(frame, TrainConfig())
    holed = frame.head(50).copy()
    holed.loc[:, "temperature_c"] = np.nan
    holed.loc[:, "hp_recent_fi_runs_allowed"] = np.nan
    probs = model.predict_yrfi_proba(holed)
    assert np.all(np.isfinite(probs))
