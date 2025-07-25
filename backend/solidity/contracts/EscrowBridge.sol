// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/security/ReentrancyGuard.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";

interface ISettlementRegistry {
    enum Status {
        Initialized,
        Registered,
        Attested,
        Confirmed,
        Failed
    }
    enum SettlementType {
        Paypal,
        Plaid,
        DocuSign,
        Github,
        Other
    }

    function initAttest(
        bytes32 idHash,
        SettlementType settlementType,
        bytes32 emailHash,
        bytes32 recipientEmailHash,
        address counterparty,
        address witness,
        uint256 amount,
        bytes32 metadataHash
    ) external;

    function getSettlementStatus(bytes32 idHash) external view returns (Status);
    function getSettlementAmount(
        bytes32 idHash
    ) external view returns (uint256);
    function getSettlementCounterparty(
        bytes32 idHash
    ) external view returns (address);
}

contract EscrowBridge is Ownable, ReentrancyGuard {
    using SafeERC20 for IERC20;

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

    event FeeRecipientUpdated(address oldRecipient, address newRecipient);
    event EscrowExpired(
        bytes32 indexed escrowId,
        address indexed payer,
        uint256 amount
    );

    struct Payment {
        address payer;
        address recipient;
        uint256 amount;
        uint256 lastCheckTimestamp;
        uint256 checkCount;
        uint256 createdAt;
    }

    ISettlementRegistry public immutable settlementRegistry;
    address public usdcToken;
    string public recipientEmail;
    uint256 public minPaymentAmount;
    uint256 public maxPaymentAmount;
    uint256 public fee;
    address public feeRecipient;
    uint256 public maxEscrowTime; // in seconds
    uint256 public constant FEE_DENOMINATOR = 10000; // 100% = 10000 bps

    uint256 public totalEscrowed;

    mapping(bytes32 => Payment) public payments;
    mapping(bytes32 => bool) public isSettled;
    mapping(address => bool) public authorizedAttesters;
    mapping(bytes32 => bool) private _usedEscrowIds;

    bytes32[] public pendingEscrows;
    mapping(bytes32 => uint256) private pendingIndex;

    bytes32[] public completedEscrows;
    bytes32[] public expiredEscrows;

    uint256 public constant MAX_CHECK_COUNT = 10;
    uint256 public constant CHECK_INTERVAL = 1 hours;

    modifier onlyAuthorizedAttester() {
        require(authorizedAttesters[msg.sender], "Not authorized attester");
        _;
    }
    modifier validAmount(uint256 amount) {
        require(amount >= minPaymentAmount, "Amount too low");
        require(amount <= maxPaymentAmount, "Amount too high");
        _;
    }

    constructor(
        uint256 _minPaymentAmount,
        uint256 _maxPaymentAmount,
        address _settlementRegistry,
        string memory _recipientEmail,
        address _usdcToken,
        uint256 _fee,
        uint256 _maxEscrowTime
    ) Ownable(msg.sender) {
        require(_minPaymentAmount < _maxPaymentAmount, "Invalid limits");
        require(_maxEscrowTime > 0, "Escrow time must be > 0");
        minPaymentAmount = _minPaymentAmount;
        maxPaymentAmount = _maxPaymentAmount;
        settlementRegistry = ISettlementRegistry(_settlementRegistry);
        recipientEmail = _recipientEmail;
        usdcToken = _usdcToken;
        authorizedAttesters[msg.sender] = true;
        fee = _fee;
        feeRecipient = owner();
        maxEscrowTime = _maxEscrowTime;
    }

    receive() external payable {}

    function getUsdcBalance() public view returns (uint256) {
        return
            usdcToken == address(0)
                ? address(this).balance
                : IERC20(usdcToken).balanceOf(address(this));
    }

    function fundEscrow(uint256 amount) external onlyOwner {
        require(usdcToken != address(0), "ERC20 only");
        IERC20(usdcToken).safeTransferFrom(msg.sender, address(this), amount);
    }

    function initPayment(
        bytes32 idHash,
        bytes32 emailHash,
        uint256 amount,
        address payableTo
    ) external validAmount(amount) nonReentrant {
        _initPaymentInternal(idHash, emailHash, amount, payableTo);
    }

    // Backward-compatible version that defaults to msg.sender
    function initPayment(
        bytes32 idHash,
        bytes32 emailHash,
        uint256 amount
    ) external validAmount(amount) nonReentrant {
        _initPaymentInternal(idHash, emailHash, amount, msg.sender);
    }

    // Shared internal logic
    function _initPaymentInternal(
        bytes32 idHash,
        bytes32 emailHash,
        uint256 amount,
        address payableTo
    ) internal {
        require(payments[idHash].payer == address(0), "Already initialized");
        require(!_usedEscrowIds[idHash], "Settlement ID already exists");

        uint256 rawBalance = getUsdcBalance();
        uint256 freeBalance = rawBalance - totalEscrowed;
        require(freeBalance >= amount, "Insufficient free funds");

        totalEscrowed += amount;
        _usedEscrowIds[idHash] = true;

        bytes32 recipientEmailHash = keccak256(bytes(recipientEmail));

        settlementRegistry.initAttest(
            idHash,
            ISettlementRegistry.SettlementType.Paypal,
            emailHash,
            recipientEmailHash,
            msg.sender,
            address(this),
            amount,
            bytes32(0)
        );

        payments[idHash] = Payment({
            payer: msg.sender,
            recipient: payableTo,
            amount: amount,
            lastCheckTimestamp: block.timestamp,
            checkCount: 0,
            createdAt: block.timestamp
        });

        pendingEscrows.push(idHash);
        pendingIndex[idHash] = pendingEscrows.length;

        emit PaymentInitialized(idHash, msg.sender, amount);
    }

    function settlePayment(bytes32 escrowId) external nonReentrant {
        Payment storage p = payments[escrowId];
        require(
            authorizedAttesters[msg.sender] || msg.sender == p.payer,
            "Not authorized to settle"
        );
        require(p.payer != address(0), "Not initialized");
        require(!isSettled[escrowId], "Already settled");

        // Check if expired
        if (block.timestamp > p.createdAt + maxEscrowTime) {
            // Mark as settled to prevent re-use
            isSettled[escrowId] = true;

            // Remove from pending
            uint256 idx1 = pendingIndex[escrowId];
            if (idx1 > 0) {
                uint256 idx0 = idx1 - 1;
                uint256 last0 = pendingEscrows.length - 1;
                if (idx0 != last0) {
                    bytes32 lastId = pendingEscrows[last0];
                    pendingEscrows[idx0] = lastId;
                    pendingIndex[lastId] = idx1;
                }
                pendingEscrows.pop();
                delete pendingIndex[escrowId];
            }

            expiredEscrows.push(escrowId);
            totalEscrowed -= p.amount; // Adjust total escrowed amount
            emit EscrowExpired(escrowId, p.payer, p.amount);
            return;
        }

        ISettlementRegistry.Status status = settlementRegistry
            .getSettlementStatus(escrowId);
        require(
            status == ISettlementRegistry.Status.Confirmed,
            "Not confirmed"
        );

        uint256 onchainAmount = settlementRegistry.getSettlementAmount(
            escrowId
        );
        require(onchainAmount == p.amount, "Amount mismatch");

        totalEscrowed -= p.amount;
        isSettled[escrowId] = true;

        uint256 feeAmount = (p.amount * fee) / FEE_DENOMINATOR;
        uint256 payoutAmount = p.amount - feeAmount;

        if (usdcToken == address(0)) {
            payable(p.recipient).transfer(payoutAmount);
        } else {
            IERC20(usdcToken).safeTransfer(p.recipient, payoutAmount);
        }

        if (feeAmount > 0) {
            if (usdcToken == address(0)) {
                payable(feeRecipient).transfer(feeAmount);
            } else {
                IERC20(usdcToken).safeTransfer(feeRecipient, feeAmount);
            }
        }

        uint256 idx1 = pendingIndex[escrowId];
        require(idx1 > 0, "Not pending");
        uint256 idx0 = idx1 - 1;
        uint256 last0 = pendingEscrows.length - 1;
        if (idx0 != last0) {
            bytes32 lastId = pendingEscrows[last0];
            pendingEscrows[idx0] = lastId;
            pendingIndex[lastId] = idx1;
        }
        pendingEscrows.pop();
        delete pendingIndex[escrowId];

        completedEscrows.push(escrowId);
        emit PaymentSettled(escrowId, p.payer, p.amount);
    }

    function withdraw(
        uint256 amount,
        address to
    ) external onlyOwner nonReentrant {
        require(to != address(0), "Invalid recipient");
        uint256 rawBalance = getUsdcBalance();
        uint256 freeBalance = rawBalance - totalEscrowed;
        require(amount <= freeBalance, "Insufficient free balance");

        if (usdcToken == address(0)) {
            payable(to).transfer(amount);
        } else {
            IERC20(usdcToken).safeTransfer(to, amount);
        }
    }

    function expireEscrow(bytes32 escrowId) external nonReentrant {
        Payment storage p = payments[escrowId];
        require(p.payer != address(0), "Escrow not initialized");
        require(!isSettled[escrowId], "Already settled");
        require(
            block.timestamp > p.createdAt + maxEscrowTime,
            "Not expired yet"
        );

        isSettled[escrowId] = true;

        uint256 idx1 = pendingIndex[escrowId];
        if (idx1 > 0) {
            uint256 idx0 = idx1 - 1;
            uint256 last0 = pendingEscrows.length - 1;
            if (idx0 != last0) {
                bytes32 lastId = pendingEscrows[last0];
                pendingEscrows[idx0] = lastId;
                pendingIndex[lastId] = idx1;
            }
            pendingEscrows.pop();
            delete pendingIndex[escrowId];
        }

        expiredEscrows.push(escrowId);
        totalEscrowed -= p.amount;
        emit EscrowExpired(escrowId, p.payer, p.amount);
    }

    function getFreeBalance() public view returns (uint256) {
        uint256 rawBalance = getUsdcBalance();
        return rawBalance - totalEscrowed;
    }

    function isEscrowExpired(bytes32 escrowId) public view returns (bool) {
        Payment memory p = payments[escrowId];
        return block.timestamp > p.createdAt + maxEscrowTime;
    }

    function setFeeRecipient(address newRecipient) external onlyOwner {
        require(newRecipient != address(0), "Invalid fee recipient");
        feeRecipient = newRecipient;
        emit FeeRecipientUpdated(feeRecipient, newRecipient);
    }

    function getSettlementStatus(
        bytes32 idHash
    ) external view returns (ISettlementRegistry.Status) {
        return settlementRegistry.getSettlementStatus(idHash);
    }

    function getSettlementAmount(
        bytes32 idHash
    ) external view returns (uint256) {
        return settlementRegistry.getSettlementAmount(idHash);
    }

    function getSettlementCounterparty(
        bytes32 idHash
    ) external view returns (address) {
        return settlementRegistry.getSettlementCounterparty(idHash);
    }

    function getPendingEscrows() external view returns (bytes32[] memory) {
        return pendingEscrows;
    }

    function getCompletedEscrows() external view returns (bytes32[] memory) {
        return completedEscrows;
    }

    function addAuthorizedAttester(address a) external onlyOwner {
        authorizedAttesters[a] = true;
    }

    function removeAuthorizedAttester(address a) external onlyOwner {
        authorizedAttesters[a] = false;
    }

    function updatePaymentLimits(uint256 lo, uint256 hi) external onlyOwner {
        require(lo < hi, "Invalid");
        minPaymentAmount = lo;
        maxPaymentAmount = hi;
    }
}
