"""Derive conservative HU flop-root ranges from Pigeon's existing screenshot-derived preflop chart."""
from __future__ import annotations
from typing import Any, Mapping

POSITIONS_BY_CLOCKWISE_DISTANCE = {0:"BTN",1:"SB",2:"BB",3:"UTG",4:"HJ",5:"CO"}
OPEN_NODE = {"UTG":"01_UTG_OPEN","HJ":"02_HJ_OPEN","CO":"03_CO_OPEN","BTN":"04_BTN_OPEN","SB":"05_SB_OPEN"}
CALL_NODE = {
 ("UTG","HJ"):"06_HJ_VS_UTG",("UTG","CO"):"07_CO_VS_UTG",("UTG","BTN"):"08_BTN_VS_UTG",
 ("UTG","SB"):"09_SB_VS_UTG",("UTG","BB"):"10_BB_VS_UTG",
 ("HJ","CO"):"11_CO_VS_HJ",("HJ","BTN"):"12_BTN_VS_HJ",("HJ","SB"):"13_SB_VS_HJ",
 ("HJ","BB"):"14_BB_VS_HJ",("CO","BTN"):"15_BTN_VS_CO",("CO","SB"):"16_SB_VS_CO",
 ("CO","BB"):"17_BB_VS_CO",("BTN","SB"):"18_SB_VS_BTN",("BTN","BB"):"19_BB_VS_BTN",
 ("SB","BB"):"20_BB_VS_SB",
}

def _result(reason: str, **fields) -> dict[str, Any]:
    return {"supported":False,"reason":reason,"schema":"pigeon-gto-plus-auto-solve-v1",**fields}

def _seat_positions(hand: Any):
    players=list(getattr(hand,"players",()) or ())
    if len(players)!=6: return None
    try: dealer=int(hand.dealer_index)%6
    except (AttributeError,TypeError,ValueError): return None
    positions={}
    for i,p in enumerate(players):
        pid=str(getattr(p,"player_id","") or "")
        if not pid: return None
        positions[pid]=POSITIONS_BY_CLOCKWISE_DISTANCE[(i-dealer)%6]
    return positions

def _preflop_actions(hand):
    out=[]
    for e in list(getattr(hand,"events",()) or ()):
        if not isinstance(e,Mapping) or e.get("type")!="action": continue
        if str(e.get("street","preflop")).lower()!="preflop": continue
        pid=str(e.get("player","") or "")
        action=str(e.get("action","")).lower().replace("_","-").strip()
        if not pid or not action: return []
        item={"player_id":pid,"action":action}
        if "target" in e: item["target"]=e.get("target")
        out.append(item)
    return out

def _weighted_range(rows, node_id, action):
    selected=[]
    for row in rows:
        if str(row.get("node",""))!=node_id: continue
        combo=str(row.get("hand",""))
        probabilities=row.get("p",{})
        if not combo or not isinstance(probabilities,Mapping): continue
        try: weight=min(1.0,float(probabilities.get(action,0.0)))
        except (TypeError,ValueError): continue
        if weight>0: selected.append((combo,weight))
    selected.sort()
    return ",".join(f"{combo}:{weight:.4f}" for combo,weight in selected),len(selected)

