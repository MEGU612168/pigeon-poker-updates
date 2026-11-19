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
    # Only derive six-max chart positions when all six seats actually received
    # cards. A short-handed table uses different positional labels and must not
    # be silently mapped onto a full-ring six-max chart.
    dealt=[p for p in players if len(list(getattr(p,"hole_cards",()) or ()))==2]
    if len(dealt)!=6: return None
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

def to_gto_plus_range_text(weighted_range: str) -> str:
    """Convert internal HAND:WEIGHT pairs into GTO+'s bracket-weighted range syntax.

    Example: 'AA:1.0000,AKs:0.5000,KQo:0.0000' -> 'AA,[50]AKs[/50]'.
    GTO+ uses percentages inside square-bracket blocks; unbracketed hands are 100%.
    """
    if not isinstance(weighted_range, str):
        raise TypeError("weighted_range must be a string")
    if not weighted_range.strip():
        return ""

    rank_order = "23456789TJQKA"
    full_weight: list[str] = []
    weighted_groups: dict[float, list[str]] = {}
    seen: set[str] = set()

    for raw_token in weighted_range.split(","):
        token = raw_token.strip()
        if not token:
            continue
        if ":" not in token:
            raise ValueError(f"weighted range token has no weight: {token!r}")
        hand, raw_weight = (part.strip() for part in token.rsplit(":", 1))
        normalized = hand.upper()
        valid_pair = len(normalized) == 2 and normalized[0] == normalized[1] and normalized[0] in rank_order
        valid_nonpair = (
            len(normalized) == 3
            and normalized[0] in rank_order
            and normalized[1] in rank_order
            and normalized[0] != normalized[1]
            and rank_order.index(normalized[0]) > rank_order.index(normalized[1])
            and normalized[2] in "SO"
        )
        if not (valid_pair or valid_nonpair):
            raise ValueError(f"unsupported GTO+ starting-hand class: {hand!r}")
        if normalized in seen:
            raise ValueError(f"duplicate hand class in weighted range: {normalized}")
        seen.add(normalized)
        hand = normalized if valid_pair else normalized[:2] + normalized[2].lower()
        try:
            weight = float(raw_weight)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid weight for {hand}: {raw_weight!r}") from exc
        if not 0.0 <= weight <= 1.0:
            raise ValueError(f"weight for {hand} is outside 0..1: {weight}")
        if weight <= 0.0:
            continue
        if weight >= 1.0:
            full_weight.append(hand)
            continue
        percentage = round(weight * 100.0, 4)
        if percentage <= 0.0:
            continue
        weighted_groups.setdefault(percentage, []).append(hand)

    sections: list[str] = []
    if full_weight:
        sections.append(",".join(sorted(full_weight)))
    for percentage in sorted(weighted_groups, reverse=True):
        value = f"{percentage:.4f}".rstrip("0").rstrip(".")
        hands = ",".join(sorted(weighted_groups[percentage]))
        sections.append(f"[{value}]{hands}[/{value}]")
    return ",".join(sections)


def _required_tree_sizes(postflop_line, oop_player_id: str, ip_player_id: str):
    """Create a compact Advanced-tree sizing profile containing every observed line size."""
    result = {
        street: {
            "oop": {"bet_pct": set(), "raise_x": set(), "three_bet_x": set(),
                    "four_bet_x": set(), "all_in": False},
            "ip": {"bet_pct": set(), "raise_x": set(), "three_bet_x": set(),
                   "four_bet_x": set(), "all_in": False},
        }
        for street in ("flop", "turn", "river")
    }
    raise_depth = {street: 0 for street in result}
    for event in postflop_line:
        if event.get("type") != "action":
            continue
        action = str(event.get("action", "")).lower().replace("_", "-")
        if action not in {"bet", "raise", "all-in"}:
            continue
        street = str(event.get("street", "")).lower()
        if street not in result:
            return None, f"postflop {action} has no valid street label"
        player_id = str(event.get("player", "") or "")
        role = "oop" if player_id == oop_player_id else "ip" if player_id == ip_player_id else None
        if role is None:
            return None, "postflop action actor is not one of the two HU players"
        cfg = result[street][role]
        if action == "all-in":
            cfg["all_in"] = True
            continue
        try:
            target = float(event["target"])
            contribution = float(event["street_contribution_before"])
            pot = float(event["pot_before"])
            if action == "bet":
                denominator = pot
                numerator = target - contribution
                key = "bet_pct"
            else:
                current_bet = float(event["current_bet_before"])
                denominator = current_bet
                numerator = target
                key = ("raise_x", "three_bet_x", "four_bet_x")[
                    min(raise_depth[street], 2)
                ]
                raise_depth[street] += 1
        except (KeyError, TypeError, ValueError):
            return None, f"postflop {action} size context is incomplete"
        if denominator <= 0 or numerator <= 0:
            return None, f"postflop {action} size cannot be reconstructed"
        cfg[key].add(round(numerator / denominator * (100.0 if action == "bet" else 1.0), 4))

    # Keep the solve tree useful beyond the one observed path without exploding
    # the branching factor. Observed sizes are always retained.
    for street in result:
        for role in ("oop", "ip"):
            cfg = result[street][role]
            cfg["bet_pct"] = sorted(cfg["bet_pct"] | {33.0, 75.0})
            cfg["raise_x"] = sorted(cfg["raise_x"] | {3.0})
            cfg["three_bet_x"] = sorted(cfg["three_bet_x"] | {3.0})
            cfg["four_bet_x"] = sorted(cfg["four_bet_x"] | {2.0})
            for key in ("bet_pct", "raise_x", "three_bet_x", "four_bet_x"):
                cfg[key] = cfg[key]
    return result, None


