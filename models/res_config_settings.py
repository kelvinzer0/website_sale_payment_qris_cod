# -*- coding: utf-8 -*-
"""Res config settings untuk QRIS Dinamis & COD.

NOTE (v17.0.2.1.1):
    Field Text TIDAK boleh pakai config_parameter= (Odoo 17
    _get_classified_fields hanya menerima boolean/integer/float/char/
    selection/many2one/datetime). Persistence ke ir.config_parameter
    ditangani manual di get_values() / set_values() bawah.
"""

from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    qris_base_string = fields.Text(
        string='Base QRIS String',
        help='Raw QRIS string hasil decode dari QR static Warung Lakku.',
    )
    qris_expiry_minutes = fields.Integer(
        string='QRIS Expiry (minutes)',
        config_parameter='website_sale_payment_qris_cod.qris_expiry_minutes',
        default=15,
    )
    cod_instructions = fields.Text(
        string='COD Instructions',
    )
    module_website_sale_payment_qris_cod_state = fields.Selection(
        [('installed', 'Installed'), ('not_installed', 'Not Installed')],
        compute='_compute_module_state',
    )

    @api.depends('qris_base_string')
    def _compute_module_state(self):
        module = self.env['ir.module.module'].search([
            ('name', '=', 'website_sale_payment_qris_cod'),
        ], limit=1)
        for rec in self:
            rec.module_website_sale_payment_qris_cod_state = (
                'installed' if module.state == 'installed' else 'not_installed'
            )

    # ------------------------------------------------------------------
    # Manual persistence untuk field Text (qris_base_string,
    # cod_instructions) -- Odoo 17 _get_classified_fields menolak tipe
    # Text dengan config_parameter=.
    # ------------------------------------------------------------------
    @api.model
    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        IrConfig = self.env['ir.config_parameter'].sudo()
        res.update(
            qris_base_string=IrConfig.get_param(
                'website_sale_payment_qris_cod.qris_base_string', default='') or '',
            cod_instructions=IrConfig.get_param(
                'website_sale_payment_qris_cod.cod_instructions', default='') or '',
        )
        return res

    def set_values(self):
        super(ResConfigSettings, self).set_values()
        IrConfig = self.env['ir.config_parameter'].sudo()
        IrConfig.set_param(
            'website_sale_payment_qris_cod.qris_base_string',
            self.qris_base_string or '')
        IrConfig.set_param(
            'website_sale_payment_qris_cod.cod_instructions',
            self.cod_instructions or '')
