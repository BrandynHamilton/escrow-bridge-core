// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";

interface IDocusignRegistry {
    enum Status {
        Initialized,
        Registered,
        Attested,
        Confirmed,
        Failed
    }

    function initAttest(
        bytes32 idHash,
        bytes32 metadataHash,
        string calldata assetName,
        string calldata assetTag,
        string calldata geoId,
        string calldata jurisdiction,
        string calldata documentURI,
        address counterparty,
        address witness
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

contract DocusignEscrow is Ownable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    /* ─────────────────────────────────────────────
       events
    ───────────────────────────────────────────── */
    event PaymentInitialized(
        bytes32 indexed escrowId,
        address indexed payer,
        uint256 amount
    );
    event PaymentSettled(
        bytes32 indexed escrowId,
        address indexed payer,
        uint256 amount
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
    struct Escrow {
        address payer; // who initiated the escrow
        address recipient; // who receives tokens when settled
        uint256 amount; // tokens reserved up front (token decimals)
        uint256 lastCheckTimestamp;
        uint256 checkCount;
        uint256 createdAt;
    }

    IDocusignRegistry public immutable settlementRegistry;
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
    uint256 public totalEscrowed; // total tokens reserved (requestedAmount sum of all active escrows)

    mapping(bytes32 => Escrow) public escrows;
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
        uint256 _maxEscrowTime
    ) Ownable(msg.sender) {
        require(_minPaymentAmount < _maxPaymentAmount, "Invalid limits");
        require(_maxEscrowTime > 0, "Escrow time must be > 0");
        require(_settlementRegistry != address(0), "registry=0");
        require(_usdcToken != address(0), "token=0");

        minPaymentAmount = _minPaymentAmount;
        maxPaymentAmount = _maxPaymentAmount;
        settlementRegistry = IDocusignRegistry(_settlementRegistry);
        recipientEmail = _recipientEmail;
        usdcToken = _usdcToken;

        authorizedAttesters[msg.sender] = true;

        fee = _feeBps;
        feeRecipient = owner();
        maxEscrowTime = _maxEscrowTime;
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
        Escrow memory e = escrows[escrowId];
        return
            e.payer != address(0) &&
            block.timestamp > e.createdAt + maxEscrowTime;
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

    function isFinalized(bytes32 idHash) external view returns (bool) {
        bool finalized = settlementRegistry.isFinalized(idHash);
        return finalized;
    }

    function getSettlementStatus(
        bytes32 idHash
    ) external view returns (IDocusignRegistry.Status) {
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

    function addAuthorizedAttester(address a) external onlyOwner {
        authorizedAttesters[a] = true;
    }

    function removeAuthorizedAttester(address a) external onlyOwner {
        authorizedAttesters[a] = false;
    }

    /* ─────────────────────────────────────────────
       core: init & settle
    ───────────────────────────────────────────── */

    function initEscrow(
        uint256 amount,
        address payableTo
    ) external nonReentrant validAmount(amount) {
        bytes32 escrowId = keccak256(
            abi.encodePacked(msg.sender, payableTo, amount, block.timestamp)
        );
        require(escrows[escrowId].payer == address(0), "Already initialized");
        require(!_usedEscrowIds[escrowId], "Escrow ID already exists");

        IERC20(usdcToken).safeTransferFrom(msg.sender, address(this), amount);

        totalEscrowed += amount;
        _usedEscrowIds[escrowId] = true;
        escrowIds.push(escrowId);

        // Call registry init
        settlementRegistry.initAttest(
            escrowId,
            bytes32(0), // metadataHash
            "", // assetName
            "", // assetTag
            "", // geoId
            "", // jurisdiction
            "", // documentURI
            msg.sender, // counterparty
            address(this) // witness
        );

        escrows[escrowId] = Escrow({
            payer: msg.sender,
            recipient: payableTo,
            amount: amount,
            lastCheckTimestamp: block.timestamp,
            checkCount: 0,
            createdAt: block.timestamp
        });

        pendingEscrows.push(escrowId);
        pendingIndex[escrowId] = pendingEscrows.length;

        emit PaymentInitialized(escrowId, msg.sender, amount);
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
        Escrow storage e = escrows[escrowId];
        require(e.payer != address(0), "Not initialized");
        require(
            authorizedAttesters[msg.sender] || msg.sender == e.payer,
            "Not authorized to settle"
        );
        require(!isSettled[escrowId], "Already settled");

        // Expiry check first
        if (block.timestamp > e.createdAt + maxEscrowTime) {
            _expire(escrowId, e);
            return;
        }

        // Require registry is finalized & confirmed
        bool finalized = settlementRegistry.isFinalized(escrowId);
        require(finalized, "Registry not finalized");

        IDocusignRegistry.Status status = settlementRegistry
            .getSettlementStatus(escrowId);
        require(status == IDocusignRegistry.Status.Confirmed, "Not confirmed");

        uint256 escrowAmount = e.amount;

        uint256 feeAmount = (escrowAmount * fee) / FEE_DENOMINATOR;

        // Transfers
        if (escrowAmount > 0) {
            IERC20(usdcToken).safeTransfer(e.recipient, escrowAmount);
        }
        if (feeAmount > 0) {
            IERC20(usdcToken).safeTransfer(feeRecipient, feeAmount);
        }

        // Remove from pending
        _removePending(escrowId);

        // Mark complete
        completedEscrows.push(escrowId);

        emit PaymentSettled(escrowId, e.payer, escrowAmount);
    }

    /* ─────────────────────────────────────────────
       expiry flow
    ───────────────────────────────────────────── */
    function expireEscrow(bytes32 escrowId) external nonReentrant {
        Escrow storage e = escrows[escrowId];
        require(e.payer != address(0), "Escrow not initialized");
        require(!isSettled[escrowId], "Already settled");
        require(
            block.timestamp > e.createdAt + maxEscrowTime,
            "Not expired yet"
        );

        _expire(escrowId, e);
    }

    function closeEscrow(bytes32 escrowId) external nonReentrant {
        Escrow storage e = escrows[escrowId];
        require(e.payer != address(0), "Escrow not initialized");
        require(!isSettled[escrowId], "Already settled");
        require(msg.sender == e.payer, "Only payer can close");

        _expire(escrowId, e);
    }

    function _expire(bytes32 escrowId, Escrow storage e) internal {
        isSettled[escrowId] = true;
        _removePending(escrowId);
        expiredEscrows.push(escrowId);

        totalEscrowed -= e.amount;

        IERC20(usdcToken).safeTransfer(e.payer, e.amount);

        emit EscrowExpired(escrowId, e.payer, e.amount);
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
