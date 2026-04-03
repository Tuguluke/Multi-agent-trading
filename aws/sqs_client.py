"""AWS SQS client — inter-agent message queues."""

from __future__ import annotations

import json
import logging

from config import get_config

logger = logging.getLogger(__name__)


class SQSClient:
    def __init__(self):
        cfg = get_config()
        self._sqs = cfg._boto_client("sqs")
        self._cfg = cfg

    def send(self, queue_url: str, body: dict, delay_seconds: int = 0) -> str:
        response = self._sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(body),
            DelaySeconds=delay_seconds,
        )
        msg_id = response["MessageId"]
        logger.info("SQS sent to %s → %s", queue_url.split("/")[-1], msg_id)
        return msg_id

    def receive(self, queue_url: str, max_messages: int = 1, wait_seconds: int = 5) -> list[dict]:
        response = self._sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=wait_seconds,
        )
        messages = []
        for msg in response.get("Messages", []):
            messages.append({
                "receipt_handle": msg["ReceiptHandle"],
                "body": json.loads(msg["Body"]),
            })
        return messages

    def delete(self, queue_url: str, receipt_handle: str) -> None:
        self._sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)

    # ── Named queue shortcuts ─────────────────────────────────────────────────

    def send_ingestion_event(self, payload: dict) -> str:
        return self.send(self._cfg.SQS_INGESTION_URL, payload)

    def send_agent_trigger(self, payload: dict) -> str:
        return self.send(self._cfg.SQS_AGENT_TRIGGER_URL, payload)
