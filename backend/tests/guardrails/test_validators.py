import pytest
from PIL import Image
import io

from app.guardrails.validators import WorkOrderValidator, PhotoValidator
from app.guardrails.errors import GuardrailViolation


def test_empty_work_order():
    try:
        WorkOrderValidator.validate_deterministic("")
        assert False
    except GuardrailViolation as e:
        assert e.detail.code.value == "EMPTY_WORK_ORDER"


def test_out_of_scope():
    try:
        WorkOrderValidator.validate_deterministic("What is the weather today?")
        assert False
    except GuardrailViolation as e:
        assert e.detail.code.value == "WORK_ORDER_OUT_OF_SCOPE"


def test_ambiguous():
    try:
        WorkOrderValidator.validate_deterministic("Fix everything")
        assert False
    except GuardrailViolation as e:
        assert e.detail.code.value == "WORK_ORDER_AMBIGUOUS"


def test_valid_work_order():
    WorkOrderValidator.validate_deterministic("- Install 2 electrical outlet covers\n- Seal bathroom edges with caulk")


def test_corrupt_image():
    try:
        PhotoValidator.validate_format_and_decode("bad.jpg", b"not-an-image", "image/jpeg", "file_1")
        assert False
    except GuardrailViolation as e:
        assert e.detail.code.value == "CORRUPT_IMAGE"


def test_unsupported_format():
    try:
        PhotoValidator.validate_format_and_decode("test.gif", b"GIF89a", "image/gif", "file_1")
        assert False
    except GuardrailViolation as e:
        assert e.detail.code.value == "UNSUPPORTED_MEDIA_TYPE"


def test_small_image():
    img = Image.new('RGB', (10, 10), color='red')
    buf = io.BytesIO()
    img.save(buf, format='JPEG')
    try:
        PhotoValidator.validate_format_and_decode("small.jpg", buf.getvalue(), "image/jpeg", "file_1")
        assert False
    except GuardrailViolation as e:
        assert e.detail.code.value == "IMAGE_TOO_SMALL"
