"""Real-artifact API and browser-page checks for the vertical slice."""

from __future__ import annotations

import asyncio
import json

import pytest

from nrfi.api import app, v3_vertical_slice_prediction, vertical_slice_page
from nrfi.real_vertical_slice import historical_prediction_payload


def test_committed_real_prediction_payload_is_complete():
    payload = historical_prediction_payload()
    assert payload["game"]["game_pk"] == 745907
    assert payload["game"]["official_date"] == "2024-05-16"
    assert payload["prediction"]["out_of_sample"] is True
    assert payload["prediction"]["pitcher_features_used"] is False
    assert payload["prediction"]["p_nrfi"] + payload["prediction"][
        "p_yrfi"
    ] == pytest.approx(1.0)
    assert payload["evidence"]["locked_holdout_used"] is False
    assert payload["evidence"]["market_data_used"] is False


def test_api_route_returns_the_committed_real_prediction_without_snowflake():
    payload = asyncio.run(v3_vertical_slice_prediction())
    assert payload == historical_prediction_payload()
    route_paths = {getattr(route, "path", None) for route in app.routes}
    assert "/v3/vertical-slice/prediction" in route_paths
    assert "/vertical-slice" in route_paths


def test_browser_page_fetches_and_displays_the_real_api_contract():
    response = asyncio.run(vertical_slice_page())
    html = bytes(response.body).decode("utf-8")
    assert response.status_code == 200
    assert "fetch('/v3/vertical-slice/prediction')" in html
    assert "NRFI probability" in html
    assert "YRFI probability" in html
    assert "market data, wagering" in html
    assert "http://" not in html and "https://" not in html


def test_api_payload_is_json_serializable():
    json.dumps(asyncio.run(v3_vertical_slice_prediction()), allow_nan=False)
