# -*- coding: utf-8 -*-
"""Controllers untuk QRIS checkout page + polling status + user confirm + admin verify."""

import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class QrisCheckoutController(http.Controller):

    @http.route('/payment/qris_dinamis/<int:tx_id>', type='http', auth='public', website=True)
    def qris_payment_page(self, tx_id, **kwargs):
        """Halaman QRIS display dengan QR code + tombol 'Saya sudah bayar'.

        Flow:
          - state=pending: tampilkan QR + tombol 'Saya sudah bayar'
          - state=pending_verification: tampilkan 'menunggu verifikasi admin'
          - state=paid: redirect ke confirmation
          - state=expired: tampilkan expired page
          - state=rejected: tampilkan rejected page
        """
        tx = request.env['payment.transaction'].sudo().browse(tx_id)
        if not tx.exists():
            return request.not_found()
        if tx.provider_id.code != 'qris_dinamis':
            return request.not_found()

        # If already paid, redirect to confirmation
        if tx.qris_state == 'paid':
            return request.redirect('/shop/payment/confirmation')
        if tx.qris_state == 'expired':
            return request.render('website_sale_payment_qris_cod.qris_expired', {
                'tx': tx,
            })
        if tx.qris_state == 'rejected':
            return request.render('website_sale_payment_qris_cod.qris_rejected', {
                'tx': tx,
            })
        if tx.qris_state == 'cancelled':
            return request.render('website_sale_payment_qris_cod.qris_cancelled', {
                'tx': tx,
            })

        # pending_verification: tampilkan page 'menunggu verifikasi admin'
        if tx.qris_state == 'pending_verification':
            values = {
                'tx': tx,
                'qris_amount': tx.qris_amount,
                'qris_amount_display': tx._format_rupiah(),
                'tx_reference': tx.reference,
            }
            return request.render('website_sale_payment_qris_cod.qris_pending_verification', values)

        # Default: state=pending, tampilkan QR + tombol bayar
        values = {
            'tx': tx,
            'qris_payload': tx.qris_payload,
            'qris_amount': tx.qris_amount,
            'qris_amount_display': tx._format_rupiah(),
            'qris_expires_at': tx.qris_expires_at,
            'qris_qr_image': tx.qris_qr_image,
            'tx_reference': tx.reference,
        }
        return request.render('website_sale_payment_qris_cod.qris_payment_page', values)

    @http.route('/payment/qris_dinamis/confirm/<int:tx_id>', type='http', auth='public', website=True, methods=['POST', 'GET'], csrf=False)
    def qris_user_confirm_paid(self, tx_id, **kwargs):
        """User klik tombol 'Saya sudah bayar'.
        Set state -> pending_verification. Tidak ada auto-verify.

        csrf=False karena:
          - Route bisa diakses customer yang belum login (auth='public')
          - Action terbatas: hanya mark state -> pending_verification
            (tidak ada financial impact, admin tetap verifikasi manual)
          - Customer tidak bisa konfirmasi tx milik customer lain
            (route hanya mark tx dengan tx_id spesifik)
        """
        tx = request.env['payment.transaction'].sudo().browse(tx_id)
        if not tx.exists():
            return request.not_found()
        if tx.provider_id.code != 'qris_dinamis':
            return request.not_found()
        if tx.qris_state != 'pending':
            # Sudah confirm / sudah paid / expired -> redirect ke page utama
            return request.redirect('/payment/qris_dinamis/%d' % tx_id)
        try:
            tx.action_qris_user_confirm_paid()
        except Exception as e:
            _logger.exception("Error when user confirm paid tx %s: %s", tx.reference, e)
        return request.redirect('/payment/qris_dinamis/%d' % tx_id)

    @http.route('/payment/qris_dinamis/status/<int:tx_id>', type='json', auth='public', website=True)
    def qris_payment_status(self, tx_id, **kwargs):
        """JSON polling endpoint untuk cek status pembayaran."""
        tx = request.env['payment.transaction'].sudo().browse(tx_id)
        if not tx.exists():
            return {'state': 'error', 'message': 'Transaction not found'}
        return tx.qris_get_status()

    @http.route('/payment/cod/<int:tx_id>', type='http', auth='public', website=True)
    def cod_payment_page(self, tx_id, **kwargs):
        """Halaman COD confirmation."""
        tx = request.env['payment.transaction'].sudo().browse(tx_id)
        if not tx.exists():
            return request.not_found()
        if tx.provider_id.code != 'cod':
            return request.not_found()
        # Auto-confirm sale order for COD
        sale_orders = tx.sale_order_ids
        for so in sale_orders:
            if so.state in ['draft', 'sent']:
                so.action_confirm()
        values = {
            'tx': tx,
            'sale_order': sale_orders[:1],
            'cod_instructions': tx.provider_id.cod_instructions or '',
        }
        return request.render('website_sale_payment_qris_cod.cod_payment_page', values)

    @http.route('/payment/qris_dinamis/cancel/<int:tx_id>', type='http', auth='public', website=True)
    def qris_cancel(self, tx_id, **kwargs):
        """Customer cancel QRIS payment."""
        tx = request.env['payment.transaction'].sudo().browse(tx_id)
        if not tx.exists():
            return request.not_found()
        if tx.qris_state == 'pending':
            tx.qris_state = 'cancelled'
            try:
                tx._set_canceled(state_message='Cancelled by customer')
            except Exception as e:
                _logger.error("Failed cancel tx %s: %s", tx.reference, e)
        return request.redirect('/shop/cart')

    # ============================================================
    # ADMIN VERIFICATION DASHBOARD (web frontend, /shop/payment_verifications)
    # Bisa diakses admin (group sales_team.group_sale_manager atau website designer).
    # Alternatif flow selain tombol di kanban website_sale_dashboard.
    # ============================================================

    def _check_admin_access(self):
        """Pastikan user login + punya group admin."""
        if not request.env.user or request.env.user._is_public():
            return False
        return (request.env.user.has_group('sales_team.group_sale_manager')
                or request.env.user.has_group('website.group_website_designer'))

    @http.route('/shop/payment_verifications', type='http', auth='user', website=True)
    def admin_payment_verifications(self, **kwargs):
        """Halaman dashboard frontend: list QRIS pending_verification + COD waiting."""
        if not self._check_admin_access():
            return request.redirect('/web/login?redirect=/shop/payment_verifications')

        tx_model = request.env['payment.transaction'].sudo()

        # QRIS pending verification (user sudah klik "saya sudah bayar")
        qris_pending = tx_model.search([
            ('provider_id.code', '=', 'qris_dinamis'),
            ('qris_state', '=', 'pending_verification'),
        ], order='qris_user_confirmed_at desc')

        # QRIS pending (user belum klik "saya sudah bayar") — info saja
        qris_pending_payment = tx_model.search([
            ('provider_id.code', '=', 'qris_dinamis'),
            ('qris_state', '=', 'pending'),
        ], order='create_date desc')

        # COD waiting delivery
        cod_waiting = tx_model.search([
            ('provider_id.code', '=', 'cod'),
            ('cod_state', '=', 'waiting_delivery'),
        ], order='create_date desc')

        # Recent verified (paid atau rejected) - 20 terbaru
        recent_verified = tx_model.search([
            '|',
            ('qris_state', 'in', ('paid', 'rejected')),
            ('cod_state', 'in', ('delivered', 'paid')),
        ], order='qris_admin_verified_at desc, write_date desc', limit=20)

        values = {
            'qris_pending': qris_pending,
            'qris_pending_payment': qris_pending_payment,
            'cod_waiting': cod_waiting,
            'recent_verified': recent_verified,
        }
        return request.render('website_sale_payment_qris_cod.qris_admin_verification_dashboard', values)

    @http.route('/shop/payment_verifications/<int:tx_id>/verify',
                type='http', auth='user', website=True, methods=['POST'])
    def admin_verify_qris(self, tx_id, **kwargs):
        """Admin verify QRIS paid dari standalone dashboard."""
        if not self._check_admin_access():
            return request.redirect('/web/login')
        tx = request.env['payment.transaction'].sudo().browse(tx_id)
        if not tx.exists() or tx.provider_id.code != 'qris_dinamis':
            return request.not_found()
        try:
            tx.action_qris_mark_paid()
        except Exception as e:
            _logger.exception("Admin verify failed for tx %s: %s", tx.reference, e)
        return request.redirect('/shop/payment_verifications')

    @http.route('/shop/payment_verifications/<int:tx_id>/reject',
                type='http', auth='user', website=True, methods=['POST'])
    def admin_reject_qris(self, tx_id, **kwargs):
        """Admin reject QRIS dari standalone dashboard (dengan reason)."""
        if not self._check_admin_access():
            return request.redirect('/web/login')
        tx = request.env['payment.transaction'].sudo().browse(tx_id)
        if not tx.exists() or tx.provider_id.code != 'qris_dinamis':
            return request.not_found()
        reason = kwargs.get('reason', '').strip() or 'Ditolak admin dari dashboard'
        try:
            tx.action_qris_reject(reason=reason)
        except Exception as e:
            _logger.exception("Admin reject failed for tx %s: %s", tx.reference, e)
        return request.redirect('/shop/payment_verifications')

    @http.route('/shop/payment_verifications/cod/<int:tx_id>/delivered',
                type='http', auth='user', website=True, methods=['POST'])
    def admin_cod_mark_delivered(self, tx_id, **kwargs):
        """Admin mark COD order delivered dari standalone dashboard."""
        if not self._check_admin_access():
            return request.redirect('/web/login')
        tx = request.env['payment.transaction'].sudo().browse(tx_id)
        if not tx.exists() or tx.provider_id.code != 'cod':
            return request.not_found()
        try:
            tx.action_cod_mark_delivered()
        except Exception as e:
            _logger.exception("Admin mark delivered failed for tx %s: %s", tx.reference, e)
        return request.redirect('/shop/payment_verifications')
