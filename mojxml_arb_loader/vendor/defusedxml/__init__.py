# defusedxml
#
# Copyright (c) 2013 by Christian Heimes <christian@python.org>
# Licensed to PSF under a Contributor Agreement.
# See https://www.python.org/psf/license for licensing details.
#
# Vendored copy (0.7.1) bundled with MOJ Arbitrary Coord Loader plugin.
# Source: https://github.com/tiran/defusedxml
#
"""defusedxml - XML bomb and XXE attack prevention"""

__version__ = "0.7.1"
__author__ = "Christian Heimes <christian@python.org>"


class DTDForbidden(ValueError):
    """Raised when a DTD is found in the document."""
    def __init__(self, name, sysid, pubid):
        super().__init__(name, sysid, pubid)
        self.name = name
        self.sysid = sysid
        self.pubid = pubid

    def __str__(self):
        return f"DTDForbidden(name={self.name!r}, system_id={self.sysid!r}, public_id={self.pubid!r})"


class EntitiesForbidden(ValueError):
    """Raised when an entity definition is found in the document."""
    def __init__(self, name, value, base, sysid, pubid, notation_name):
        super().__init__(name, value, base, sysid, pubid, notation_name)
        self.name = name
        self.value = value
        self.base = base
        self.sysid = sysid
        self.pubid = pubid
        self.notation_name = notation_name

    def __str__(self):
        return (
            f"EntitiesForbidden(name={self.name!r}, system_id={self.sysid!r}, "
            f"public_id={self.pubid!r})"
        )


class ExternalReferenceForbidden(ValueError):
    """Raised when an external reference is found in the document."""
    def __init__(self, context, base, sysid, pubid):
        super().__init__(context, base, sysid, pubid)
        self.context = context
        self.base = base
        self.sysid = sysid
        self.pubid = pubid

    def __str__(self):
        return (
            f"ExternalReferenceForbidden(system_id={self.sysid!r}, "
            f"public_id={self.pubid!r})"
        )


class NotSupportedError(ValueError):
    """Raised when an unsupported feature is used."""


def _check_doctype(dtd):
    """Check doctype node."""
    raise DTDForbidden(dtd.name, dtd.system_id, dtd.public_id)


def _check_entity(name, value, base, sysid, pubid, notation_name):
    """Check entity definition."""
    raise EntitiesForbidden(name, value, base, sysid, pubid, notation_name)


def _check_unparsed_entity(name, base, sysid, pubid, notation_name):
    """Check unparsed entity definition."""
    raise EntitiesForbidden(name, None, base, sysid, pubid, notation_name)


def _check_external_subset(context, base, sysid, pubid):
    """Check external subset."""
    raise ExternalReferenceForbidden(context, base, sysid, pubid)
