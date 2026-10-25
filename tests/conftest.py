"""
tests/conftest.py
Shared pytest fixtures for all tests.
"""
import pytest

# Use an in-memory/temp database for tests
@pytest.fixture(autouse=True)
def temp_db(monkeypatch, tmp_path):
    """Use a temporary database file for each test."""
    db_path = str(tmp_path / "test_quiz_assistant.db")
    monkeypatch.setenv("DATABASE_PATH", db_path)
    # Clear cached settings
    from app.config import get_settings
    get_settings.cache_clear()
    from app import database
    database.init_db()
    yield db_path
    get_settings.cache_clear()


@pytest.fixture
def sample_question():
    """A sample quiz question for testing."""
    from app.models import QuizOption, QuizQuestion, QuestionType
    return QuizQuestion(
        question_id="q_1",
        page=0,
        question_text="Which of the following is an example of a Boolean query?",
        question_type=QuestionType.SINGLE,
        options=[
            QuizOption(option_id="a", label="a", text='"car AND vehicle"'),
            QuizOption(option_id="b", label="b", text='"say*"'),
            QuizOption(option_id="c", label="c", text='"drive OR drive"'),
            QuizOption(option_id="d", label="d", text='"car driving fast"'),
        ],
        current_selection=[],
    )


@pytest.fixture
def mock_gemini_answer():
    """A mock Gemini answer."""
    from app.models import GeminiAnswer
    return GeminiAnswer(
        selected_option_ids=["a"],
        explanation="'car AND vehicle' uses a Boolean AND operator.",
        confidence=0.92,
        is_ambiguous=False,
        requires_image=False,
    )
