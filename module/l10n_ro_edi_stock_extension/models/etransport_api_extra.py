# Copyright 2026 NextERP Romania SRL

from urllib.parse import urlencode
import requests
from odoo import _

from odoo.addons.l10n_ro_edi_stock.models.etransport_api import ETransportAPI, ETRANSPORT_URLS


class ETransportAPIExtra(ETransportAPI):
    """Extends the official API with the LIST and TRANSPORTER INFO services.

    Reuses _make_etransport_request for oauth2 authentication.
    """

    def _make_etransport_request(
        self, company, endpoint, method, session=None, data=None
    ):
        # LIST/INFO return lists or envelopes with "mesaje"; the upload/status
        # parser in Odoo 19 requires ExecutionStatus and cannot parse these.
        if endpoint.startswith(("lista/", "info?")):
            if not company.l10n_ro_edi_access_token:
                return {"error": _("Configure ANAF access for this company first.")}
            client = session or requests.Session()
            try:
                env = "test" if company.l10n_ro_edi_test_env else "prod"
                response = client.request(
                    method=method, url=f"{ETRANSPORT_URLS[env]}/{endpoint}",
                    headers={"Authorization": f"Bearer {company.l10n_ro_edi_access_token}"},
                    timeout=10)
                if response.status_code != 200:
                    return {"error": _("ANAF eTransport returned HTTP %s.", response.status_code)}
                content = response.json()
                if isinstance(content, list):
                    return {"content": content}
                if isinstance(content, dict) and content.get("ExecutionStatus") != 1 and (
                        "mesaje" in content or "inregistrari" in content):
                    return {"content": content}
                return {"error": _("Unexpected ANAF eTransport list/info response.")}
            except (requests.RequestException, ValueError, TypeError) as err:
                return {"error": _("ANAF eTransport request failed: %s", str(err))}
            finally:
                if session is None:
                    client.close()
        # OVERRIDE: the base only maps HTTP 404/403/401/204 and then assumes the
        # body always contains 'ExecutionStatus'. Any other shape (e.g. a gateway
        # error body, or JSON without that key) raises KeyError and crashes the
        # caller. Catch it and return a normal error dict instead.
        try:
            return super()._make_etransport_request(
                company=company,
                endpoint=endpoint,
                method=method,
                session=session,
                data=data,
            )
        except (KeyError, ValueError, TypeError) as err:
            return {
                # ``ETransportAPI`` is a plain class, not a model - there is no
                # ``self.env`` here, so the module-level ``_`` is the only option.
                # pylint: disable=prefer-env-translation
                "error": _("Unexpected response from ANAF eTransport: %s", err)
            }

    def get_list(self, company_id, days=60, session=None):
        cif = (company_id.vat or "").replace("RO", "")
        if not cif:
            return {"error": _("The company VAT number is missing.")}
        return self._make_etransport_request(
            company=company_id,
            endpoint=f"lista/{days}/{cif}",
            method="get",
            session=session,
        )

    def get_transporter_info(
        self, company_id, cui_op, cui_decl=None, uit=None, ref_decl=None, session=None
    ):
        params = {"cui_op": cui_op}
        if cui_decl:
            params["cui_decl"] = cui_decl
        if uit:
            params["uit"] = uit
        if ref_decl:
            params["ref_decl"] = ref_decl
        return self._make_etransport_request(
            company=company_id,
            endpoint=f"info?{urlencode(params)}",
            method="get",
            session=session,
        )
