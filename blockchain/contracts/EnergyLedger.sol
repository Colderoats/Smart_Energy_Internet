// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title EnergyLedger - Module 5 of the Smart Energy Internet
/// @notice Append-only, tamper-evident log of important grid actions.
///         The full JSON payload of each action lives OFF-CHAIN (TimescaleDB,
///         table chain_records); this contract stores only its keccak256
///         fingerprint. Verification = re-hash the stored payload and compare
///         with the hash recorded here.
/// @dev    There are deliberately NO update or delete functions. Once a record
///         is appended it can never be changed by anyone, including the owner.
///         Data provenance (live API / replayed SCADA / simulated trade /
///         offline federated run) is carried inside the hashed payload.
contract EnergyLedger {
    enum EventType {
        ENERGY_REDISTRIBUTION, // 0 - Module 2 self-healing reroute / isolate / curtail
        P2P_TRADE,             // 1 - peer-to-peer energy trade (SIMULATED until hardware exists)
        FAULT_ALERT,           // 2 - fault / fault_predicted verdict (rule_based and/or ta_gnn)
        FL_ROUND               // 3 - Module 4 federated round (replayed from the offline run)
    }

    struct Record {
        uint256 id;
        EventType eventType;
        bytes32 payloadHash;
        string actor;       // node id (or "federated_server" for FL rounds)
        uint256 timestamp;  // block timestamp at append time
        address recorder;
    }

    address public immutable owner;
    Record[] private _records;

    event RecordAppended(
        uint256 indexed id,
        EventType indexed eventType,
        bytes32 indexed payloadHash,
        string actor,
        uint256 timestamp,
        address recorder
    );

    error NotOwner();
    error EmptyHash();
    error EmptyActor();
    error UnknownRecord(uint256 id);

    constructor() {
        owner = msg.sender;
    }

    /// @notice Append one record. Only the backend's recorder account (the
    ///         deployer) may append, so third parties cannot spam the ledger.
    function appendRecord(EventType eventType, bytes32 payloadHash, string calldata actor)
        external
        returns (uint256 id)
    {
        if (msg.sender != owner) revert NotOwner();
        if (payloadHash == bytes32(0)) revert EmptyHash();
        if (bytes(actor).length == 0) revert EmptyActor();

        id = _records.length;
        _records.push(Record(id, eventType, payloadHash, actor, block.timestamp, msg.sender));
        emit RecordAppended(id, eventType, payloadHash, actor, block.timestamp, msg.sender);
    }

    function recordCount() external view returns (uint256) {
        return _records.length;
    }

    function getRecord(uint256 id) external view returns (Record memory) {
        if (id >= _records.length) revert UnknownRecord(id);
        return _records[id];
    }

    /// @notice True when `payloadHash` equals the hash stored for record `id`.
    function verify(uint256 id, bytes32 payloadHash) external view returns (bool) {
        if (id >= _records.length) revert UnknownRecord(id);
        return _records[id].payloadHash == payloadHash;
    }
}