def build_live_hu_solver_setup(hand: Any, chart_data: Mapping[str,Any], *, rake_pct: float):
    """Create a replayable GTO+ flop-root request only for a standard open/flat-call HU line.

    Ranges are approximations reconstructed from the user's chart images. The
    builder rejects 3-bets, limps, nonstandard opens and unsupported seat lines.
    """
    positions=_seat_positions(hand)
    if positions is None: return _result("six-max seat/button data unavailable")
    eligible=[str(p.player_id) for p in getattr(hand,"players",()) if bool(getattr(p,"eligible",False))]
    if len(eligible)!=2: return _result(f"requires exactly two eligible players; found {len(eligible)}")
    actions=_preflop_actions(hand)
    if not actions: return _result("preflop action history unavailable")
    if any(e["player_id"] not in positions for e in actions): return _result("unknown preflop seat in action history")
    if any(e["action"] not in {"fold","raise","bet","call"} for e in actions):
        return _result("preflop line contains an unsupported action")
    raises=[e for e in actions if e["action"] in {"raise","bet"}]
    calls=[e for e in actions if e["action"]=="call"]
    if len(raises)!=1 or len(calls)!=1: return _result("requires exactly one open raise and one flat call")
    opener,caller=raises[0]["player_id"],calls[0]["player_id"]
    opener_pos,caller_pos=positions[opener],positions[caller]
    try:
        actual=float(raises[0].get("target"))/float(getattr(hand,"big_blind",0) or 0)
    except (TypeError,ValueError,ZeroDivisionError):
        return _result("open size cannot be verified against chart")
    expected=3.5 if opener_pos=="SB" else 2.5
    if abs(actual-expected)>0.06: return _result(f"open size {actual:.3f} BB differs from chart assumption {expected:.1f} BB")
    if set(eligible)!={opener,caller}: return _result("postflop players do not match open/call line")
    if sum(e["action"]!="fold" for e in actions)!=2: return _result("line contains a limp, cold call or extra voluntary action")
    open_node=OPEN_NODE.get(opener_pos)
    call_node=CALL_NODE.get((opener_pos,caller_pos))
    if not open_node or not call_node: return _result(f"preflop positions not covered: {opener_pos} open / {caller_pos} call")
    rows=chart_data.get("rows",[])
    if not isinstance(rows,list): return _result("preflop chart dataset is invalid")
    opener_range,opener_count=_weighted_range(rows,open_node,"raise")
    caller_range,caller_count=_weighted_range(rows,call_node,"call")
    if not opener_range or not caller_range: return _result("no usable open/call frequencies in chart")

    players=list(getattr(hand,"players",()))
    try: dealer=int(hand.dealer_index)%len(players)
    except (AttributeError,TypeError,ValueError,ZeroDivisionError): return _result("dealer position unavailable")
    indices=[i for i,p in enumerate(players) if str(p.player_id) in eligible]
    if len(indices)!=2: return _result("could not resolve the two active seats")
    if dealer in indices:
        ip=str(players[dealer].player_id)
        oop=next(str(players[i].player_id) for i in indices if i!=dealer)
    else:
        clockwise=sorted(indices,key=lambda i:((i-dealer)%len(players)) or len(players))
        oop,ip=str(players[clockwise[0]].player_id),str(players[clockwise[1]].player_id)
    oop_range=opener_range if oop==opener else caller_range
    ip_range=opener_range if ip==opener else caller_range
    oop_count=opener_count if oop==opener else caller_count
    ip_count=opener_count if ip==opener else caller_count

    events=list(getattr(hand,"events",()) or ())
    flop_i=next((i for i,e in enumerate(events) if isinstance(e,Mapping) and e.get("type")=="street" and str(e.get("street","")).lower()=="flop"),None)
    if flop_i is None: return _result("flop root not found")
    board=list(events[flop_i].get("board",()) or ())
    if len(board)!=3: return _result("flop root must contain exactly three cards")
    by_id={str(p.player_id):p for p in players}
    paid={}
    postflop_line=[]
    for e in events[flop_i+1:]:
        if not isinstance(e,Mapping): continue
        if e.get("type")=="street" and str(e.get("street","")).lower() in {"turn","river"}:
            postflop_line.append({"type":"street","street":e.get("street"),"board":list(e.get("board",()) or ())})
        if e.get("type")!="action": continue
        pid=str(e.get("player","") or "")
        action=str(e.get("action","")).lower().replace("_","-")
        try:
            if action in {"bet","raise","all-in"}: amount=max(0,int(e.get("target",0))-int(e.get("street_contribution_before",0)))
            elif action=="call": amount=max(0,int(e.get("to_call_before",0)))
            elif action=="all-in-call": amount=max(0,int(e.get("amount",0)))
            else: amount=0
        except (TypeError,ValueError): amount=0
        paid[pid]=paid.get(pid,0)+amount
        postflop_line.append({k:e.get(k) for k in ("player","action","target","paid","amount","street","street_contribution_before","current_bet_before","to_call_before","pot_before","full_raise") if k in e})
    stacks={pid:int(getattr(by_id[pid],"stack",0))+paid.get(pid,0) for pid in (oop,ip)}
    bb=int(getattr(hand,"big_blind",0) or 0)
    effective=min(stacks.values())
    if bb<=0 or effective<=0: return _result("invalid big blind or effective stack")
    first_action=next((e for e in events[flop_i+1:] if isinstance(e,Mapping) and e.get("type")=="action"),None)
    try: root_pot=int(first_action.get("pot_before")) if first_action else int(getattr(hand,"pot",0))
    except (TypeError,ValueError): return _result("could not reconstruct flop-root pot")
    if root_pot<=0: return _result("flop-root pot is empty")
    try: rake=float(rake_pct)
    except (TypeError,ValueError): return _result("invalid rake percentage")
    if not 0<=rake<=100: return _result("rake percentage is outside 0..100")
    return {
        "supported":True,"reason":"standard single-open/flat-call HU line; flop-root state reconstructed",
        "schema":"pigeon-gto-plus-auto-solve-v1",
        "root":{"game":"NLHE","players":2,"board":board,"pot_bb":round(root_pot/bb,6),
                "effective_stack_bb":round(effective/bb,6),"rake_pct":rake,
                "oop_player_id":oop,"ip_player_id":ip,"oop_position":positions[oop],"ip_position":positions[ip],
                "oop_range":oop_range,"ip_range":ip_range,"range_source":"screenshot_preflop_chart_frequency",
                "preflop_nodes":{"open":open_node,"call":call_node},
                "range_hand_classes":{"oop":oop_count,"ip":ip_count}},
        "postflop_line":postflop_line,
        "assumptions":["Preflop ranges are screenshot-derived approximations, not solver-certified.",
                       "Bet-tree sizes and solver precision settings must be included in the resulting tree identity.",
                       "Unsupported preflop lines are rejected rather than assigned guessed ranges."]
    }
