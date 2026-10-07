"""Assembly: builds the service from its layers. Decides nothing else.

The one place that chooses implementations (which repositories, which
provider factory), so tests and deployments swap them here. One module
per part:

- ``storage``: the repositories, the audit and the activity log.
- ``secrets``: the key provider and the vault of the credentials.
- ``providers``: the guard of every connection, the adapters' factory,
  the OAuth apps, the kinds of account offered, autodiscovery.
- ``domain``: the services of the domain, wired in ``build_services``.
- ``services``: ``Services``, as the web layer and the command line
  reach them.
- ``lifecycle``: the services for one command, and while the app serves.
- ``web``: the app and the OpenAPI document.
"""

from __future__ import annotations

from .domain import build_services
from .lifecycle import opened
from .providers import build_oauth, offered_providers
from .secrets import key_provider
from .services import Services
from .web import create_app, openapi_json

__all__ = [
    "Services",
    "build_oauth",
    "build_services",
    "create_app",
    "key_provider",
    "offered_providers",
    "openapi_json",
    "opened",
]
