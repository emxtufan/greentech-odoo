# -*- coding: utf-8 -*-

import logging
import os
import subprocess
import tempfile

from odoo import api, models, _

_logger = logging.getLogger(__name__)

# DUKIntegrator installation path (must be readable by the odoo user).
# Configurable via the ``tbs_anaf_duk_validator.duk_path`` system parameter
# (Settings > General Settings > ANAF DUKIntegrator, or Settings > Technical
# > Parameters > System Parameters). This default matches where TBS installs
# it on its own servers; other installs will typically need to change it.
DUK_PATH_DEFAULT = '/var/odoo/dukintegrator'

# Legacy system parameter key, used by installs that ran this validator
# bundled inside l10n_ro_anaf_declarations before it was split out into this
# standalone module (PR extracting tbs_anaf_duk_validator). Read as a
# fallback only, so nobody has to re-enter their path on upgrade.
_LEGACY_DUK_PATH_PARAM = 'l10n_ro_anaf_declarations.duk_path'
_DUK_PATH_PARAM = 'tbs_anaf_duk_validator.duk_path'


class AnafDukValidator(models.AbstractModel):
    """Stateless service wrapping ANAF's official DUKIntegrator tool.

    DUKIntegrator is the Java validator ANAF itself uses to check tax
    declaration XML before acceptance. This service shells out to a local
    DUKIntegrator install (``.jar`` files, not bundled with this module —
    see README.md for where to get them) and returns a plain result dict.

    Any module that already builds ANAF declaration XML can call
    ``self.env['anaf.duk.validator'].validate(xml_content, 'D300', year=2026,
    month=7)`` without depending on how that XML was produced.
    """
    _name = 'anaf.duk.validator'
    _description = 'ANAF DUKIntegrator Validation Service'

    @api.model
    def get_duk_path(self):
        """Return the configured DUKIntegrator installation path.

        Reads the ``tbs_anaf_duk_validator.duk_path`` system parameter so
        self-hosted DUKIntegrator setups don't require a code change or
        server access — it's a Settings page field. Falls back to the
        legacy parameter key (pre-extraction installs), then to the
        historical default.
        """
        icp = self.env['ir.config_parameter'].sudo()
        return (
            icp.get_param(_DUK_PATH_PARAM)
            or icp.get_param(_LEGACY_DUK_PATH_PARAM)
            or DUK_PATH_DEFAULT
        )

    @api.model
    def check_installation(self):
        """Check whether DUKIntegrator is installed at the configured path.

        Returns:
            dict: {installed: bool, path: str, jar: str or None, message: str}
        """
        duk_path = self.get_duk_path()
        jar = self._find_jar(duk_path)
        if jar:
            return {
                'installed': True,
                'path': duk_path,
                'jar': jar,
                'message': _('DUKIntegrator găsit la %s') % jar,
            }
        return {
            'installed': False,
            'path': duk_path,
            'jar': None,
            'message': self._not_found_message(duk_path),
        }

    def _find_jar(self, duk_path):
        """Return the full path to the DUKIntegrator jar, or None."""
        duk_jar = os.path.join(duk_path, 'DUKIntegrator_AnLunaUI.jar')
        if not os.path.exists(duk_jar):
            duk_jar = os.path.join(duk_path, 'DUKIntegrator.jar')
        if not os.path.exists(duk_jar):
            return None
        return duk_jar

    def _not_found_message(self, duk_path):
        return _(
            'DUKIntegrator.jar nu a fost găsit la: %s\n\n'
            'Instalează DUKIntegrator (fișierele .jar distribuite de ANAF) '
            'pe acea cale, sau schimbă calea din Setări > Setări generale > '
            'ANAF DUKIntegrator.'
        ) % duk_path

    @api.model
    def validate(self, xml_content, duk_code, year=None, month=None):
        """Validate declaration XML with DUKIntegrator.

        Args:
            xml_content: XML content as string.
            duk_code: DUKIntegrator declaration code (e.g. 'D300', 'D112').
            year: declaration period year, for validators that dispatch by
                version (e.g. D101). Optional.
            month: declaration period month. Optional.

        Returns:
            dict: {success: bool, message: str} or {success: False, errors: str}
        """
        return self._run(xml_content, duk_code, mode='validate', year=year, month=month)

    @api.model
    def generate_pdf(self, xml_content, duk_code, year=None, month=None):
        """Validate declaration XML and generate DUKIntegrator's flat PDF.

        Same as :meth:`validate`, but on success also returns the
        non-editable confirmation PDF DUKIntegrator produces.

        Returns:
            dict: {success: bool, message: str, pdf_data: bytes} on success,
                {success: False, errors: str} on failure.
        """
        return self._run(xml_content, duk_code, mode='pdf', year=year, month=month)

    def _run(self, xml_content, duk_code, mode, year=None, month=None):
        """Run DUKIntegrator on the XML content.

        Uses DUKIntegrator_AnLunaUI.jar (supports an=/luna= params for
        proper version dispatch to newer validators). Falls back to
        DUKIntegrator.jar if AnLunaUI isn't available.
        """
        duk_path = self.get_duk_path()
        duk_jar = self._find_jar(duk_path)
        if not duk_jar:
            return {'success': False, 'errors': self._not_found_message(duk_path)}

        an_param = str(year) if year else ''
        luna_param = str(month) if month else ''

        with tempfile.TemporaryDirectory() as tmpdir:
            xml_path = os.path.join(tmpdir, 'declaration.xml')
            err_path = os.path.join(tmpdir, 'errors.txt')
            pdf_path = os.path.join(tmpdir, 'output.pdf')

            with open(xml_path, 'w', encoding='utf-8') as f:
                f.write(xml_content)

            java_opts = [
                'java', '-Xmx128m', '-Xms32m', '-XX:CompressedClassSpaceSize=64m',
                '-jar', duk_jar,
            ]
            if mode == 'validate':
                cmd = java_opts + ['-v', duk_code, xml_path, err_path, '0']
            else:  # pdf
                cmd = java_opts + ['-p', duk_code, xml_path, err_path, '0', '0', pdf_path]

            if an_param and luna_param and 'AnLunaUI' in duk_jar:
                cmd += ['an=%s' % an_param, 'luna=%s' % luna_param]

            _logger.info("DUK cmd: %s", ' '.join(cmd))
            try:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=30,
                    cwd=duk_path,
                )
                _logger.info("DUK %s exit=%d stdout=%s stderr=%s",
                             mode, proc.returncode,
                             proc.stdout[:500] if proc.stdout else '',
                             proc.stderr[:500] if proc.stderr else '')
            except subprocess.TimeoutExpired:
                return {'success': False, 'errors': _('DUKIntegrator timeout (30s)')}
            except Exception as e:
                _logger.exception("DUK subprocess error")
                return {'success': False, 'errors': str(e)}

            errors = ''
            if os.path.exists(err_path):
                with open(err_path, 'r', encoding='utf-8', errors='replace') as f:
                    errors = f.read().strip()
            _logger.info("DUK errors file content: [%s]", errors)

            pdf_exists = os.path.exists(pdf_path) if mode == 'pdf' else False

            if errors == 'ok':
                result = {'success': True, 'message': _('Validare fara erori')}
                if mode == 'pdf' and pdf_exists:
                    with open(pdf_path, 'rb') as f:
                        result['pdf_data'] = f.read()
                return result
            else:
                diag = errors
                if proc.stdout and proc.stdout.strip():
                    diag += '\n\nSTDOUT: ' + proc.stdout.strip()
                if proc.stderr and proc.stderr.strip():
                    diag += '\n\nSTDERR: ' + proc.stderr.strip()
                return {'success': False, 'errors': diag}