def build_live_hu_solver_setup(hand: Any, chart_data: Mapping[str,Any], *, rake_pct: float, rake_cap_bb: float | None = None):
    """Create a replayable GTO+ flop-root request only for a standard open/flat-call HU line.

    Ranges are approximations reconstructed from the user's chart images. The
    builder rejects 3-bets, limps, nonstandard opens and unsupported seat lines.
    """
    positions=_seat_positions(hand)
    if positions is None: return _result("requires six dealt players and a valid six-max button position")
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
        postflop_line.append({"type":"action", **{k:e.get(k) for k in ("player","action","target","paid","amount","street","street_contribution_before","current_bet_before","to_call_before","pot_before","full_raise") if k in e}})
    stacks={pid:int(getattr(by_id[pid],"stack",0))+paid.get(pid,0) for pid in (oop,ip)}
    bb=int(getattr(hand,"big_blind",0) or 0)
    effective=min(stacks.values())
    if bb<=0 or effective<=0: return _result("invalid big blind or effective stack")
    first_action=next((e for e in events[flop_i+1:] if isinstance(e,Mapping) and e.get("type")=="action"),None)
    try: root_pot=int(first_action.get("pot_before")) if first_action else int(getattr(hand,"pot",0))
    except (TypeError,ValueError): return _result("could not reconstruct flop-root pot")
    if root_pot<=0: return _result("flop-root pot is empty")
    required_tree_sizes, size_error = _required_tree_sizes(postflop_line, oop, ip)
    if size_error:
        return _result(size_error)
    try: rake=float(rake_pct)
    except (TypeError,ValueError): return _result("invalid rake percentage")
    if not 0<=rake<=100: return _result("rake percentage is outside 0..100")
    if rake_cap_bb is None:
        rake_cap = None
    else:
        try: rake_cap = max(0.0, float(rake_cap_bb))
        except (TypeError, ValueError): return _result("invalid rake cap")
    return {
        "supported":True,"reason":"standard single-open/flat-call HU line; flop-root state reconstructed",
        "schema":"pigeon-gto-plus-auto-solve-v1",
        "root":{"game":"NLHE","players":2,"board":board,"pot_bb":round(root_pot/bb,6),
                "effective_stack_bb":round(effective/bb,6),"rake_pct":rake,"rake_cap_bb":rake_cap,
                "oop_player_id":oop,"ip_player_id":ip,"oop_position":positions[oop],"ip_position":positions[ip],
                "oop_range":oop_range,"ip_range":ip_range,
                "oop_range_gto_plus":to_gto_plus_range_text(oop_range),
                "ip_range_gto_plus":to_gto_plus_range_text(ip_range),
                "range_source":"screenshot_preflop_chart_frequency",
                "preflop_nodes":{"open":open_node,"call":call_node},
                "range_hand_classes":{"oop":oop_count,"ip":ip_count}},
        "postflop_line":postflop_line,"required_tree_sizes":required_tree_sizes,
        "assumptions":["Preflop ranges are screenshot-derived approximations, not solver-certified.",
                       "Bet-tree sizes and solver precision settings must be included in the resulting tree identity.",
                       "Unsupported preflop lines are rejected rather than assigned guessed ranges."]
    }

# candidate validation trigger: include this deterministic source in the v1.3.41-dev build.

# Build v1.3.41 after actual table rake/cap integration.

# Candidate archive path checked.

# Rebuild after adding the v1.3.41 updater and stable-release assembly steps.

# Re-run release packaging after JSON metadata serialisation correction.

# Rebuild v1.3.41 with direct stable-manifest publication.

# Rebuild v1.3.42 with visual dialog verification.

# Rebuild v1.3.42 after bundling the diagnostic's ui_probe dependency.

# Retry v1.3.42 build after adding urllib/base64/io imports.
