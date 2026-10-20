"""Live prosumer market (surplus -> deficit energy trading, every step on-chain).

    prosumer_source (ingestion)  real weather -> estimated PV + synthetic load  ->  ingest_reading
    pipeline._ingest_prosumer    normalize -> twin update -> persist -> broadcast   (no fault detection)
    service.MarketService        every MARKET_INTERVAL_SECONDS: offers/bids from the forecast net power,
                                 match (engine.py), then an async worker puts register / offer / bid /
                                 match / meter / settle on the EnergyMarket contract (chain.py) and
                                 mirrors each settled trade into the EnergyLedger as a P2P_TRADE record.
    store.py                     market_prosumers / market_intervals / market_orders / market_trades

Prosumers are SIMULATED buildings: solar is estimated from live weather, load is
synthetic, amounts are demo credits. See prosumers.py for the provenance rules.
"""
