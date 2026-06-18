# Website Sale Payment QRIS Dinamis & COD

Modul Odoo 17 untuk pembayaran website dengan **Bayar Ditempat (COD)** dan **QRIS Dinamis** dengan **verifikasi manual oleh admin** via `website_sale_dashboard`.

**Current version**: `17.0.2.1.0`

---

## Cara Kerja (Workflow Sesungguhnya)

### 1. Bayar Ditempat (COD)
- Customer pilih "Bayar Ditempat" saat checkout
- Sale order auto-confirm
- Admin deliver + terima cash + register payment via tombol "Cash Received (COD)" di kanban dashboard
- Bisa dikelola lewat kanban `website_sale_dashboard` (Sales > Orders > Website Orders)

### 2. QRIS Dinamis (Verifikasi Manual, TANPA expiry)
- Customer pilih QRIS saat checkout
- Sistem generate QRIS dinamis dengan nominal = **exact order total** (tanpa suffix unik, tanpa auto-match)
- QRIS **tidak punya batas waktu** — customer bisa scan kapan saja
- Customer scan QR dengan aplikasi e-wallet/bank apapun (GoPay, OVO, DANA, ShopeePay, m-Banking, dll)
- Customer klik tombol **"Saya Sudah Bayar"** di halaman QRIS
- State transaksi → `pending_verification`
- Admin verifikasi manual via 3 cara:
  1. Tombol di kanban `website_sale_dashboard` (Sales > Orders > Website Orders)
  2. Tombol di `sale.order` form: **Verify QRIS Payment** / **Reject QRIS Payment**
  3. Halaman standalone `/shop/payment_verifications` (list view + reject with reason)
- Cron expire **di-DISABLE** (tidak ada expiry)

### Flow Diagram
```
Customer checkout
     ↓
Pilih QRIS Dinamis
     ↓
Generate QRIS dinamis (nominal = exact order total)
     ↓
Display QR code (TANPA countdown timer)
     ↓
Customer scan & bayar via e-wallet/bank
     ↓
Customer klik "Saya Sudah Bayar"
     ↓
State → pending_verification
     ↓
Admin cek mutasi rekening / e-wallet manually
     ↓
Admin klik "Verify QRIS Payment" atau "Reject QRIS Payment"
     ↓
Verify → mark paid → confirm SO → post invoice → register payment
Reject → state kembali ke pending + kirim alasan ke customer
     ↓
Customer lihat status berubah "Pembayaran berhasil" / "Pembayaran ditolak"
```

---

## Menu di Odoo Backend

### Top-level "QRIS Payment" menu (sequence 20)
| Submenu | Fungsi |
|---|---|
| **Mutations** | List record `qris.mutation.import` (audit trail upload CSV — fitur legacy, masih ada untuk jaga-jaga volume tinggi) |
| **Upload Mutation CSV** | Wizard upload CSV mutasi bank/e-wallet untuk auto-match (alternatif kalau volume QRIS naik) |

### Verifikasi QRIS Pending
- **Sales → Orders → Website Orders** (kanban `website_sale_dashboard`): card action "Verify" / "Reject"
- **Sales → Orders → Orders** (sale.order form): tombol di header
- **Halaman standalone**: `/shop/payment_verifications` (list view + reject with reason modal)

---

## Instalasi

1. Copy folder `website_sale_payment_qris_cod` ke `addons/` Odoo (atau `/mnt/extra-addons/` di Docker)
2. Update App List
3. Install modul "Website Sale Payment QRIS Dinamis & COD"
4. Pastikan modul `website_sale_dashboard` sudah terinstall (untuk kanban verifikasi)

## Konfigurasi

