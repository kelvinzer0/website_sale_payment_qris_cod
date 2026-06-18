# -*- coding: utf-8 -*-
"""qris.mutation.import - upload CSV mutasi bank/e-wallet + auto-match ke transaksi pending.

CSV format yang didukung (flexible, di-map via wizard):
  - date: DD/MM/YYYY atau YYYY-MM-DD
  - amount: numeric (positif = kredit/masuk)
  - description: text (optional)
  - reference: text (optional)

Logic match:
  1. Parse amount jadi (main, suffix) jika ada desimal
  2. Cari payment.transaction dengan provider_id.code='qris_dinamis',
     qris_state='pending', dan qris_amount yang exact match (string compare)
  3. Jika match: mark paid + confirm SO + register payment
  4. Simpan record mutation untuk audit
"""

import base64
import csv
import io
import logging
from datetime import datetime

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class QrisMutationImport(models.Model):
    _name = 'qris.mutation.import'
    _description = 'QRIS Mutation Import (CSV dari bank/e-wallet)'
    _order = 'mutation_date desc, id desc'
    _rec_name = 'display_name'

    mutation_date = fields.Datetime(
        string='Mutation Date',
        required=True,
    )
    amount = fields.Monetary(
        string='Amount',
        currency_field='currency_id',
        required=True,
    )
    amount_str = fields.Char(
        string='Amount String (raw)',
        help='Raw amount string as it appears in CSV (e.g. "50000.415" atau "50000,415").',
    )
    description = fields.Text(
        string='Description',
    )
    reference = fields.Char(
        string='Bank Reference',
    )
    raw_line = fields.Text(
        string='Raw CSV Line',
        readonly=True,
    )
    matched_transaction_id = fields.Many2one(
        'payment.transaction',
        string='Matched Transaction',
        readonly=True,
        copy=False,
    )
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('matched', 'Matched'),
            ('unmatched', 'Unmatched'),
            ('error', 'Error'),
        ],
        string='State',
        default='draft',
        tracking=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
    )
    import_batch_id = fields.Char(
        string='Import Batch',
        help='Identifier untuk batch upload yang sama.',
    )
    error_message = fields.Text(
        string='Error Message',
        readonly=True,
    )

    def name_get(self):
        result = []
        for rec in self:
            label = f"{rec.mutation_date.strftime('%Y-%m-%d %H:%M')} | {rec.amount:.2f}"
            if rec.matched_transaction_id:
                label += f" | {rec.matched_transaction_id.reference}"
            elif rec.state == 'unmatched':
                label += " | UNMATCHED"
            result.append((rec.id, label))
        return result

    # === Action: try match ke transaksi pending ===
    def action_try_match(self):
        """Coba match record ke payment.transaction QRIS yang pending."""
        for mutation in self:
            if mutation.state == 'matched':
                continue
            try:
                tx = self._find_matching_transaction(mutation)
                if tx:
                    mutation.matched_transaction_id = tx.id
                    mutation.state = 'matched'
                    tx.action_qris_mark_paid(mutation_record=mutation)
                    _logger.info(
                        "Mutation %s matched to tx %s",
                        mutation.id, tx.reference,
                    )
                else:
                    mutation.state = 'unmatched'
                    _logger.info(
                        "Mutation %s unmatched (amount=%s, raw=%s)",
                        mutation.id, mutation.amount, mutation.amount_str,
                    )
            except Exception as e:
                mutation.state = 'error'
                mutation.error_message = str(e)
                _logger.exception("Error matching mutation %s", mutation.id)

    def _find_matching_transaction(self, mutation):
        """Cari transaksi QRIS pending yang match dengan mutation.

        Flow admin-verifikasi: amount = exact integer, tidak ada suffix.
        Strategy: exact numeric match antara mutation.amount (rounded) dan
        qris_amount (string integer) transaksi pending atau pending_verification.
        """
        self.ensure_one()
        domain = [
            ('provider_id.code', '=', 'qris_dinamis'),
            ('qris_state', 'in', ['pending', 'pending_verification']),
        ]
        candidates = self.env['payment.transaction'].search(domain)

        mutation_main = int(round(mutation.amount)) if mutation.amount else 0

        # Exact integer match
        for tx in candidates:
            if not tx.qris_amount:
                continue
            try:
                tx_main = int(tx.qris_amount)
            except (ValueError, TypeError):
                continue
            if tx_main == mutation_main:
                return tx
        return None


