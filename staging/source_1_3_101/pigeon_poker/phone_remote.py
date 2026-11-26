from __future__ import annotations

import ipaddress
import json
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit


PHONE_ACTIONS = frozenset({"fold", "check", "call", "bet", "raise", "all-in"})


def build_phone_snapshot(
    tables: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
    *,
    wallet_cents: int = 0,
    message: str = "",
) -> dict[str, Any]:
    """Return a strict, JSON-safe public snapshot for the paired phone UI.

    Only HERO's own hole cards are copied. Unknown fields (including opponent
    hole cards, CPU strategy state, and internal hand objects) are discarded.
    """
    safe_tables: list[dict[str, Any]] = []
    for raw in tables:
        if not isinstance(raw, Mapping):
            continue
        players: list[dict[str, Any]] = []
        for player in raw.get("players", []) or []:
            if not isinstance(player, Mapping):
                continue
            players.append({
                "name": str(player.get("name", "Player"))[:48],
                "stack_cents": max(0, int(player.get("stack_cents", 0) or 0)),
                "folded": bool(player.get("folded", False)),
                "all_in": bool(player.get("all_in", False)),
                "is_hero": bool(player.get("is_hero", False)),
            })
        actions = [
            action for action in (raw.get("actions", []) or [])
            if isinstance(action, str) and action in PHONE_ACTIONS
        ]
        safe_tables.append({
            "id": str(raw.get("id", ""))[:128],
            "title": str(raw.get("title", ""))[:80],
            "rate": str(raw.get("rate", ""))[:24],
            "mode": str(raw.get("mode", ""))[:32],
            "hand_number": max(0, int(raw.get("hand_number", 0) or 0)),
            "street": str(raw.get("street", "waiting")).upper()[:16],
            "status": str(raw.get("status", ""))[:100],
            "hero_hole_cards": [str(card)[:8] for card in (raw.get("hero_hole_cards", []) or [])[:2]],
            "board": [str(card)[:8] for card in (raw.get("board", []) or [])[:5]],
            "pot_cents": max(0, int(raw.get("pot_cents", 0) or 0)),
            "hero_stack_cents": max(0, int(raw.get("hero_stack_cents", 0) or 0)),
            "small_blind_cents": max(0, int(raw.get("small_blind_cents", 0) or 0)),
            "big_blind_cents": max(1, int(raw.get("big_blind_cents", 1) or 1)),
            "to_call_cents": max(0, int(raw.get("to_call_cents", 0) or 0)),
            "min_target_cents": max(0, int(raw.get("min_target_cents", 0) or 0)),
            "max_target_cents": max(0, int(raw.get("max_target_cents", 0) or 0)),
            "actions": actions,
            "busy": bool(raw.get("busy", False)),
            "hero_turn": bool(raw.get("hero_turn", False)),
            "rush_fold_available": bool(raw.get("rush_fold_available", False)),
            "sitting_out": bool(raw.get("sitting_out", False)),
            "players": players,
        })
    return {
        "wallet_cents": max(0, int(wallet_cents)),
        "message": str(message)[:160],
        "tables": safe_tables,
        "updated_at": time.time(),
    }


