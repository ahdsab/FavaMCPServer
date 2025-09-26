import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
import os
import sys

# Add the parent directory to the Python path so we can import main
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the app from main.py
from main import app

client = TestClient(app)


class TestIncomeStatementAPI:
    """Test cases for the income statement API endpoint."""

    def test_income_statement_success_basic(self):
        """Test successful income statement retrieval with basic response."""
        mock_response_data = {
            "totals": {
                "income": 10000.0,
                "expenses": -7500.0,
                "net": 2500.0
            },
            "children": [
                {"name": "Salary", "balance": 10000.0},
                {"name": "Rent", "balance": -2000.0},
                {"name": "Food", "balance": -1500.0}
            ]
        }
        
        with patch('main.requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_response_data
            mock_get.return_value = mock_response
            
            response = client.get("/income_statement")
            
            assert response.status_code == 200
            data = response.json()
            
            # Check response structure
            assert "source" in data
            assert "summary" in data
            assert "raw" in data
            
            # Check summary totals
            assert data["summary"]["totals"]["income"] == 10000.0
            assert data["summary"]["totals"]["expenses"] == -7500.0
            assert data["summary"]["totals"]["net_profit"] == 2500.0
            
            # Check top income/expenses
            assert len(data["summary"]["top_income"]) > 0
            assert len(data["summary"]["top_expenses"]) > 0
            
            # Verify Fava API was called
            mock_get.assert_called_once()

    def test_income_statement_with_query_params(self):
        """Test income statement with various query parameters."""
        mock_response_data = {"totals": {"income": 5000.0, "expenses": -3000.0}}
        
        with patch('main.requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_response_data
            mock_get.return_value = mock_response
            
            response = client.get(
                "/income_statement",
                params={
                    "time": "2024",
                    "interval": "month",
                    "conversion": "USD",
                    "filter": "account:Assets",
                    "return_raw": "false"
                }
            )
            
            assert response.status_code == 200
            data = response.json()
            
            # Check that raw data is not included when return_raw=false
            assert "raw" not in data
            
            # Verify correct parameters were passed to Fava
            mock_get.assert_called_once()
            call_args = mock_get.call_args
            assert call_args[1]["params"]["time"] == "2024"
            assert call_args[1]["params"]["interval"] == "month"
            assert call_args[1]["params"]["conversion"] == "USD"
            assert call_args[1]["params"]["filter"] == "account:Assets"

    def test_income_statement_fava_api_error(self):
        """Test handling when Fava API returns an error status."""
        with patch('main.requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_get.return_value = mock_response
            
            response = client.get("/income_statement")
            
            assert response.status_code == 500
            data = response.json()
            assert "Fava returned 500" in data["detail"]

    def test_income_statement_network_error(self):
        """Test handling when network request to Fava fails."""
        with patch('main.requests.get') as mock_get:
            import requests
            mock_get.side_effect = requests.exceptions.RequestException("Connection failed")
            
            response = client.get("/income_statement")
            
            assert response.status_code == 502
            data = response.json()
            assert "Failed to reach Fava" in data["detail"]

    def test_income_statement_alternative_data_structure(self):
        """Test parsing with alternative Fava response structure."""
        mock_response_data = {
            "income": 8000.0,
            "expenses": -6000.0,
            "net_profit": 2000.0,
            "accounts": [
                {"name": "Investment Income", "amount": 8000.0},
                {"name": "Utilities", "amount": -2000.0},
                {"name": "Insurance", "amount": -4000.0}
            ]
        }
        
        with patch('main.requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_response_data
            mock_get.return_value = mock_response
            
            response = client.get("/income_statement")
            
            assert response.status_code == 200
            data = response.json()
            
            # Check that alternative structure is parsed correctly
            assert data["summary"]["totals"]["income"] == 8000.0
            assert data["summary"]["totals"]["expenses"] == -6000.0
            assert data["summary"]["totals"]["net_profit"] == 2000.0

    def test_income_statement_malformed_data(self):
        """Test handling of malformed or unexpected data from Fava."""
        mock_response_data = {
            "some_unexpected_field": "value",
            "nested": {
                "complex": {
                    "structure": "that_doesnt_match_expected_format"
                }
            }
        }
        
        with patch('main.requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_response_data
            mock_get.return_value = mock_response
            
            response = client.get("/income_statement")
            
            assert response.status_code == 200
            data = response.json()
            
            # Should still return a response with None totals
            assert data["summary"]["totals"]["income"] is None
            assert data["summary"]["totals"]["expenses"] is None
            assert data["summary"]["totals"]["net_profit"] is None

    def test_income_statement_empty_response(self):
        """Test handling of empty response from Fava."""
        mock_response_data = {}
        
        with patch('main.requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_response_data
            mock_get.return_value = mock_response
            
            response = client.get("/income_statement")
            
            assert response.status_code == 200
            data = response.json()
            
            # Should handle empty response gracefully
            assert "summary" in data
            assert "totals" in data["summary"]

    def test_income_statement_timeout_handling(self):
        """Test handling of request timeout."""
        with patch('main.requests.get') as mock_get:
            import requests
            mock_get.side_effect = requests.exceptions.Timeout("Request timed out")
            
            response = client.get("/income_statement")
            
            assert response.status_code == 502
            data = response.json()
            assert "Failed to reach Fava" in data["detail"]

    def test_income_statement_connection_error(self):
        """Test handling of connection error."""
        with patch('main.requests.get') as mock_get:
            import requests
            mock_get.side_effect = requests.exceptions.ConnectionError("Connection refused")
            
            response = client.get("/income_statement")
            
            assert response.status_code == 502
            data = response.json()
            assert "Failed to reach Fava" in data["detail"]

    def test_income_statement_request_exception(self):
        """Test handling of general request exception."""
        with patch('main.requests.get') as mock_get:
            import requests
            mock_get.side_effect = requests.exceptions.RequestException("General request error")
            
            response = client.get("/income_statement")
            
            assert response.status_code == 502
            data = response.json()
            assert "Failed to reach Fava" in data["detail"]
