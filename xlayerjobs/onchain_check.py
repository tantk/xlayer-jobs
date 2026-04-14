"""Check on-chain activity for service provider wallets via OnchainOS."""

import json
import os
import subprocess
import time
import urllib.request

from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY", "")

# Chains to check — most x402 services are on Base or Ethereum
CHAINS_TO_CHECK = ["base", "ethereum", "arbitrum", "xlayer", "solana"]


def run_onchainos(*args: str, timeout: int = 30) -> dict:
    result = subprocess.run(
        ["onchainos", *args],
        capture_output=True, text=True, timeout=timeout,
    )
    if not result.stdout.strip():
        return {"ok": False, "error": "no output"}
    return json.loads(result.stdout)


def check_wallet_activity(address: str) -> dict:
    """Check wallet total value and transaction count across chains."""
    total_value = 0.0
    tx_count = 0

    # Check if it's an EVM address
    if address.startswith("0x") and len(address) == 42:
        chains = "1,8453,42161,196"  # eth, base, arb, xlayer
    else:
        # Might be Solana
        chains = "501"

    # Get total value
    try:
        data = run_onchainos(
            "portfolio", "total-value",
            "--address", address,
            "--chains", chains,
            "--chain", "ethereum",
        )
        if data.get("ok"):
            for item in data.get("data", []):
                val = item.get("totalValue", "0")
                total_value += float(val)
    except Exception:
        pass

    # Get transaction history (count)
    try:
        data = run_onchainos(
            "wallet", "history",
            "--address", address,
            "--chain", "ethereum",
            "--limit", "1",
        )
        # Can't easily get tx count from history — use the total from portfolio
    except Exception:
        pass

    return {
        "total_value_usd": round(total_value, 2),
        "tx_count": tx_count,  # TODO: get actual count
    }


def check_wallet_via_rpc(address: str) -> dict:
    """Check wallet tx count via direct RPC — more reliable than onchainos for public addresses."""
    total_value = 0.0
    tx_count = 0

    if not address.startswith("0x") or len(address) != 42:
        return {"total_value_usd": 0, "tx_count": 0}

    rpcs = {
        "base": "https://mainnet.base.org",
        "ethereum": "https://eth.llamarpc.com",
        "arbitrum": "https://arb1.arbitrum.io/rpc",
        "xlayer": "https://rpc.xlayer.tech",
    }

    for chain, rpc in rpcs.items():
        try:
            # Get transaction count (nonce)
            body = json.dumps({
                "jsonrpc": "2.0",
                "method": "eth_getTransactionCount",
                "params": [address, "latest"],
                "id": 1,
            }).encode()
            req = urllib.request.Request(rpc, data=body, headers={"Content-Type": "application/json"})
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read())
            nonce = int(data["result"], 16)
            tx_count += nonce

            # Get ETH balance
            body2 = json.dumps({
                "jsonrpc": "2.0",
                "method": "eth_getBalance",
                "params": [address, "latest"],
                "id": 1,
            }).encode()
            req2 = urllib.request.Request(rpc, data=body2, headers={"Content-Type": "application/json"})
            resp2 = urllib.request.urlopen(req2, timeout=10)
            data2 = json.loads(resp2.read())
            balance_wei = int(data2["result"], 16)
            # Rough ETH value — just for indication, not precision
            if chain in ("ethereum", "arbitrum", "xlayer"):
                total_value += balance_wei / 1e18 * 2200  # rough ETH price
            elif chain == "base":
                total_value += balance_wei / 1e18 * 2200
        except Exception:
            continue

    return {
        "total_value_usd": round(total_value, 2),
        "tx_count": tx_count,
    }


def update_service_onchain_data(service_id: int, tx_count: int, total_value: float):
    """Update a service record with on-chain data."""
    body = json.dumps({
        "tx_count": tx_count,
        "total_value_usd": total_value,
        "last_chain_check": "now()",
    }).encode()

    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/services?id=eq.{service_id}",
        data=body,
        headers={
            "apikey": SUPABASE_SECRET_KEY,
            "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        },
        method="PATCH",
    )
    urllib.request.urlopen(req, timeout=15)


def check_all_services():
    """Check on-chain activity for all services with wallet addresses."""
    # Get services with wallet addresses
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/services?wallet_address=not.is.null&select=id,agent_name,wallet_address,service_type&order=id.asc",
        headers={
            "apikey": SUPABASE_SECRET_KEY,
            "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
        },
    )
    resp = urllib.request.urlopen(req, timeout=15)
    services = json.loads(resp.read())

    # Deduplicate by wallet address
    seen_wallets = {}
    for s in services:
        addr = s["wallet_address"]
        if addr not in seen_wallets:
            seen_wallets[addr] = s

    print(f"Checking {len(seen_wallets)} unique wallets...")

    for addr, s in seen_wallets.items():
        print(f"  {s['agent_name']:20s} | {addr[:16]}... ", end="")

        activity = check_wallet_via_rpc(addr)
        tx = activity["tx_count"]
        val = activity["total_value_usd"]
        print(f"| txs: {tx:>5d} | value: ${val:>10.2f}")

        # Update all services with this wallet
        for svc in services:
            if svc["wallet_address"] == addr:
                try:
                    update_service_onchain_data(svc["id"], tx, val)
                except Exception as e:
                    print(f"    update error: {e}")

        time.sleep(1)  # rate limit

    print(f"\nDone. Checked {len(seen_wallets)} wallets.")


if __name__ == "__main__":
    check_all_services()
