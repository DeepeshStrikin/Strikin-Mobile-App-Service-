"""Control-panel web UI.

NOTE: this is a temporary placeholder. The full control panel will be built to match
the "Strikin control centre" Figma once its design is exported to PDF/PNG and shared.
The admin API it will use (POST/PUT/DELETE /admin/activities|bays|food) is already live.
"""

ADMIN_HTML = """<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Strikin Control Centre</title>
<style>
  html,body{margin:0;height:100%;background:#191919;color:#E5E8EA;
    font-family:system-ui,Segoe UI,Roboto,sans-serif;display:flex;align-items:center;justify-content:center}
  .card{max-width:420px;text-align:center;padding:32px}
  h1{color:#D6FD31;font-size:22px;margin-bottom:8px}
  p{color:#9A9A9A;line-height:1.5}
  code{background:#262626;padding:2px 6px;border-radius:6px;color:#E5E8EA}
</style></head>
<body><div class="card">
  <h1>Strikin Control Centre</h1>
  <p>The control panel is being built to match your design.</p>
  <p>The admin API is already live at <code>/admin/activities</code>, <code>/admin/bays</code>
     and <code>/admin/food</code> (create / update / delete).</p>
</div></body></html>"""
