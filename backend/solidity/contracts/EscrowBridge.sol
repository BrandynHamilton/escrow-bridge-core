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
        string calldata settlementId,
        SettlementType settlementType,
        bytes32 salt,
        string calldata userEmail,
        string calldata recipientEmail,
        address counterparty,
        address witness,
        uint256 amount,
        string calldata metadata
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

    struct Payment {
        address payer;
        uint256 amount;
        uint256 lastCheckTimestamp;
        uint256 checkCount;
    }

    ISettlementRegistry public immutable settlementRegistry;
    address public usdcToken;
    string public recipientEmail;
    uint256 public minPaymentAmount;
    uint256 public maxPaymentAmount;
    uint256 public fee;

    /// @dev Total raw USDC units locked up by all pending escrows.
    uint256 public totalEscrowed;

    mapping(bytes32 => Payment) public payments;
    mapping(bytes32 => bool) public isSettled;
    mapping(address => bool) public authorizedAttesters;
    mapping(string => bool) private _usedEscrowIds;

    // pending escrows: dynamic list + 1-based index map for efficient removal
    bytes32[] public pendingEscrows;
    mapping(bytes32 => uint256) private pendingIndex; // idHash => index+1 in pendingEscrows

    // completed escrows: just a list
    bytes32[] public completedEscrows;

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
        uint256 _fee
    ) Ownable(msg.sender) {
        require(_minPaymentAmount < _maxPaymentAmount, "Invalid limits");
        minPaymentAmount = _minPaymentAmount;
        maxPaymentAmount = _maxPaymentAmount;
        settlementRegistry = ISettlementRegistry(_settlementRegistry);
        recipientEmail = _recipientEmail;
        usdcToken = _usdcToken;
        authorizedAttesters[msg.sender] = true;
        fee = _fee;
    }

    receive() external payable {}

    /// @dev Returns how many raw USDC tokens this contract currently holds.
    function getUsdcBalance() public view returns (uint256) {
        return
            usdcToken == address(0)
                ? address(this).balance
                : IERC20(usdcToken).balanceOf(address(this));
    }

    /// @notice Owner can top up the contract’s USDC pool.
    function fundEscrow(uint256 amount) external onlyOwner {
        require(usdcToken != address(0), "ERC20 only");
        IERC20(usdcToken).safeTransferFrom(msg.sender, address(this), amount);
    }

    /// @notice Create a new escrow, reserving exactly `amount` raw USDC units
    ///         so that those tokens cannot be used by any other pending escrow.
    function initPayment(
        string calldata escrowId,
        bytes32 salt,
        string calldata userEmail,
        uint256 amount
    ) external validAmount(amount) nonReentrant {
        bytes32 idHash = keccak256(abi.encodePacked(salt, escrowId));
        // 1) Must not already have created this escrow
        require(payments[idHash].payer == address(0), "Already initialized");
        require(!_usedEscrowIds[escrowId], "Settlement ID already exists");

        // 2) Reserve the funds: check free balance = totalBalance - totalEscrowed
        uint256 rawBalance = getUsdcBalance();
        uint256 freeBalance = rawBalance - totalEscrowed;
        require(freeBalance >= amount, "Insufficient free funds");

        totalEscrowed += amount;
        _usedEscrowIds[escrowId] = true;

        // 3) Notify the registry that a new escrow is initialized
        settlementRegistry.initAttest(
            escrowId,
            ISettlementRegistry.SettlementType.Paypal,
            salt,
            userEmail,
            recipientEmail,
            msg.sender,
            address(this),
            amount,
            ""
        );

        // 4) Record this escrow locally, add to pending
        payments[idHash] = Payment({
            payer: msg.sender,
            amount: amount,
            lastCheckTimestamp: block.timestamp,
            checkCount: 0
        });
        pendingEscrows.push(idHash);
        pendingIndex[idHash] = pendingEscrows.length; // 1-based

        emit PaymentInitialized(idHash, msg.sender, amount);
    }

    /// @notice Once the registry marks a given escrow “Confirmed,” pay out and free its reservation.
    function settlePayment(bytes32 escrowId) external nonReentrant {
        Payment storage p = payments[escrowId];
        require(
            authorizedAttesters[msg.sender] || msg.sender == p.payer,
            "Not authorized to settle"
        );
        require(p.payer != address(0), "Not initialized");
        require(!isSettled[escrowId], "Already settled");

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

        if (usdcToken == address(0)) {
            payable(p.payer).transfer(p.amount);
        } else {
            IERC20(usdcToken).safeTransfer(p.payer, p.amount);
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

    /// @notice Allows authorized attesters to withdraw any unreserved USDC (or ETH) from the contract.
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

    /// @notice Exposes settlement status from the registry for a given idHash
    function getSettlementStatus(
        bytes32 idHash
    ) external view returns (ISettlementRegistry.Status) {
        return settlementRegistry.getSettlementStatus(idHash);
    }

    /// @notice Exposes settlement amount from the registry for a given idHash
    function getSettlementAmount(
        bytes32 idHash
    ) external view returns (uint256) {
        return settlementRegistry.getSettlementAmount(idHash);
    }

    /// @notice Exposes settlement counterparty from the registry for a given idHash
    function getSettlementCounterparty(
        bytes32 idHash
    ) external view returns (address) {
        return settlementRegistry.getSettlementCounterparty(idHash);
    }

    /// @notice List all escrow idHashes that have been initialized but not yet settled
    function getPendingEscrows() external view returns (bytes32[] memory) {
        return pendingEscrows;
    }

    /// @notice List all escrow idHashes that have already been paid out
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
