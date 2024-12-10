import json
from datetime import datetime
import pandas as pd
import base58
import os
import time
import requests
from dotenv import load_dotenv
import base64
from time import sleep
from typing import List, Dict, Any

class TokenSnapshot:
    def __init__(self):
        """Initialize the token snapshot tool using environment variables"""
        load_dotenv()
        
        # Load configuration from .env
        self.rpc_url = os.getenv('SOLANA_RPC_URL')
        self.token_mint = os.getenv('TOKEN_MINT_ADDRESS')
        self.target_mcap = float(os.getenv('TARGET_MCAP_SOL', '500'))
        self.snapshot_dir = os.getenv('SNAPSHOT_DIR', 'snapshots')
        
        print(f"Initialized with:")
        print(f"RPC URL: {self.rpc_url}")
        print(f"Token Mint: {self.token_mint}")
        print(f"Target Market Cap: {self.target_mcap} SOL")
        print(f"Snapshot Directory: {self.snapshot_dir}")
        
        # Rate limiting settings
        self.request_delay = 1.0  # Increased delay between requests
        self.max_retries = 3
        self.retry_delay = 2
        
        # Create snapshots directory if it doesn't exist
        os.makedirs(self.snapshot_dir, exist_ok=True)
    
    def make_rpc_request(self, method: str, params: List[Any], retry_count: int = 0) -> Dict:
        """Make a JSON RPC request with retry logic and rate limiting"""
        headers = {'Content-Type': 'application/json'}
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params
        }
        
        try:
            print(f"Making RPC request: {method}")
            print(f"Params: {json.dumps(params, indent=2)}")
            
            # Rate limiting delay
            sleep(self.request_delay)
            
            response = requests.post(self.rpc_url, headers=headers, json=payload)
            result = response.json()
            
            print(f"Response: {json.dumps(result, indent=2)}")
            
            # Check for rate limit response
            if 'error' in result:
                error_code = result['error'].get('code', 0)
                error_msg = result['error'].get('message', 'Unknown error')
                print(f"RPC error {error_code}: {error_msg}")
                
                if error_code in [-32005, 429] and retry_count < self.max_retries:
                    wait_time = self.retry_delay * (retry_count + 1)
                    print(f"Rate limited. Waiting {wait_time} seconds before retry {retry_count + 1}/{self.max_retries}")
                    sleep(wait_time)
                    return self.make_rpc_request(method, params, retry_count + 1)
                    
            return result
            
        except Exception as e:
            print(f"RPC request failed with exception: {str(e)}")
            if retry_count < self.max_retries:
                wait_time = self.retry_delay * (retry_count + 1)
                print(f"Retrying in {wait_time} seconds. Attempt {retry_count + 1}/{self.max_retries}")
                sleep(wait_time)
                return self.make_rpc_request(method, params, retry_count + 1)
            return None

    def get_token_largest_accounts(self) -> List[Dict]:
        """Get the largest token accounts"""
        print("Fetching largest token accounts...")
        try:
            params = [
                self.token_mint,
                {
                    "commitment": "confirmed"
                }
            ]
            
            response = self.make_rpc_request("getTokenLargestAccounts", params)
            
            if response and 'result' in response:
                accounts = response['result']['value']
                print(f"Found {len(accounts)} large accounts")
                return accounts
            
            print("No accounts found in response")
            return []
            
        except Exception as e:
            print(f"Error fetching largest token accounts: {str(e)}")
            return []

    def get_account_info(self, address: str) -> Dict:
        """Get information about a specific token account"""
        print(f"Fetching info for account: {address}")
        try:
            params = [
                address,
                {
                    "encoding": "jsonParsed",
                    "commitment": "confirmed"
                }
            ]
            
            response = self.make_rpc_request("getAccountInfo", params)
            
            if response and 'result' in response and response['result']:
                print("Successfully fetched account info")
                return response['result']['value']
            
            print("No account info found in response")
            return None
            
        except Exception as e:
            print(f"Error fetching account info: {str(e)}")
            return None

    def get_token_accounts(self) -> List[Dict]:
        """Query token holders using a combination of methods"""
        print("\nStarting token account collection...")
        try:
            holders = []
            
            # Get largest accounts first
            largest_accounts = self.get_token_largest_accounts()
            print(f"Found {len(largest_accounts)} large accounts to process")
            
            for i, account in enumerate(largest_accounts):
                print(f"\nProcessing account {i+1}/{len(largest_accounts)}")
                account_info = self.get_account_info(account['address'])
                
                if account_info and 'data' in account_info:
                    try:
                        parsed_data = account_info['data']['parsed']['info']
                        balance = int(parsed_data['tokenAmount']['amount'])
                        owner = parsed_data['owner']
                        
                        if balance > 0:
                            print(f"Added holder {owner} with balance {balance}")
                            holders.append({
                                'address': owner,
                                'balance': balance
                            })
                    except (KeyError, TypeError) as e:
                        print(f"Error parsing account data: {str(e)}")
                        continue
            
            print(f"\nFinished collecting {len(holders)} holder accounts")
            return holders
            
        except Exception as e:
            print(f"Error in get_token_accounts: {str(e)}")
            return []

    def get_token_sol_price(self) -> float:
        # Placeholder - implement your specific token pricing logic
        return 0.001  # Example value

    def calculate_market_cap(self, total_supply: int) -> float:
        """Calculate market cap in SOL based on current token supply and price"""
        try:
            token_price_in_sol = self.get_token_sol_price()
            market_cap_in_sol = total_supply * token_price_in_sol
            return market_cap_in_sol
        except Exception as e:
            print(f"Error calculating market cap: {str(e)}")
            return None

    def determine_snapshot_interval(self, current_mcap: float) -> int:
        """Determine snapshot interval based on how close we are to target market cap"""
        if current_mcap is None:
            return 3600  # Default to hourly if we can't calculate market cap
        
        mcap_difference = abs(self.target_mcap - current_mcap)
        
        if mcap_difference <= 10:  # Within 10 SOL
            return 60  # Every minute
        elif mcap_difference <= 50:  # Within 50 SOL
            return 300  # Every 5 minutes
        elif mcap_difference <= 100:  # Within 100 SOL
            return 900  # Every 15 minutes
        else:
            return 3600  # Every hour

    def take_snapshot(self) -> Dict:
        """Take a snapshot of all token holders and their balances"""
        print("\nTaking new snapshot...")
        timestamp = datetime.now()
        holders = self.get_token_accounts()
        
        if not holders:
            print("No holders found in snapshot")
            return None
            
        print("Processing holder data...")
        # Create DataFrame
        df = pd.DataFrame(holders)
        
        # Group by address and sum balances
        df = df.groupby('address')['balance'].sum().reset_index()
        
        # Sort by balance descending
        df = df.sort_values('balance', ascending=False)
        
        # Add timestamp
        df['timestamp'] = timestamp.isoformat()
        
        # Calculate total supply and market cap
        total_supply = df['balance'].sum()
        market_cap = self.calculate_market_cap(total_supply)
        
        print(f"Total supply: {total_supply}")
        print(f"Market cap in SOL: {market_cap}")
        
        # Save snapshot with timestamp
        filename = f"{self.snapshot_dir}/snapshot_{timestamp.strftime('%Y%m%d_%H%M%S')}"
        df.to_csv(f"{filename}.csv", index=False)
        
        snapshot_info = {
            'timestamp': timestamp.isoformat(),
            'total_holders': len(df),
            'total_supply': float(total_supply),
            'market_cap_sol': market_cap,
            'target_reached': market_cap >= self.target_mcap if market_cap else False
        }
        
        with open(f"{filename}_info.json", 'w') as f:
            json.dump(snapshot_info, f, indent=2)
        
        print("Snapshot saved successfully")
        return snapshot_info

    def monitor_market_cap(self):
        """Continuously monitor market cap and take snapshots at appropriate intervals"""
        print(f"Starting market cap monitoring. Target: {self.target_mcap} SOL")
        
        while True:
            try:
                snapshot_info = self.take_snapshot()
                
                if snapshot_info:
                    current_mcap = snapshot_info['market_cap_sol']
                    print(f"\nSnapshot taken at {snapshot_info['timestamp']}")
                    print(f"Current Market Cap: {current_mcap:.2f} SOL")
                    print(f"Total Holders: {snapshot_info['total_holders']}")
                    
                    if snapshot_info['target_reached']:
                        print(f"\n🎯 TARGET MARKET CAP REACHED! 🎯")
                        print("Final snapshot saved. Monitoring stopped.")
                        break
                    
                    # Determine next snapshot interval
                    interval = self.determine_snapshot_interval(current_mcap)
                    print(f"Next snapshot in {interval/60:.1f} minutes")
                    
                    time.sleep(interval)
                else:
                    print("Error taking snapshot. Retrying in 1 hour...")
                    time.sleep(3600)
                    
            except Exception as e:
                print(f"Error in monitoring loop: {str(e)}")
                print(f"Stack trace:", e.__traceback__)
                time.sleep(3600)  # Retry in an hour if there's an error

def main():
    # Create .env file template if it doesn't exist
    if not os.path.exists('.env'):
        with open('.env', 'w') as f:
            f.write("""# Solana Configuration
SOLANA_RPC_URL=https://api.mainnet-beta.solana.com
TOKEN_MINT_ADDRESS=your_token_mint_address
TARGET_MCAP_SOL=500
SNAPSHOT_DIR=snapshots
""")
        print("Created .env template file. Please fill in your configuration details.")
        return

    snapshot = TokenSnapshot()
    snapshot.monitor_market_cap()

if __name__ == "__main__":
    main()