class QrisMutationImportWizard(models.TransientModel):
    _name = 'qris.mutation.import.wizard'
    _description = 'Wizard untuk upload CSV mutasi bank'

    csv_file = fields.Binary(
        string='CSV File',
        required=True,
    )
    csv_filename = fields.Char(
        string='Filename',
    )
    date_format = fields.Selection(
        [
            ('%d/%m/%Y', 'DD/MM/YYYY'),
            ('%Y-%m-%d', 'YYYY-MM-DD'),
            ('%d-%m-%Y', 'DD-MM-YYYY'),
            ('%m/%d/%Y', 'MM/DD/YYYY'),
        ],
        string='Date Format',
        default='%d/%m/%Y',
        required=True,
    )
    delimiter = fields.Selection(
        [
            (',', 'Comma (,)'),
            (';', 'Semicolon (;)'),
            ('\t', 'Tab'),
        ],
        string='Delimiter',
        default=',',
        required=True,
    )
    state = fields.Selection(
        [('upload', 'Upload'), ('result', 'Result')],
        default='upload',
    )
    result_total = fields.Integer(
        string='Total Rows',
        readonly=True,
    )
    result_matched = fields.Integer(
        string='Matched',
        readonly=True,
    )
    result_unmatched = fields.Integer(
        string='Unmatched',
        readonly=True,
    )
    result_errors = fields.Integer(
        string='Errors',
        readonly=True,
    )

    def action_import(self):
        """Parse CSV dan create qris.mutation.import records + auto-match."""
        self.ensure_one()
        if not self.csv_file:
            raise UserError(_("Upload CSV file dulu."))
        content = base64.b64decode(self.csv_file)
        try:
            text = content.decode('utf-8-sig')  # handle BOM
        except UnicodeDecodeError:
            try:
                text = content.decode('latin-1')
            except UnicodeDecodeError as e:
                raise UserError(_("Failed decode CSV: %s") % e)

        reader = csv.DictReader(io.StringIO(text), delimiter=self.delimiter)
        if not reader.fieldnames:
            raise UserError(_("CSV kosong atau header tidak terbaca."))

        # Normalisasi header (lowercase, strip)
        fieldnames = {fn.lower().strip(): fn for fn in reader.fieldnames}
        # Cari kolom amount, date, description, reference (flexible)
        amount_col = None
        for candidate in ['amount', 'nominal', 'jumlah', 'kredit', 'credit', 'masuk', 'value']:
            if candidate in fieldnames:
                amount_col = fieldnames[candidate]
                break
        date_col = None
        for candidate in ['date', 'tanggal', 'tgl', 'waktu', 'time', 'datetime']:
            if candidate in fieldnames:
                date_col = fieldnames[candidate]
                break
        desc_col = None
        for candidate in ['description', 'keterangan', 'desc', 'note', 'notes', 'remark']:
            if candidate in fieldnames:
                desc_col = fieldnames[candidate]
                break
        ref_col = None
        for candidate in ['reference', 'ref', 'no', 'number', 'id']:
            if candidate in fieldnames:
                ref_col = fieldnames[candidate]
                break

        if not amount_col:
            raise UserError(_("Kolom amount tidak ditemukan. Pastikan ada kolom 'amount'/'nominal'/'jumlah'."))

        batch_id = f"BATCH-{fields.Datetime.now().strftime('%Y%m%d%H%M%S')}"
        mutation_model = self.env['qris.mutation.import']
        total = matched = unmatched = errors = 0

        for row in reader:
            total += 1
            try:
                amount_str = (row.get(amount_col) or '').strip()
                if not amount_str:
                    continue
                # Parse amount: handle thousand separator dan decimal
                # Indonesian: "50.000,415" -> 50000.415
                # English: "50,000.415" -> 50000.415
                cleaned = amount_str
                # Remove currency symbols
                for sym in ['Rp', 'rp', 'IDR', 'idr', ' ', 'Rp.']:
                    cleaned = cleaned.replace(sym, '')
                # Detect format
                if ',' in cleaned and '.' in cleaned:
                    # Both present: last one is decimal separator
                    if cleaned.rfind(',') > cleaned.rfind('.'):
                        # Indonesian: dot is thousand sep, comma is decimal
                        cleaned = cleaned.replace('.', '').replace(',', '.')
                    else:
                        # English: comma is thousand sep, dot is decimal
                        cleaned = cleaned.replace(',', '')
                elif ',' in cleaned:
                    # Only comma: assume decimal (Indonesian)
                    cleaned = cleaned.replace(',', '.')
                # else: only dot or no separator
                try:
                    amount_float = float(cleaned)
                except ValueError:
                    errors += 1
                    mutation_model.create({
                        'mutation_date': fields.Datetime.now(),
                        'amount': 0,
                        'amount_str': amount_str,
                        'raw_line': str(row),
                        'state': 'error',
                        'error_message': f"Cannot parse amount: {amount_str}",
                        'import_batch_id': batch_id,
                    })
                    continue

                # Parse date
                date_str = (row.get(date_col) or '').strip() if date_col else ''
                mutation_date = fields.Datetime.now()
                if date_str:
                    for fmt in [self.date_format, '%d/%m/%Y %H:%M', '%Y-%m-%d %H:%M:%S', '%d-%m-%Y %H:%M']:
                        try:
                            dt = datetime.strptime(date_str, fmt)
                            mutation_date = fields.Datetime.to_datetime(dt)
                            break
                        except ValueError:
                            continue

                description = (row.get(desc_col) or '').strip() if desc_col else ''
                reference = (row.get(ref_col) or '').strip() if ref_col else ''

                mutation = mutation_model.create({
                    'mutation_date': mutation_date,
                    'amount': amount_float,
                    'amount_str': amount_str,
                    'description': description,
                    'reference': reference,
                    'raw_line': str(row),
                    'state': 'draft',
                    'import_batch_id': batch_id,
                })
                mutation.action_try_match()
                if mutation.state == 'matched':
                    matched += 1
                elif mutation.state == 'unmatched':
                    unmatched += 1
                else:
                    errors += 1
            except Exception as e:
                errors += 1
                _logger.exception("Error processing row: %s", row)
                mutation_model.create({
                    'mutation_date': fields.Datetime.now(),
                    'amount': 0,
                    'amount_str': '',
                    'raw_line': str(row),
                    'state': 'error',
                    'error_message': str(e),
                    'import_batch_id': batch_id,
                })

        self.write({
            'state': 'result',
            'result_total': total,
            'result_matched': matched,
            'result_unmatched': unmatched,
            'result_errors': errors,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Import Result'),
            'res_model': 'qris.mutation.import.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_view_mutations(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Mutations'),
            'res_model': 'qris.mutation.import',
            'view_mode': 'tree,form',
            'domain': [('import_batch_id', '=', self.import_batch_id)] if hasattr(self, 'import_batch_id') else [],
            'target': 'current',
        }