PHONE_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<meta name="theme-color" content="#09121f">
<title>Pigeon Poker Remote</title>
<style>
:root{color-scheme:dark;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;background:#07111d;color:#edf3fb}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at top,#14263a,#07111d 68%);min-height:100vh}
main{width:min(100%,620px);margin:0 auto;padding:16px 13px 28px}
header{display:flex;align-items:center;justify-content:space-between;margin:3px 2px 15px}
.brand{font-size:18px;font-weight:900;letter-spacing:.13em;color:#e7c779}.sub{font-size:10px;color:#92a4b8;letter-spacing:.13em}
.panel{background:#101d2d;border:1px solid #2b4057;border-radius:17px;padding:15px;margin:11px 0;box-shadow:0 12px 30px #0004}
h1{font-size:19px;margin:0 0 6px}h2{font-size:13px;margin:0 0 12px;color:#c2d0df;letter-spacing:.08em}
.small{font-size:12px;color:#9aacc0;line-height:1.5}.muted{color:#8fa1b7}
input,button{font:inherit}input{width:100%;background:#081321;border:1px solid #40566f;color:#fff;border-radius:11px;padding:12px;font-size:18px}
button{border:0;border-radius:12px;min-height:48px;font-weight:850;letter-spacing:.035em;padding:11px 13px;touch-action:manipulation}
.primary{background:#19a879;color:#061b14}.secondary{background:#263b52;color:#f1f6fc}.danger{background:#bd454e;color:#fff}.gold{background:#cba85b;color:#211707}
button:disabled{opacity:.35}
#pair{margin-top:9vh}#pair button{width:100%;margin-top:10px}
#app[hidden],#pair[hidden]{display:none}
.table-head{display:flex;justify-content:space-between;gap:10px;align-items:start}
.rate{color:#e4c36f;font-weight:900;font-size:14px}.status{font-size:12px;color:#7edbb5;text-align:right;font-weight:800}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin:12px 0}
.stat{background:#091624;border-radius:11px;padding:10px 8px;text-align:center}.stat b{display:block;font-size:17px;font-variant-numeric:tabular-nums}.stat span{font-size:9px;letter-spacing:.1em;color:#92a5ba}
.cards{display:flex;gap:8px;justify-content:center;min-height:66px;align-items:center;margin:10px 0}
.card{width:43px;height:61px;border-radius:7px;background:#f1f4f7;color:#111827;display:grid;place-items:center;font-size:20px;font-weight:900;box-shadow:0 3px 7px #0006}
.card.red{color:#c62838}.card.back{background:linear-gradient(135deg,#193f56,#0e2639);border:2px solid #d4b86f;color:#d4b86f}
.board .card{width:39px;height:54px;font-size:17px}
.seats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;margin-top:10px}
.seat{background:#0a1725;border:1px solid #253a50;border-radius:9px;padding:7px 5px;text-align:center;min-width:0}
.seat.hero{border-color:#d2b568}.seat .name{font-size:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.seat .stack{font-size:12px;font-weight:800;margin-top:3px}
.actions{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
.actions .wide{grid-column:1/-1}
.bet-row{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:10px 0}
.presets{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0}.presets button{min-height:36px;padding:6px 10px;font-size:12px}
.notice{min-height:20px;font-size:12px;color:#e7c779;margin-top:8px}
.table-tabs{display:flex;gap:7px;overflow:auto}.table-tabs button{white-space:nowrap;min-height:38px}.selected{outline:2px solid #d5b86d}
hr{border:0;border-top:1px solid #26384d;margin:12px 0}
footer{text-align:center;color:#71869d;font-size:10px;padding:15px}
@media(min-width:480px){main{padding:22px}.panel{padding:18px}.card{width:49px;height:69px}.board .card{width:46px;height:61px}}
</style>
</head>
<body>
<main>
<header><div><div class="brand">PIGEON POKER</div><div class="sub">LOCAL PHONE CONTROL</div></div><div class="sub" id="connection">NOT PAIRED</div></header>
<section class="panel" id="pair">
<h1>Connect to your table</h1>
<p class="small">Enter the 8-digit pairing code shown in the Pigeon Poker window on your PC. Your phone and PC must be on the same Wi-Fi network.</p>
<input id="pin" inputmode="numeric" autocomplete="one-time-code" maxlength="8" placeholder="8-digit pairing code">
<button class="primary" id="pairButton" onclick="pairDevice()">PAIR PHONE</button>
<div class="notice" id="pairMessage"></div>
</section>
<section id="app" hidden>
<div class="panel">
<div class="table-head"><div><div class="sub">CONNECTED WALLET</div><div class="rate" id="wallet">$0.00</div></div><div class="status" id="globalStatus">SYNCING</div></div>
<hr><div class="table-tabs" id="tabs"></div>
</div>
<div id="tableArea"></div>
</section>
<footer>Private LAN connection • Do not share your pairing code</footer>
</main>
<script>
let token=sessionStorage.getItem("pigeonRemoteToken")||"";
let currentTable="";
let timer=0;
const $=id=>document.getElementById(id);
const money=c=>"$"+(Number(c||0)/100).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
function esc(s){return String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function cardHtml(v,back=false){if(back)return '<div class="card back">♠</div>';let s=String(v||"");let red=/[♥♦]/.test(s);return '<div class="card '+(red?'red':'')+'">'+esc(s)+'</div>';}
async function pairDevice(){
 const pin=$("pin").value.trim();$("pairMessage").textContent="Pairing…";
 try{const r=await fetch("/api/pair",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({code:pin})});const j=await r.json();if(!r.ok)throw new Error(j.error||"Pairing failed");token=j.token;sessionStorage.setItem("pigeonRemoteToken",token);$("pair").hidden=true;$("app").hidden=false;$("connection").textContent="PAIRED";poll();}
 catch(e){$("pairMessage").textContent=e.message;}
}
async function api(path,body){
 const opt={headers:{"Authorization":"Bearer "+token}};
 if(body!==undefined){opt.method="POST";opt.headers["Content-Type"]="application/json";opt.body=JSON.stringify(body);}
 const r=await fetch(path,opt);const j=await r.json().catch(()=>({error:"Invalid response"}));
 if(r.status===401){token="";sessionStorage.removeItem("pigeonRemoteToken");$("app").hidden=true;$("pair").hidden=false;$("connection").textContent="NOT PAIRED";}
 if(!r.ok)throw new Error(j.error||"Request failed");return j;
}
function render(data){
 $("wallet").textContent=money(data.wallet_cents);
 $("globalStatus").textContent=data.tables.length?(data.tables.length+" TABLE"+(data.tables.length===1?"":"S")+" OPEN"):"NO TABLE";
 if(data.message)$("globalStatus").textContent=data.message;
 const tabs=$("tabs");tabs.innerHTML="";
 data.tables.forEach(t=>{const b=document.createElement("button");b.className="secondary"+(t.id===currentTable?" selected":"");b.textContent=(t.rate||"TABLE")+" • "+(t.mode||"");b.onclick=()=>{currentTable=t.id;render(data);};tabs.appendChild(b);});
 const previousBet=$("betAmount")?.value??null;
 const betWasFocused=document.activeElement?.id==="betAmount";
 let t=data.tables.find(x=>x.id===currentTable)||data.tables[0];if(t)currentTable=t.id;
 if(!t){$("tableArea").innerHTML='<div class="panel"><h2>NO OPEN TABLE</h2><p class="small">Open a cash table in Pigeon Poker on your PC.</p></div>';return;}
 const canFold=t.actions.includes("fold");
 const callAction=t.actions.includes("check")?"check":(t.actions.includes("call")?"call":"");
 const betAction=t.actions.includes("bet")?"bet":(t.actions.includes("raise")?"raise":"");
 const canAllIn=t.actions.includes("all-in");
 let html='<div class="panel"><div class="table-head"><div><div class="rate">'+esc(t.title||t.rate)+'</div><div class="small">HAND #'+t.hand_number+' • '+esc(t.street)+'</div></div><div class="status">'+esc(t.status)+'</div></div>';
 html+='<div class="stats"><div class="stat"><b>'+money(t.pot_cents)+'</b><span>POT</span></div><div class="stat"><b>'+money(t.hero_stack_cents)+'</b><span>YOUR STACK</span></div><div class="stat"><b>'+money(t.to_call_cents)+'</b><span>TO CALL</span></div></div>';
 html+='<div class="sub" style="text-align:center">YOUR HAND</div><div class="cards">'+(t.hero_hole_cards.length?t.hero_hole_cards.map(c=>cardHtml(c)).join(""):'<span class="small">Cards not dealt</span>')+'</div>';
 html+='<div class="sub" style="text-align:center">COMMUNITY CARDS</div><div class="cards board">'+t.board.map(c=>cardHtml(c)).join("")+Array.from({length:5-t.board.length},()=>cardHtml("",true)).join("")+'</div>';
 html+='<div class="seats">'+t.players.map(p=>'<div class="seat '+(p.is_hero?'hero':'')+'"><div class="name">'+esc(p.name)+(p.folded?' • FOLD':p.all_in?' • ALL-IN':'')+'</div><div class="stack">'+money(p.stack_cents)+'</div></div>').join("")+'</div><hr>';
 if(t.sitting_out){html+='<div class="small">You are sitting out. Resume from the PC table window.</div>';}
 else if(t.busy&&!t.rush_fold_available){html+='<div class="small">The CPU or deal animation is in progress. Controls will appear when it is your turn.</div>';}
 else if(!t.hero_turn&&!t.rush_fold_available){html+='<div class="small">Waiting for the next action. This screen updates automatically.</div>';}
 html+='<div class="actions">';
 if(canFold)html+='<button class="danger" onclick="sendAction(\'fold\')">FOLD</button>';
 if(callAction)html+='<button class="primary" onclick="sendAction(\''+callAction+'\')">'+(callAction==="check"?"CHECK":"CALL "+money(t.to_call_cents))+'</button>';
 if(canAllIn)html+='<button class="gold '+(!callAction&&!canFold?"wide":"")+'" onclick="sendAction(\'all-in\')">ALL-IN</button>';
 html+='</div>';
 if(betAction){
  const min=Math.max(0,t.min_target_cents),max=Math.max(min,t.max_target_cents);
  const start=min;
  html+='<hr><h2>'+(betAction==="bet"?"BET TO":"RAISE TO")+'</h2><div class="bet-row"><input id="betAmount" type="number" inputmode="decimal" min="'+(min/100).toFixed(2)+'" max="'+(max/100).toFixed(2)+'" step="0.01" value="'+(start/100).toFixed(2)+'"><button class="primary" onclick="submitBet(\''+betAction+'\','+max+')">'+(max>0?"SUBMIT "+betAction.toUpperCase():"SUBMIT")+'</button></div>';
  html+='<div class="presets">'+[33,50,75,100].map(p=>'<button class="secondary" onclick="setBetPreset('+p+','+t.pot_cents+','+t.to_call_cents+','+min+','+max+')">'+p+'%</button>').join("")+'</div>';
  html+='<div class="small">Enter total target in USD • '+money(min)+' to '+money(max)+'</div>';
 }
 html+='<div class="notice" id="actionMessage"></div></div>';
 $("tableArea").innerHTML=html;
 if(previousBet!==null){const nextBet=$("betAmount");if(nextBet){nextBet.value=previousBet;if(betWasFocused)nextBet.focus();}}
}
function setBetPreset(p,pot,toCall,min,max){const target=Math.max(min,Math.min(max,Math.round((pot+toCall)*p/100)));$("betAmount").value=(target/100).toFixed(2);}
async function sendAction(action,amount){$("actionMessage").textContent="Sending…";try{await api("/api/action",{table_id:currentTable,action,amount_cents:amount});$("actionMessage").textContent="Action sent to PC";}catch(e){$("actionMessage").textContent=e.message;}}
async function submitBet(action,max){const amount=Math.round(Number($("betAmount").value)*100);if(!Number.isFinite(amount)||amount<0){$("actionMessage").textContent="Enter a valid amount";return;}await sendAction(action,amount);}
async function poll(){
 if(!token)return;
 try{const data=await api("/api/state");if(document.activeElement?.id!=="betAmount")render(data);$("connection").textContent="CONNECTED";}
 catch(e){$("connection").textContent="RECONNECTING";}
 timer=window.setTimeout(poll,550);
}
if(token){$("pair").hidden=true;$("app").hidden=false;poll();}
</script>
</body>
</html>
"""


class PhoneRemoteServer:
    """Authenticated, same-LAN browser remote for the local Tk poker application."""

    def __init__(
        self,
        on_action: Callable[[dict[str, Any]], bool],
        *,
        host: str = "0.0.0.0",
        port: int = 0,
    ) -> None:
        self._on_action = on_action
        self._host = str(host)
        self._requested_port = int(port)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._state: dict[str, Any] = build_phone_snapshot([])
        self._pairing_code = ""
        self._sessions: set[str] = set()
        self._pair_attempts: dict[str, list[float]] = {}
        self._running = False

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    @property
    def port(self) -> int:
        with self._lock:
            return int(self._server.server_address[1]) if self._server else 0

    @property
    def pairing_code(self) -> str:
        with self._lock:
            return self._pairing_code

    @property
    def urls(self) -> list[str]:
        port = self.port
        if not port:
            return []
        ips: list[str] = []
        # A UDP route probe discovers the active Wi-Fi/Ethernet interface
        # without sending application data to the external destination.
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                probe.connect(("192.0.2.1", 9))
                route_ip = str(probe.getsockname()[0])
                parsed_route_ip = ipaddress.ip_address(route_ip)
                if parsed_route_ip.is_private and not parsed_route_ip.is_loopback and not parsed_route_ip.is_link_local:
                    ips.append(route_ip)
            finally:
                probe.close()
        except OSError:
            pass
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM):
                address = str(info[4][0])
                parsed = ipaddress.ip_address(address)
                if parsed.is_private and not parsed.is_loopback and not parsed.is_link_local:
                    if address not in ips:
                        ips.append(address)
        except OSError:
            pass
        ips.sort(key=lambda item: (not item.startswith("192.168."), item))
        if not ips and self._host in {"127.0.0.1", "localhost"}:
            ips = ["127.0.0.1"]
        return [f"http://{address}:{port}/" for address in ips]

    def publish_state(self, state: Mapping[str, Any]) -> None:
        tables = state.get("tables", [])
        wallet = state.get("wallet_cents", 0)
        message = state.get("message", "")
        safe = build_phone_snapshot(
            tables if isinstance(tables, (list, tuple)) else [],
            wallet_cents=int(wallet or 0),
            message=str(message or ""),
        )
        with self._lock:
            self._state = safe

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._pairing_code = f"{secrets.randbelow(100_000_000):08d}"
            self._sessions.clear()
            self._pair_attempts.clear()
            owner = self

            class Handler(BaseHTTPRequestHandler):
                protocol_version = "HTTP/1.1"
                server_version = "PigeonPhoneRemote/1"

                def log_message(self, _format: str, *args: Any) -> None:
                    return

                def _client_is_private(self) -> bool:
                    try:
                        address = ipaddress.ip_address(str(self.client_address[0]).split("%", 1)[0])
                        return address.is_private or address.is_loopback
                    except ValueError:
                        return False

                def _send(self, status: int, data: bytes, content_type: str) -> None:
                    self.send_response(status)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.send_header("Referrer-Policy", "no-referrer")
                    self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(data)
                    self.close_connection = True

                def _json(self, status: int, value: Mapping[str, Any]) -> None:
                    data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                    self._send(status, data, "application/json; charset=utf-8")

                def _body(self) -> dict[str, Any]:
                    try:
                        length = int(self.headers.get("Content-Length", "0"))
                    except ValueError:
                        raise ValueError("Invalid request length")
                    if length < 1 or length > 4096:
                        raise ValueError("Invalid request size")
                    raw = self.rfile.read(length)
                    value = json.loads(raw.decode("utf-8"))
                    if not isinstance(value, dict):
                        raise ValueError("JSON body must be an object")
                    return value

                def _authorized(self) -> bool:
                    header = self.headers.get("Authorization", "")
                    if not header.startswith("Bearer "):
                        return False
                    token = header[7:].strip()
                    with owner._lock:
                        return bool(token) and token in owner._sessions

                def _origin_is_local(self) -> bool:
                    origin = self.headers.get("Origin")
                    if not origin:
                        return True
                    try:
                        origin_host = urlsplit(origin).netloc.lower()
                        request_host = self.headers.get("Host", "").lower()
                        return bool(origin_host) and origin_host == request_host
                    except Exception:
                        return False

                def do_GET(self) -> None:
                    if not self._client_is_private():
                        self._json(403, {"error": "Local network clients only"})
                        return
                    route = urlsplit(self.path).path
                    if route == "/":
                        self._send(200, PHONE_HTML.encode("utf-8"), "text/html; charset=utf-8")
                        return
                    if route == "/api/state":
                        if not self._authorized():
                            self._json(401, {"error": "Pair this phone first"})
                            return
                        with owner._lock:
                            snapshot = dict(owner._state)
                        self._json(200, snapshot)
                        return
                    self._json(404, {"error": "Not found"})

                def do_POST(self) -> None:
                    if not self._client_is_private() or not self._origin_is_local():
                        self._json(403, {"error": "Request rejected"})
                        return
                    route = urlsplit(self.path).path
                    try:
                        body = self._body()
                    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
                        self._json(400, {"error": str(exc)})
                        return
                    if route == "/api/pair":
                        peer = str(self.client_address[0])
                        now = time.monotonic()
                        with owner._lock:
                            attempts = [stamp for stamp in owner._pair_attempts.get(peer, []) if now - stamp < 60]
                            if len(attempts) >= 8:
                                owner._pair_attempts[peer] = attempts
                                self._json(429, {"error": "Too many attempts. Wait one minute and retry."})
                                return
                            attempts.append(now)
                            owner._pair_attempts[peer] = attempts
                            supplied = str(body.get("code", "")).strip()
                            if not secrets.compare_digest(supplied, owner._pairing_code):
                                self._json(401, {"error": "Incorrect pairing code"})
                                return
                            token = secrets.token_urlsafe(32)
                            owner._sessions.add(token)
                        self._json(200, {"token": token})
                        return
                    if route == "/api/action":
                        if not self._authorized():
                            self._json(401, {"error": "Pair this phone first"})
                            return
                        table_id = str(body.get("table_id", "")).strip()
                        action = str(body.get("action", "")).strip().lower()
                        if not table_id or len(table_id) > 128 or action not in PHONE_ACTIONS:
                            self._json(400, {"error": "Invalid table or action"})
                            return
                        amount = body.get("amount_cents")
                        if action in {"bet", "raise"}:
                            if isinstance(amount, bool) or not isinstance(amount, int) or not 0 <= amount <= 100_000_000:
                                self._json(400, {"error": "Bet size must be a valid amount in cents"})
                                return
                        else:
                            amount = None
                        try:
                            accepted = bool(owner._on_action({
                                "table_id": table_id,
                                "action": action,
                                "amount_cents": amount,
                            }))
                        except Exception:
                            accepted = False
                        if not accepted:
                            self._json(503, {"error": "The PC could not queue this action"})
                            return
                        self._json(202, {"accepted": True})
                        return
                    self._json(404, {"error": "Not found"})

            server = ThreadingHTTPServer((self._host, self._requested_port), Handler)
            server.daemon_threads = True
            server.allow_reuse_address = True
            self._server = server
            self._running = True
            self._thread = threading.Thread(
                target=server.serve_forever,
                name="PigeonPhoneRemote",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            server = self._server
            thread = self._thread
            self._running = False
            self._server = None
            self._thread = None
            self._sessions.clear()
            self._pairing_code = ""
            self._pair_attempts.clear()
            self._state = build_phone_snapshot([])
        if server is not None:
            try:
                server.shutdown()
            finally:
                server.server_close()
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
