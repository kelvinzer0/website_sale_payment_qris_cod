# -*- coding: utf-8 -*-
"""Extend payment.provider untuk QRIS Dinamis dan COD."""

import logging
from odoo import fields, models, _

_logger = logging.getLogger(__name__)


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    code = fields.Selection(
        selection_add=[
            ('qris_dinamis', 'QRIS Dinamis'),
            ('cod', 'Bayar Ditempat (COD)'),
        ],
        ondelete={'qris_dinamis': 'set default', 'cod': 'set default'},
    )

    # === QRIS-specific config ===
    qris_base_string = fields.Text(
        string='Base QRIS String',
        help='Raw QRIS string hasil decode dari QR static Warung Lakku. '
             'Contoh: 00020101021126570011ID.DANA.WWW...63044E65',
        compute='_compute_qris_base_string',
        inverse='_inverse_qris_base_string',
        store=True,
    )
    qris_expiry_minutes = fields.Integer(
        string='QRIS Expiry (minutes)',
        default=15,
        help='Berapa menit QRIS valid sebelum dianggap expired.',
    )
    cod_instructions = fields.Text(
        string='COD Instructions',
        default='Siapkan uang pas. Kurir akan menghubungi sebelum datang.',
        help='Instruksi untuk customer yang pilih Bayar Ditempat.',
    )

    def _compute_qris_base_string(self):
        # Default ambil dari config parameter kalau provider tidak punya value
        for provider in self:
            if provider.code == 'qris_dinamis' and not provider.qris_base_string:
                param = self.env['ir.config_parameter'].sudo().get_param(
                    'website_sale_payment_qris_cod.qris_base_string', ''
                )
                provider.qris_base_string = param

    def _inverse_qris_base_string(self):
        for provider in self:
            if provider.code == 'qris_dinamis' and provider.qris_base_string:
                # Sync ke config parameter supaya bisa dipakai transaksi lain
                self.env['ir.config_parameter'].sudo().set_param(
                    'website_sale_payment_qris_cod.qris_base_string',
                    provider.qris_base_string,
                )
