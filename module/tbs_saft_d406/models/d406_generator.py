# Part of tbs_saft_d406. See LICENSE file for full copyright and licensing details.
"""D406 SAF-T generator — orchestration, Header and MasterFiles.

``GeneralLedgerEntries`` lives in :mod:`.d406_generator_gl` and
``SourceDocuments`` in :mod:`.d406_generator_source`; all three extend the
same ``l10n.ro.d406.generator`` abstract model.

Design note — why an abstract model and not a plain Python class: it lets
integrators override a single section with a normal Odoo ``_inherit``
without forking the module, which is the usual reason a localisation module
gets copy-pasted.
"""
from odoo import _, api, models
from odoo.exceptions import UserError

from ..d406 import registration, sanitize
from ..d406.xmlbuilder import AUDIT_FILE_VERSION, AuditFile, Node

#: Reported in ``Header/SoftwareID``. ANAF uses it to attribute rejections
#: to a producer, so it must identify this module, not the Odoo core.
SOFTWARE_COMPANY_NAME = 'Transilvania Business Suite'
SOFTWARE_ID = 'tbs_saft_d406'

#: ``Header/HeaderComment`` — the declaration type. This single character is
#: what tells DUKIntegrator which sections it may find in the file; the XSD
#: itself does not gate them (see README, "Why XSD validation is not enough").
DECLARATION_TYPES = [
    ('L', 'L - Lunară'),
    ('T', 'T - Trimestrială'),
    ('NL', 'NL - Nerezidenți, lunară'),
    ('NT', 'NT - Nerezidenți, trimestrială'),
]

#: ``Products/Product/GoodsServicesID`` — workbook field MF.P.3 allows
#: exactly two values.
GOODS_SERVICES_PRODUCT = '01'
GOODS_SERVICES_SERVICE = '02'

#: ``ProductCommodityCode`` when no NC8 customs code applies. Workbook field
#: MF.P.6: "Where Cod NC is not applicable or required according to the
#: Romanian law, will be filled in with value 0 (zero)."
COMMODITY_CODE_NOT_APPLICABLE = '0'

#: ``TaxCodeDetails/BaseRate`` — the fraction of the taxable base the rate
#: applies to. Romanian VAT always applies to the full base. The schema types
#: it as a decimal with 4 fraction digits.
BASE_RATE_FULL = '1.0000'

#: Declaration types this module produces today. ``A`` (annual, fixed assets)
#: and ``C`` (on demand, stock) need sections that Odoo Community has no
#: source for; they are deliberately out of scope here and are planned as
#: separate bridge modules.
SUPPORTED_DECLARATION_TYPES = {'L', 'T', 'NL', 'NT'}


