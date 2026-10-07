"""What a form holds, turned into what the domain takes."""

from __future__ import annotations

import pytest

from benethos_mailbox_service.data.models import FolderCreate
from benethos_mailbox_service.web.pages.forms import FormError, model_of, text_of


class _NamedError(FormError):
    pass


def test_a_model_from_a_form() -> None:
    assert model_of(FolderCreate, {"name": "Projects"}).name == "Projects"


def test_what_the_model_refuses_is_a_form_error() -> None:
    with pytest.raises(FormError, match="^name: "):
        model_of(FolderCreate, {"name": ""})
    with pytest.raises(_NamedError, match="^a name, please$"):
        model_of(FolderCreate, {}, error=_NamedError, message="a name, please")


def test_a_field_as_text() -> None:
    form = {"name": "  Anna ", "empty": None}
    assert text_of(form, "name") == "Anna"
    assert text_of(form, "name", strip=False) == "  Anna "
    assert text_of(form, "empty") == "" and text_of(form, "missing") == ""
