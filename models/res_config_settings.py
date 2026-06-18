# -*- coding: utf-8 -*-
"""Res config settings untuk QRIS Dinamis & COD."""

from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    qris_base_string = fields.Text(
        string='Base QRIS String',
        config_parameter='website_sale_payment_qris_cod.qris_base_string',
        help='Raw QRIS string hasil decode dari QR static Warung Lakku.',
    )
    qris_expiry_minutes = fields.Integer(
        string='QRIS Expiry (minutes)',
        config_parameter='website_sale_payment_qris_cod.qris_expiry_minutes',
        default=15,
    )
    cod_instructions = fields.Text(
        string='COD Instructions',
        config_parameter='website_sale_payment_qris_cod.cod_instructions',
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