class D406Generator(models.AbstractModel):
    _name = 'l10n.ro.d406.generator'
    _description = 'D406 SAF-T Generator'

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    @api.private
    @api.model
    def generate(self, options):
        """Build the complete ``AuditFile`` document.

        :param options: a :class:`~..d406.context.ExportOptions`-shaped dict
            carrying ``company``, ``date_from``, ``date_to``,
            ``declaration_type``, ``segment_index`` and
            ``total_segments``.
        :returns: the XML document as bytes.
        """
        self._check_options(options)
        audit_file = AuditFile()
        context = self._build_context(options)

        self._build_header(audit_file.section('Header'), context)
        self._build_master_files(audit_file.section('MasterFiles'), context)
        self._build_general_ledger_entries(
            audit_file.section('GeneralLedgerEntries'), context)
        self._build_source_documents(
            audit_file.section('SourceDocuments'), context)

        return audit_file.to_bytes()

    @api.model
    def _check_options(self, options):
        declaration_type = options.get('declaration_type')
        if declaration_type not in SUPPORTED_DECLARATION_TYPES:
            raise UserError(_(
                'Declaration type %(type)s is not supported by this module. '
                'It produces the periodic declarations (%(supported)s). The '
                'annual (A) and on-demand (C) declarations require fixed '
                'asset and stock data that Odoo Community does not provide '
                'on its own.',
                type=declaration_type,
                supported=', '.join(sorted(SUPPORTED_DECLARATION_TYPES)),
            ))
        if options['date_from'] > options['date_to']:
            raise UserError(_('The start date must precede the end date.'))

    @api.model
    def _build_context(self, options):
        """Collect everything the sections need, once.

        Sections are built in schema order but reference each other's data
        (an invoice needs the customer's identifier, a journal line needs the
        account's ANAF code), so the identifier maps are resolved up front
        instead of being recomputed per row.
        """
        company = options['company']
        context = dict(options)
        context['company_registration'] = \
            registration.company_header_registration_number(
                self._partner_identity(company.partner_id))
        context['partner_ids'] = {}
        context['anaf_account_codes'] = \
            self.env['l10n.ro.d406.account'].code_set(
                company.l10n_ro_d406_chart or 'bal_soc_com')
        context['warnings'] = []
        return context

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    @api.model
    def _partner_identity(self, partner):
        """Adapt an Odoo partner to the pure-Python identity object."""
        return registration.PartnerIdentity(
            name=partner.name or '',
            vat=partner.vat or '',
            company_registry=partner.company_registry or '',
            country_code=(partner.country_id.code or ''),
            is_company=partner.is_company,
            partner_ref=partner.ref or '',
            partner_id=partner.id,
        )

    @api.model
    def _partner_saft_id(self, partner, context, is_customer=True):
        """Return the cached SAF-T identifier for a partner.

        Falls back to the reporting company's own identifier for partners we
        cannot classify — card payments to foreign merchants are the common
        case and produced a confirmed rejection when left as ``0``.
        """
        if not partner:
            return context['company_registration']
        cache_key = (partner.id, is_customer)
        if cache_key in context['partner_ids']:
            return context['partner_ids'][cache_key]

        identifier = registration.partner_registration_number(
            self._partner_identity(partner), is_customer=is_customer)
        if not identifier:
            identifier = registration.unclassified_partner_id(
                context['company_registration'])
            context['warnings'].append(_(
                'Partner "%(name)s" has no usable fiscal identifier; the '
                'reporting company identifier was used instead.',
                name=partner.display_name,
            ))
        context['partner_ids'][cache_key] = identifier
        return identifier

    @api.model
    def _add_address(self, parent, partner, tag='Address'):
        """Append an ``AddressStructure``, or nothing when unusable.

        ``City`` and ``Country`` are the only mandatory children. Odoo
        Enterprise emits the block only when both zip *and* city are present,
        which silently drops the whole address — and therefore the mandatory
        ``<Country>`` — for the many Romanian companies that ANAF's own
        ``v9/tva`` service returns with an empty postal code. Postal code is
        optional here, exactly as the schema says.
        """
        city = sanitize.text(partner.city, 50)
        country_code = (partner.country_id.code or '').upper()
        if not city or not country_code:
            return None

        node = parent.child(tag)
        node.add('StreetName', sanitize.text(partner.street, 200))
        node.add('AdditionalAddressDetail', sanitize.text(partner.street2, 200))
        node.add_required('City', city)
        node.add('PostalCode', sanitize.text(partner.zip, 35))
        # Region is accepted only for Romania, formatted RO-XX. Emitting it
        # for any other country is a hard rejection.
        node.add('Region', sanitize.region_code(
            country_code, partner.state_id.code))
        node.add_required('Country', country_code)
        return node

    @api.model
    def _add_contact(self, parent, partner):
        """Append a ``Contact`` block only when a full person name exists.

        ``FirstName`` and ``LastName`` are both mandatory. A contact carrying
        only one of them yields ``LastName: atribut prezent dar vid nepermis``,
        so the entire optional block is skipped instead.
        """
        first_name, last_name = self._split_person_name(partner)
        if not first_name or not last_name:
            return None

        contact = parent.child('Contact')
        person = contact.child('ContactPerson')
        person.add_required('FirstName', first_name)
        person.add_required('LastName', last_name)
        contact.add('Telephone', sanitize.text(partner.phone, 20))
        contact.add('Email', sanitize.text(partner.email, 254))
        contact.add('Website', sanitize.text(partner.website, 254))
        return contact

    @api.model
    def _split_person_name(self, partner):
        """Split an Odoo free-text name into first and last name.

        Odoo stores a single ``name``; SAF-T wants two mandatory parts. The
        split is naive by necessity, and the caller drops the block entirely
        when it cannot produce both parts.
        """
        name = sanitize.text(partner.name, 200)
        if not name:
            return '', ''
        parts = name.split(' ')
        if len(parts) < 2:
            return '', ''
        return parts[0], ' '.join(parts[1:])

    @api.model
    def _add_bank_accounts(self, parent, partner):
        """Append ``BankAccount`` blocks using the sanitised IBAN.

        Always the sanitised number, never ``acc_number``: the raw field
        renders with the spaces the user typed, and DUK rejects
        ``RO49 AAAA 1B31 0075 9384 0000`` as malformed for country RO.
        """
        added = 0
        for bank in partner.bank_ids:
            iban = sanitize.iban(bank.sanitized_acc_number or bank.acc_number)
            if not iban:
                continue
            node = parent.child('BankAccount')
            node.add_required('IBANNumber', iban)
            node.add('BankAccountName', sanitize.text(bank.bank_id.name, 200))
            added += 1
        return added

    @api.model
    def _add_company_structure(self, parent, partner, registration_number):
        """Append the shared ``CompanyStructure`` block."""
        node = parent.child('CompanyStructure')
        node.add_required('RegistrationNumber', registration_number)
        node.add_required('Name', sanitize.text(partner.name, 350) or registration_number)
        self._add_address(node, partner)
        self._add_contact(node, partner)
        self._add_bank_accounts(node, partner)
        return node

    @api.model
    def _add_balance_pair(self, parent, balance, opening=True):
        """Append the debit/credit balance choice for an account or partner.

        The schema models these as an ``xs:choice``: exactly one of the two
        elements must appear. A zero balance is reported on the debit side.
        """
        prefix = 'Opening' if opening else 'Closing'
        if balance < 0:
            parent.add_required(f'{prefix}CreditBalance', sanitize.monetary(-balance))
        else:
            parent.add_required(f'{prefix}DebitBalance', sanitize.monetary(balance))

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------

    @api.model
    def _build_header(self, header: Node, context):
        company = context['company']
        header.add_required('AuditFileVersion', AUDIT_FILE_VERSION)
        header.add_required('AuditFileCountry', 'RO')
        header.add_required(
            'AuditFileDateCreated', context['creation_date'].isoformat())
        header.add_required('SoftwareCompanyName', SOFTWARE_COMPANY_NAME)
        header.add_required('SoftwareID', SOFTWARE_ID)
        header.add_required('SoftwareVersion', context['software_version'])

        self._add_header_company(header, context)

        header.add_required(
            'DefaultCurrencyCode', company.currency_id.name or 'RON')
        self._add_selection_criteria(header, context)
        header.add_required('HeaderComment', context['declaration_type'])
        header.add_required('SegmentIndex', str(context['segment_index']))
        header.add_required(
            'TotalSegmentsInsequence', str(context['total_segments']))
        header.add_required(
            'TaxAccountingBasis',
            company.l10n_ro_d406_tax_accounting_basis or 'I')
        header.add('TaxEntity', sanitize.text(company.l10n_ro_d406_tax_entity, 70))

    @api.model
    def _add_header_company(self, header: Node, context):
        """``Header/Company`` — the reporting taxpayer.

        Two things differ from every partner block and both are easy to get
        wrong. First, this ``RegistrationNumber`` carries no two-digit type
        prefix: a VAT-registered resident reports the VAT number *with* its
        RO prefix. Second, the schema types this element as
        ``CompanyHeaderStructure``, which is a *restriction* of the ordinary
        ``CompanyStructure``: ``Contact`` (including its ``Telephone``) and
        ``BankAccount`` are mandatory here even though they are optional for
        partners.
        """
        company = context['company']
        partner = company.partner_id
        node = header.child('Company')
        node.add_required('RegistrationNumber', context['company_registration'])
        node.add_required('Name', sanitize.text(company.name, 350))
        if not self._add_address(node, partner):
            raise UserError(_(
                'The company address is incomplete. SAF-T requires at least '
                'a city and a country on %(company)s.',
                company=company.display_name,
            ))
        self._add_header_contact(node, partner, company)
        # TaxRegistration is where the fiscal identifier is repeated for the
        # tax authority; ANAF expects its own authority code here.
        tax_registration = node.child('TaxRegistration')
        tax_registration.add_required(
            'TaxRegistrationNumber', context['company_registration'])
        tax_registration.add('TaxAuthority', 'ANAF')
        if not self._add_bank_accounts(node, partner):
            raise UserError(_(
                'Company %(company)s has no bank account with a valid IBAN. '
                'SAF-T requires at least one bank account for the reporting '
                'company.',
                company=company.display_name,
            ))

    @api.model
    def _add_header_contact(self, parent: Node, partner, company):
        """``Header/Company/Contact`` — mandatory, unlike a partner contact.

        A partner contact is dropped when incomplete; the taxpayer's own
        contact cannot be, so missing data is reported as a configuration
        error the accountant can fix rather than as an invalid file.
        """
        first_name, last_name = self._split_person_name(partner)
        if not first_name or not last_name:
            # Fall back to the company name so a single-word contact does not
            # block the export; ANAF only needs a reachable person.
            parts = sanitize.text(company.name, 200).split(' ')
            first_name = parts[0]
            last_name = ' '.join(parts[1:]) or parts[0]

        phone = sanitize.text(partner.phone or partner.mobile, 20)
        if not phone:
            raise UserError(_(
                'Company %(company)s has no phone number. SAF-T requires a '
                'contact telephone for the reporting company.',
                company=company.display_name,
            ))

        contact = parent.child('Contact')
        person = contact.child('ContactPerson')
        person.add_required('FirstName', first_name)
        person.add_required('LastName', last_name)
        contact.add_required('Telephone', phone)
        contact.add('Email', sanitize.text(partner.email, 254))
        contact.add('Website', sanitize.text(partner.website, 254))
        return contact

    @api.model
    def _add_selection_criteria(self, header: Node, context):
        """``Header/SelectionCriteria`` — the reported period.

        The schema offers a choice between an explicit date range and a
        period/year pair. The period form is used because ANAF's period
        consistency checks are expressed in months and years.
        """
        node = header.child('SelectionCriteria')
        date_from, date_to = context['date_from'], context['date_to']
        node.add_required('PeriodStart', str(date_from.month))
        node.add_required('PeriodStartYear', str(date_from.year))
        node.add_required('PeriodEnd', str(date_to.month))
        node.add_required('PeriodEndYear', str(date_to.year))

    # ------------------------------------------------------------------
    # MasterFiles
    # ------------------------------------------------------------------

    @api.model
    def _build_master_files(self, master: Node, context):
        """Build ``MasterFiles`` in strict schema order.

        Every direct child below is mandatory in the schema even when it has
        no entries, so the containers are always created. ``PhysicalStock``
        and ``Assets`` are optional-by-declaration and belong to the A and C
        declarations, which this module does not produce.
        """
        self._build_general_ledger_accounts(
            master.child('GeneralLedgerAccounts'), context)
        self._build_customers(master.child('Customers'), context)
        self._build_suppliers(master.child('Suppliers'), context)
        self._build_tax_table(master.child('TaxTable'), context)
        self._build_uom_table(master.child('UOMTable'), context)
        self._build_analysis_type_table(
            master.child('AnalysisTypeTable'), context)
        self._build_movement_type_table(
            master.child('MovementTypeTable'), context)
        self._build_products(master.child('Products'), context)
        self._build_owners(master.child('Owners'), context)
        # Assets is structurally mandatory in the schema regardless of
        # declaration type, so the container is always emitted. It stays
        # empty for L/T/NL/NT: fixed-asset accounting does not exist in Odoo
        # Community, and populating it belongs to the annual (A) declaration.
        master.child('Assets')

    @api.model
    def _build_general_ledger_accounts(self, parent: Node, context):
        balances = self._account_balances(context)
        accounts = self.env['account.account'].browse(
            sorted(balances)).sorted(lambda a: a.code or '')
        for account in accounts:
            opening, closing = balances[account.id]
            anaf_code = account.l10n_ro_d406_account_code
            account_id = sanitize.account_id(account.code)
            if not account_id:
                raise UserError(_(
                    'Account "%(account)s" has a non-numeric code. SAF-T '
                    '<AccountID> must be an integer. Set a manual SAF-T code '
                    'on the account.',
                    account=account.display_name,
                ))
            node = parent.child('Account')
            node.add_required('AccountID', account_id)
            node.add_required(
                'AccountDescription', sanitize.text(account.name, 256))
            # StandardAccountID is the *statutory* code the account maps to,
            # not a copy of AccountID. Reporting the account's own code here
            # (as Odoo Enterprise does) produces semantically wrong data that
            # DUK happens not to reject.
            node.add('StandardAccountID', anaf_code)
            node.add_required(
                'AccountType', account.l10n_ro_d406_saft_account_type())
            self._add_balance_pair(node, opening, opening=True)
            self._add_balance_pair(node, closing, opening=False)

    @api.model
    def _build_customers(self, parent: Node, context):
        for partner, opening, closing, account in self._partner_balances(
                context, receivable=True):
            node = parent.child('Customer')
            identifier = self._partner_saft_id(partner, context, is_customer=True)
            self._add_company_structure(node, partner, identifier)
            node.add_required('CustomerID', identifier)
            node.add_required('AccountID', account)
            self._add_balance_pair(node, opening, opening=True)
            self._add_balance_pair(node, closing, opening=False)

    @api.model
    def _build_suppliers(self, parent: Node, context):
        for partner, opening, closing, account in self._partner_balances(
                context, receivable=False):
            node = parent.child('Supplier')
            identifier = self._partner_saft_id(partner, context, is_customer=False)
            self._add_company_structure(node, partner, identifier)
            node.add_required('SupplierID', identifier)
            node.add_required('AccountID', account)
            self._add_balance_pair(node, opening, opening=True)
            self._add_balance_pair(node, closing, opening=False)

    @api.model
    def _build_tax_table(self, parent: Node, context):
        """``TaxTable`` — one entry per ANAF tax type actually used."""
        taxes = self._period_taxes(context)
        by_type = {}
        for tax in taxes:
            tax_type = tax.l10n_ro_d406_tax_type_id
            if not tax_type or not tax.l10n_ro_d406_tax_code_id:
                continue
            by_type.setdefault(tax_type, self.env['account.tax'])
            by_type[tax_type] |= tax

        for tax_type, type_taxes in sorted(
                by_type.items(), key=lambda item: item[0].code):
            node = parent.child('TaxTableEntry')
            node.add_required('TaxType', tax_type.code)
            node.add_required('Description', sanitize.text(tax_type.name, 256))
            seen_codes = set()
            for tax in type_taxes.sorted(
                    lambda t: t.l10n_ro_d406_tax_code_id.code):
                tax_code = tax.l10n_ro_d406_tax_code_id
                if tax_code.code in seen_codes:
                    continue
                seen_codes.add(tax_code.code)
                detail = node.child('TaxCodeDetails')
                detail.add_required('TaxCode', tax_code.code)
                detail.add('EffectiveDate',
                           tax_code.date_start.isoformat()
                           if tax_code.date_start else '')
                detail.add('ExpirationDate',
                           tax_code.date_end.isoformat()
                           if tax_code.date_end else '')
                detail.add('Description', sanitize.text(tax_code.name, 256))
                # The schema offers TaxPercentage or FlatTaxRate as a choice;
                # Romanian VAT is always a percentage.
                detail.add_required(
                    'TaxPercentage', sanitize.monetary(tax.amount))
                # BaseRate is mandatory and expresses the share of the base
                # the rate applies to. Romanian VAT always applies to the
                # whole base, so it is 1.
                detail.add_required('BaseRate', BASE_RATE_FULL)
                detail.add_required('Country', 'RO')

    @api.model
    def _build_uom_table(self, parent: Node, context):
        """``UOMTable`` — every unit used, each with a mandatory description.

        Odoo Enterprise omits ``<Description>`` here, which is a schema
        violation its own test suite asserts rather than catches.
        """
        uom_source = self.env['l10n.ro.d406.uom.code']
        for code in sorted(self._period_uom_codes(context)):
            node = parent.child('UOMTableEntry')
            node.add_required('UnitOfMeasure', code)
            node.add_required('Description', uom_source.description_for(code))

    @api.model
    def _build_analysis_type_table(self, parent: Node, context):
        """``AnalysisTypeTable`` — populated from analytic plans.

        Odoo Enterprise hardcodes this as an empty node. Community has
        ``account.analytic.plan`` and ``account.analytic.account``, so the
        real data is available.

        Both searches are scoped to the reporting company (plus the
        company-neutral records, which carry ``company_id = False``). Without
        that scope a multi-company database leaks the other companies'
        analytic codes into a declaration filed for this one.
        """
        company_domain = [('company_id', 'in', (False, context['company'].id))]
        # Odoo 19 plans are shared; their analytic accounts carry the company.
        plans = self.env['account.analytic.plan'].search([])
        for plan in plans:
            accounts = self.env['account.analytic.account'].search(
                [('plan_id', '=', plan.id)] + company_domain)
            for account in accounts:
                node = parent.child('AnalysisTypeTableEntry')
                node.add_required(
                    'AnalysisType', sanitize.text(plan.id and str(plan.id), 9))
                node.add_required(
                    'AnalysisTypeDescription', sanitize.text(plan.name, 256))
                node.add_required(
                    'AnalysisID', sanitize.text(account.code or str(account.id), 70))
                node.add_required(
                    'AnalysisIDDescription', sanitize.text(account.name, 256))

    @api.model
    def _build_movement_type_table(self, parent: Node, context):
        """``MovementTypeTable`` — goods movement types.

        Sourced from ``stock.picking.type`` when the Stock app is installed.
        Left empty otherwise, which is valid: the element is mandatory but
        may have zero entries.

        Scoped to the reporting company for the same reason as
        ``AnalysisTypeTable``: warehouse and operation-type names from a
        sibling company have no business in this company's declaration.
        """
        picking_type = self.env['stock.picking.type']._name \
            if 'stock.picking.type' in self.env else None
        if not picking_type:
            return
        for record in self.env['stock.picking.type'].search(
                [('company_id', 'in', (False, context['company'].id))]):
            node = parent.child('MovementTypeTableEntry')
            node.add_required('MovementType', sanitize.text(record.id and str(record.id), 9))
            node.add_required('Description', sanitize.text(record.display_name, 256))

    @api.model
    def _build_products(self, parent: Node, context):
        products = self._period_products(context)
        for product in products:
            node = parent.child('Product')
            node.add_required(
                'ProductCode',
                sanitize.text(product.default_code or str(product.id), 70))
            node.add('GoodsServicesID',
                     GOODS_SERVICES_SERVICE if product.type == 'service'
                     else GOODS_SERVICES_PRODUCT)
            # Emitted only when non-empty: an empty <ProductGroup> is a
            # confirmed rejection ("atribut prezent dar vid nepermis").
            node.add('ProductGroup',
                     sanitize.text(product.categ_id.name, 70))
            node.add_required(
                'Description', sanitize.text(product.name, 256))
            node.add_required(
                'ProductCommodityCode',
                self._product_commodity_code(product))
            node.add_required('UOMBase', self._uom_code(product.uom_id))
            node.add_required('UOMStandard', self._uom_code(product.uom_id))
            node.add_required('UOMToUOMBaseConversionFactor', '1.00')

    @api.model
    def _product_commodity_code(self, product):
        """Return ``ProductCommodityCode`` (NC8), which is mandatory.

        The workbook (MF.P.6) requires an 8-digit NC code, validated against
        ANAF's NC8/TARIC nomenclature, and states that where an NC code is
        not applicable under Romanian law the element is filled with the
        literal value ``0``. Services and ordinary domestic goods therefore
        report ``0`` rather than an invented code — DUKIntegrator checks this
        value against its nomenclature and rejects anything else.

        Community exposes ``hs_code`` on ``product.template`` through
        ``stock_delivery`` when that module is installed.
        """
        hs_code = sanitize.text(getattr(product, 'hs_code', False), 70)
        digits = ''.join(char for char in hs_code if char.isdigit())
        if len(digits) == 8:
            return digits
        return COMMODITY_CODE_NOT_APPLICABLE

    @api.model
    def _uom_code(self, uom):
        """Map an Odoo unit to its UN/ECE code."""
        if not uom:
            return 'C62'
        code = getattr(uom, 'l10n_ro_d406_uom_code', False)
        return sanitize.text(code) or 'C62'

    @api.model
    def _build_owners(self, parent: Node, context):
        """``Owners`` — mandatory container, empty for periodic declarations.

        The container itself is required by the schema, but DUKIntegrator
        allows zero ``Owner`` entries in a periodic declaration and rejects
        any that are present (``Owner ... min:0, max:0``). Stock ownership
        belongs to the on-demand (C) declaration, which this module does not
        produce, so nothing is emitted inside.
        """
        return
