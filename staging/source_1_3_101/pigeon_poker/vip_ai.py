from __future__ import annotations

from typing import Any, Iterable, Mapping

# VIP is intentionally a single opponent tier: every seat is PRO ONLY.
# PURE_GTO_ROLE is retained as a compatibility symbol for the existing
# Pigeon UI, but the role badge makes no claim of solver-exact GTO.
VIP_PRO_ROLE = "pro_only"
PURE_GTO_ROLE = VIP_PRO_ROLE
NEAR_GTO_ROLE = "near_gto"
VIP_PURE_GTO_COUNT = 5
VIP_NEAR_GTO_COUNT = 0


def assign_vip_cpu_roles(cpu_ids: Iterable[str], rng: Any = None) -> dict[str, str]:
    """Assign all five VIP opponent seats to the professional-only tier."""
    identities = [str(cpu_id) for cpu_id in cpu_ids]
    if len(identities) != len(set(identities)):
        raise ValueError("VIP CPU identities must be unique")
    return {cpu_id: VIP_PRO_ROLE for cpu_id in identities}


def vip_cpu_role_label(role: str | None) -> str:
    """Display an honest, unambiguous badge for the active VIP opponent tier."""
    if role == VIP_PRO_ROLE:
        return "PRO ONLY"
    if role == NEAR_GTO_ROLE:
        return "NEAR GTO"
    return ""


def validate_vip_cpu_roles(cpu_ids: Iterable[str], roles: Mapping[str, str]) -> bool:
    """Validate exact seat coverage and reject any weaker VIP opponent tier."""
    identities = [str(cpu_id) for cpu_id in cpu_ids]
    if len(identities) != len(set(identities)):
        return False
    return (
        set(str(key) for key in roles.keys()) == set(identities)
        and all(roles.get(cpu_id) == VIP_PRO_ROLE for cpu_id in identities)
    )
