"""
Generates an HTML newsletter from simulated thesis portfolios + watchlist data,
and sends it via SMTP.
"""

import os
import smtplib
from datetime import date
from typing import Optional
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background:#f4f6f8; margin:0; padding:20px; color:#222; }}
  .card {{ background:#fff; border-radius:8px; padding:24px; margin-bottom:16px;
           box-shadow:0 1px 4px rgba(0,0,0,.08); }}
  h1 {{ margin:0 0 4px; font-size:22px; color:#1a1a2e; }}
  h2 {{ margin:0 0 16px; font-size:17px; color:#1a1a2e; }}
  .date {{ color:#888; font-size:13px; margin-bottom:20px; }}
  .kpi {{ display:flex; gap:24px; flex-wrap:wrap; margin-bottom:4px; }}
  .kpi-item {{ flex:1; min-width:120px; }}
  .kpi-label {{ font-size:12px; text-transform:uppercase; color:#888; }}
  .kpi-value {{ font-size:24px; font-weight:700; margin:4px 0; }}
  .green {{ color:#16a34a; }} .red {{ color:#dc2626; }} .gray {{ color:#555; }}
  table {{ width:100%; border-collapse:collapse; font-size:14px; }}
  th {{ text-align:left; border-bottom:2px solid #e5e7eb; padding:8px 4px;
        color:#555; font-size:12px; text-transform:uppercase; }}
  td {{ padding:10px 4px; border-bottom:1px solid #f0f0f0; }}
  tr:last-child td {{ border-bottom:none; }}
  .badge {{ display:inline-block; padding:2px 8px; border-radius:9999px;
            font-size:12px; font-weight:600; }}
  .badge-green {{ background:#dcfce7; color:#15803d; }}
  .badge-red {{ background:#fee2e2; color:#b91c1c; }}
  .section-title {{ font-size:16px; font-weight:600; margin:0 0 12px; }}
  .thesis-header {{ display:flex; justify-content:space-between; align-items:baseline;
                    margin-bottom:12px; }}
  .thesis-meta {{ font-size:13px; color:#888; }}
  .no-data {{ color:#aaa; font-style:italic; font-size:14px; }}
  .divider {{ border:none; border-top:1px solid #e5e7eb; margin:20px 0; }}
</style>
</head>
<body>
<div class="card">
  <h1>VC, PE &amp; Public Markets Tracker</h1>
  <div class="date">{report_date}</div>
  <div class="kpi">
    <div class="kpi-item">
      <div class="kpi-label">Total Deployed</div>
      <div class="kpi-value">{total_cost}</div>
    </div>
    <div class="kpi-item">
      <div class="kpi-label">Total Value</div>
      <div class="kpi-value">{total_value}</div>
    </div>
    <div class="kpi-item">
      <div class="kpi-label">Overall Return</div>
      <div class="kpi-value {overall_class}">{overall_gain} ({overall_pct})</div>
    </div>
  </div>
</div>

{theses_html}

<div class="card">
  <div class="section-title">Watchlist</div>
  {watchlist_html}
</div>
</body>
</html>
"""

_THESIS_BLOCK = """\
<div class="card">
  <div class="thesis-header">
    <h2>{name}</h2>
    <span class="thesis-meta">since {created} &nbsp;·&nbsp;
      cost ${total_cost:,.2f} &nbsp;·&nbsp;
      value ${total_value:,.2f} &nbsp;·&nbsp;
      <span class="{return_class}">{return_sign}{total_gain_pct:.2f}%</span>
    </span>
  </div>
  {positions_html}
</div>
"""

_POSITIONS_TABLE = """\
<table>
  <thead>
    <tr>
      <th>Ticker</th><th>Shares</th><th>Entry</th>
      <th>Current</th><th>Value</th><th>Return</th><th>Days</th>
    </tr>
  </thead>
  <tbody>
    {rows}
  </tbody>
</table>
"""

_WATCHLIST_TABLE = """\
<table>
  <thead>
    <tr>
      <th>Ticker</th><th>Price</th><th>Day %</th>
      <th>P/E</th><th>52W Low</th><th>Div Yield</th>
    </tr>
  </thead>
  <tbody>
    {rows}
  </tbody>
</table>
"""


# ---------------------------------------------------------------------------
# HTML builders
# ---------------------------------------------------------------------------

def _fmt(v: float) -> str:
    return f"${v:,.2f}"


def _sign(v: float) -> str:
    return "+" if v >= 0 else ""


def _build_thesis_html(thesis: dict) -> str:
    positions = thesis["positions"]
    if not positions:
        positions_html = '<p class="no-data">No positions yet.</p>'
    else:
        rows = []
        for p in positions:
            gain = p["gain"]
            badge = "badge-green" if gain >= 0 else "badge-red"
            s = _sign(gain)
            rows.append(
                f"<tr>"
                f"<td><b>{p['ticker']}</b></td>"
                f"<td>{p['shares']:,.4f}</td>"
                f"<td>{_fmt(p['entry_price'])}</td>"
                f"<td>{_fmt(p['current_price'])}</td>"
                f"<td>{_fmt(p['value'])}</td>"
                f"<td><span class='badge {badge}'>{s}{_fmt(abs(gain))} ({s}{abs(p['gain_pct']):.2f}%)</span></td>"
                f"<td>{p['days_held']}d</td>"
                f"</tr>"
            )
        positions_html = _POSITIONS_TABLE.format(rows="\n".join(rows))

    gain = thesis["total_gain"]
    return _THESIS_BLOCK.format(
        name=thesis["name"],
        created=thesis["created"],
        total_cost=thesis["total_cost"],
        total_value=thesis["total_value"],
        return_class="green" if gain >= 0 else "red",
        return_sign=_sign(gain),
        total_gain_pct=thesis["total_gain_pct"],
        positions_html=positions_html,
    )


def _build_watchlist_html(watchlist_data: list[dict]) -> str:
    if not watchlist_data:
        return '<p class="no-data">Watchlist is empty.</p>'
    rows = []
    for item in watchlist_data:
        day_pct = item.get("day_change_pct", 0)
        day_class = "green" if day_pct >= 0 else "red"
        s = "+" if day_pct >= 0 else ""
        pe = item.get("pe_ratio")
        low_52 = item.get("low_52w")
        div = item.get("dividend_yield")
        rows.append(
            f"<tr><td><b>{item.get('ticker','')}</b></td>"
            f"<td>${item.get('price',0):,.2f}</td>"
            f"<td class='{day_class}'>{s}{day_pct:.2f}%</td>"
            f"<td>{f'{pe:.1f}' if pe else 'N/A'}</td>"
            f"<td>{f'${low_52:,.2f}' if low_52 else 'N/A'}</td>"
            f"<td>{f'{div*100:.2f}%' if div else 'N/A'}</td></tr>"
        )
    return _WATCHLIST_TABLE.format(rows="\n".join(rows))


def build_html(theses: list[dict], watchlist_data: list[dict]) -> str:
    today = date.today().strftime("%A, %B %d, %Y")

    total_cost = sum(t["total_cost"] for t in theses)
    total_value = sum(t["total_value"] for t in theses)
    overall_gain = total_value - total_cost
    overall_pct = (overall_gain / total_cost * 100) if total_cost else 0.0
    s = _sign(overall_gain)

    theses_html = "\n".join(_build_thesis_html(t) for t in theses) if theses else \
        '<div class="card"><p class="no-data">No theses yet. Create one in the app to get started.</p></div>'

    return _TEMPLATE.format(
        report_date=today,
        total_cost=_fmt(total_cost),
        total_value=_fmt(total_value),
        overall_gain=f"{s}{_fmt(abs(overall_gain))}",
        overall_pct=f"{s}{abs(overall_pct):.2f}%",
        overall_class="green" if overall_gain >= 0 else "red",
        theses_html=theses_html,
        watchlist_html=_build_watchlist_html(watchlist_data),
    )


# ---------------------------------------------------------------------------
# Send
# ---------------------------------------------------------------------------

def send_email(html: str, subject: Optional[str] = None) -> bool:
    sender = os.getenv("EMAIL_SENDER", "")
    password = os.getenv("EMAIL_APP_PASSWORD", "")
    recipient = os.getenv("EMAIL_RECIPIENT", sender)
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))

    if not sender or not password:
        print("[email] EMAIL_SENDER and EMAIL_APP_PASSWORD must be set in .env")
        return False

    if subject is None:
        subject = f"VC, PE & Public Markets Tracker — {date.today().strftime('%b %d, %Y')}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())
        print(f"[email] Sent to {recipient}")
        return True
    except Exception as e:
        print(f"[email] Send failed: {e}")
        return False
