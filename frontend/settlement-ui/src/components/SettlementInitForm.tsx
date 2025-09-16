import { useState } from "react";
import { ethers } from "ethers";
import { Input } from "../components/ui/input";
import { Button } from "../components/ui/button";
import dotenv from "dotenv";
import './styles/index.css'; 

import ERC20_ABI from "@/abi/ERC20.json";
import RAMP_ABI from "@/abi/EscrowBridge.json";

dotenv.config();

const BRIDGE_ADDRESS = process.env.BRIDGE_ADDRESS || "0x51966c1468DedD9de6Cf1378ab0A2234C5341c1D"; 

const CHAINSETTLE_API = process.env.CHAINSETTLE_API || "http://localhost:5045";
const ESCROW_BRIDGE_API = process.env.ESCROW_BRIDGE_API || "http://localhost:4028";

declare global {
  interface Window {
    ethereum?: any;
  }
}

export default function SettlementInitForm() {
  const [email, setEmail] = useState("");
  const [amount, setAmount] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [walletAddress, setWalletAddress] = useState<string | null>(null);
  const [userUsdcBalance, setUserUsdcBalance] = useState<string | null>(null);
  const [contractUsdcBalance, setContractUsdcBalance] = useState<string | null>(null);
  const [freeBalance, setFreeBalance] = useState<string | null>(null);
  const [recipient, setRecipient] = useState("");

  const generateSalt = () =>
    "0x" + ethers.utils.hexlify(ethers.utils.randomBytes(32)).slice(2);

  const getMetaMaskProvider = (): any => {
    if (window.ethereum?.providers?.length) {
      return window.ethereum.providers.find((p: any) => p.isMetaMask);
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
      setUserUsdcBalance(ethers.utils.formatUnits(tokenBalanceRaw, decimals));

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

      await fetch(`${CHAINSETTLE_API}/api/store_salt`, {
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
    console.log('recipient:', recipient)

      let tx;
      if (recipient && ethers.utils.isAddress(recipient)) {
        tx = await contract["initPayment(bytes32,bytes32,uint256,address)"](
          idHash,
          userEmailHash,
          rawAmount,
          recipient
        );
      } else {
        tx = await contract["initPayment(bytes32,bytes32,uint256)"](
          idHash,
          userEmailHash,
          rawAmount
        );
      }

	  console.log(' after initPayment')
      await tx.wait();
      setStatus("Transaction confirmed! Waiting for settlement...");

      for (let i = 0; i < 60; i++) {
        const res = await fetch(`${ESCROW_BRIDGE_API}/status`, {
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

	  // Refresh balances after payment
      await fetchBalances(signer, address);

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

      {userUsdcBalance && (
        <div className="text-sm text-gray-700">
          Wallet USDC Balance: {userUsdcBalance}
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
        <Input
          placeholder="(Optional) Recipient Address"
          value={recipient}
          onChange={(e) => setRecipient(e.target.value)}
        />
        <Button type="submit">Submit Payment</Button>
      </form>

      {status && <div className="text-sm text-gray-600">{status}</div>}
    </div>
  );
}