from __future__ import annotations

import base64
import typing as t
import warnings
from functools import wraps

from ..http import dump_header
from ..http import parse_dict_header
from ..http import parse_set_header
from ..http import quote_header_value
from .structures import CallbackDict
from .structures import HeaderSet

if t.TYPE_CHECKING:
    import typing_extensions as te


class Authorization:
    """Represents the parts of an ``Authorization`` request header.

    :attr:`.Request.authorization` returns an instance if the header is set.

    An instance can be used with the test :class:`.Client` request methods' ``auth``
    parameter to send the header in test requests.

    Depending on the auth scheme, either :attr:`parameters` or :attr:`token` will be
    set. The ``Basic`` scheme's token is decoded into the ``username`` and ``password``
    parameters.

    For convenience, ``auth["key"]`` and ``auth.key`` both access the key in the
    :attr:`parameters` dict, along with ``auth.get("key")`` and ``"key" in auth``.

    .. versionchanged:: 2.3
        The ``token`` parameter and attribute was added to support auth schemes that use
        a token instead of parameters, such as ``Bearer``.

    .. versionchanged:: 2.3
        The object is no longer a ``dict``.

    .. versionchanged:: 0.5
        The object is an immutable dict.
    """

    def __init__(
        self,
        auth_type: str,
        data: dict[str, str] | None = None,
        token: str | None = None,
    ) -> None:
        self.type = auth_type
        """The authorization scheme, like ``Basic``, ``Digest``, or ``Bearer``."""

        if data is None:
            data = {}

        self.parameters = data
        """A dict of parameters parsed from the header. Either this or :attr:`token`
        will have a value for a give scheme.
        """

        self.token = token
        """A token parsed from the header. Either this or :attr:`parameters` will have a
        value for a given scheme.

        .. versionadded:: 2.3
        """

    def __getattr__(self, name: str) -> str | None:
        return self.parameters.get(name)

    def __getitem__(self, name: str) -> str | None:
        return self.parameters.get(name)

    def get(self, key: str, default: str | None = None) -> str | None:
        return self.parameters.get(key, default)

    def __contains__(self, key: str) -> bool:
        return key in self.parameters

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Authorization):
            return NotImplemented

        return (
            other.type == self.type
            and other.token == self.token
            and other.parameters == self.parameters
        )

    @classmethod
    def from_header(cls, value: str | None) -> te.Self | None:
        """Parse an ``Authorization`` header value and return an instance, or ``None``
        if the value is empty.

        :param value: The header value to parse.

        .. versionadded:: 2.3
        """
        if not value:
            return None

        scheme, _, rest = value.partition(" ")
        scheme = scheme.lower()
        rest = rest.strip()

        if scheme == "basic":
            try:
                username, _, password = base64.b64decode(rest).decode().partition(":")
            except UnicodeError:
                return None

            return cls(scheme, {"username": username, "password": password})

        if "=" in rest.rstrip("="):
            # = that is not trailing, this is parameters.
            return cls(scheme, parse_dict_header(rest), None)

        # No = or only trailing =, this is a token.
        return cls(scheme, None, rest)

    def to_header(self) -> str:
        """Produce an ``Authorization`` header value representing this data.

        .. versionadded:: 2.0
        """
        if self.type == "basic":
            value = base64.b64encode(
                f"{self.username}:{self.password}".encode()
            ).decode("utf8")
            return f"Basic {value}"

        if self.token is not None:
            return f"{self.type.title()} {self.token}"

        return f"{self.type.title()} {dump_header(self.parameters)}"

    def __str__(self) -> str:
        return self.to_header()

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.to_header()}>"


def auth_property(name: str, doc: str | None = None) -> property:
    """A static helper function for Authentication subclasses to add
    extra authentication system properties onto a class::

        class FooAuthenticate(WWWAuthenticate):
            special_realm = auth_property('special_realm')

    .. deprecated:: 2.3
        Will be removed in Werkzeug 2.4.
    """
    warnings.warn(
        "'auth_property' is deprecated and will be removed in Werkzeug 2.4.",
        DeprecationWarning,
        stacklevel=2,
    )

    def _set_value(self, value):  # type: ignore[no-untyped-def]
        if value is None:
            self.pop(name, None)
        else:
            self[name] = str(value)

    return property(lambda x: x.get(name), _set_value, doc=doc)


