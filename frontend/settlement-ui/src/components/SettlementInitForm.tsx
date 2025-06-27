import { useState } from "react";
import { ethers } from "ethers";
import { Input } from "../components/ui/input";
import { Button } from "../components/ui/button";
import './styles/index.css'; 

const BRIDGE_ADDRESS = "0x0460f6f3C3448Cda1E9C6d54ebFA99D7C8f0C168"; 

const ERC20_ABI = [
  {
    constant: true,
    inputs: [{ name: "account", type: "address" }],
    name: "balanceOf",
    outputs: [{ name: "", type: "uint256" }],
    type: "function",
  },
  {
    constant: true,
    inputs: [],
    name: "decimals",
    outputs: [{ name: "", type: "uint8" }],
    type: "function",
  },
  {
    constant: true,
    inputs: [
      { name: "owner", type: "address" },
      { name: "spender", type: "address" },
    ],
    name: "allowance",
    outputs: [{ name: "", type: "uint256" }],
    type: "function",
  },
  {
    constant: false,
    inputs: [
      { name: "spender", type: "address" },
      { name: "amount", type: "uint256" },
    ],
    name: "approve",
    outputs: [{ name: "", type: "bool" }],
    type: "function",
  },
  {
    constant: false,
    inputs: [
      { name: "to", type: "address" },
      { name: "value", type: "uint256" },
    ],
    name: "transfer",
    outputs: [{ name: "", type: "bool" }],
    type: "function",
  },
];
const RAMP_ABI = [
	{
		"inputs": [
			{
				"internalType": "address",
				"name": "a",
				"type": "address"
			}
		],
		"name": "addAuthorizedAttester",
		"outputs": [],
		"stateMutability": "nonpayable",
		"type": "function"
	},
	{
		"inputs": [
			{
				"internalType": "bytes32",
				"name": "escrowId",
				"type": "bytes32"
			}
		],
		"name": "expireEscrow",
		"outputs": [],
		"stateMutability": "nonpayable",
		"type": "function"
	},
	{
		"inputs": [
			{
				"internalType": "uint256",
				"name": "amount",
				"type": "uint256"
			}
		],
		"name": "fundEscrow",
		"outputs": [],
		"stateMutability": "nonpayable",
		"type": "function"
	},
	{
		"inputs": [
			{
				"internalType": "bytes32",
				"name": "idHash",
				"type": "bytes32"
			},
			{
				"internalType": "bytes32",
				"name": "emailHash",
				"type": "bytes32"
			},
			{
				"internalType": "uint256",
				"name": "amount",
				"type": "uint256"
			}
		],
		"name": "initPayment",
		"outputs": [],
		"stateMutability": "nonpayable",
		"type": "function"
	},
	{
		"inputs": [
			{
				"internalType": "uint256",
				"name": "_minPaymentAmount",
				"type": "uint256"
			},
			{
				"internalType": "uint256",
				"name": "_maxPaymentAmount",
				"type": "uint256"
			},
			{
				"internalType": "address",
				"name": "_settlementRegistry",
				"type": "address"
			},
			{
				"internalType": "string",
				"name": "_recipientEmail",
				"type": "string"
			},
			{
				"internalType": "address",
				"name": "_usdcToken",
				"type": "address"
			},
			{
				"internalType": "uint256",
				"name": "_fee",
				"type": "uint256"
			},
			{
				"internalType": "uint256",
				"name": "_maxEscrowTime",
				"type": "uint256"
			}
		],
		"stateMutability": "nonpayable",
		"type": "constructor"
	},
	{
		"inputs": [
			{
				"internalType": "address",
				"name": "owner",
				"type": "address"
			}
		],
		"name": "OwnableInvalidOwner",
		"type": "error"
	},
	{
		"inputs": [
			{
				"internalType": "address",
				"name": "account",
				"type": "address"
			}
		],
		"name": "OwnableUnauthorizedAccount",
		"type": "error"
	},
	{
		"inputs": [
			{
				"internalType": "address",
				"name": "token",
				"type": "address"
			}
		],
		"name": "SafeERC20FailedOperation",
		"type": "error"
	},
	{
		"anonymous": false,
		"inputs": [
			{
				"indexed": true,
				"internalType": "bytes32",
				"name": "escrowId",
				"type": "bytes32"
			},
			{
				"indexed": true,
				"internalType": "address",
				"name": "payer",
				"type": "address"
			},
			{
				"indexed": false,
				"internalType": "uint256",
				"name": "amount",
				"type": "uint256"
			}
		],
		"name": "EscrowExpired",
		"type": "event"
	},
	{
		"anonymous": false,
		"inputs": [
			{
				"indexed": false,
				"internalType": "address",
				"name": "oldRecipient",
				"type": "address"
			},
			{
				"indexed": false,
				"internalType": "address",
				"name": "newRecipient",
				"type": "address"
			}
		],
		"name": "FeeRecipientUpdated",
		"type": "event"
	},
	{
		"anonymous": false,
		"inputs": [
			{
				"indexed": true,
				"internalType": "address",
				"name": "previousOwner",
				"type": "address"
			},
			{
				"indexed": true,
				"internalType": "address",
				"name": "newOwner",
				"type": "address"
			}
		],
		"name": "OwnershipTransferred",
		"type": "event"
	},
	{
		"anonymous": false,
		"inputs": [
			{
				"indexed": true,
				"internalType": "bytes32",
				"name": "escrowId",
				"type": "bytes32"
			},
			{
				"indexed": true,
				"internalType": "address",
				"name": "payer",
				"type": "address"
			},
			{
				"indexed": false,
				"internalType": "uint256",
				"name": "amount",
				"type": "uint256"
			}
		],
		"name": "PaymentInitialized",
		"type": "event"
	},
	{
		"anonymous": false,
		"inputs": [
			{
				"indexed": true,
				"internalType": "bytes32",
				"name": "escrowId",
				"type": "bytes32"
			},
			{
				"indexed": true,
				"internalType": "address",
				"name": "payer",
				"type": "address"
			},
			{
				"indexed": false,
				"internalType": "uint256",
				"name": "amount",
				"type": "uint256"
			}
		],
		"name": "PaymentSettled",
		"type": "event"
	},
	{
		"inputs": [
			{
				"internalType": "address",
				"name": "a",
				"type": "address"
			}
		],
		"name": "removeAuthorizedAttester",
		"outputs": [],
		"stateMutability": "nonpayable",
		"type": "function"
	},
	{
		"inputs": [],
		"name": "renounceOwnership",
		"outputs": [],
		"stateMutability": "nonpayable",
		"type": "function"
	},
	{
		"inputs": [
			{
				"internalType": "address",
				"name": "newRecipient",
				"type": "address"
			}
		],
		"name": "setFeeRecipient",
		"outputs": [],
		"stateMutability": "nonpayable",
		"type": "function"
	},
	{
		"inputs": [
			{
				"internalType": "bytes32",
				"name": "escrowId",
				"type": "bytes32"
			}
		],
		"name": "settlePayment",
		"outputs": [],
		"stateMutability": "nonpayable",
		"type": "function"
	},
	{
		"inputs": [
			{
				"internalType": "address",
				"name": "newOwner",
				"type": "address"
			}
		],
		"name": "transferOwnership",
		"outputs": [],
		"stateMutability": "nonpayable",
		"type": "function"
	},
	{
		"inputs": [
			{
				"internalType": "uint256",
				"name": "lo",
				"type": "uint256"
			},
			{
				"internalType": "uint256",
				"name": "hi",
				"type": "uint256"
			}
		],
		"name": "updatePaymentLimits",
		"outputs": [],
		"stateMutability": "nonpayable",
		"type": "function"
	},
	{
		"inputs": [
			{
				"internalType": "uint256",
				"name": "amount",
				"type": "uint256"
			},
			{
				"internalType": "address",
				"name": "to",
				"type": "address"
			}
		],
		"name": "withdraw",
		"outputs": [],
		"stateMutability": "nonpayable",
		"type": "function"
	},
	{
		"stateMutability": "payable",
		"type": "receive"
	},
	{
		"inputs": [
			{
				"internalType": "address",
				"name": "",
				"type": "address"
			}
		],
		"name": "authorizedAttesters",
		"outputs": [
			{
				"internalType": "bool",
				"name": "",
				"type": "bool"
			}
		],
		"stateMutability": "view",
		"type": "function"
	},
	{
		"inputs": [],
		"name": "CHECK_INTERVAL",
		"outputs": [
			{
				"internalType": "uint256",
				"name": "",
				"type": "uint256"
			}
		],
		"stateMutability": "view",
		"type": "function"
	},
	{
		"inputs": [
			{
				"internalType": "uint256",
				"name": "",
				"type": "uint256"
			}
		],
		"name": "completedEscrows",
		"outputs": [
			{
				"internalType": "bytes32",
				"name": "",
				"type": "bytes32"
			}
		],
		"stateMutability": "view",
		"type": "function"
	},
	{
		"inputs": [
			{
				"internalType": "uint256",
				"name": "",
				"type": "uint256"
			}
		],
		"name": "expiredEscrows",
		"outputs": [
			{
				"internalType": "bytes32",
				"name": "",
				"type": "bytes32"
			}
		],
		"stateMutability": "view",
		"type": "function"
	},
	{
		"inputs": [],
		"name": "fee",
		"outputs": [
			{
				"internalType": "uint256",
				"name": "",
				"type": "uint256"
			}
		],
		"stateMutability": "view",
		"type": "function"
	},
	{
		"inputs": [],
		"name": "FEE_DENOMINATOR",
		"outputs": [
			{
				"internalType": "uint256",
				"name": "",
				"type": "uint256"
			}
		],
		"stateMutability": "view",
		"type": "function"
	},
	{
		"inputs": [],
		"name": "feeRecipient",
		"outputs": [
			{
				"internalType": "address",
				"name": "",
				"type": "address"
			}
		],
		"stateMutability": "view",
		"type": "function"
	},
	{
		"inputs": [],
		"name": "getCompletedEscrows",
		"outputs": [
			{
				"internalType": "bytes32[]",
				"name": "",
				"type": "bytes32[]"
			}
		],
		"stateMutability": "view",
		"type": "function"
	},
	{
		"inputs": [],
		"name": "getFreeBalance",
		"outputs": [
			{
				"internalType": "uint256",
				"name": "",
				"type": "uint256"
			}
		],
		"stateMutability": "view",
		"type": "function"
	},
	{
		"inputs": [],
		"name": "getPendingEscrows",
		"outputs": [
			{
				"internalType": "bytes32[]",
				"name": "",
				"type": "bytes32[]"
			}
		],
		"stateMutability": "view",
		"type": "function"
	},
	{
		"inputs": [
			{
				"internalType": "bytes32",
				"name": "idHash",
				"type": "bytes32"
			}
		],
		"name": "getSettlementAmount",
		"outputs": [
			{
				"internalType": "uint256",
				"name": "",
				"type": "uint256"
			}
		],
		"stateMutability": "view",
		"type": "function"
	},
	{
		"inputs": [
			{
				"internalType": "bytes32",
				"name": "idHash",
				"type": "bytes32"
			}
		],
		"name": "getSettlementCounterparty",
		"outputs": [
			{
				"internalType": "address",
				"name": "",
				"type": "address"
			}
		],
		"stateMutability": "view",
		"type": "function"
	},
	{
		"inputs": [
			{
				"internalType": "bytes32",
				"name": "idHash",
				"type": "bytes32"
			}
		],
		"name": "getSettlementStatus",
		"outputs": [
			{
				"internalType": "enum ISettlementRegistry.Status",
				"name": "",
				"type": "uint8"
			}
		],
		"stateMutability": "view",
		"type": "function"
	},
	{
		"inputs": [],
		"name": "getUsdcBalance",
		"outputs": [
			{
				"internalType": "uint256",
				"name": "",
				"type": "uint256"
			}
		],
		"stateMutability": "view",
		"type": "function"
	},
	{
		"inputs": [
			{
				"internalType": "bytes32",
				"name": "escrowId",
				"type": "bytes32"
			}
		],
		"name": "isEscrowExpired",
		"outputs": [
			{
				"internalType": "bool",
				"name": "",
				"type": "bool"
			}
		],
		"stateMutability": "view",
		"type": "function"
	},
	{
		"inputs": [
			{
				"internalType": "bytes32",
				"name": "",
				"type": "bytes32"
			}
		],
		"name": "isSettled",
		"outputs": [
			{
				"internalType": "bool",
				"name": "",
				"type": "bool"
			}
		],
		"stateMutability": "view",
		"type": "function"
	},
	{
		"inputs": [],
		"name": "MAX_CHECK_COUNT",
		"outputs": [
			{
				"internalType": "uint256",
				"name": "",
				"type": "uint256"
			}
		],
		"stateMutability": "view",
		"type": "function"
	},
	{
		"inputs": [],
		"name": "maxEscrowTime",
		"outputs": [
			{
				"internalType": "uint256",
				"name": "",
				"type": "uint256"
			}
		],
		"stateMutability": "view",
		"type": "function"
	},
	{
		"inputs": [],
		"name": "maxPaymentAmount",
		"outputs": [
			{
				"internalType": "uint256",
				"name": "",
				"type": "uint256"
			}
		],
		"stateMutability": "view",
		"type": "function"
	},
	{
		"inputs": [],
		"name": "minPaymentAmount",
		"outputs": [
			{
				"internalType": "uint256",
				"name": "",
				"type": "uint256"
			}
		],
		"stateMutability": "view",
		"type": "function"
	},
	{
		"inputs": [],
		"name": "owner",
		"outputs": [
			{
				"internalType": "address",
				"name": "",
				"type": "address"
			}
		],
		"stateMutability": "view",
		"type": "function"
	},
	{
		"inputs": [
			{
				"internalType": "bytes32",
				"name": "",
				"type": "bytes32"
			}
		],
		"name": "payments",
		"outputs": [
			{
				"internalType": "address",
				"name": "payer",
				"type": "address"
			},
			{
				"internalType": "uint256",
				"name": "amount",
				"type": "uint256"
			},
			{
				"internalType": "uint256",
				"name": "lastCheckTimestamp",
				"type": "uint256"
			},
			{
				"internalType": "uint256",
				"name": "checkCount",
				"type": "uint256"
			},
			{
				"internalType": "uint256",
				"name": "createdAt",
				"type": "uint256"
			}
		],
		"stateMutability": "view",
		"type": "function"
	},
	{
		"inputs": [
			{
				"internalType": "uint256",
				"name": "",
				"type": "uint256"
			}
		],
		"name": "pendingEscrows",
		"outputs": [
			{
				"internalType": "bytes32",
				"name": "",
				"type": "bytes32"
			}
		],
		"stateMutability": "view",
		"type": "function"
	},
	{
		"inputs": [],
		"name": "recipientEmail",
		"outputs": [
			{
				"internalType": "string",
				"name": "",
				"type": "string"
			}
		],
		"stateMutability": "view",
		"type": "function"
	},
	{
		"inputs": [],
		"name": "settlementRegistry",
		"outputs": [
			{
				"internalType": "contract ISettlementRegistry",
				"name": "",
				"type": "address"
			}
		],
		"stateMutability": "view",
		"type": "function"
	},
	{
		"inputs": [],
		"name": "totalEscrowed",
		"outputs": [
			{
				"internalType": "uint256",
				"name": "",
				"type": "uint256"
			}
		],
		"stateMutability": "view",
		"type": "function"
	},
	{
		"inputs": [],
		"name": "usdcToken",
		"outputs": [
			{
				"internalType": "address",
				"name": "",
				"type": "address"
			}
		],
		"stateMutability": "view",
		"type": "function"
	}
]; // import or paste your contract ABI here
const BACKEND_API = "http://localhost:5045";

