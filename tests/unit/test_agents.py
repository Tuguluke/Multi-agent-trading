"""Unit tests for base agent and signal parsing."""

from unittest.mock import MagicMock
import pytest

from agents.base_agent import BaseAgent
from data.schemas import AgentSignal, SignalDirection, SignalStrength


class ConcreteAgent(BaseAgent):
    """Minimal concrete implementation for testing."""
    def run(self, context: dict) -> AgentSignal:
        return AgentSignal(
            agent_name=self.name,
            asset="XLE",
            direction=SignalDirection.BULLISH,
            strength=SignalStrength.MODERATE,
            confidence=0.75,
            reasoning="test",
        )


def make_agent(llm_text="DIRECTION: BULLISH\nSTRENGTH: STRONG\nCONFIDENCE: 80%"):
    router = MagicMock()
    router.complete.return_value = llm_text
    return ConcreteAgent("TestAgent", router)


def test_parse_direction_bullish():
    agent = make_agent()
    assert agent._parse_direction("DIRECTION: BULLISH") == SignalDirection.BULLISH


def test_parse_direction_bearish():
    agent = make_agent()
    assert agent._parse_direction("The market is BEARISH today") == SignalDirection.BEARISH


def test_parse_direction_neutral():
    agent = make_agent()
    assert agent._parse_direction("No clear trend here") == SignalDirection.NEUTRAL


def test_parse_strength_strong():
    agent = make_agent()
    assert agent._parse_strength("STRENGTH: STRONG") == SignalStrength.STRONG


def test_parse_confidence_percentage():
    agent = make_agent()
    assert agent._parse_confidence("CONFIDENCE: 75%") == pytest.approx(0.75)


def test_parse_confidence_decimal():
    agent = make_agent()
    assert agent._parse_confidence("confidence: 0.82") == pytest.approx(0.82)


def test_parse_confidence_fallback():
    agent = make_agent()
    assert agent._parse_confidence("no confidence mentioned here") == 0.5


def test_log_signal_saves_to_db():
    db = MagicMock()
    router = MagicMock()
    agent = ConcreteAgent("TestAgent", router, db_client=db)
    signal = agent.run({})
    agent.log_signal(signal)
    db.save_agent_signal.assert_called_once()


def test_timed_run_returns_signal():
    agent = make_agent()
    signal = agent.timed_run({})
    assert isinstance(signal, AgentSignal)
    assert signal.direction == SignalDirection.BULLISH
