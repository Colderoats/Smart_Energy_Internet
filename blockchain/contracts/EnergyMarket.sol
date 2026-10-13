// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title EnergyMarket - peer-to-peer trading contract of the Smart Energy Internet papers
/// @notice register prosumer -> post sell offer / buy bid -> match (price compatible) -> oracle submits
///         metered quantities -> settle at Pay = p * min(q_s, q_b)   (journal Eq. 19).
/// @dev    Separate from EnergyLedger (which only stores hashes). Participants are prosumer BUSES / microgrid
///         nodes identified by a bytes32 node id - never households. Quantities are Wh, prices are
///         milli-currency per kWh, payments milli-currency. Balances are internal credits (no ETH moves),
///         as in the conference paper's Eq. (16).
///         Ordering by price is done off-chain by the gateway (sorting on-chain would make gas depend on the
///         number of participants); the contract enforces price compatibility (ask <= bid) and the interval.
///         Metered quantities are accepted only from the authorised gateway/oracle account. An offer or bid
///         that is not matched expires at the end of its interval (the gateway advances the interval).
contract EnergyMarket {
    struct Offer {
        address seller;
        uint32 interval;
        uint64 qtyWh;      // offered
        uint64 remainWh;   // not yet matched
        uint32 priceMilli; // ask per kWh
        bool expired;
    }

    struct Bid {
        address buyer;
        uint32 interval;
        uint64 qtyWh;
        uint64 remainWh;
        uint32 priceMilli; // maximum price per kWh
        bool expired;
    }

    struct Trade {
        uint256 offerId;
        uint256 bidId;
        address seller;
        address buyer;
        uint32 interval;
        uint64 matchedWh;
        uint32 priceMilli; // agreed price p_sb (the seller's ask)
        uint64 meterSellerWh;
        uint64 meterBuyerWh;
        bool metered;
        bool settled;
    }

    address public immutable owner;
    address public gateway;          // authorised oracle between the edge nodes and the chain
    uint32 public currentInterval;

    mapping(address => bytes32) public nodeOf;      // registered account -> node id
    mapping(bytes32 => address) public accountOf;   // node id -> account
    mapping(address => int256) public balanceMilli; // internal credit balance

    Offer[] private _offers;
    Bid[] private _bids;
    Trade[] private _trades;

    event Registered(address indexed account, bytes32 indexed nodeId);
    event OfferPosted(uint256 indexed id, address indexed seller, uint32 interval, uint64 qtyWh, uint32 priceMilli);
    event BidPosted(uint256 indexed id, address indexed buyer, uint32 interval, uint64 qtyWh, uint32 priceMilli);
    event TradeMatched(uint256 indexed id, uint256 indexed offerId, uint256 indexed bidId, uint64 matchedWh, uint32 priceMilli);
    event Metered(uint256 indexed tradeId, uint64 sellerWh, uint64 buyerWh);
    event Settled(uint256 indexed tradeId, address indexed seller, address indexed buyer, uint64 settledWh, uint256 payMilli);
    event OfferExpired(uint256 indexed id, uint64 unmatchedWh);
    event BidExpired(uint256 indexed id, uint64 unmatchedWh);
    event IntervalAdvanced(uint32 interval);
    event GatewayChanged(address indexed gateway);

    error NotOwner();
    error NotGateway();
    error NotRegistered();
    error AlreadyRegistered();
    error NodeIdTaken();
    error WrongInterval();
    error ZeroQuantity();
    error UnknownId();
    error PriceMismatch();
    error AlreadyExpired();
    error NothingToMatch();
    error NotMetered();
    error AlreadyMetered();
    error AlreadySettled();
    error StillOpen();

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    modifier onlyGateway() {
        if (msg.sender != gateway) revert NotGateway();
        _;
    }

    modifier onlyRegistered() {
        if (nodeOf[msg.sender] == bytes32(0)) revert NotRegistered();
        _;
    }

    constructor(address gateway_) {
        owner = msg.sender;
        gateway = gateway_;
        emit GatewayChanged(gateway_);
    }

    function setGateway(address gateway_) external onlyOwner {
        gateway = gateway_;
        emit GatewayChanged(gateway_);
    }

    // ------------------------------------------------------------------ participants
    function register(bytes32 nodeId) external {
        if (nodeOf[msg.sender] != bytes32(0)) revert AlreadyRegistered();
        if (accountOf[nodeId] != address(0)) revert NodeIdTaken();
        nodeOf[msg.sender] = nodeId;
        accountOf[nodeId] = msg.sender;
        emit Registered(msg.sender, nodeId);
    }

    // ------------------------------------------------------------------ offers and bids
    function postOffer(uint64 qtyWh, uint32 priceMilli) external onlyRegistered returns (uint256 id) {
        if (qtyWh == 0) revert ZeroQuantity();
        id = _offers.length;
        _offers.push(Offer(msg.sender, currentInterval, qtyWh, qtyWh, priceMilli, false));
        emit OfferPosted(id, msg.sender, currentInterval, qtyWh, priceMilli);
    }

    function postBid(uint64 qtyWh, uint32 priceMilli) external onlyRegistered returns (uint256 id) {
        if (qtyWh == 0) revert ZeroQuantity();
        id = _bids.length;
        _bids.push(Bid(msg.sender, currentInterval, qtyWh, qtyWh, priceMilli, false));
        emit BidPosted(id, msg.sender, currentInterval, qtyWh, priceMilli);
    }

    // ------------------------------------------------------------------ matching (gateway = market operator)
    /// @notice Match one offer with one bid of the current interval. Matched quantity = min(remaining offer, remaining bid);
    ///         the agreed price is the seller's ask, which must not exceed the buyer's maximum (conference Eq. 15).
    function matchTrade(uint256 offerId, uint256 bidId) external onlyGateway returns (uint256 id) {
        if (offerId >= _offers.length || bidId >= _bids.length) revert UnknownId();
        Offer storage o = _offers[offerId];
        Bid storage b = _bids[bidId];
        if (o.interval != currentInterval || b.interval != currentInterval) revert WrongInterval();
        if (o.expired || b.expired) revert AlreadyExpired();
        if (o.priceMilli > b.priceMilli) revert PriceMismatch();
        uint64 q = o.remainWh < b.remainWh ? o.remainWh : b.remainWh;
        if (q == 0) revert NothingToMatch();
        o.remainWh -= q;
        b.remainWh -= q;
        id = _trades.length;
        _trades.push(Trade(offerId, bidId, o.seller, b.buyer, currentInterval, q, o.priceMilli, 0, 0, false, false));
        emit TradeMatched(id, offerId, bidId, q, o.priceMilli);
    }

    // ------------------------------------------------------------------ metering (oracle only) and settlement
    function submitMeter(uint256 tradeId, uint64 sellerWh, uint64 buyerWh) external onlyGateway {
        if (tradeId >= _trades.length) revert UnknownId();
        Trade storage t = _trades[tradeId];
        if (t.metered) revert AlreadyMetered();
        t.meterSellerWh = sellerWh;
        t.meterBuyerWh = buyerWh;
        t.metered = true;
        emit Metered(tradeId, sellerWh, buyerWh);
    }

    /// @notice Pay = p_sb * min(q_s, q_b) with the metered quantities (Eq. 19). Callable by anyone once metered.
    function settle(uint256 tradeId) external {
        if (tradeId >= _trades.length) revert UnknownId();
        Trade storage t = _trades[tradeId];
        if (!t.metered) revert NotMetered();
        if (t.settled) revert AlreadySettled();
        t.settled = true;
        uint64 q = t.meterSellerWh < t.meterBuyerWh ? t.meterSellerWh : t.meterBuyerWh;
        uint256 pay = (uint256(t.priceMilli) * uint256(q)) / 1000; // milli-currency per kWh * Wh / 1000
        balanceMilli[t.buyer] -= int256(pay);
        balanceMilli[t.seller] += int256(pay);
        emit Settled(tradeId, t.seller, t.buyer, q, pay);
    }

    // ------------------------------------------------------------------ intervals and expiry
    function advanceInterval() external onlyGateway {
        currentInterval += 1;
        emit IntervalAdvanced(currentInterval);
    }

    /// @notice An offer left unmatched at the end of its interval expires; anyone may record that.
    function expireOffer(uint256 id) external {
        if (id >= _offers.length) revert UnknownId();
        Offer storage o = _offers[id];
        if (o.interval >= currentInterval) revert StillOpen();
        if (o.expired) revert AlreadyExpired();
        o.expired = true;
        emit OfferExpired(id, o.remainWh);
    }

    function expireBid(uint256 id) external {
        if (id >= _bids.length) revert UnknownId();
        Bid storage b = _bids[id];
        if (b.interval >= currentInterval) revert StillOpen();
        if (b.expired) revert AlreadyExpired();
        b.expired = true;
        emit BidExpired(id, b.remainWh);
    }

    // ------------------------------------------------------------------ views
    function offerCount() external view returns (uint256) { return _offers.length; }
    function bidCount() external view returns (uint256) { return _bids.length; }
    function tradeCount() external view returns (uint256) { return _trades.length; }
    function getOffer(uint256 id) external view returns (Offer memory) { if (id >= _offers.length) revert UnknownId(); return _offers[id]; }
    function getBid(uint256 id) external view returns (Bid memory) { if (id >= _bids.length) revert UnknownId(); return _bids[id]; }
    function getTrade(uint256 id) external view returns (Trade memory) { if (id >= _trades.length) revert UnknownId(); return _trades[id]; }
}
