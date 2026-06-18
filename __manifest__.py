# -*- coding: utf-8 -*-
{
    'name': 'Website Sale Payment QRIS Dinamis & COD',
    'version': '17.0.2.1.1',
    'category': 'Website/Website',
    'summary': 'Bayar Ditempat (COD) + QRIS Dinamis dengan verifikasi manual admin via website_sale_dashboard',
    'description': """
Website Sale Payment QRIS Dinamis & COD
========================================

Modul pembayaran website untuk Odoo 17 dengan 2 metode:

1. Bayar Ditempat (COD)
   - Customer pilih COD di checkout
   - Sale order auto-confirm
   - Admin deliver + terima cash + register payment
   - Bisa dikelola lewat kanban website_sale_dashboard

2. QRIS Dinamis (verifikasi manual oleh admin, TANPA expiry)
   - Customer pilih QRIS di checkout
   - Sistem generate QRIS dinamis dengan nominal = exact order total
     (tidak ada suffix unik, tidak ada auto-match)
   - QRIS TIDAK punya batas waktu (customer bisa scan kapan saja)
   - Customer scan QR dengan aplikasi e-wallet/bank apapun
   - Customer klik tombol "Saya Sudah Bayar" di halaman QRIS
   - State transaksi -> pending_verification
   - Admin verifikasi manual via:
     * Tombol di kanban website_sale_dashboard (Sales > Orders > Website Orders)
     * Tombol di sale.order form (Verify QRIS Payment / Reject QRIS Payment)
     * Halaman standalone /shop/payment_verifications (list view + reject w/ reason)
   - Cron expire di-DISABLE (tidak ada expiry)

Reference: github.com/versfache/qris-dinamis (port CRC16 + TLV parser)
QRIS Logic: TLV parser + CRC16-CCITT (poly 0x1021, init 0xFFFF)

Config:
   - Settings > Website > QRIS Dinamis Settings
   - Set Base QRIS string (decoded dari QR static Warung Lakku)
   - Set COD instructions
""",
    'author': 'Warung Lakku',
    'website': 'https://warunglakku.com',
    'license': 'LGPL-3',
    'depends': [
        'website_sale',
        'payment',
        'sale_management',
        'account',
        'website_sale_dashboard',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/payment_provider_data.xml',
        'data/ir_cron_data.xml',
        'views/payment_provider_views.xml',
        'views/res_config_settings_views.xml',
        'views/payment_transaction_views.xml',
        'views/sale_order_views.xml',
        'views/website_sale_dashboard_views.xml',
        'views/qris_mutation_import_views.xml',
        'views/redirect_form_templates.xml',
        'views/website_sale_payment_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'website_sale_payment_qris_cod/static/src/js/qris_checkout.js',
            'website_sale_payment_qris_cod/static/src/css/qris_checkout.css',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
