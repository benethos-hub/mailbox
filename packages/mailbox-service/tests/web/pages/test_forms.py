"""What a form holds, turned into what the domain takes."""

from __future__ import annotations

import pytest

from benethos_mailbox_service.data.models import FolderCreate
from benethos_mailbox_service.web.pages.forms import FormError, model_of


class _Named(FormError):
    pass


def test_a_model_from_a_form() -> None:
    assert model_of(FolderCreate, {"name": "Projects"}).name == "Projects"


def test_what_the_model_refuses_is_a_form_error() -> None:
    with pytest.raises(FormError, match="^name: "):
        model_of(FolderCreate, {"name": ""})
    with pytest.raises(_Named, match="^a name, please$"):
        model_of(FolderCreate, {}, error=_Named, message="a name, please")
