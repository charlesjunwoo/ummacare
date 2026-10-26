"""Render the SYNTHETIC DEMO FIXTURE lab report PDF (real text layer) used to test medical-document reading."""
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "backend" / "data" / "fixtures" / "demo_lab_report.pdf"
HTML = """<html><body style="font-family:Arial;font-size:12px;margin:40px">
<p style="color:#888">SYNTHETIC DEMO FIXTURE - invented values for testing UmmaCare - not a real patient</p>
<h2>Example Diagnostics Laboratory</h2>
<p>Patient: DEMO PATIENT &nbsp; DOB: 01/01/1960 &nbsp; Ordering provider: Dr. Kim (Endocrinology)<br>
Collected: 2026-10-02 &nbsp; Reported: 2026-10-03</p>
<table border="1" cellpadding="6" style="border-collapse:collapse;width:100%">
<tr><th>Test</th><th>Result</th><th>Flag</th><th>Units</th><th>Reference range</th></tr>
<tr><td>TSH</td><td>3.9</td><td></td><td>mIU/L</td><td>0.45-4.50</td></tr>
<tr><td>Free T4</td><td>1.1</td><td></td><td>ng/dL</td><td>0.82-1.77</td></tr>
<tr><td>Thyroid Peroxidase (TPO) Ab</td><td>210</td><td>High</td><td>IU/mL</td><td>0-34</td></tr>
<tr><td>Ferritin</td><td>22</td><td></td><td>ng/mL</td><td>15-150</td></tr>
<tr><td>Vitamin D, 25-Hydroxy</td><td>24</td><td>Low</td><td>ng/mL</td><td>30-100</td></tr>
</table>
<p>Comments: Results reviewed by ordering provider. Please discuss with your clinician.</p>
</body></html>"""
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_page()
    pg.set_content(HTML)
    pg.pdf(path=str(OUT), format="Letter")
    b.close()
print("wrote", OUT)
