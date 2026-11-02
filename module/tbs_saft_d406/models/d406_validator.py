# Part of tbs_saft_d406. See LICENSE file for full copyright and licensing details.
"""Validation of a generated D406 file.

Two layers, in this order:

1. **XSD** — always run, using the official schema shipped inside the module.
   Cheap and catches structural mistakes immediately.
2. **DUKIntegrator** — the actual gate ANAF applies. Detected *softly*: if
   the ``tbs_anaf_duk_validator`` module happens to be installed, its
   validator is offered as an extra button. This module never declares a
   dependency on it, so the export works standalone.

Why both: the XSD does not encode the business rules. It declares ``Assets``
and ``MovementOfGoods`` as mandatory regardless of declaration type, so a
schema-valid file can still be rejected for carrying a section that does not
belong to the declaration. XSD is necessary and not sufficient.
"""
import logging

from lxml import etree

from odoo import _, api, models
from odoo.tools import file_open

from ..d406.xmlbuilder import SAFT_NAMESPACE, SCHEMA_NAMESPACE

_logger = logging.getLogger(__name__)

#: Official ANAF schema, shipped in the module so validation works offline.
XSD_PATH = 'tbs_saft_d406/static/xsd/Ro_SAFT_Schema_v249_2025.xsd'

#: Model provided by the optional DUK bridge module, when installed.
DUK_VALIDATOR_MODEL = 'anaf.duk.validator'

#: DUKIntegrator declaration code for the periodic SAF-T declaration.
DUK_DECLARATION_CODE = 'D406'

#: Hardened parser for every document this module parses.
#:
#: lxml resolves external entities by default on the versions Odoo still
#: pins, which turns a document like
#: ``<!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>`` into a local
#: file read whose contents can surface through the returned error log. The
#: files we validate are our own output and never legitimately carry a
#: doctype, so entity resolution and DTD loading are simply switched off.
SAFT_XML_PARSER = etree.XMLParser(
    resolve_entities=False, no_network=True, load_dtd=False,
    dtd_validation=False, huge_tree=False)


class D406Validator(models.AbstractModel):
    _name = 'l10n.ro.d406.validator'
    _description = 'D406 SAF-T Validator'

    # ------------------------------------------------------------------
    # XSD
    # ------------------------------------------------------------------

    @api.model
    def _schema(self):
        """Load and cache the compiled XSD."""
        with file_open(XSD_PATH, 'rb') as handle:
            return etree.XMLSchema(etree.parse(handle, SAFT_XML_PARSER))

    @api.private
    @api.model
    def validate_xsd(self, xml_bytes):
        """Validate a document against the official schema.

        The file is emitted in the namespace DUKIntegrator demands, which is
        not the one the XSD declares as its target (see
        :data:`..d406.xmlbuilder.SAFT_NAMESPACE`). The namespace is therefore
        swapped in memory before validating, so the structural check still
        runs against the official schema. Only the copy being validated is
        rewritten; the file handed to ANAF keeps DUK's namespace.

        :returns: ``(is_valid, [messages])``. Messages carry the line number
            and element name so the caller can point at the offending record.
        """
        try:
            document = etree.fromstring(
                self._to_schema_namespace(xml_bytes), SAFT_XML_PARSER)
        except etree.XMLSyntaxError as error:
            return False, [_('The generated file is not well-formed XML: %s',
                             error)]

        schema = self._schema()
        if schema.validate(document):
            return True, []

        messages = [
            _('Line %(line)s: %(message)s',
              line=entry.line, message=entry.message)
            for entry in schema.error_log
        ]
        return False, messages

    @api.model
    def _to_schema_namespace(self, xml_bytes):
        """Rewrite the emitted namespace to the one the XSD declares.

        A byte-level replacement is used rather than a tree rewrite because
        the namespace appears exactly once, in the root element's ``xmlns``,
        and this keeps the validated bytes otherwise identical to the file
        that will be submitted.
        """
        return xml_bytes.replace(
            SAFT_NAMESPACE.encode(), SCHEMA_NAMESPACE.encode(), 1)

    # ------------------------------------------------------------------
    # DUKIntegrator (optional)
    # ------------------------------------------------------------------

    @api.private
    @api.model
    def duk_validator(self):
        """Return the DUK bridge model, or ``None`` when not installed.

        Soft detection on purpose: this module is LGPL-3 and free-standing.
        A hard dependency would drag the whole bridge — and a local Java
        installation — into every deployment that only wants the export.
        """
        return self.env.get(DUK_VALIDATOR_MODEL)

    @api.private
    @api.model
    def is_duk_available(self):
        return self.duk_validator() is not None

    @api.private
    @api.model
    def validate_duk(self, xml_bytes, year=None, month=None):
        """Run the file through DUKIntegrator when the bridge is available.

        :returns: ``(is_valid, [messages])`` mirroring :meth:`validate_xsd`,
            so callers treat both layers uniformly.
        """
        validator = self.duk_validator()
        if validator is None:
            return False, [_(
                'The DUKIntegrator bridge is not installed, so only schema '
                'validation was performed. ANAF applies additional business '
                'rules that this file has not been checked against.')]

        result = validator.validate(
            xml_bytes.decode('utf-8'), DUK_DECLARATION_CODE,
            year=year, month=month)
        if result.get('success'):
            return True, [result.get('message') or _('DUKIntegrator: valid.')]
        errors = result.get('errors') or result.get('message') or ''
        return False, [line for line in str(errors).splitlines() if line.strip()]
