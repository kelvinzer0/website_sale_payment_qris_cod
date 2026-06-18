# Website Sale Payment QRIS Dinamis & COD

Modul Odoo 17 untuk pembayaran website dengan **Bayar Ditempat (COD)** dan **QRIS Dinamis** dengan suffix 3 digit perak untuk auto-verification.

## Fitur Utama

### 1. Bayar Ditempat (COD)
- Customer pilih "Bayar Ditempat" saat checkout
- Sale order auto-confirm
- Admin deliver + terima cash + register payment via tombol "Cash Received (COD)"

### 2. QRIS Dinamis dengan Suffix 3 Digit Perak
- Customer pilih "QRIS Dinamis" saat checkout
- Sistem generate QRIS dinamis dengan nominal unik:
  - Total order + suffix random 3 digit perak (001-999)
  - Contoh: Order Rp 50.000 + suffix 415 = **Rp 50.415**
  - Suffix disimpan di `payment.transaction`, tidak boleh duplikat dengan order lain yang masih pending
- Customer scan QR dengan aplikasi e-wallet/bank apapun (GoPay, OVO, DANA, ShopeePay, m-Banking, dll)
- Admin upload CSV mutasi bank/e-wallet
- Sistem **auto-match** nominal yang persis sama dengan `qris_amount` di transaksi
- Sale order auto-confirm + invoice posted + payment registered

## Cara Kerja Auto-Verification

```
Customer checkout
     ↓
Pilih QRIS Dinamis
     ↓
Generate suffix unik (001-999)
     ↓
Generate QRIS dinamis: total + .suffix
     ↓
Display QR code + countdown timer (default 15 menit)
     ↓
Customer scan & bayar via e-wallet/bank
     ↓
[Cron job tiap 5 menit: expire pending yang lewat deadline]
     ↓
Admin download mutasi dari bank/e-wallet (CSV)
     ↓
Upload CSV via menu QRIS Payment > Upload Mutation CSV
     ↓
Sistem auto-match nominal (exact string compare)
     ↓
Match found → mark paid → confirm SO → post invoice → register payment
     ↓
Customer lihat status berubah "Pembayaran berhasil"
```

## Instalasi

1. Copy folder `website_sale_payment_qris_cod` ke `addons/` Odoo
2. Update App List
3. Install modul "Website Sale Payment QRIS Dinamis & COD"

## Konfigurasi

1. Buka **Settings > Website > QRIS Dinamis & COD**
2. Set **Base QRIS String**:
   - Decode QR static Warung Lakku (bisa pakai https://qris-dinamis-ten.vercel.app)
   - Copy raw QRIS string, paste di field ini
   - Contoh: `00020101021126570011ID.DANA.WWW...63044E65`
3. Set **QRIS Expiry (minutes)**: default 15 menit
4. Set **COD Instructions**: instruksi untuk customer COD

## Format CSV Mutasi yang Didukung

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
| `50000.415` | 50000.415 (suffix=415) |
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

## QRIS Logic Reference

Port dari https://github.com/verssache/qris-dinamis (MIT License, by Gidhan).

- CRC16-CCITT (poly 0x1021, init 0xFFFF)
- TLV parser untuk EMVCo QR
- Convert static → dynamic:
  1. Tag 01 (Point of Initiation): `11` → `12`
  2. Insert Tag 54 (Transaction Amount) sebelum Tag 58 (Country Code)
  3. Recalculate CRC16, append `6304` + 4-char CRC

## Struktur Modul

```
website_sale_payment_qris_cod/
├── __init__.py
├── __manifest__.py
├── README.md
├── controllers/
│   ├── __init__.py
│   └── main.py                    # QRIS display page + polling endpoint
├── data/
│   ├── payment_provider_data.xml  # Default QRIS + COD providers
│   └── ir_cron_data.xml          # Cron expire pending QRIS
├── models/
│   ├── __init__.py
│   ├── qris_helper.py            # Pure QRIS logic (CRC16, TLV, converter)
│   ├── payment_provider.py       # Extend provider + config fields
│   ├── payment_transaction.py    # Generate suffix, payload, QR image, auto-confirm
│   ├── sale_order.py             # Denormalized QRIS info
│   ├── qris_mutation_import.py   # CSV import + auto-match
│   └── res_config_settings.py    # Settings
├── security/
│   └── ir.model.access.csv
├── static/
│   ├── description/
│   │   └── icon.png
│   └── src/
│       ├── js/qris_checkout.js   # Polling + countdown timer
│       └── css/qris_checkout.css
└── views/
    ├── payment_provider_views.xml
    ├── payment_transaction_views.xml
    ├── sale_order_views.xml
    ├── qris_mutation_import_views.xml
    ├── res_config_settings_views.xml
    └── website_sale_payment_templates.xml
```

## Dependencies

- `website_sale`
- `payment`
- `sale_management`
- `account`

## License

LGPL-3

## Author

Warung Lakku (https://warunglakku.com)

## Changelog

### 17.0.1.0.0
- Initial release
- Bayar Ditempat (COD) flow
- QRIS Dinamis dengan suffix 3 digit perak
- CSV mutation import + auto-match
- Cron expire pending transactions (5 menit)