class WWWAuthenticate:
    """Represents the parts of a ``WWW-Authenticate`` response header.

    Set :attr:`.Response.www_authenticate` to an instance of list of instances to set
    values for this header in the response. Modifying this instance will modify the
    header value.

    Depending on the auth scheme, either :attr:`parameters` or :attr:`token` should be
    set. The ``Basic`` scheme will encode ``username`` and ``password`` parameters to a
    token.

    For convenience, ``auth["key"]`` and ``auth.key`` both act on the :attr:`parameters`
    dict, and can be used to get, set, or delete parameters. ``auth.get("key")`` and
    ``"key" in auth`` are also provided.

    .. versionchanged:: 2.3
        The ``token`` parameter and attribute was added to support auth schemes that use
        a token instead of parameters, such as ``Bearer``.

    .. versionchanged:: 2.3
        The object is no longer a ``dict``.

    .. versionchanged:: 2.3
        The ``on_update`` parameter was removed.
    """

    def __init__(
        self,
        auth_type: str | None = None,
        values: dict[str, str] | None = None,
        token: str | None = None,
    ):
        if auth_type is None:
            warnings.warn(
                "An auth type must be given as the first parameter. Assuming 'basic' is"
                " deprecated and will be removed in Werkzeug 2.4.",
                DeprecationWarning,
                stacklevel=2,
            )
            auth_type = "basic"

        self._type = auth_type.lower()
        self._parameters: dict[str, str] = CallbackDict(  # type: ignore[misc]
            values, lambda _: self._trigger_on_update()
        )
        self._token = token
        self._on_update: t.Callable[[WWWAuthenticate], None] | None = None

    def _trigger_on_update(self) -> None:
        if self._on_update is not None:
            self._on_update(self)

    @property
    def type(self) -> str:
        """The authorization scheme, like ``Basic``, ``Digest``, or ``Bearer``."""
        return self._type

    @type.setter
    def type(self, value: str) -> None:
        self._type = value
        self._trigger_on_update()

    @property
    def parameters(self) -> dict[str, str]:
        """A dict of parameters for the header. Only one of this or :attr:`token` should
        have a value for a give scheme.
        """
        return self._parameters

    @parameters.setter
    def parameters(self, value: dict[str, str]) -> None:
        self._parameters = CallbackDict(  # type: ignore[misc]
            value, lambda _: self._trigger_on_update()
        )
        self._trigger_on_update()

    @property
    def token(self) -> str | None:
        """A dict of parameters for the header. Only one of this or :attr:`token` should
        have a value for a give scheme.
        """
        return self._token

    @token.setter
    def token(self, value: str | None) -> None:
        """A token for the header. Only one of this or :attr:`parameters` should have a
        value for a given scheme.

        .. versionadded:: 2.3
        """
        self._token = value
        self._trigger_on_update()

    def set_basic(self, realm: str = "authentication required") -> None:
        """Clear any existing data and set a ``Basic`` challenge.

        .. deprecated:: 2.3
            Will be removed in Werkzeug 2.4. Create and assign an instance instead.
        """
        warnings.warn(
            "The 'set_basic' method is deprecated and will be removed in Werkzeug 2.4."
            " Create and assign an instance instead."
        )
        self._type = "basic"
        dict.clear(self.parameters)  # type: ignore[arg-type]
        dict.update(
            self.parameters,  # type: ignore[arg-type]
            {"realm": realm},  # type: ignore[dict-item]
        )
        self._token = None
        self._trigger_on_update()

    def set_digest(
        self,
        realm: str,
        nonce: str,
        qop: t.Sequence[str] = ("auth",),
        opaque: str | None = None,
        algorithm: str | None = None,
        stale: bool = False,
    ) -> None:
        """Clear any existing data and set a ``Digest`` challenge.

        .. deprecated:: 2.3
            Will be removed in Werkzeug 2.4. Create and assign an instance instead.
        """
        warnings.warn(
            "The 'set_digest' method is deprecated and will be removed in Werkzeug 2.4."
            " Create and assign an instance instead."
        )
        self._type = "digest"
        dict.clear(self.parameters)  # type: ignore[arg-type]
        parameters = {
            "realm": realm,
            "nonce": nonce,
            "qop": ", ".join(qop),
            "stale": "TRUE" if stale else "FALSE",
        }

        if opaque is not None:
            parameters["opaque"] = opaque

        if algorithm is not None:
            parameters["algorithm"] = algorithm

        dict.update(self.parameters, parameters)  # type: ignore[arg-type]
        self._token = None
        self._trigger_on_update()

    def __getitem__(self, key: str) -> str | None:
        return self.parameters.get(key)

    def __setitem__(self, key: str, value: str | None) -> None:
        if value is None:
            if key in self.parameters:
                del self.parameters[key]
        else:
            self.parameters[key] = value

        self._trigger_on_update()

    def __delitem__(self, key: str) -> None:
        if key in self.parameters:
            del self.parameters[key]
            self._trigger_on_update()

    def __getattr__(self, name: str) -> str | None:
        return self[name]

    def __setattr__(self, name: str, value: str | None) -> None:
        if name in {"_type", "_parameters", "_token", "_on_update"}:
            super().__setattr__(name, value)
        else:
            self[name] = value

    def __delattr__(self, name: str) -> None:
        del self[name]

    def __contains__(self, key: str) -> bool:
        return key in self.parameters

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, WWWAuthenticate):
            return NotImplemented

        return (
            other.type == self.type
            and other.token == self.token
            and other.parameters == self.parameters
        )

    def get(self, key: str, default: str | None = None) -> str | None:
        return self.parameters.get(key, default)

    @classmethod
    def from_header(cls, value: str | None) -> te.Self | None:
        """Parse a ``WWW-Authenticate`` header value and return an instance, or ``None``
        if the value is empty.

        :param value: The header value to parse.

        .. versionadded:: 2.3
        """
        if not value:
            return None

        scheme, _, rest = value.partition(" ")
        scheme = scheme.lower()
        rest = rest.strip()

        if "=" in rest.rstrip("="):
            # = that is not trailing, this is parameters.
            return cls(scheme, parse_dict_header(rest), None)

        # No = or only trailing =, this is a token.
        return cls(scheme, None, rest)

    def to_header(self) -> str:
        """Produce a ``WWW-Authenticate`` header value representing this data."""
        if self.token is not None:
            return f"{self.type.title()} {self.token}"

        if self.type == "digest":
            items = []

            for key, value in self.parameters.items():
                if key in {"realm", "domain", "nonce", "opaque", "realm", "qop"}:
                    value = quote_header_value(value, allow_token=False)
                else:
                    value = quote_header_value(value)

                items.append(f"{key}={value}")

            return f"Digest {', '.join(items)}"

        return f"{self.type.title()} {dump_header(self.parameters)}"

    def __str__(self) -> str:
        return self.to_header()

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.to_header()}>"

    @property
    def qop(self) -> set[str]:
        """The ``qop`` parameter as a set.

        .. deprecated:: 2.3
            Will be removed in Werkzeug 2.4. It will become the same as other
            parameters, returning a string.
        """
        warnings.warn(
            "The 'qop' property is deprecated and will be removed in Werkzeug 2.4."
            " It will become the same as other parameters, returning a string.",
            DeprecationWarning,
            stacklevel=2,
        )

        def on_update(value: HeaderSet) -> None:
            if not value:
                if "qop" in self:
                    del self["qop"]

                return

            self.parameters["qop"] = value.to_header()

        return parse_set_header(self.parameters.get("qop"), on_update)

    @property
    def stale(self) -> bool | None:
        """The ``stale`` parameter as a boolean.

        .. deprecated:: 2.3
            Will be removed in Werkzeug 2.4. It will become the same as other
            parameters, returning a string.
        """
        warnings.warn(
            "The 'stale' property is deprecated and will be removed in Werkzeug 2.4."
            " It will become the same as other parameters, returning a string.",
            DeprecationWarning,
            stacklevel=2,
        )

        if "stale" in self.parameters:
            return self.parameters["stale"].lower() == "true"

        return None

    @stale.setter
    def stale(self, value: bool | str | None) -> None:
        if value is None:
            if "stale" in self.parameters:
                del self.parameters["stale"]

            return

        if isinstance(value, bool):
            warnings.warn(
                "Setting the 'stale' property to a boolean is deprecated and will be"
                " removed in Werkzeug 2.4.",
                DeprecationWarning,
                stacklevel=2,
            )
            self.parameters["stale"] = "TRUE" if value else "FALSE"
        else:
            self.parameters["stale"] = value

    auth_property = staticmethod(auth_property)


def _deprecated_dict_method(f):  # type: ignore[no-untyped-def]
    @wraps(f)
    def wrapper(*args, **kwargs):  # type: ignore[no-untyped-def]
        warnings.warn(
            "Treating 'Authorization' and 'WWWAuthenticate' as a dict is deprecated and"
            " will be removed in Werkzeug 2.4. Use the 'parameters' attribute instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return f(*args, **kwargs)

    return wrapper


for name in (
    "__iter__",
    "clear",
    "copy",
    "items",
    "keys",
    "pop",
    "popitem",
    "setdefault",
    "update",
    "values",
):
    f = _deprecated_dict_method(getattr(dict, name))
    setattr(Authorization, name, f)
    setattr(WWWAuthenticate, name, f)
