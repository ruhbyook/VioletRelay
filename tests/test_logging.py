from reelferry.errors import error_message
from reelferry.logging_utils import redact_text


def test_redacts_credentials_and_url_query():
    text = (
        "credentials=abcdef token: xyz "
        "https://user:password@example.test/video.mp4?token=secret#fragment"
    )
    redacted = redact_text(text)
    assert "abcdef" not in redacted
    assert "xyz" not in redacted
    assert "password" not in redacted
    assert "secret" not in redacted
    assert "fragment" not in redacted
    assert "<redacted>" in redacted


def test_user_facing_errors_redact_url_credentials_and_queries():
    message = error_message(
        RuntimeError(
            "failed https://user:pass@example.test/movie.mp4?token=secret"
        ),
        "failed",
    )
    assert "user:pass" not in message
    assert "token=secret" not in message