1. Buka **Settings > Website > QRIS Dinamis & COD**
2. Set **Base QRIS String**:
   - Decode QR static Warung Lakku (bisa pakai https://qris-dinamis-ten.vercel.app)
   - Copy raw QRIS string, paste di field ini
   - Contoh: `00020101021126570011ID.DANA.WWW...63044E65`
3. Set **COD Instructions**: instruksi untuk customer COD (ditampilkan di halaman konfirmasi)

---

## CSV Mutation Import (Fitur Alternatif)

Modul ini juga menyediakan fitur upload CSV mutasi bank/e-wallet untuk **auto-match** pembayaran QRIS yang pending. Cocok dipakai saat:
- Volume QRIS tinggi (puluhan transaksi per hari)
- Setelah campaign besar (flash sale, promo)
- Mau audit trail rapi per batch upload

### Format CSV yang Didukung

CSV harus punya header. Kolom yang dikenali (flexible naming):

| Field | Synonyms yang diterima |
|-------|------------------------|
| Amount | `amount`, `nominal`, `jumlah`, `kredit`, `credit`, `masuk`, `value` |
| Date | `date`, `tanggal`, `tgl`, `waktu`, `time`, `datetime` |
| Description | `description`, `keterangan`, `desc`, `note`, `remark` |
| Reference | `reference`, `ref`, `no`, `number`, `id` |

### Format Amount yang Didukung

| Input | Parsed As |
|-------|-----------|
| `50000` | 50000 |
| `50000,415` | 50000.415 (Indonesian decimal) |
| `50.000,415` | 50000.415 (Indonesian thousand+decimal) |
| `50,000.415` | 50000.415 (English thousand+decimal) |
| `Rp 50.000,415` | 50000.415 (dengan prefix Rp) |

### Format Date yang Didukung

Pilih saat upload:
- `DD/MM/YYYY` (default, Indonesian)
- `YYYY-MM-DD` (ISO)
- `DD-MM-YYYY`
- `MM/DD/YYYY`

### Logic Auto-Match
1. Parse amount di setiap row CSV (handle thousand separator + decimal)
2. Cari `payment.transaction` dengan `provider_id.code = 'qris_dinamis'`, `qris_state IN ('pending', 'pending_verification')`, dan `qris_amount` exact integer match
3. Jika match: mark paid + confirm SO + register payment
4. Simpan record mutation untuk audit (`qris.mutation.import`)
5. State record: `draft` → `matched` / `unmatched` / `error`

---

## QRIS Logic Reference

Port dari https://github.com/verssache/qris-dinamis (MIT License, by Gidhan).

- CRC16-CCITT (poly 0x1021, init 0xFFFF)
- TLV parser untuk EMVCo QR
- Convert static → dynamic:
  1. Tag 01 (Point of Initiation): `11` → `12`
  2. Insert Tag 54 (Transaction Amount) sebelum Tag 58 (Country Code)
  3. Recalculate CRC16, append `6304` + 4-char CRC

---

## Struktur Modul

```
website_sale_payment_qris_cod/
├── __init__.py
├── __manifest__.py                          # v17.0.2.1.0
├── README.md
├── controllers/
│   ├── __init__.py
│   └── main.py                              # QRIS display page + polling + payment_verifications
├── data/
│   ├── payment_provider_data.xml            # Default QRIS + COD providers
│   └── ir_cron_data.xml                     # Cron (DISABLED — no expiry)
├── models/
│   ├── __init__.py
│   ├── qris_helper.py                       # Pure QRIS logic (CRC16, TLV, converter)
│   ├── payment_provider.py                  # Extend provider + config fields
│   ├── payment_transaction.py               # Generate payload, QR image, verify/reject hooks
│   ├── sale_order.py                        # Denormalized QRIS info + dashboard actions
│   ├── qris_mutation_import.py              # CSV import wizard + auto-match
│   └── res_config_settings.py               # Settings
├── security/
│   └── ir.model.access.csv
├── static/
│   ├── description/
│   │   └── icon.png
│   └── src/
│       ├── js/qris_checkout.js              # "Saya Sudah Bayar" button handler
│       └── css/qris_checkout.css
└── views/
    ├── payment_provider_views.xml
    ├── payment_transaction_views.xml
    ├── sale_order_views.xml                 # Verify/Reject QRIS buttons
    ├── qris_mutation_import_views.xml       # CSV import wizard + list
    ├── website_sale_dashboard_views.xml     # Kanban card actions
    ├── redirect_form_templates.xml          # QRIS redirect page
    ├── website_sale_payment_templates.xml   # Checkout payment templates
    └── res_config_settings_views.xml
```

---

## Dependencies

- `website_sale`
- `payment`
- `sale_management`
- `account`
- `website_sale_dashboard` (for kanban verification UI)

---

## Changelog

### 17.0.2.1.0
- **Redesigned to manual admin verification** (per workflow Warung Lakku):
  - Removed QRIS suffix 3-digit auto-match as primary flow
  - QRIS amount sekarang = exact order total (tanpa suffix)
  - QRIS TIDAK ada expiry (cron expire di-DISABLE)
  - Customer klik "Saya Sudah Bayar" → state `pending_verification`
  - Admin verify/reject via 3 UI: kanban dashboard, sale.order form, `/shop/payment_verifications`
- Added tombol "Cash Received (COD)" di kanban dashboard
- Added `/shop/payment_verifications` standalone list view with reject modal (with reason)
- CSV mutation import tetap dipertahankan sebagai fitur alternatif (untuk volume tinggi)

### 17.0.1.0.0
- Initial release
- Bayar Ditempat (COD) flow
- QRIS Dinamis dengan suffix 3 digit perak (auto-match via CSV)
- Cron expire pending transactions (5 menit)
- CSV mutation import + auto-match

---

## License

LGPL-3

## Author

Warung Lakku (https://warunglakku.com)
