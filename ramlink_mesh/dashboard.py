#!/usr/bin/env python3
"""Loopback-only, read-only live dashboard for RAMLink mesh nodes."""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .agent import STATS, request, read_token

DEFAULT_CONFIG = {
    "poll_seconds": 5,
    "nodes": [
        {
            "name": "This device (example)",
            "host": "127.0.0.1",
            "port": 18080,
            "token_file": "token.txt",
        }
    ],
}

HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#0b1220"><title>RAMLink Mesh Dashboard</title>
<style>
:root{color-scheme:dark;--bg:#0b1220;--panel:#142137;--line:#293b54;--muted:#9aacc5;--text:#eef5ff;--accent:#60e2bd;--bad:#ff929b}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at top,#182c46,var(--bg) 58%);color:var(--text);font:15px system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1120px;margin:auto;padding:24px 16px 44px}.top{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
.brand{font-size:25px;font-weight:850;letter-spacing:-.7px}.brand span{color:var(--accent)}.sub,.muted,.hint,footer{color:var(--muted)}
.sub{margin-top:4px}button{background:var(--accent);color:#09221b;border:0;border-radius:11px;padding:11px 15px;font-weight:800;cursor:pointer}button:disabled{opacity:.6}
.cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:22px 0}
.card,.node{background:linear-gradient(145deg,#172840,#101a2a);border:1px solid var(--line);border-radius:16px;padding:17px;min-width:0}
.label{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:1px}.value{font-size:26px;font-weight:850;margin-top:8px;overflow-wrap:anywhere}.hint{font-size:12px;margin-top:5px}
.section{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:26px 0 12px}.section h2{font-size:18px;margin:0}.muted{font-size:13px}
.nodes{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.node-head{display:flex;align-items:flex-start;justify-content:space-between;gap:8px}.node-name{font-size:17px;font-weight:750;overflow-wrap:anywhere}
.pill{font-size:11px;border-radius:99px;padding:5px 9px;background:#183d38;color:var(--accent);white-space:nowrap}.pill.down{background:#43252d;color:var(--bad)}
.bar{height:8px;background:#26364d;border-radius:20px;overflow:hidden;margin:12px 0 7px}.fill{height:100%;background:linear-gradient(90deg,#43b9a7,#8cf0c5);border-radius:20px;width:0%}
.meters{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:15px}.meter{background:#0b1422;border:1px solid #203047;border-radius:10px;padding:10px}.meter strong{display:block;font-size:16px;margin-top:5px;overflow-wrap:anywhere}
.error{color:var(--bad);font-size:12px;margin-top:12px;overflow-wrap:anywhere}.empty{border:1px dashed var(--line);border-radius:14px;padding:22px;color:var(--muted);line-height:1.6}
footer{font-size:12px;line-height:1.65;margin-top:24px}
@media(max-width:700px){.cards{grid-template-columns:repeat(2,minmax(0,1fr))}.nodes{grid-template-columns:1fr}.value{font-size:23px}.meter{padding:8px}}
</style></head><body><main>
<div class="top"><div><div class="brand">RAM<span>Link</span> / Mesh</div><div class="sub">Live peer health · read-only local monitor</div></div><button id="refresh">↻ Refresh now</button></div>
<div class="cards">
<div class="card"><div class="label">Nodes online</div><div class="value" id="online">—</div><div class="hint" id="node-count">Waiting for first poll</div></div>
<div class="card"><div class="label">Configured pool</div><div class="value" id="capacity">—</div><div class="hint">Across reachable nodes</div></div>
<div class="card"><div class="label">Used pool</div><div class="value" id="used">—</div><div class="hint" id="free">Available: —</div></div>
<div class="card"><div class="label">Traffic transferred</div><div class="value" id="traffic">—</div><div class="hint">Cumulative in + out</div></div>
</div>
<div class="section"><h2>Network nodes</h2><span class="muted" id="updated">Connecting…</span></div>
<div class="nodes" id="nodes"><div class="empty">Loading node status…</div></div>
<footer>Auto-refreshes every 5 seconds. “Pool” means RAMLink's explicitly allocated object buffers, not total device RAM or guaranteed OS memory. This dashboard binds to localhost only. For remote access, use a trusted VPN or SSH tunnel; do not expose the dashboard port publicly.</footer>
</main>
<script>
const $=id=>document.getElementById(id);
function mib(n){return Number.isFinite(n)?(n/1048576).toLocaleString(undefined,{maximumFractionDigits:1})+' MiB':'—'}
function bytes(n){if(!Number.isFinite(n))return '—';if(n<1024)return n+' B';if(n<1048576)return (n/1024).toFixed(1)+' KiB';return (n/1048576).toFixed(2)+' MiB'}
function safe(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
async function poll(){
 $('refresh').disabled=true;
 try{
  const res=await fetch('/api/status',{cache:'no-store'});if(!res.ok)throw new Error('HTTP '+res.status);
  const body=await res.json(),nodes=body.nodes||[],online=nodes.filter(n=>n.online);
  const sum=k=>online.reduce((a,n)=>a+(Number(n.stats?.[k])||0),0);
  $('online').textContent=online.length+' / '+nodes.length;
  $('node-count').textContent=nodes.length?'Configured peers':'No peers configured';
  $('capacity').textContent=mib(sum('capacity_bytes'));$('used').textContent=mib(sum('used_bytes'));
  $('free').textContent='Available: '+mib(sum('available_bytes'));
  $('traffic').textContent=bytes(sum('bytes_in')+sum('bytes_out'));
  $('updated').textContent='Updated '+new Date(body.timestamp*1000).toLocaleTimeString();
  $('nodes').innerHTML=nodes.length?nodes.map(n=>{
   const s=n.stats||{},pct=s.capacity_bytes?Math.min(100,Math.max(0,(s.used_bytes||0)/s.capacity_bytes*100)):0;
   return '<article class="node"><div class="node-head"><div><div class="node-name">'+safe(n.name)+'</div><div class="muted">'+safe(n.host)+':'+safe(n.port)+'</div></div><span class="pill '+(n.online?'':'down')+'">'+(n.online?'ONLINE':'OFFLINE')+'</span></div>'+
   (n.online?'<div class="bar"><div class="fill" style="width:'+pct.toFixed(1)+'%"></div></div><div class="muted">'+pct.toFixed(1)+'% of RAMLink pool used</div><div class="meters">'+
   '<div class="meter"><span class="muted">Used</span><strong>'+mib(s.used_bytes)+'</strong></div>'+
   '<div class="meter"><span class="muted">Available</span><strong>'+mib(s.available_bytes)+'</strong></div>'+
   '<div class="meter"><span class="muted">Objects</span><strong>'+safe(s.objects??0)+'</strong></div></div>'+
   '<div class="meters"><div class="meter"><span class="muted">Received</span><strong>'+bytes(s.bytes_in||0)+'</strong></div><div class="meter"><span class="muted">Sent</span><strong>'+bytes(s.bytes_out||0)+'</strong></div><div class="meter"><span class="muted">Requests</span><strong>'+safe(s.requests??0)+'</strong></div></div>'+
   '<div class="hint">Uptime: '+Math.floor(s.uptime_seconds||0)+' seconds</div>'
   :'<div class="error">'+safe(n.error||'Peer did not respond')+'</div>')+'</article>';
  }).join(''):'<div class="empty">No peers configured. Create config/dashboard.json using config/dashboard.example.json as a template.</div>';
 }catch(e){$('updated').textContent='Dashboard API unavailable';$('nodes').innerHTML='<div class="error">'+safe(e.message)+'</div>'}
 finally{$('refresh').disabled=false}
}
$('refresh').addEventListener('click',poll);poll();setInterval(poll,5000);
</script></body></html>"""


def load_config(path: str | Path) -> dict[str, Any]:
    """Load and validate dashboard config; resolve token/CA paths from its folder."""
    config_path = Path(path).resolve()
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read dashboard config: {exc}") from exc
    if not isinstance(config, dict) or not isinstance(config.get("nodes"), list):
        raise ValueError("config must be a JSON object containing a nodes array")
    poll_seconds = config.get("poll_seconds", 5)
    if not isinstance(poll_seconds, (int, float)) or isinstance(poll_seconds, bool):
        raise ValueError("poll_seconds must be a number")
    config["poll_seconds"] = max(2, min(60, float(poll_seconds)))
    for index, node in enumerate(config["nodes"]):
        if not isinstance(node, dict):
            raise ValueError(f"nodes[{index}] must be an object")
        if not isinstance(node.get("name"), str) or not node["name"].strip():
            raise ValueError(f"nodes[{index}].name is required")
        if not isinstance(node.get("host"), str) or not node["host"].strip():
            raise ValueError(f"nodes[{index}].host is required")
        port = node.get("port", 18080)
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise ValueError(f"nodes[{index}].port must be 1..65535")
        token_file = node.get("token_file")
        if not isinstance(token_file, str) or not token_file:
            raise ValueError(f"nodes[{index}].token_file is required")
        node["port"] = port
        token_path = Path(token_file).expanduser()
        node["token_file"] = str((config_path.parent / token_path).resolve()) if not token_path.is_absolute() else str(token_path)
        ca_file = node.get("ca_file")
        if ca_file:
            ca_path = Path(ca_file).expanduser()
            node["ca_file"] = str((config_path.parent / ca_path).resolve()) if not ca_path.is_absolute() else str(ca_path)
    return config


async def poll_node(node: dict[str, Any], timeout: float = 2.5) -> dict[str, Any]:
    """Return safe, displayable status for one configured node."""
    result: dict[str, Any] = {
        "name": node["name"], "host": node["host"], "port": node["port"],
        "online": False, "stats": None, "error": None,
    }
    try:
        token = read_token(node["token_file"])
        _, payload = await asyncio.wait_for(
            request(
                node["host"], node["port"], token, STATS, b"{}",
                node.get("ca_file"), node.get("server_name"),
            ),
            timeout=timeout,
        )
        stats = json.loads(payload.decode("utf-8"))
        required = ("capacity_bytes", "used_bytes", "available_bytes", "objects")
        if not isinstance(stats, dict) or any(not isinstance(stats.get(k), (int, float)) for k in required):
            raise ValueError("peer returned invalid stats")
        result["online"] = True
        result["stats"] = stats
    except Exception as exc:
        # Avoid exposing tokens, file contents, or tracebacks in the local dashboard.
        result["error"] = f"{type(exc).__name__}: {str(exc)[:180]}"
    return result


def make_handler(config: dict[str, Any], config_path: Path):
    class Handler(BaseHTTPRequestHandler):
        server_version = "RAMLinkDashboard/0.1"

        def do_GET(self):
            route = urlparse(self.path).path
            if route == "/":
                data = HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(data)
                return
            if route == "/api/status":
                try:
                    nodes = asyncio.run(asyncio.gather(*[])) if False else None
                    async def collect():
                        return await asyncio.gather(*(poll_node(node) for node in config["nodes"]))
                    data_obj = {"timestamp": time.time(), "nodes": asyncio.run(collect())}
                    data = json.dumps(data_obj, separators=(",", ":")).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.end_headers()
                    self.wfile.write(data)
                except Exception:
                    self.send_error(502, "Unable to poll configured peers")
                return
            self.send_error(404)

        def log_message(self, fmt, *args):
            # Keep token files and payloads out of access logs; only paths/status are logged.
            super().log_message(fmt, *args)

    return Handler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RAMLink local live dashboard")
    parser.add_argument("--config", default="config/dashboard.json", help="path to dashboard JSON config")
    parser.add_argument("--bind", default="127.0.0.1", help="must be loopback; remote binding is disabled")
    parser.add_argument("--port", type=int, default=8765)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.bind not in ("127.0.0.1", "::1", "localhost"):
        raise SystemExit("Security: dashboard only binds to loopback; use a trusted SSH tunnel/VPN for remote viewing.")
    if not 0 < args.port < 65536:
        raise SystemExit("port must be 1..65535")
    config_path = Path(args.config).expanduser().resolve()
    config = load_config(config_path)
    server = ThreadingHTTPServer((args.bind, args.port), make_handler(config, config_path))
    server.daemon_threads = True
    print(f"RAMLink dashboard: http://{args.bind}:{args.port}")
    print(f"Peer config: {config_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping RAMLink dashboard.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
