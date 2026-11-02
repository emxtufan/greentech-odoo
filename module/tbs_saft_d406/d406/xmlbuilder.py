# Part of tbs_saft_d406. See LICENSE file for full copyright and licensing details.
"""Thin lxml wrapper that enforces the SAF-T structural invariants.

Why a builder and not a QWeb template: the "never emit an empty element"
rule has to hold for every one of the ~250 elements in the schema. Expressed
as ``t-if`` guards in a template it is 250 chances to forget one — and two of
our confirmed DUK rejections (``ProductGroup`` empty, ``LastName`` empty) are
exactly that mistake. Expressed here it is one ``if`` in :meth:`Node.add`.

Element *order* is not enforced by this module. It is enforced by the XSD
validation step, which is run on every export and reports the offending
element by name.
"""
from __future__ import annotations

from lxml import etree

#: Namespace written to the output file.
#:
#: ANAF's two authorities disagree here and they cannot both be satisfied:
#:
#: * ``Ro_SAFT_Schema_v249_2025.xsd`` declares
#:   ``targetNamespace="mfp:anaf:dgti:d406t:declaratie:v1"`` (with a ``t``),
#:   so a document in any other namespace fails XSD validation with
#:   "No matching global declaration available for the validation root".
#: * DUKIntegrator — the gate a submission actually passes through — rejects
#:   that exact namespace: *"namespace ('mfp:anaf:dgti:d406t:declaratie:v1')
#:   lipsa sau incorect la sectiunea AuditFile. Valoarea corecta este
#:   xmlns='mfp:anaf:dgti:d406:declaratie:v1'"*. Verified by running the
#:   official validator against a generated file.
#:
#: DUKIntegrator wins, because it decides whether a declaration is accepted.
#: The validator in ``models/d406_validator.py`` bridges the gap by swapping
#: this namespace for :data:`SCHEMA_NAMESPACE` in memory before validating,
#: so we still get full structural checking against the official schema.
SAFT_NAMESPACE = 'mfp:anaf:dgti:d406:declaratie:v1'

#: The namespace the XSD itself declares. Used only for validation.
SCHEMA_NAMESPACE = 'mfp:anaf:dgti:d406t:declaratie:v1'

#: Emitted as ``Header/AuditFileVersion``. Taken from the XSD's ``version``
#: attribute (2.4.9), NOT from its internal ``doc:Number`` annotation, which
#: still says 2.4.8 — a known inconsistency in ANAF's own file.
AUDIT_FILE_VERSION = '2.4.9'


class EmptyRequiredValue(ValueError):
    """Raised when a mandatory SAF-T element has no value to emit.

    Surfacing this as an exception rather than writing an empty tag is
    deliberate: an empty mandatory element is rejected by DUK anyway, and a
    Python traceback naming the element is far more actionable than
    ``atribut prezent dar vid nepermis``.
    """


def _qname(tag: str) -> str:
    return f'{{{SAFT_NAMESPACE}}}{tag}'


class Node:
    """A single SAF-T element under construction."""

    __slots__ = ('_element',)

    def __init__(self, element):
        self._element = element

    @property
    def element(self):
        return self._element

    def child(self, tag: str) -> 'Node':
        """Append an always-present child container and return it."""
        return Node(etree.SubElement(self._element, _qname(tag)))

    def add(self, tag: str, value) -> 'Node | None':
        """Append ``<tag>value</tag>`` **only if the value is non-empty**.

        This is the single point where the "no empty element" invariant is
        applied. ``None``, ``False`` and blank/whitespace-only strings all
        cause the element to be skipped entirely rather than emitted empty.
        """
        text = _as_text(value)
        if not text:
            return None
        node = etree.SubElement(self._element, _qname(tag))
        node.text = text
        return Node(node)

    def add_required(self, tag: str, value) -> 'Node':
        """Append a mandatory element, raising when it has no value."""
        text = _as_text(value)
        if not text:
            raise EmptyRequiredValue(
                f'Mandatory SAF-T element <{tag}> has no value. '
                f'Fix the source record rather than exporting an empty tag.'
            )
        node = etree.SubElement(self._element, _qname(tag))
        node.text = text
        return Node(node)

    def add_all(self, pairs) -> None:
        """Append a sequence of optional ``(tag, value)`` pairs in order."""
        for tag, value in pairs:
            self.add(tag, value)

    def is_empty(self) -> bool:
        """True when nothing was actually appended to this node."""
        return len(self._element) == 0 and not (self._element.text or '').strip()

    def drop_if_empty(self) -> bool:
        """Remove this node from its parent when nothing was added to it.

        Used for optional container elements (``<Contact>``, ``<Address>``)
        that must not appear as empty shells.
        """
        if self.is_empty() and self._element.getparent() is not None:
            self._element.getparent().remove(self._element)
            return True
        return False


def _as_text(value) -> str:
    if value is None or value is False:
        return ''
    if value is True:
        return 'true'
    return str(value).strip()


class AuditFile:
    """Root ``<AuditFile>`` document."""

    def __init__(self):
        self._root = etree.Element(
            _qname('AuditFile'), nsmap={None: SAFT_NAMESPACE})
        self.root = Node(self._root)

    def section(self, tag: str) -> Node:
        return self.root.child(tag)

    def to_bytes(self, pretty: bool = True) -> bytes:
        return etree.tostring(
            self._root,
            xml_declaration=True,
            encoding='UTF-8',
            pretty_print=pretty,
        )

    @property
    def element(self):
        return self._root
