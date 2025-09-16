// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";

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

    // New getters aligned with your PayPalRegistry
    function getSettlementStatus(bytes32 idHash) external view returns (Status);
    function getRequestedAmount(bytes32 idHash) external view returns (uint256);
    function getPostedAmount(bytes32 idHash) external view returns (uint256);
    function isFinalized(bytes32 idHash) external view returns (bool);

    // If you need to cross-check participant addresses
    function getSettlementParticipants(
        bytes32 idHash
    )
        external
        view
        returns (address sender, address counterparty, address witness);
}

contract EscrowBridge is Ownable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    /* ─────────────────────────────────────────────
       events
    ───────────────────────────────────────────── */
    event PaymentInitialized(
        bytes32 indexed escrowId,
        address indexed payer,
        uint256 amountRequestedTokens,
        uint256 amountRequestedUsd
    );
    event PaymentSettled(
        bytes32 indexed escrowId,
        address indexed payer,
        uint256 payoutTokensAfterDeskFee,
        uint256 postedUsdFromRegistry
    );
    event EscrowExpired(
        bytes32 indexed escrowId,
        address indexed payer,
        uint256 amountReservedTokens
    );
    event FeeRecipientUpdated(address oldRecipient, address newRecipient);
    event ExchangeRateUpdated(uint256 oldRate, uint256 newRate);

    /* ─────────────────────────────────────────────
       storage
    ───────────────────────────────────────────── */
    struct Payment {
        address payer; // who initiated the escrow
        address recipient; // who receives tokens when settled
        uint256 requestedAmount; // tokens reserved up front (token decimals)
        uint256 requestedAmountUsd; // computed at init using exchangeRate (USD 6-decimals)
        uint256 postedAmount; // tokens derived from registry.postedAmount (USD) using exchangeRate at settle time
        uint256 postedAmountUsd; // registry.postedAmount (USD, after PayPal fees)
        uint256 lastCheckTimestamp;
        uint256 checkCount;
        uint256 createdAt;
        uint256 exchangeRateAtInit;
    }

    IPayPalRegistry public immutable settlementRegistry;
    address public immutable usdcToken; // token paid out by this escrow (e.g., USDC)
    string public recipientEmail;

    uint256 public minPaymentAmount; // min token amount (token decimals)
    uint256 public maxPaymentAmount; // max token amount (token decimals)
    uint256 public fee; // desk fee in bps (out of FEE_DENOMINATOR)
    address public feeRecipient;

    uint256 public maxEscrowTime; // seconds
    uint256 public constant FEE_DENOMINATOR = 10000; // 100% = 10000 bps

    /**
     * @notice exchangeRate = USD(6 decimals) per 1 token unit (token has 6 decimals too in typical USDC).
     * For USDC, set exchangeRate = 1e6 (i.e., $1.000000 per 1 USDC).
     */
    uint256 public exchangeRate;

    uint256 public totalEscrowed; // total tokens reserved (requestedAmount sum of all active escrows)

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
        address _usdcToken,
        uint256 _feeBps,
        uint256 _maxEscrowTime,
        uint256 _exchangeRate // USD(6) per 1 token
    ) Ownable(msg.sender) {
        require(_minPaymentAmount < _maxPaymentAmount, "Invalid limits");
        require(_maxEscrowTime > 0, "Escrow time must be > 0");
        require(_settlementRegistry != address(0), "registry=0");
        require(_usdcToken != address(0), "token=0");

        minPaymentAmount = _minPaymentAmount;
        maxPaymentAmount = _maxPaymentAmount;
        settlementRegistry = IPayPalRegistry(_settlementRegistry);
        recipientEmail = _recipientEmail;
        usdcToken = _usdcToken;

        authorizedAttesters[msg.sender] = true;

        fee = _feeBps;
        feeRecipient = owner();
        maxEscrowTime = _maxEscrowTime;
        exchangeRate = _exchangeRate;
    }

    receive() external payable {}

    /* ─────────────────────────────────────────────
       views & helpers
    ───────────────────────────────────────────── */
    function getUsdcBalance() public view returns (uint256) {
        return IERC20(usdcToken).balanceOf(address(this));
    }

    function getFreeBalance() public view returns (uint256) {
        uint256 rawBalance = getUsdcBalance();
        return rawBalance - totalEscrowed;
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
        bool finalized = settlementRegistry.isFinalized(idHash);
        return finalized;
    }

    function getSettlementStatus(
        bytes32 idHash
    ) external view returns (IPayPalRegistry.Status) {
        return settlementRegistry.getSettlementStatus(idHash);
    }

    /* ─────────────────────────────────────────────
       admin: balances & params
    ───────────────────────────────────────────── */
    function fundEscrow(uint256 amount) external onlyOwner {
        IERC20(usdcToken).safeTransferFrom(msg.sender, address(this), amount);
    }

    function withdraw(
        uint256 amount,
        address to
    ) external onlyOwner nonReentrant {
        require(to != address(0), "Invalid recipient");
        uint256 freeBalance = getFreeBalance();
        require(amount <= freeBalance, "Insufficient free balance");
        IERC20(usdcToken).safeTransfer(to, amount);
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

    /// EOA-style oracle updater for price (USD(6) per 1 token)
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
        uint256 amount, // token units (e.g., USDC 6 decimals)
        address payableTo // recipient of tokens upon settlement
    ) external validAmount(amount) nonReentrant {
        _initPaymentInternal(idHash, amount, payableTo);
    }

    // Backward-compatible: default to msg.sender as recipient
    function initPayment(
        bytes32 idHash,
        uint256 amount
    ) external validAmount(amount) nonReentrant {
        _initPaymentInternal(idHash, amount, msg.sender);
    }

    function _initPaymentInternal(
        bytes32 idHash,
        uint256 amount,
        address payableTo
    ) internal {
        require(payments[idHash].payer == address(0), "Already initialized");
        require(!_usedEscrowIds[idHash], "Settlement ID already exists");

        // Ensure we have unreserved balance to cover this requested amount
        uint256 freeBalance = getFreeBalance();
        require(freeBalance >= amount, "Insufficient free funds");

        // Convert requested token amount to USD using current oracle
        // USD(6) = token(6) * rate(6) / 1e6
        uint256 amountUsd = (amount * exchangeRate) / 1e6;

        totalEscrowed += amount;
        _usedEscrowIds[idHash] = true;
        escrowIds.push(idHash);

        bytes32 recipientEmailHash = keccak256(bytes(recipientEmail));

        // Initialize settlement in the registry
        settlementRegistry.initAttest(
            idHash,
            recipientEmailHash,
            msg.sender, // counterparty
            address(this), // witness
            amountUsd, // "requested amount (USD)" to registry
            bytes32(0) // metadataHash (none)
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

        // Track as pending
        pendingEscrows.push(idHash);
        pendingIndex[idHash] = pendingEscrows.length; // 1-based index

        emit PaymentInitialized(idHash, msg.sender, amount, amountUsd);
    }

    /**
     * @dev Settle after registry is Confirmed & Finalized:
     * - Reads posted USD amount (after PayPal fees) from registry
     * - Converts posted USD to token units using current exchangeRate
     * - Applies desk fee bps to that token amount
     * - Caps payout to the originally reserved (requested) token amount
     * - Releases funds and updates accounting
     */
    function settlePayment(bytes32 escrowId) external nonReentrant {
        Payment storage p = payments[escrowId];
        require(p.payer != address(0), "Not initialized");
        require(
            authorizedAttesters[msg.sender] || msg.sender == p.payer,
            "Not authorized to settle"
        );
        require(!isSettled[escrowId], "Already settled");

        // Expiry check first
        if (block.timestamp > p.createdAt + maxEscrowTime) {
            _expire(escrowId, p);
            return;
        }

        // Require registry is finalized & confirmed
        bool finalized = settlementRegistry.isFinalized(escrowId);
        require(finalized, "Registry not finalized");

        IPayPalRegistry.Status status = settlementRegistry.getSettlementStatus(
            escrowId
        );
        require(status == IPayPalRegistry.Status.Confirmed, "Not confirmed");

        // Read posted USD (after PayPal fees) and convert to token units using current exchangeRate
        uint256 postedUsd = settlementRegistry.getPostedAmount(escrowId); // USD(6)
        require(postedUsd > 0, "No posted amount");

        // token(6) = USD(6) * 1e6 / rate(6)
        uint256 tokenFromPosted = (postedUsd * 1e6) / p.exchangeRateAtInit;

        // Cap by the originally reserved token amount
        // PayPal posted amount is almost always less than requested amount due to fees

        uint256 effectiveTokenAmount = tokenFromPosted;
        if (effectiveTokenAmount > p.requestedAmount) {
            effectiveTokenAmount = p.requestedAmount;
        }

        // Apply desk fee bps to effectiveTokenAmount
        uint256 feeAmount = (effectiveTokenAmount * fee) / FEE_DENOMINATOR;
        uint256 payoutAmount = effectiveTokenAmount - feeAmount;

        // Mark settled before external calls
        isSettled[escrowId] = true;

        // Unreserve the originally requested amount (we reserved that much in totalEscrowed)
        totalEscrowed -= p.requestedAmount;

        // Persist posted amounts for record
        p.postedAmountUsd = postedUsd;
        p.postedAmount = effectiveTokenAmount;

        // Transfers
        if (payoutAmount > 0) {
            IERC20(usdcToken).safeTransfer(p.recipient, payoutAmount);
        }
        if (feeAmount > 0) {
            IERC20(usdcToken).safeTransfer(feeRecipient, feeAmount);
        }

        // Remove from pending
        _removePending(escrowId);

        // Mark complete
        completedEscrows.push(escrowId);

        emit PaymentSettled(escrowId, p.payer, payoutAmount, postedUsd);
    }

    /* ─────────────────────────────────────────────
       expiry flow
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

        // Unreserve the requested tokens (they remain in contract free balance)
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
