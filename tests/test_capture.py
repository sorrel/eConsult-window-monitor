from flow_capture.capture import ECONSULT_HOST, classify_control, is_write_to_econsult


def test_terminal_controls_are_never_treated_as_advance():
    # Anything that could submit MUST classify as terminal (so it is never clicked).
    for label in [
        "Submit", "Submit eConsult", "Send", "Send to your practice",
        "Send to the surgery", "Finish", "Complete", "Confirm and send",
        "Review your answers", "SUBMIT NOW",
    ]:
        assert classify_control(label) == "terminal", label


def test_advance_controls_classified_as_advance():
    for label in ["Continue", "Next", "Proceed", "Get started", "Start now", "Begin"]:
        assert classify_control(label) == "advance", label


def test_ambiguous_or_empty_controls_are_other():
    for label in ["Back", "Cancel", "Help", "", "   ", "Add a photo"]:
        assert classify_control(label) == "other", label


def test_send_beats_continue_if_both_words_present():
    # A control that says "Send" must be terminal even if other words appear.
    assert classify_control("Continue to send") == "terminal"


def test_writes_to_econsult_are_flagged_for_blocking():
    host = f"https://{ECONSULT_HOST}"
    assert is_write_to_econsult("POST", f"{host}/consultation") is True
    assert is_write_to_econsult("PUT", f"{host}/x") is True
    assert is_write_to_econsult("PATCH", f"{host}/x") is True
    assert is_write_to_econsult("GET", f"{host}/x") is False          # reads allowed
    assert is_write_to_econsult("POST", "https://example.com/x") is False  # other host untouched
