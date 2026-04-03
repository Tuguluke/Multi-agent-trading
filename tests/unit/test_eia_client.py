"""Unit tests for EIAClient."""

from unittest.mock import MagicMock, patch
import pytest


@patch("data.eia_client.get_config")
@patch("data.eia_client.requests.Session")
def test_get_wti_price(mock_session_cls, mock_cfg):
    mock_cfg.return_value.EIA_API_KEY = "test_key"
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "response": {
            "data": [
                {"period": "2026-03-28", "value": "69.50"},
                {"period": "2026-03-27", "value": "68.80"},
            ]
        }
    }
    mock_session_cls.return_value.get.return_value = mock_response

    from data.eia_client import EIAClient
    client = EIAClient()
    prices = client.get_wti_price(days=5)

    assert len(prices) == 2
    assert prices[0].commodity == "WTI"
    assert prices[0].price == 69.50
    assert prices[0].unit == "USD/bbl"


@patch("data.eia_client.get_config")
@patch("data.eia_client.requests.Session")
def test_get_inventory(mock_session_cls, mock_cfg):
    mock_cfg.return_value.EIA_API_KEY = "test_key"
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "response": {
            "data": [
                {"period": "2026-03-28", "value": "440.5"},
                {"period": "2026-03-21", "value": "438.2"},
            ]
        }
    }
    mock_session_cls.return_value.get.return_value = mock_response

    from data.eia_client import EIAClient
    client = EIAClient()
    result = client.get_weekly_inventory()

    assert result["inventory_mmbbl"] == 440.5
    assert result["change_mmbbl"] == pytest.approx(2.3, abs=0.01)
