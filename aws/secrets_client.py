"""AWS Secrets Manager client."""

from __future__ import annotations

import json
import logging

from config import get_config

logger = logging.getLogger(__name__)


class SecretsClient:
    def __init__(self):
        cfg = get_config()
        self._client = cfg._boto_client("secretsmanager")

    def get_secret(self, secret_name: str) -> str:
        response = self._client.get_secret_value(SecretId=secret_name)
        return response["SecretString"]

    def get_secret_json(self, secret_name: str) -> dict:
        return json.loads(self.get_secret(secret_name))

    def put_secret(self, secret_name: str, value: str) -> None:
        try:
            self._client.put_secret_value(SecretId=secret_name, SecretString=value)
        except self._client.exceptions.ResourceNotFoundException:
            self._client.create_secret(Name=secret_name, SecretString=value)
        logger.info("Secret stored: %s", secret_name)
