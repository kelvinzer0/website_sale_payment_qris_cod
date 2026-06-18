/* QRIS Checkout - polling status + tombol "Saya sudah bayar"
 * Berjalan di halaman /payment/qris_dinamis/<tx_id>
 *
 * NOTE: Sejak v17.0.2.1.0, QRIS TIDAK punya batas waktu (no expiry/countdown).
 *       Admin verifikasi manual di dashboard.
 *
 * Flow:
 *   - state=pending: tampilkan QR + tombol "Saya sudah bayar"
 *   - state=pending_verification: tampilkan "menunggu verifikasi admin" (page berbeda, JS tetap poll)
 *   - state=paid: redirect ke confirmation
 *   - state=rejected: tampilkan rejected
 */
(function () {
    'use strict';

    function initQrisCheckout() {
        var qrWrapper = document.querySelector('.qris-qr-wrapper');
        // Juga handle page pending_verification (tidak ada .qris-qr-wrapper)
        var pendingVerificationPage = document.getElementById('qris-pending-verification');
        if (!qrWrapper && !pendingVerificationPage) {
            // Not on QRIS payment page, skip
            return;
        }

        // Extract transaction ID from URL: /payment/qris_dinamis/<tx_id>
        var match = window.location.pathname.match(/\/payment\/qris_dinamis\/(\d+)/);
        if (!match) {
            console.error('QRIS: Transaction ID not found in URL');
            return;
        }
        var txId = parseInt(match[1], 10);

        var pollInterval = 5000; // 5 seconds (lebih lama karena admin verifikasi manual)
        var pollTimer = null;

        function showStatus(state, message) {
            var box = document.getElementById('qris-status-box');
            if (!box) return;
            box.className = 'qris-status-box ' + state;
            box.innerHTML = '<span>' + message + '</span>';
        }

        function pollStatus() {
            if (!txId) return;
            fetch('/payment/qris_dinamis/status/' + txId, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                body: JSON.stringify({}),
                credentials: 'same-origin',
            }).then(function (response) {
                if (!response.ok) throw new Error('HTTP ' + response.status);
                return response.json();
            }).then(function (data) {
                if (data.state === 'paid') {
                    showStatus('paid', 'Pembayaran berhasil! Mengalihkan...');
                    setTimeout(function () {
                        window.location.href = '/shop/payment/confirmation';
                    }, 1500);
                    return;
                }
                if (data.state === 'pending_verification') {
                    // Redirect ke page pending_verification (admin akan verify)
                    if (!pendingVerificationPage) {
                        // Halaman masih di QR page, reload supaya pindah ke pending_verification page
                        window.location.reload();
                        return;
                    }
                    showStatus('pending_verification', data.message || 'Menunggu verifikasi admin...');
                    pollTimer = setTimeout(pollStatus, pollInterval);
                    return;
                }
                if (data.state === 'rejected') {
                    showStatus('rejected', data.message || 'Pembayaran ditolak admin.');
                    setTimeout(function () { window.location.reload(); }, 2000);
                    return;
                }
                if (data.state === 'expired') {
                    showStatus('expired', data.message || 'QRIS expired.');
                    setTimeout(function () { window.location.reload(); }, 2000);
                    return;
                }
                if (data.state === 'cancelled') {
                    showStatus('cancelled', data.message || 'Transaksi dibatalkan.');
                    setTimeout(function () { window.location.reload(); }, 2000);
                    return;
                }
                // Still pending, schedule next poll
                pollTimer = setTimeout(pollStatus, pollInterval);
            }).catch(function () {
                // Retry after longer delay on error
                pollTimer = setTimeout(pollStatus, pollInterval * 2);
            });
        }

        // Handle tombol "Saya sudah bayar" - konfirmasi via form submit
        var confirmBtn = document.getElementById('qris-confirm-paid-btn');
        var confirmForm = document.getElementById('qris-confirm-form');
        if (confirmBtn && confirmForm) {
            confirmBtn.addEventListener('click', function (e) {
                e.preventDefault();
                if (!confirm('Konfirmasi bahwa Anda sudah melakukan pembayaran QRIS?\n\nAdmin akan memverifikasi pembayaran Anda.')) {
                    return;
                }
                confirmBtn.disabled = true;
                confirmBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Mengirim konfirmasi...';
                confirmForm.submit();
            });
        }

        // Start polling
        pollTimer = setTimeout(pollStatus, pollInterval);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initQrisCheckout);
    } else {
        initQrisCheckout();
    }
})();
