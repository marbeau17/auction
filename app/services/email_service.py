"""Email service for invoice delivery."""

from __future__ import annotations
import io
import smtplib
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional
from uuid import UUID

import structlog

from app.config import get_settings

logger = structlog.get_logger()


class EmailService:
    """Sends invoice emails with PDF attachments."""

    def __init__(self, supabase_client=None):
        self.supabase = supabase_client
        settings = get_settings()
        self.smtp_host = settings.smtp_host
        self.smtp_port = settings.smtp_port
        self.smtp_user = settings.smtp_user
        self.smtp_password = settings.smtp_password
        self.from_email = settings.from_email
        self.from_name = settings.from_name
        self.dry_run = settings.email_dry_run

    async def send_invoice_email(
        self,
        recipient_email: str,
        invoice_data: dict,
        pdf_bytes: Optional[bytes] = None,
        subject: Optional[str] = None,
    ) -> dict:
        """Send an invoice email with optional PDF attachment.

        Args:
            recipient_email: Recipient email address
            invoice_data: Invoice dict with number, amount, period, etc.
            pdf_bytes: PDF file content (optional)
            subject: Custom email subject (optional)

        Returns:
            Email log record dict
        """
        invoice_number = invoice_data.get("invoice_number", "N/A")
        billing_period = invoice_data.get("billing_period_start", "")
        total_amount = invoice_data.get("total_amount", 0)

        if not subject:
            subject = f"【請求書】{invoice_number} - {billing_period}分"

        # Build email body
        body_html = self._build_invoice_email_body(invoice_data)
        body_text = self._build_invoice_email_text(invoice_data)

        # Log the attempt
        log_data = {
            "invoice_id": invoice_data.get("id"),
            "recipient_email": recipient_email,
            "subject": subject,
            "body_text": body_text,
            "status": "queued",
        }

        if self.supabase:
            log_result = self.supabase.table("email_logs").insert(log_data).execute()
            log_id = log_result.data[0]["id"] if log_result.data else None
        else:
            log_id = None

        # Send
        try:
            if self.dry_run:
                logger.info(
                    "email_dry_run",
                    to=recipient_email,
                    subject=subject,
                    invoice=invoice_number,
                    amount=total_amount,
                )
                status = "sent"
                error_msg = None
            else:
                self._send_smtp(recipient_email, subject, body_text, body_html, pdf_bytes, invoice_number)
                status = "sent"
                error_msg = None

        except Exception as e:
            logger.error("email_send_failed", error=str(e), to=recipient_email)
            status = "failed"
            error_msg = str(e)

        # Update log
        if self.supabase and log_id:
            update_data = {"status": status}
            if status == "sent":
                update_data["sent_at"] = datetime.utcnow().isoformat()
            if error_msg:
                update_data["error_message"] = error_msg
            self.supabase.table("email_logs").update(update_data).eq("id", log_id).execute()

        return {
            "log_id": log_id,
            "status": status,
            "error_message": error_msg,
            "recipient": recipient_email,
        }

    def _send_smtp(
        self,
        to_email: str,
        subject: str,
        body_text: str,
        body_html: str,
        pdf_bytes: Optional[bytes],
        invoice_number: str,
    ):
        """Send email via SMTP."""
        msg = MIMEMultipart("mixed")
        msg["From"] = f"{self.from_name} <{self.from_email}>"
        msg["To"] = to_email
        msg["Subject"] = subject

        # Body (prefer HTML)
        body_part = MIMEMultipart("alternative")
        body_part.attach(MIMEText(body_text, "plain", "utf-8"))
        body_part.attach(MIMEText(body_html, "html", "utf-8"))
        msg.attach(body_part)

        # PDF attachment
        if pdf_bytes:
            pdf_attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
            pdf_attachment.add_header(
                "Content-Disposition",
                "attachment",
                filename=f"invoice_{invoice_number}.pdf"
            )
            msg.attach(pdf_attachment)

        with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
            if self.smtp_port == 587:
                server.starttls()
            if self.smtp_user and self.smtp_password:
                server.login(self.smtp_user, self.smtp_password)
            server.send_message(msg)

    def _build_invoice_email_body(self, invoice_data: dict) -> str:
        """Build HTML email body for invoice."""
        return f"""
        <html>
        <body style="font-family: 'Hiragino Sans', sans-serif; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #1a365d;">請求書のお知らせ</h2>
            <p>いつもお世話になっております。</p>
            <p>下記の通り、請求書を送付いたします。</p>

            <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
                <tr>
                    <td style="padding: 8px; border: 1px solid #ddd; background: #f7f7f7; width: 30%;"><strong>請求書番号</strong></td>
                    <td style="padding: 8px; border: 1px solid #ddd;">{invoice_data.get('invoice_number', '')}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border: 1px solid #ddd; background: #f7f7f7;"><strong>請求期間</strong></td>
                    <td style="padding: 8px; border: 1px solid #ddd;">{invoice_data.get('billing_period_start', '')} ～ {invoice_data.get('billing_period_end', '')}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border: 1px solid #ddd; background: #f7f7f7;"><strong>請求金額（税込）</strong></td>
                    <td style="padding: 8px; border: 1px solid #ddd; font-size: 1.2em; font-weight: bold;">¥{invoice_data.get('total_amount', 0):,}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border: 1px solid #ddd; background: #f7f7f7;"><strong>お支払期日</strong></td>
                    <td style="padding: 8px; border: 1px solid #ddd;">{invoice_data.get('due_date', '')}</td>
                </tr>
            </table>

            <p>添付のPDFファイルをご確認ください。</p>
            <p>ご不明な点がございましたら、お気軽にお問い合わせください。</p>

            <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">
            <p style="font-size: 0.9em; color: #999;">
                このメールはCVLPOS請求管理システムから自動送信されています。<br>
                株式会社カーチスロジテック
            </p>
        </div>
        </body>
        </html>
        """

    def _build_invoice_email_text(self, invoice_data: dict) -> str:
        """Build plain text email body."""
        return f"""
請求書のお知らせ

いつもお世話になっております。
下記の通り、請求書を送付いたします。

請求書番号: {invoice_data.get('invoice_number', '')}
請求期間: {invoice_data.get('billing_period_start', '')} ～ {invoice_data.get('billing_period_end', '')}
請求金額（税込）: ¥{invoice_data.get('total_amount', 0):,}
お支払期日: {invoice_data.get('due_date', '')}

添付のPDFファイルをご確認ください。
ご不明な点がございましたら、お気軽にお問い合わせください。

---
CVLPOS 請求管理システム
株式会社カーチスロジテック
        """.strip()

    def generate_invoice_pdf_html(self, invoice_data: dict) -> str:
        """Generate invoice PDF as HTML (for WeasyPrint conversion)."""
        line_items = invoice_data.get("line_items", [])

        items_html = ""
        for item in line_items:
            items_html += f"""
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;">{item.get('description', '')}</td>
                <td style="padding: 8px; border: 1px solid #ddd; text-align: center;">{item.get('quantity', 1)}</td>
                <td style="padding: 8px; border: 1px solid #ddd; text-align: right;">¥{item.get('unit_price', 0):,}</td>
                <td style="padding: 8px; border: 1px solid #ddd; text-align: right;">¥{item.get('amount', 0):,}</td>
            </tr>
            """

        return f"""<!DOCTYPE html>
<html lang="ja">
<head><meta charset="UTF-8">
<style>
    @page {{ size: A4; margin: 2cm; }}
    body {{ font-family: 'Hiragino Sans', sans-serif; font-size: 11pt; color: #333; }}
    h1 {{ text-align: center; font-size: 24pt; margin-bottom: 30px; }}
    .invoice-header {{ display: flex; justify-content: space-between; margin-bottom: 30px; }}
    .invoice-meta td {{ padding: 4px 12px; }}
    table.items {{ width: 100%; border-collapse: collapse; }}
    table.items th {{ background: #1a365d; color: white; padding: 10px; text-align: left; }}
    .totals {{ margin-top: 20px; text-align: right; }}
    .totals table {{ margin-left: auto; }}
    .totals td {{ padding: 6px 15px; }}
    .total-row {{ font-size: 1.3em; font-weight: bold; border-top: 2px solid #333; }}
    .stamp-area {{ margin-top: 50px; text-align: right; }}
    .stamp-box {{ display: inline-block; width: 80px; height: 80px; border: 1px solid #ccc; text-align: center; line-height: 80px; color: #ccc; }}
</style>
</head>
<body>
<h1>請 求 書</h1>

<div class="invoice-header">
    <div>
        <p style="font-size: 14pt; font-weight: bold;">御中</p>
    </div>
    <div>
        <table class="invoice-meta">
            <tr><td>請求書番号:</td><td><strong>{invoice_data.get('invoice_number', '')}</strong></td></tr>
            <tr><td>発行日:</td><td>{datetime.now().strftime('%Y年%m月%d日')}</td></tr>
            <tr><td>お支払期日:</td><td>{invoice_data.get('due_date', '')}</td></tr>
        </table>
    </div>
</div>

<p>下記の通りご請求申し上げます。</p>

<div style="background: #f0f4f8; padding: 15px; border-radius: 5px; text-align: center; font-size: 18pt; margin: 20px 0;">
    ご請求金額: <strong>¥{invoice_data.get('total_amount', 0):,}</strong>（税込）
</div>

<p>請求期間: {invoice_data.get('billing_period_start', '')} ～ {invoice_data.get('billing_period_end', '')}</p>

<table class="items">
    <thead>
        <tr>
            <th>項目</th>
            <th style="text-align: center; width: 80px;">数量</th>
            <th style="text-align: right; width: 120px;">単価</th>
            <th style="text-align: right; width: 120px;">金額</th>
        </tr>
    </thead>
    <tbody>
        {items_html}
    </tbody>
</table>

<div class="totals">
    <table>
        <tr><td>小計:</td><td style="text-align: right;">¥{invoice_data.get('subtotal', 0):,}</td></tr>
        <tr><td>消費税 ({int(float(invoice_data.get('tax_rate', 0.1)) * 100)}%):</td><td style="text-align: right;">¥{invoice_data.get('tax_amount', 0):,}</td></tr>
        <tr class="total-row"><td>合計:</td><td style="text-align: right;">¥{invoice_data.get('total_amount', 0):,}</td></tr>
    </table>
</div>

<div class="stamp-area">
    <p>株式会社カーチスロジテック</p>
    <div class="stamp-box">印</div>
</div>

<div style="margin-top: 40px; font-size: 9pt; color: #999; border-top: 1px solid #eee; padding-top: 10px;">
    <p>お振込先: [銀行名] [支店名] [口座種別] [口座番号]</p>
    <p>※振込手数料はお客様のご負担でお願いいたします。</p>
</div>
</body>
</html>"""
