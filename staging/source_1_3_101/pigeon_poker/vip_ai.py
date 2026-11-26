from __future__ import annotations

from typing import Any, Iterable, Mapping

# VIP lineup: three professional seats and two elite top-professional seats.
VIP_PRO_ROLE = "pro"
VIP_TOP_PRO_ROLE = "top_pro"
NEAR_GTO_ROLE = "near_gto"  # retained only for older saved-state compatibility
PURE_GTO_ROLE = VIP_PRO_ROLE
VIP_PRO_COUNT = 3
VIP_TOP_PRO_COUNT = 2
VIP_PURE_GTO_COUNT = VIP_PRO_COUNT + VIP_TOP_PRO_COUNT  # legacy total-seat alias
VIP_NEAR_GTO_COUNT = 0

VIP_AUTO_REBUY_THRESHOLD_BB = 80
VIP_AUTO_REBUY_TARGET_BB = 100


def assign_vip_cpu_roles(cpu_ids: Iterable[str], rng: Any = None) -> dict[str, str]:
    """Assign exactly three PRO and two TOP PRO roles across five VIP seats."""
    identities = [str(cpu_id) for cpu_id in cpu_ids]
    if len(identities) != 5 or len(identities) != len(set(identities)):
        raise ValueError("VIP requires five unique CPU identities")
    if rng is not None and hasattr(rng, "sample"):
        top_ids = set(rng.sample(identities, VIP_TOP_PRO_COUNT))
    else:
        top_ids = set(identities[-VIP_TOP_PRO_COUNT:])
    return {
        cpu_id: VIP_TOP_PRO_ROLE if cpu_id in top_ids else VIP_PRO_ROLE
        for cpu_id in identities
    }


def vip_cpu_role_label(role: str | None) -> str:
    """Return the only two visible VIP CPU names: PRO or TOP PRO."""
    if role == VIP_PRO_ROLE:
        return "PRO"
    if role == VIP_TOP_PRO_ROLE:
        return "TOP PRO"
    return ""


def validate_vip_cpu_roles(cpu_ids: Iterable[str], roles: Mapping[str, str]) -> bool:
    """Require exact lineup coverage: three PRO seats and two TOP PRO seats."""
    identities = [str(cpu_id) for cpu_id in cpu_ids]
    if len(identities) != 5 or len(identities) != len(set(identities)):
        return False
    if set(str(key) for key in roles.keys()) != set(identities):
        return False
    values = [roles.get(cpu_id) for cpu_id in identities]
    return (
        values.count(VIP_PRO_ROLE) == VIP_PRO_COUNT
        and values.count(VIP_TOP_PRO_ROLE) == VIP_TOP_PRO_COUNT
    )


def make_vip_auto_rebuy_plan(
    stacks: Mapping[str, int],
    big_blind_cents: int,
    *,
    wallet_available_cents: int = 0,
    hero_id: str = "hero",
) -> dict[str, Any]:
    """Top up VIP seats below 80 BB to 100 BB; debit HERO only when funded.

    Opponents are virtually replenished. HERO is replenished only when the
    wallet can cover the full top-up, so this rule never creates a negative
    wallet balance or a partial, ambiguous rebuy.
    """
    bb = int(big_blind_cents)
    wallet = max(0, int(wallet_available_cents))
    if bb <= 0:
        raise ValueError("Big blind must be positive")
    threshold = VIP_AUTO_REBUY_THRESHOLD_BB * bb
    target = VIP_AUTO_REBUY_TARGET_BB * bb
    targets: dict[str, int] = {}
    cpu_rebuys: dict[str, int] = {}
    hero_debit = 0
    hero_skipped = 0

    for player_id, raw_stack in stacks.items():
        pid = str(player_id)
        stack = max(0, int(raw_stack))
        if stack >= threshold:
            continue
        top_up = target - stack
        if pid == hero_id:
            if top_up <= wallet:
                targets[pid] = target
                hero_debit = top_up
            else:
                hero_skipped = top_up
        else:
            targets[pid] = target
            cpu_rebuys[pid] = top_up

    return {
        "targets": targets,
        "cpu_rebuys": cpu_rebuys,
        "hero_debit_cents": hero_debit,
        "hero_skipped_cents": hero_skipped,
        "threshold_cents": threshold,
        "target_cents": target,
    }
