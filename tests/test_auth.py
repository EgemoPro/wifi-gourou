"""
test_auth.py — Tests d'authentification pour wifizone-agent

Vérifie que CENTRAL_API_KEY est obligatoire et que les endpoints
FastAPI retournent 401 quand la clé est absente ou invalide.
"""
import sys
import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient


class TestConfigAuth:
    """Tests que CENTRAL_API_KEY est obligatoire dans config.py."""

    def test_config_requires_central_api_key(self, monkeypatch):
        """config.py raise ValueError quand CENTRAL_API_KEY est absente."""
        # Pointer ENV_PATH vers un fichier inexistant pour éviter que
        # load_dotenv ne recharge le vrai .env pendant le re-import
        monkeypatch.setenv("ENV_PATH", "/tmp/nonexistent-opencode-test/.env")

        # Toutes les vars obligatoires SAUF CENTRAL_API_KEY
        for key, val in {
            "SITE_ID": "test_site",
            "SITE_NAME": "Test Site",
            "MIKROTIK_HOST": "192.168.1.1",
            "MIKROTIK_PASSWORD": "test_password",
            "CENTRAL_HOST": "central.test.local",
        }.items():
            monkeypatch.setenv(key, val)
        monkeypatch.delenv("CENTRAL_API_KEY", raising=False)

        # Vider le cache du module config pour le re-importer
        sys.modules.pop("config", None)

        with pytest.raises(ValueError, match="CENTRAL_API_KEY is required"):
            __import__("config")


class TestCheckApiKey:
    """Tests unitaires de _check_api_key (helper HMAC)."""

    @patch("main.CONFIG", {"central_api_key": "secret-key-123"})
    def test_valid_key_passes(self):
        """Clé valide → aucune exception."""
        from main import _check_api_key
        req = MagicMock(spec=Request)
        req.headers.get.return_value = "secret-key-123"
        assert _check_api_key(req) is None

    @patch("main.CONFIG", {"central_api_key": "secret-key-123"})
    def test_wrong_key_raises_401(self):
        """Mauvaise clé → HTTPException 401."""
        from main import _check_api_key
        req = MagicMock(spec=Request)
        req.headers.get.return_value = "wrong-key"
        with pytest.raises(HTTPException) as exc:
            _check_api_key(req)
        assert exc.value.status_code == 401

    @patch("main.CONFIG", {"central_api_key": "secret-key-123"})
    def test_missing_key_raises_401(self):
        """Header X-API-Key absent → HTTPException 401."""
        from main import _check_api_key
        req = MagicMock(spec=Request)
        req.headers.get.return_value = ""
        with pytest.raises(HTTPException) as exc:
            _check_api_key(req)
        assert exc.value.status_code == 401


class TestEndpointAuth:
    """Tests d'intégration : les endpoints retournent 401 sans clé valide.

    On teste alert_app (pas de lifespan) pour éviter les effets de bord
    du démarrage (SSH, storage, etc.).
    """

    # ── Pas de clé ──────────────────────────────────────────────────────

    def test_alert_endpoint_no_key(self):
        """POST /alert sans X-API-Key → 401."""
        from main import alert_app
        client = TestClient(alert_app)
        response = client.post(
            "/alert",
            json={"site": "test_site", "type": "test", "value": "test alert"},
        )
        assert response.status_code == 401

    # ── Mauvaise clé ────────────────────────────────────────────────────

    def test_alert_endpoint_wrong_key(self):
        """POST /alert avec X-API-Key erronée → 401."""
        from main import alert_app
        client = TestClient(alert_app)
        response = client.post(
            "/alert",
            json={"site": "test_site", "type": "test", "value": "test alert"},
            headers={"X-API-Key": "wrong-key-here"},
        )
        assert response.status_code == 401

    # ── Clé valide ──────────────────────────────────────────────────────

    @patch("main.forwarder")
    @patch("main.storage", None)
    def test_alert_endpoint_valid_key(self, mock_forwarder):
        """POST /alert avec X-API-Key valide → pas 401."""
        from main import alert_app, CONFIG
        real_key = CONFIG["central_api_key"]
        client = TestClient(alert_app)
        response = client.post(
            "/alert",
            json={"site": "test_site", "type": "test", "value": "test alert"},
            headers={"X-API-Key": real_key},
        )
        # La requête réussit (auth OK, le reste est mocké)
        assert response.status_code != 401
        assert response.json().get("status") == "received"
