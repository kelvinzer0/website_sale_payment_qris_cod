# -*- coding: utf-8 -*-
"""Extend payment.transaction untuk QRIS Dinamis dan COD.

Flow QRIS (admin-verifikasi, tanpa auto-match):
  1. _get_specific_create_values: simpan qris_amount (exact integer), qris_payload
  2. _get_specific_rendering_values: pass qris_payload + qris_amount ke template
  3. User klik "Saya sudah bayar" -> state jadi pending_verification
  4. Admin verifikasi manual: action_qris_mark_paid (confirm) atau action_qris_reject
  5. Cron job: auto-expire transaksi state=pending yang melebihi qris_expiry_minutes

Flow COD:
  1. _get_specific_create_values: mark as pending (waiting delivery)
  2. Set is_post_processed = True setelah sale.order confirm
"""

import base64
import io
import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .qris_helper import (
    convert_qris,
    format_amount_exact,
    validate_qris,
)

_logger = logging.getLogger(__name__)

try:
    import qrcode
except ImportError:
    qrcode = None
    _logger.warning("qrcode library not installed. QR PNG generation disabled.")


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    # === QRIS-specific fields ===
    qris_amount = fields.Char(
        string='QRIS Amount String',
        help='Nominal yang harus dibayar customer, format QRIS. Contoh: "50000"',
        readonly=True,
        copy=False,
    )
    qris_payload = fields.Text(
        string='QRIS Payload',
        help='Full dynamic QRIS string yang di-encode jadi QR code.',
        readonly=True,
        copy=False,
    )
    qris_qr_image = fields.Binary(
        string='QRIS QR Image (PNG)',
        compute='_compute_qris_qr_image',
    )
    qris_expires_at = fields.Datetime(
        string='QRIS Expires At',
        readonly=True,
        copy=False,
    )
    qris_state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('pending', 'Pending Payment'),
            ('pending_verification', 'Pending Admin Verification'),
            ('paid', 'Paid'),
            ('rejected', 'Rejected by Admin'),
            ('expired', 'Expired'),
            ('cancelled', 'Cancelled'),
        ],
        string='QRIS State',
        default='draft',
        tracking=True,
    )
    qris_user_confirmed_at = fields.Datetime(
        string='User Confirmed At',
        help='Timestamp saat user klik tombol "Saya sudah bayar".',
        readonly=True,
        copy=False,
    )
    qris_admin_verified_by = fields.Many2one(
        'res.users',
        string='Verified By',
        readonly=True,
        copy=False,
    )
    qris_admin_verified_at = fields.Datetime(
        string='Verified At',
        readonly=True,
        copy=False,
    )
    qris_reject_reason = fields.Text(
        string='Reject Reason',
        readonly=True,
        copy=False,
    )
    qris_matched_mutation_id = fields.Many2one(
        'qris.mutation.import',
        string='Matched Mutation (Audit)',
        readonly=True,
        copy=False,
    )
    cod_state = fields.Selection(
        [
            ('waiting_delivery', 'Waiting Delivery'),
            ('delivered', 'Delivered'),
            ('paid', 'Paid (Cash Received)'),
        ],
        string='COD State',
        default='waiting_delivery',
        tracking=True,
    )

    # === Hook: create values saat transaction dibuat (Odoo 17 signature) ===
    @api.model
    def _get_specific_create_values(self, provider_code, values):
        """Odoo 17 signature: (provider_code: str, values: dict) -> dict."""
        res = super()._get_specific_create_values(provider_code, values) if hasattr(super(), '_get_specific_create_values') else {}
        if provider_code == 'qris_dinamis':
            amount = values.get('amount', 0)
            try:
                amount_main = int(round(float(amount)))
            except (TypeError, ValueError):
                amount_main = 0
            # Exact integer amount (no suffix)
            qris_amount_str = format_amount_exact(amount_main)
            # Get base QRIS dari provider atau config parameter
            base_qris = ''
            provider_id = values.get('provider_id')
            if provider_id:
                provider = self.env['payment.provider'].browse(provider_id)
                if provider.exists():
                    base_qris = provider.qris_base_string
            if not base_qris:
                base_qris = self.env['ir.config_parameter'].sudo().get_param(
                    'website_sale_payment_qris_cod.qris_base_string', ''
                )
            if not base_qris:
                _logger.error("Base QRIS string belum di-set. Transaction akan dibuat tanpa payload QRIS.")
                res.update({'qris_state': 'draft', 'cod_state': False})
                return res
            try:
                payload = convert_qris(base_qris, qris_amount_str)
                valid, msg = validate_qris(payload)
                if not valid:
                    _logger.error("QRIS generated invalid: %s", msg)
                    res.update({'qris_state': 'draft'})
                    return res
                # QRIS TIDAK ada expiry sejak v17.0.2.1.0 — qris_expires_at diset False.
                # Customer bisa scan kapan saja, admin yang verifikasi manual.
                res.update({
                    'qris_amount': qris_amount_str,
                    'qris_payload': payload,
                    'qris_expires_at': False,
                    'qris_state': 'pending',
                })
            except Exception as e:
                _logger.exception("Error generating QRIS payload: %s", e)
                res.update({'qris_state': 'draft'})
        elif provider_code == 'cod':
            res.update({
                'cod_state': 'waiting_delivery',
            })
        return res

    # === Hook: rendering values untuk frontend redirect ===
    def _get_specific_rendering_values(self, processing_values):
        """Odoo 17 signature: (processing_values: dict) -> dict."""
        res = super()._get_specific_rendering_values(processing_values) if hasattr(super(), '_get_specific_rendering_values') else {}
        # processing_values contains 'provider_code' key
        provider_code = processing_values.get('provider_code')
        if provider_code == 'qris_dinamis':
            tx_id = processing_values.get('tx_id') or processing_values.get('id') or self.id
            tx = self.browse(tx_id) if tx_id else self
            res.update({
                'qris_payload': tx.qris_payload,
                'qris_amount': tx.qris_amount,
                'qris_expires_at': tx.qris_expires_at.isoformat() if tx.qris_expires_at else None,
                'qris_amount_display': tx._format_rupiah(),
                'tx_reference': tx.reference,
                'tx_id': tx.id,
            })
        elif provider_code == 'cod':
            tx_id = processing_values.get('tx_id') or processing_values.get('id') or self.id
            tx = self.browse(tx_id) if tx_id else self
            res.update({
                'cod_instructions': tx.provider_id.cod_instructions or '',
                'tx_reference': tx.reference,
                'tx_id': tx.id,
            })
        return res

    def _get_specific_processing_values(self, processing_values):
        """Include tx_id in processing values so frontend can use it for redirect."""
        res = super()._get_specific_processing_values(processing_values) if hasattr(super(), '_get_specific_processing_values') else {}
        res['tx_id'] = self.id
        return res

    def _format_rupiah(self):
        """Format Rp 50.000 dari qris_amount string (exact integer)."""
        if not self.qris_amount:
            return ''
        try:
            main = int(self.qris_amount)
        except (ValueError, TypeError):
            return self.qris_amount
        return f"Rp {main:,.0f}".replace(',', '.')

    # Pindah ke method baru tanpa suffix
    def _format_rupiah_with_suffix(self):
        """Backward-compat wrapper."""
        return self._format_rupiah()

    # === Compute QR image dari payload ===
    def _compute_qris_qr_image(self):
        for tx in self:
            if not tx.qris_payload or qrcode is None:
                tx.qris_qr_image = False
                continue
            try:
                qr = qrcode.QRCode(
                    version=None,
                    error_correction=qrcode.constants.ERROR_CORRECT_M,
                    box_size=10,
                    border=2,
                )
                qr.add_data(tx.qris_payload)
                qr.make(fit=True)
                img = qr.make_image(fill_color="black", back_color="white")
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                tx.qris_qr_image = base64.b64encode(buf.getvalue())
            except Exception as e:
                _logger.error("Failed generate QR image for tx %s: %s", tx.reference, e)
                tx.qris_qr_image = False

    # === Action: USER klik "Saya sudah bayar" ===
    def action_qris_user_confirm_paid(self):
        """User mengkonfirmasi bahwa sudah bayar. State -> pending_verification.

        Tidak ada auto-verify. Admin yang akan verifikasi manual di dashboard.
        """
        for tx in self:
            if tx.provider_id.code != 'qris_dinamis':
                continue
            if tx.qris_state not in ('pending',):
                # Hanya bisa konfirmasi kalau masih pending payment
                # (sudah konfirmasi ulang tidak boleh)
                continue
            tx.write({
                'qris_state': 'pending_verification',
                'qris_user_confirmed_at': fields.Datetime.now(),
            })
            _logger.info(
                "User confirmed payment for tx %s (amount=%s). Waiting admin verification.",
                tx.reference, tx.qris_amount,
            )

    # === Action: ADMIN verifikasi - mark as paid ===
    def action_qris_mark_paid(self, mutation_record=None):
        """Admin verifikasi: konfirmasi pembayaran QRIS valid.

        Auto-confirm sale.order + register payment.
        """
        for tx in self:
            if tx.provider_id.code != 'qris_dinamis':
                continue
            if tx.qris_state == 'paid':
                continue
            tx.write({
                'qris_state': 'paid',
                'qris_admin_verified_by': self.env.user.id,
                'qris_admin_verified_at': fields.Datetime.now(),
            })
            if mutation_record:
                tx.qris_matched_mutation_id = mutation_record.id
            try:
                tx._set_done()
            except Exception as e:
                _logger.error("Failed set_done tx %s: %s", tx.reference, e)
            tx._post_process_paid_sale_order()

    # === Action: ADMIN reject pembayaran ===
    def action_qris_reject(self, reason=''):
        """Admin menolak pembayaran. State -> rejected. Sale order di-cancel."""
        for tx in self:
            if tx.provider_id.code != 'qris_dinamis':
                continue
            if tx.qris_state == 'paid':
                continue
            tx.write({
                'qris_state': 'rejected',
                'qris_reject_reason': reason,
                'qris_admin_verified_by': self.env.user.id,
                'qris_admin_verified_at': fields.Datetime.now(),
            })
            try:
                tx._set_canceled(state_message=f'Rejected by admin: {reason}' if reason else 'Rejected by admin')
            except Exception as e:
                _logger.error("Failed cancel tx %s: %s", tx.reference, e)
            # Cancel sale order juga
            for so in tx.sale_order_ids:
                if so.state in ('draft', 'sent', 'sale'):
                    try:
                        so.action_cancel()
                    except Exception as e:
                        _logger.error("Failed cancel SO %s: %s", so.name, e)
            _logger.info("Admin rejected tx %s. Reason: %s", tx.reference, reason)

    def action_cod_mark_delivered(self):
        for tx in self:
            if tx.provider_id.code != 'cod':
                continue
            tx.cod_state = 'delivered'

    def action_cod_mark_paid(self):
        """COD: cash sudah diterima kurir. Register payment + done."""
        for tx in self:
            if tx.provider_id.code != 'cod':
                continue
            tx.cod_state = 'paid'
            try:
                tx._set_done()
            except Exception as e:
                _logger.error("Failed set_done tx %s: %s", tx.reference, e)
            tx._post_process_paid_sale_order()

    def _post_process_paid_sale_order(self):
        """Confirm sale.order + post invoice + register payment."""
        self.ensure_one()
        sale_orders = self.sale_order_ids
        if not sale_orders:
            _logger.warning("Transaction %s tidak punya sale.order", self.reference)
            return
        for so in sale_orders:
            if so.state in ['draft', 'sent']:
                try:
                    so.action_confirm()
                except Exception as e:
                    _logger.error("Failed confirm SO %s: %s", so.name, e)
            if not so.invoice_ids:
                try:
                    so._create_invoices()
                except Exception as e:
                    _logger.error("Failed create invoice SO %s: %s", so.name, e)
            for inv in so.invoice_ids:
                if inv.state == 'draft':
                    try:
                        inv.action_post()
                    except Exception as e:
                        _logger.error("Failed post invoice %s: %s", inv.name, e)
                if inv.payment_state != 'paid':
                    try:
                        self._register_payment_on_invoice(inv)
                    except Exception as e:
                        _logger.error("Failed register payment inv %s: %s", inv.name, e)

    def _register_payment_on_invoice(self, invoice):
        """Register payment ke invoice menggunakan journal yang sesuai."""
        self.ensure_one()
        journal = self.provider_id.journal_id or self.env['account.journal'].search(
            [('type', '=', 'bank'), ('company_id', '=', invoice.company_id.id)],
            limit=1,
        )
        if not journal:
            raise UserError(_("Tidak ada journal bank untuk provider %s") % self.provider_id.name)
        payment_method_line = journal.inbound_payment_method_line_ids[:1]
        if not payment_method_line:
            raise UserError(_("Journal %s tidak punya inbound payment method") % journal.name)
        payment = self.env['account.payment'].create({
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': invoice.partner_id.id,
            'amount': self.amount,
            'journal_id': journal.id,
            'payment_method_line_id': payment_method_line.id,
            'payment_reference': self.reference,
            'ref': f"QRIS/COD payment for {invoice.name}",
            'date': fields.Date.context_today(self),
        })
        payment.action_post()
        liquidity_lines = payment._seek_for_lines()[0]
        invoice.js_assign_outstanding_line(liquidity_lines.id)

    # === Cron: NO-OP sejak v17.0.2.1.0 (QRIS tidak ada expiry) ===
    @api.model
    def _cron_expire_qris_transactions(self):
        """NO-OP: QRIS tidak punya expiry lagi sejak v17.0.2.1.0.
        
        Cron tetap dipertahankan untuk backward compatibility tapi tidak melakukan apa-apa.
        Transaksi lama dengan qris_expires_at sudah lewat akan dibiarkan apa adanya
        (admin bisa reject manual di dashboard kalau perlu).
        """
        _logger.debug("QRIS expire cron dipanggil tapi QRIS tidak punya expiry (no-op).")
        return 0

    # === Polling endpoint helper: cek status untuk frontend ===
    def qris_get_status(self):
        """Return dict status untuk polling frontend."""
        self.ensure_one()
        if self.qris_state == 'paid':
            return {'state': 'paid', 'redirect_url': '/shop/payment/confirmation'}
        if self.qris_state == 'pending_verification':
            return {
                'state': 'pending_verification',
                'message': 'Menunggu verifikasi admin. Pembayaran Anda sedang diverifikasi.',
            }
        if self.qris_state == 'rejected':
            return {
                'state': 'rejected',
                'message': 'Pembayaran ditolak admin. Hubungi admin untuk info lebih lanjut.',
            }
        if self.qris_state == 'expired':
            return {'state': 'expired', 'message': 'QRIS expired. Silakan ulangi transaksi.'}
        if self.qris_state == 'cancelled':
            return {'state': 'cancelled', 'message': 'Transaksi dibatalkan.'}
        # QRIS tidak ada batas waktu lagi, tetap pending sampai user klik "saya sudah bayar"
        # atau admin verifikasi manual
        return {'state': 'pending'}
