"""Pure market logic (no I/O): offers/bids, matching, metering, settlement amount.

Units mirror EnergyMarket.sol: quantities are integer Wh, prices are integer
milli-credits per kWh ("demo credits", not money), payments milli-credits.

Matching rule (also in ARCHITECTURE.md): offers sorted ascending by ask, bids
descending by max price; while best ask <= best max, match
qty = min(remaining offer, remaining bid) at price = the SELLER'S ASK (the
contract's rule). Once the best ask exceeds the best max nothing further can match.
Same ordering idea as backend/testbed/market (which is not imported: its venv
and pandapower are separate).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Order:
    node_id: str
    qty_wh: int
    price_milli: int


@dataclass
class Match:
    offer_idx: int  # index into the offers list passed to match_orders
    bid_idx: int
    seller: str
    buyer: str
    qty_wh: int
    price_milli: int


def energy_wh(mean_kw: float, interval_hours: float) -> int:
    """kWh = kW * hours, returned as integer Wh (floored: never promise more than the mean supports)."""
    return max(0, int(mean_kw * interval_hours * 1000.0))


def match_orders(offers: list[Order], bids: list[Order]) -> tuple[list[Match], list[int], list[int]]:
    """Returns (matches, remaining_wh per offer, remaining_wh per bid), both
    remaining lists indexed like the inputs. Total matched Wh is conserved:
    offered = matched + remaining (per side)."""
    off_rem = [o.qty_wh for o in offers]
    bid_rem = [b.qty_wh for b in bids]
    off_order = sorted(range(len(offers)), key=lambda i: (offers[i].price_milli, offers[i].node_id))
    bid_order = sorted(range(len(bids)), key=lambda j: (-bids[j].price_milli, bids[j].node_id))
    matches: list[Match] = []
    a = b = 0
    while a < len(off_order) and b < len(bid_order):
        i, j = off_order[a], bid_order[b]
        if offers[i].price_milli > bids[j].price_milli:
            break
        if off_rem[i] == 0:
            a += 1
            continue
        if bid_rem[j] == 0:
            b += 1
            continue
        q = min(off_rem[i], bid_rem[j])
        off_rem[i] -= q
        bid_rem[j] -= q
        matches.append(Match(i, j, offers[i].node_id, bids[j].node_id, q, offers[i].price_milli))
        if off_rem[i] == 0:
            a += 1
        if bid_rem[j] == 0:
            b += 1
    return matches, off_rem, bid_rem


def allocate_metering(matches: list[Match], actual_surplus_wh: dict[str, int], actual_deficit_wh: dict[str, int]) -> list[tuple[int, int]]:
    """METERED quantities per match = energy actually delivered/taken. A node's
    actual surplus (deficit) over the interval is handed out to its matches in
    order; a match never meters more than it matched. Returns [(seller_wh, buyer_wh)]."""
    sur = dict(actual_surplus_wh)
    dfc = dict(actual_deficit_wh)
    out = []
    for m in matches:
        s = min(m.qty_wh, sur.get(m.seller, 0))
        d = min(m.qty_wh, dfc.get(m.buyer, 0))
        sur[m.seller] = sur.get(m.seller, 0) - s
        dfc[m.buyer] = dfc.get(m.buyer, 0) - d
        out.append((s, d))
    return out


def settle_amount(price_milli: int, seller_wh: int, buyer_wh: int) -> tuple[int, int]:
    """(settled_wh, pay_milli) exactly as EnergyMarket.settle: q = min(q_s, q_b),
    pay = price_milli * q / 1000 (integer division)."""
    q = min(seller_wh, buyer_wh)
    return q, (price_milli * q) // 1000
