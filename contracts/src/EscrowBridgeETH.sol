// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

interface IPayPalRegistry {
    enum Status {
        Initialized,
        Registered,
        Attested,
        Confirmed,
        Failed
    }

    function initAttest(
        bytes32 idHash,
        bytes32 recipientEmailHash,
        address counterparty,
        address witness,
        uint256 amount,
        bytes32 metadataHash
    ) external;

    function getSettlementStatus(bytes32 idHash) external view returns (Status);
    function getRequestedAmount(bytes32 idHash) external view returns (uint256);
    function getPostedAmount(bytes32 idHash) external view returns (uint256);
    function isFinalized(bytes32 idHash) external view returns (bool);
    function getSettlementParticipants(
        bytes32 idHash
    )
        external
        view
        returns (address sender, address counterparty, address witness);
}

contract EscrowBridgeETH is Ownable, ReentrancyGuard {
    /* ─────────────────────────────────────────────
       events
    ───────────────────────────────────────────── */
    event PaymentInitialized(
        bytes32 indexed escrowId,
        address indexed payer,
        uint256 amountWei,
        uint256 amountUsd
    );
    event PaymentSettled(
        bytes32 indexed escrowId,
        address indexed payer,
        uint256 payoutWeiAfterFee,
        uint256 postedUsd
    );
    event EscrowExpired(
        bytes32 indexed escrowId,
        address indexed payer,
        uint256 amountReservedWei
    );
    event FeeRecipientUpdated(address oldRecipient, address newRecipient);
    event ExchangeRateUpdated(uint256 oldRate, uint256 newRate);

    /* ─────────────────────────────────────────────
       storage
    ───────────────────────────────────────────── */
    struct Payment {
        address payer;
        address recipient;
        uint256 requestedAmount; // in wei
        uint256 requestedAmountUsd; // USD(6)
        uint256 postedAmount; // in wei
        uint256 postedAmountUsd; // USD(6)
        uint256 lastCheckTimestamp;
        uint256 checkCount;
        uint256 createdAt;
        uint256 exchangeRateAtInit;
    }

    IPayPalRegistry public immutable settlementRegistry;
    string public recipientEmail;

    uint256 public minPaymentAmount; // in wei
    uint256 public maxPaymentAmount; // in wei
    uint256 public fee; // bps
    address public feeRecipient;
    uint256 public maxEscrowTime; // seconds
    uint256 public constant FEE_DENOMINATOR = 10000;
    uint256 public exchangeRate; // USD(6) per 1 ETH (6 decimals)
    uint256 public totalEscrowed;

    mapping(bytes32 => Payment) public payments;
    mapping(bytes32 => bool) public isSettled;
    mapping(address => bool) public authorizedAttesters;
    mapping(bytes32 => bool) private _usedEscrowIds;
    bytes32[] public escrowIds;

    bytes32[] public pendingEscrows;
    mapping(bytes32 => uint256) private pendingIndex;
    bytes32[] public completedEscrows;
    bytes32[] public expiredEscrows;

    uint256 public constant MAX_CHECK_COUNT = 10;
    uint256 public constant CHECK_INTERVAL = 1 hours;

    /* ─────────────────────────────────────────────
       modifiers
    ───────────────────────────────────────────── */
    modifier onlyAuthorizedAttester() {
        require(authorizedAttesters[msg.sender], "Not authorized attester");
        _;
    }

    modifier validAmount(uint256 amount) {
        require(amount >= minPaymentAmount, "Amount too low");
        require(amount <= maxPaymentAmount, "Amount too high");
        _;
    }

    /* ─────────────────────────────────────────────
       constructor
    ───────────────────────────────────────────── */
    constructor(
        uint256 _minPaymentAmount,
        uint256 _maxPaymentAmount,
        address _settlementRegistry,
        string memory _recipientEmail,
        uint256 _feeBps,
        uint256 _maxEscrowTime,
        uint256 _exchangeRate
    ) Ownable(msg.sender) {
        require(_minPaymentAmount < _maxPaymentAmount, "Invalid limits");
        require(_maxEscrowTime > 0, "Escrow time must be > 0");
        require(_settlementRegistry != address(0), "registry=0");

        minPaymentAmount = _minPaymentAmount;
        maxPaymentAmount = _maxPaymentAmount;
        settlementRegistry = IPayPalRegistry(_settlementRegistry);
        recipientEmail = _recipientEmail;

        authorizedAttesters[msg.sender] = true;

        fee = _feeBps;
        feeRecipient = owner();
        maxEscrowTime = _maxEscrowTime;
        exchangeRate = _exchangeRate;
    }

    receive() external payable {}

    /* ─────────────────────────────────────────────
       views
    ───────────────────────────────────────────── */
    function getFreeBalance() public view returns (uint256) {
        return address(this).balance - totalEscrowed;
    }

    function isEscrowExpired(bytes32 escrowId) public view returns (bool) {
        Payment memory p = payments[escrowId];
        return
            p.payer != address(0) &&
            block.timestamp > p.createdAt + maxEscrowTime;
    }

    function getEscrowIds() external view returns (bytes32[] memory) {
        return escrowIds;
    }

    function getPendingEscrows() external view returns (bytes32[] memory) {
        return pendingEscrows;
    }
    function getCompletedEscrows() external view returns (bytes32[] memory) {
        return completedEscrows;
    }
    function getExchangeRate() external view returns (uint256) {
        return exchangeRate;
    }
    function isFinalized(bytes32 idHash) external view returns (bool) {
        return settlementRegistry.isFinalized(idHash);
    }
    function getSettlementStatus(
        bytes32 idHash
    ) external view returns (IPayPalRegistry.Status) {
        return settlementRegistry.getSettlementStatus(idHash);
    }

    /* ─────────────────────────────────────────────
       admin
    ───────────────────────────────────────────── */
    function withdraw(
        uint256 amount,
        address payable to
    ) external onlyOwner nonReentrant {
        require(to != address(0), "Invalid recipient");
        require(amount <= getFreeBalance(), "Insufficient free balance");
        to.transfer(amount);
    }

    function setFeeRecipient(address newRecipient) external onlyOwner {
        require(newRecipient != address(0), "Invalid fee recipient");
        address old = feeRecipient;
        feeRecipient = newRecipient;
        emit FeeRecipientUpdated(old, newRecipient);
    }

    function updatePaymentLimits(uint256 lo, uint256 hi) external onlyOwner {
        require(lo < hi, "Invalid limits");
        minPaymentAmount = lo;
        maxPaymentAmount = hi;
    }

    function updateExchangeRate(uint256 newRate) external onlyOwner {
        uint256 old = exchangeRate;
        exchangeRate = newRate;
        emit ExchangeRateUpdated(old, newRate);
    }

    function addAuthorizedAttester(address a) external onlyOwner {
        authorizedAttesters[a] = true;
    }
    function removeAuthorizedAttester(address a) external onlyOwner {
        authorizedAttesters[a] = false;
    }

    /* ─────────────────────────────────────────────
       core: init & settle
    ───────────────────────────────────────────── */
    function initPayment(
        bytes32 idHash,
        uint256 amount,
        address payable payableTo
    ) external validAmount(amount) nonReentrant {
        _initPaymentInternal(idHash, amount, payableTo);
    }

    function initPayment(
        bytes32 idHash,
        uint256 amount
    ) external validAmount(amount) nonReentrant {
        _initPaymentInternal(idHash, amount, payable(msg.sender));
    }

    function _initPaymentInternal(
        bytes32 idHash,
        uint256 amount,
        address payable payableTo
    ) internal {
        require(payments[idHash].payer == address(0), "Already initialized");
        require(!_usedEscrowIds[idHash], "Settlement ID already exists");
        require(getFreeBalance() >= amount, "Insufficient free funds");

        // Convert ETH amount (wei) to USD with 6 decimals
        // amount is in wei (1 ETH = 1e18)
        // exchangeRate is USD with 6 decimals per 1 ETH
        // amountUsd is then USD * 1e6
        uint256 amountUsd = (amount * exchangeRate) / 1e18;

        totalEscrowed += amount;
        _usedEscrowIds[idHash] = true;
        escrowIds.push(idHash);

        bytes32 recipientEmailHash = keccak256(bytes(recipientEmail));

        settlementRegistry.initAttest(
            idHash,
            recipientEmailHash,
            msg.sender,
            address(this),
            amountUsd,
            bytes32(0)
        );

        payments[idHash] = Payment({
            payer: msg.sender,
            recipient: payableTo,
            requestedAmount: amount,
            requestedAmountUsd: amountUsd,
            postedAmount: 0,
            postedAmountUsd: 0,
            lastCheckTimestamp: block.timestamp,
            checkCount: 0,
            createdAt: block.timestamp,
            exchangeRateAtInit: exchangeRate
        });

        pendingEscrows.push(idHash);
        pendingIndex[idHash] = pendingEscrows.length;

        emit PaymentInitialized(idHash, msg.sender, amount, amountUsd);
    }

    function settlePayment(bytes32 escrowId) external nonReentrant {
        Payment storage p = payments[escrowId];
        require(p.payer != address(0), "Not initialized");
        require(
            authorizedAttesters[msg.sender] || msg.sender == p.payer,
            "Not authorized"
        );
        require(!isSettled[escrowId], "Already settled");

        if (block.timestamp > p.createdAt + maxEscrowTime) {
            _expire(escrowId, p);
            return;
        }

        require(
            settlementRegistry.isFinalized(escrowId),
            "Registry not finalized"
        );
        require(
            settlementRegistry.getSettlementStatus(escrowId) ==
                IPayPalRegistry.Status.Confirmed,
            "Not confirmed"
        );

        uint256 postedUsd = settlementRegistry.getPostedAmount(escrowId);
        require(postedUsd > 0, "No posted amount");

        // Convert posted USD (6 decimals) back to ETH (wei)
        // postedUsd has 6 decimals
        // exchangeRate has 6 decimals
        // Multiply by 1e18 to scale to wei
        uint256 tokenFromPosted = (postedUsd * 1e18) / p.exchangeRateAtInit;
        uint256 effectiveTokenAmount = tokenFromPosted;

        // Cap by the originally reserved token amount; contract owner can issue PayPal refund if needed
        // PayPal posted amount is almost always less than requested amount due to fees

        if (effectiveTokenAmount > p.requestedAmount) {
            effectiveTokenAmount = p.requestedAmount;
        }

        uint256 feeAmount = (effectiveTokenAmount * fee) / FEE_DENOMINATOR;
        uint256 payoutAmount = effectiveTokenAmount - feeAmount;

        isSettled[escrowId] = true;
        totalEscrowed -= p.requestedAmount;

        p.postedAmountUsd = postedUsd;
        p.postedAmount = effectiveTokenAmount;

        if (payoutAmount > 0) {
            payable(p.recipient).transfer(payoutAmount);
        }
        if (feeAmount > 0) {
            payable(feeRecipient).transfer(feeAmount);
        }

        _removePending(escrowId);
        completedEscrows.push(escrowId);

        emit PaymentSettled(escrowId, p.payer, payoutAmount, postedUsd);
    }

    /* ─────────────────────────────────────────────
       expiry
    ───────────────────────────────────────────── */
    function expireEscrow(bytes32 escrowId) external nonReentrant {
        Payment storage p = payments[escrowId];
        require(p.payer != address(0), "Escrow not initialized");
        require(!isSettled[escrowId], "Already settled");
        require(
            block.timestamp > p.createdAt + maxEscrowTime,
            "Not expired yet"
        );
        _expire(escrowId, p);
    }

    function _expire(bytes32 escrowId, Payment storage p) internal {
        isSettled[escrowId] = true;
        _removePending(escrowId);
        expiredEscrows.push(escrowId);
        totalEscrowed -= p.requestedAmount;
        emit EscrowExpired(escrowId, p.payer, p.requestedAmount);
    }

    function _removePending(bytes32 escrowId) internal {
        uint256 idx1 = pendingIndex[escrowId];
        if (idx1 > 0) {
            uint256 idx0 = idx1 - 1;
            uint256 last = pendingEscrows.length - 1;
            if (idx0 != last) {
                bytes32 lastId = pendingEscrows[last];
                pendingEscrows[idx0] = lastId;
                pendingIndex[lastId] = idx1;
            }
            pendingEscrows.pop();
            delete pendingIndex[escrowId];
        }
    }
}
