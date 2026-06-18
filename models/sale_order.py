# -*- coding: utf-8 -*-
"""Extend sale.order dengan field QRIS/COD dan auto-confirm logic."""

import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # === QRIS info (denormalized dari payment.transaction) ===
    qris_amount = fields.Char(
        string='QRIS Amount',
        compute='_compute_qris_info',
        store=True,
    )
    qris_state = fields.Selection(
        related='transaction_ids.qris_state',
        string='QRIS State',
        store=False,
    )
    cod_state = fields.Selection(
        related='transaction_ids.cod_state',
        string='COD State',
        store=False,
    )
    payment_method_code = fields.Char(
        string='Payment Method',
        compute='_compute_payment_method_code',
        store=True,
    )

    @api.depends('transaction_ids', 'transaction_ids.qris_amount')
    def _compute_qris_info(self):
        for so in self:
            tx = so.transaction_ids[:1]
            so.qris_amount = tx.qris_amount if tx else ''

    @api.depends('transaction_ids', 'transaction_ids.provider_id', 'transaction_ids.provider_id.code')
    def _compute_payment_method_code(self):
        for so in self:
            tx = so.transaction_ids[:1]
            so.payment_method_code = tx.provider_id.code if tx else ''

    def action_open_qris_payment(self):
        """Smart button: open QRIS payment detail di payment.transaction."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'QRIS Payment',
            'res_model': 'payment.transaction',
            'res_id': self.transaction_ids[:1].id,
            'view_mode': 'form',
            'target': 'current',
        }

    # === Admin verifikasi langsung dari Website Orders dashboard (kanban) ===
    def action_wsd_verify_qris_payment(self):
        """Dipanggil dari tombol 'Verify Payment' di kanban website_sale_dashboard.
        Cari QRIS transaction dari SO ini, panggil action_qris_mark_paid().
        """
        self.ensure_one()
        tx = self.transaction_ids.filtered(
            lambda t: t.provider_id.code == 'qris_dinamis' and t.qris_state == 'pending_verification'
        )
        if not tx:
            tx = self.transaction_ids.filtered(
                lambda t: t.provider_id.code == 'qris_dinamis' and t.qris_state == 'pending'
            )
        if not tx:
            _logger.warning(
                "action_wsd_verify_qris_payment: no pending QRIS tx on SO %s", self.name,
            )
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Tidak ada QRIS pending',
                    'message': 'Pesanan ini tidak punya transaksi QRIS yang menunggu verifikasi.',
                    'type': 'warning',
                    'sticky': False,
                },
            }
        try:
            tx[:1].action_qris_mark_paid()
        except Exception as e:
            _logger.exception("Error verifying QRIS payment for SO %s: %s", self.name, e)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Gagal verifikasi',
                    'message': 'Terjadi error: %s' % e,
                    'type': 'danger',
                    'sticky': True,
                },
            }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Pembayaran terverifikasi',
                'message': 'Pembayaran QRIS untuk %s berhasil dikonfirmasi.' % self.name,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def action_wsd_reject_qris_payment(self):
        """Dipanggil dari tombol 'Reject Payment' di kanban.
        Reject QRIS transaction + cancel sale order.
        """
        self.ensure_one()
        tx = self.transaction_ids.filtered(
            lambda t: t.provider_id.code == 'qris_dinamis'
                      and t.qris_state in ('pending', 'pending_verification')
        )
        if not tx:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Tidak ada QRIS tx',
                    'message': 'Pesanan ini tidak punya transaksi QRIS yang bisa di-reject.',
                    'type': 'warning',
                    'sticky': False,
                },
            }
        try:
            tx[:1].action_qris_reject(reason='Ditolak admin dari dashboard')
        except Exception as e:
            _logger.exception("Error rejecting QRIS payment for SO %s: %s", self.name, e)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Gagal reject',
                    'message': 'Terjadi error: %s' % e,
                    'type': 'danger',
                    'sticky': True,
                },
            }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Pembayaran ditolak',
                'message': 'Pembayaran QRIS untuk %s ditolak. Sale order di-cancel.' % self.name,
                'type': 'warning',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