export default function SettlementInitForm() {
  const [email, setEmail] = useState("");
  const [amount, setAmount] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [walletAddress, setWalletAddress] = useState<string | null>(null);
  const [usdcBalance, setUsdcBalance] = useState<string | null>(null);
  const [contractUsdcBalance, setContractUsdcBalance] = useState<string | null>(null);
  const [freeBalance, setFreeBalance] = useState<string | null>(null);

  const generateSalt = () =>
    "0x" + ethers.utils.hexlify(ethers.utils.randomBytes(32)).slice(2);

  const getMetaMaskProvider = (): any => {
    if (window.ethereum?.providers?.length) {
      return window.ethereum.providers.find((p) => p.isMetaMask);
    }
    return window.ethereum;
  };

  const fetchBalances = async (signer: ethers.Signer, address: string) => {
    try {
      const contract = new ethers.Contract(BRIDGE_ADDRESS, RAMP_ABI, signer);
      const usdcTokenAddress = await contract.usdcToken();
      const decimals = 6;

      const usdcContract = new ethers.Contract(usdcTokenAddress, ERC20_ABI, signer);
      const tokenBalanceRaw = await usdcContract.balanceOf(address);
      setUsdcBalance(ethers.utils.formatUnits(tokenBalanceRaw, decimals));

      const rawContractUsdcBalance = await contract.getUsdcBalance();
      setContractUsdcBalance(ethers.utils.formatUnits(rawContractUsdcBalance, decimals));

      const rawFreeBalance = await contract.getFreeBalance();
      setFreeBalance(ethers.utils.formatUnits(rawFreeBalance, decimals));
    } catch (err: any) {
      console.error("Error fetching balances:", err.message);
    }
  };

  const connectWallet = async () => {
    const provider = getMetaMaskProvider();
    if (!provider || !provider.isMetaMask) {
      alert("MetaMask not found. Please install or switch to MetaMask.");
      return;
    }

    await provider.request({ method: "eth_requestAccounts" });
    const ethersProvider = new ethers.providers.Web3Provider(provider);
    const signer = ethersProvider.getSigner();
    const address = await signer.getAddress();
    setWalletAddress(address);

    await fetchBalances(signer, address);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setStatus("Processing...");

    try {
      if (!window.ethereum) throw new Error("No wallet detected");
      const provider = getMetaMaskProvider();
      if (!provider || !provider.isMetaMask) throw new Error("MetaMask provider not found.");

      const ethersProvider = new ethers.providers.Web3Provider(provider);
      const signer = ethersProvider.getSigner();
      const address = await signer.getAddress();
	  console.log('address:', address)
      const contract = new ethers.Contract(BRIDGE_ADDRESS, RAMP_ABI, signer);
      const decimals = 6;
	  console.log('decimals:',decimals)

      const rawAmount = ethers.utils.parseUnits(amount, decimals);

      // 🔒 Validate free balance
      const rawFreeBalance = await contract.getFreeBalance();
	  console.log('rawFreeBalance:',rawFreeBalance)
      if (rawFreeBalance.lt(rawAmount)) {
        setStatus("Insufficient contract free balance to process this settlement.");
        return;
      }

      const recipientEmail = await contract.recipientEmail();
	  console.log('recipientEmail:', recipientEmail)
      const salt = generateSalt();
      const settlementId = `${address}-${Date.now()}`;
      const idHash = ethers.utils.solidityKeccak256(["bytes32", "string"], [salt, settlementId]);
      const userEmailHash = ethers.utils.solidityKeccak256(["bytes32", "string"], [salt, email]);

      await fetch(`${BACKEND_API}/api/store_salt`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id_hash: idHash,
          salt,
          email,
          recipient_email: recipientEmail,
        }),
      });

	  console.log('at initPayment')

      const tx = await contract.initPayment(idHash, userEmailHash, rawAmount);
	  console.log(' after initPayment')
      await tx.wait();
      setStatus("Transaction confirmed! Waiting for settlement...");

      // 🔄 Refresh balances after payment
      await fetchBalances(signer, address);

      for (let i = 0; i < 60; i++) {
        const res = await fetch("http://localhost:4028/status", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ escrowId: idHash }),
        });
        const json = await res.json();
        if (json.status === "completed" || json.status === "failed") {
          setStatus(`Settlement ${json.status}`);
          return;
        }
        await new Promise((r) => setTimeout(r, 5000));
      }

      setStatus("Timeout reached. Check again later.");
    } catch (err: any) {
      setStatus(`Error: ${err.message}`);
    }
  };

  return (
    <div className="max-w-md mx-auto p-4 border rounded-xl shadow-md space-y-4">
      <h2 className="text-xl font-semibold">Start New Settlement</h2>

      <Button onClick={connectWallet}>
        {walletAddress ? `Connected: ${walletAddress.slice(0, 6)}...` : "Connect Wallet"}
      </Button>

      {usdcBalance && (
        <div className="text-sm text-gray-700">
          Wallet USDC Balance: {usdcBalance}
        </div>
      )}
      {contractUsdcBalance && (
        <div className="text-sm text-gray-700">
          Contract USDC Balance: {contractUsdcBalance}
        </div>
      )}
      {freeBalance && (
        <div className="text-sm text-gray-700">
          Contract Free Balance: {freeBalance}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-3">
        <Input
          placeholder="Your Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
        <Input
          placeholder="Amount in USDC"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          type="number"
          step="0.01"
          required
        />
        <Button type="submit">Submit Payment</Button>
      </form>

      {status && <div className="text-sm text-gray-600">{status}</div>}
    </div>
  );
}